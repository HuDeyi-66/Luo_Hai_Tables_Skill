"""Opt-in RECONSTRUCT_VERIFY and ACCOUNT_LOSS; contract 1.0.0."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass, replace
from hashlib import sha256
from io import BytesIO
import json
import math
from pathlib import Path
from typing import Any, Literal
import xml.etree.ElementTree as ET
import zipfile

from . import ooxml
from .backends import FixtureXlsxBackend
from .citation import (Ambiguous, Citation, CitationSelector, RangeCitation,
                       Unresolved, iter_cells, resolve_citation)
from .contracts import (TableArtifact, TableEvidenceUnit, TableLossKind,
                        TableRunResult, table_summarise_loss)

VERSION = '1.0.0'


@dataclass(frozen=True)
class VerificationPolicy:
    level: Literal['artifact', 'address', 'observations', 'interpretation'] = 'observations'
    max_cells: int = 10000


@dataclass(frozen=True)
class VerificationResult:
    schema: str
    operator: str
    status: Literal['verified', 'ambiguous', 'unresolved', 'integrity_failure',
                    'unsupported', 'unavailable', 'corrupt', 'mismatch', 'invalid_input']
    artifact_id: str
    source_id: str
    unit_id: str
    content_digest: str
    policy: VerificationPolicy
    artifact_identity_verified: bool = False
    citation_address_reconstructable: bool = False
    stored_observations_verified: bool = False
    value_interpretation: str = 'not_verified'
    citation: dict[str, Any] | None = None
    original_observations: tuple[dict[str, Any], ...] = ()
    diagnostics: tuple[str, ...] = ()
    verified_cell_fields: tuple[str, ...] = ()
    claim_scope: str = 'selected_cell_fields_only; headers_and_region_interpretation_not_verified; no_workbook_completeness_or_Excel_display_claim'
    result_id: str = ''

    def as_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class LossAccountingResult:
    schema: str
    operator: str
    status: Literal['accounted', 'inconsistent', 'unknown']
    input_digest: str | None
    observed_losses_by_kind: dict[str, int]
    unit_losses: tuple[dict[str, Any], ...]
    declared_risks: tuple[str, ...]
    unsurfaced_risks: tuple[str, ...]
    unsupported_capabilities: tuple[str, ...]
    inconsistencies: tuple[str, ...]
    unresolved_states: tuple[str, ...]
    declared_complete_success: bool
    complete_success_justified: bool
    diagnostics: dict[str, Any]
    count_semantics: str = 'unique_unit_loss_declarations; not_independent_source_loss_events'
    workbook_observation_completeness: str = 'unknown'
    result_id: str = ''

    def as_dict(self):
        return asdict(self)


def _stable(data):
    return 'sha256:' + sha256(json.dumps(data, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _identify(result):
    body = result.as_dict()
    body.pop('result_id')
    return replace(result, result_id=_stable(body))


def _guard_package(snapshot, package):
    """Reject canonical-reader ambiguities before claiming verification.

    This is an envelope guard, not another value parser. read_package owns all
    workbook decoding. In particular it overwrites repeated coordinates, so
    those must be refused rather than accepted as original-source facts.
    """
    names = [s.name for s in package.sheets]
    parts = [s.part_path for s in package.sheets]
    if len(names) != len(set(names)) or len(parts) != len(set(parts)):
        return 'duplicate_worksheet_address'
    with zipfile.ZipFile(BytesIO(snapshot)) as archive:
        for sheet in package.sheets:
            root = ET.fromstring(archive.read(sheet.part_path))
            if root.tag != '{' + ooxml.NS_MAIN + '}worksheet':
                return 'unsupported_worksheet_namespace'
            refs = [c.get('r', '').upper().replace('$', '') for c in root.iter('{' + ooxml.NS_MAIN + '}c')]
            if len(refs) != len(set(refs)):
                return 'duplicate_original_cell_address'
            for formula in root.iter('{' + ooxml.NS_MAIN + '}f'):
                if formula.attrib:
                    return 'unsupported_formula_encoding'
            for cell in root.iter('{' + ooxml.NS_MAIN + '}c'):
                if cell.get('t') == 'b':
                    value = cell.find('{' + ooxml.NS_MAIN + '}v')
                    if value is None or value.text not in ('0', '1'):
                        return 'unsupported_boolean_encoding'
            covered = set()
            for region in sheet.merged_ranges:
                from .citation import _parse_range
                try:
                    normalized, _, r0, r1, c0, c1 = _parse_range(region)
                except ValueError:
                    return 'unsupported_merge_encoding'
                if region != normalized:
                    return 'unsupported_merge_encoding'
                if (r1-r0+1)*(c1-c0+1) > ooxml.MAX_EXPANDED_CELLS:
                    return 'unsupported_merge_budget'
                positions = {(r, c) for r in range(r0, r1+1) for c in range(c0, c1+1)}
                if positions & covered:
                    return 'overlapping_merge_ranges'
                covered.update(positions)
            for cell in sheet.cells.values():
                if cell.kind == 'unknown' or (isinstance(cell.value, float) and not math.isfinite(cell.value)):
                    return 'unsupported_cell_encoding'
    return None


def reconstruct_verify(artifact: TableArtifact, unit: TableEvidenceUnit,
                       selector: CitationSelector,
                       policy: VerificationPolicy = VerificationPolicy()) -> VerificationResult:
    """Verify one snapshot of original bytes, then check selected stored fields."""
    state = dict(artifact_identity_verified=False, citation_address_reconstructable=False,
                 stored_observations_verified=False)
    def output(status, **kwargs):
        return _identify(VerificationResult('luohai-reconstruct-verify/1.0.0', 'RECONSTRUCT_VERIFY',
            status, artifact.artifact_id, unit.source_id, unit.unit_id, artifact.content_digest,
            policy, **{**state, **kwargs}))
    if policy.level not in ('artifact', 'address', 'observations', 'interpretation') or type(policy.max_cells) is not int or not 0 < policy.max_cells <= 10000:
        return output('invalid_input', diagnostics=('invalid_verification_policy',))
    try:
        if artifact.digest_algorithm != 'sha256':
            return output('unsupported', diagnostics=('unsupported_digest_algorithm',))
        snapshot = artifact.payload_bytes
        if snapshot is None:
            if not artifact.location:
                return output('unavailable', diagnostics=('original_artifact_unavailable',))
            snapshot = Path(artifact.location).read_bytes()
        if not artifact.verify_bytes(snapshot) or len(snapshot) != artifact.byte_length:
            return output('integrity_failure', diagnostics=('artifact_digest_or_length_mismatch',))
        state['artifact_identity_verified'] = True
        if unit.artifact_id != artifact.artifact_id or unit.provenance != artifact.content_digest:
            return output('integrity_failure', diagnostics=('unit_artifact_or_provenance_mismatch',))
        if policy.level == 'artifact':
            return output('verified')
        if not isinstance(selector, CitationSelector):
            return output('invalid_input', diagnostics=('CitationSelector_required',))
        if selector.ref is not None and selector.ref_range is not None:
            return output('invalid_input', diagnostics=('point_and_range_are_exclusive',))
        if (selector.ref is not None or selector.ref_range is not None) and any(x is not None for x in
            (selector.value, selector.row_header, selector.column_header, selector.row_index, selector.column_index)):
            return output('unsupported', diagnostics=('mixed_address_and_label_constraints',))
        # Prevent canonical range allocation above this operator's declared bound.
        if selector.ref_range:
            from .citation import _parse_range
            _, _, r0, r1, c0, c1 = _parse_range(selector.ref_range)
            if (r1-r0+1)*(c1-c0+1) > policy.max_cells:
                return output('unsupported', diagnostics=('verification_cell_budget_exceeded',))
        refs = [str(c.get('ref', '')).upper() for c in iter_cells(unit)]
        if len(refs) != len(set(refs)):
            return output('ambiguous', diagnostics=('duplicate_stored_cell_addresses',))
        native = resolve_citation(unit, selector)
        if isinstance(native, Ambiguous):
            return output('ambiguous', citation=deepcopy(native.as_dict()), diagnostics=(native.problem,))
        if isinstance(native, Unresolved):
            return output('unresolved', citation=deepcopy(native.as_dict()), diagnostics=(native.problem,))
        if not isinstance(native, (Citation, RangeCitation)):
            return output('unsupported', diagnostics=('unsupported_citation_contract',))
        state['citation_address_reconstructable'] = True
        record = deepcopy(native.as_dict())
        if policy.level == 'address':
            return output('verified', citation=record)
        if artifact.media_type not in ('application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                                       'application/vnd.ms-excel.sheet.macroEnabled.12'):
            return output('unsupported', citation=record, diagnostics=('observation_verification_requires_OOXML',))
        if unit.producer.backend_id != FixtureXlsxBackend.backend_id:
            return output('unsupported', citation=record, diagnostics=('backend_interpretation_not_supported',))
        package = ooxml.read_package(BytesIO(snapshot))
        guard = _guard_package(snapshot, package)
        if guard:
            return output('unsupported', citation=record, diagnostics=(guard,))
        sheets = [s for s in package.sheets if s.name == native.sheet_name]
        if len(sheets) != 1:
            return output('unresolved', citation=record, diagnostics=('original_sheet_unresolved',))
        sheet = sheets[0]
        if native.sheet_index != sheet.index:
            return output('mismatch', citation=record, diagnostics=('sheet_index_mismatch',))
        selected = list(native.cells) if isinstance(native, RangeCitation) else [native]
        stored = {str(c['ref']).upper(): c for c in iter_cells(unit)}
        observed_sheet = FixtureXlsxBackend()._observe_sheet(sheet)
        originals = []
        mismatches = []
        for target in selected:
            ref = target.ref
            raw = sheet.cells.get(ref)
            row, column = ooxml.parse_cell_reference(ref)
            if raw is not None:
                observed = observed_sheet.cells[ref]
                expected = {k: getattr(observed, k) for k in ('row', 'column', 'value', 'value_kind', 'formula', 'merged_from', 'hidden')}
            else:
                from .backends import _merge_anchor_for
                anchor = _merge_anchor_for(sheet, row, column) if ref in sheet.merged_covered else None
                expected = dict(row=row, column=column, value=None,
                    value_kind='merged' if anchor else 'absent', formula=None,
                    merged_from=anchor, hidden=sheet.is_hidden_address(row, column))
            # These are raw original facts, kept apart from backend projection.
            originals.append(dict(ref=ref, element_present=raw is not None,
                raw_kind=raw.kind if raw else 'absent', formula_text=raw.formula if raw else None,
                stored_or_cached_value=raw.value if raw else None,
                merge_anchor=sheet.merge_anchors.get(ref), **expected))
            claim = stored.get(ref)
            if claim is None:
                # An omitted stored record is only reconstructable as absent.
                if raw is not None or ref in sheet.merged_covered:
                    mismatches.append(ref + ':missing_stored_observation')
            else:
                for key, value in expected.items():
                    if key not in claim or _stable(claim[key]) != _stable(value):
                        mismatches.append(ref + ':' + key)
            if _stable(target.value) != _stable(expected['value']) or target.value_kind != expected['value_kind']:
                mismatches.append(ref + ':citation_value')
        if mismatches:
            return output('mismatch', citation=record, original_observations=tuple(originals),
                          diagnostics=tuple(mismatches))
        state['stored_observations_verified'] = True
        state['verified_cell_fields'] = ('row', 'column', 'value', 'value_kind', 'formula', 'merged_from', 'hidden')
        if policy.level == 'interpretation':
            return output('unsupported', citation=record, original_observations=tuple(originals),
                          value_interpretation='unsupported', diagnostics=('no_formula_evaluation_or_Excel_display_verifier',))
        return output('verified', citation=record, original_observations=tuple(originals))
    except OSError:
        return output('unavailable', diagnostics=('original_artifact_unreadable',))
    except (ooxml.XlsxPackageError, zipfile.BadZipFile, ET.ParseError, EOFError):
        return output('corrupt', diagnostics=('invalid_OOXML_package',))
    except (TypeError, ValueError, KeyError, AttributeError, OverflowError):
        return output('invalid_input', diagnostics=('malformed_or_unsupported_evidence',))


def account_loss(run: TableRunResult) -> LossAccountingResult:
    """Observe declarations only. Never invoke downgrade_for_declared_risk()."""
    try:
        snapshot = deepcopy(run.as_dict())
        input_digest = _stable(snapshot)
    except (TypeError, ValueError, AttributeError):
        return _identify(LossAccountingResult('luohai-loss-accounting/1.0.0', 'ACCOUNT_LOSS',
            'unknown', None, {}, (), (), (), (), (), ('unsupported_non_JSON_run_observations',),
            run.is_complete_success, False, {'serialization': 'unavailable'}))
    inconsistencies = []
    unknown = []
    units = {}
    for unit in run.units:
        if unit.unit_id in units:
            if unit.as_dict() != units[unit.unit_id].as_dict():
                inconsistencies.append('conflicting_duplicate_unit:' + unit.unit_id)
            continue
        units[unit.unit_id] = unit
    normalized_list = []
    cell_declarations = {}
    for unit_id, unit in sorted(units.items()):
        cell_losses = {loss for cell in iter_cells(unit) for loss in cell.get('loss', ())}
        cell_declarations[unit_id] = tuple(sorted(cell_losses))
        if cell_losses - set(unit.loss):
            inconsistencies.append('cell_losses_missing_from_unit_summary:' + unit_id)
        normalized_list.append(replace(unit, loss=tuple(sorted(set(unit.loss) | cell_losses))))
    normalized = tuple(normalized_list)
    summary = table_summarise_loss(normalized)
    producer = snapshot['producer']
    diag = snapshot['diagnostics']
    for key in ('backend_id', 'backend_version'):
        if producer.get(key) and diag.get(key) and producer[key] != diag[key]:
            inconsistencies.append('run_producer_disagreement:' + key)
        if not producer.get(key) or not diag.get(key):
            unknown.append('run_producer_unknown:' + key)
    if producer.get('skill_id') != run.skill_id:
        inconsistencies.append('run_skill_id_disagreement')
    if not run.artifact:
        unknown.append('artifact_unavailable')
    if not normalized:
        unknown.append('no_units_observed')
    if diag['errors']:
        unknown.append('run_errors')
    declared = set(diag['known_collapse_risks'])
    surfaced = set(diag['observed_loss_kinds']) | set(summary)
    unsurfaced = set(run.unsurfaced_risks)
    # Retain canonical assessment, plus strict visibility of declarations that
    # canonical logic exempts when an unsupported capability is declared.
    unsurfaced.update(declared - surfaced)
    for kind in sorted((declared | surfaced) - set(TableLossKind.ALL)):
        unknown.append('unknown_loss_kind:' + kind)
    for unit in normalized:
        for key in ('skill_id', 'skill_version', 'backend_id', 'backend_version', 'run_id'):
            actual, expected = getattr(unit.producer, key), producer.get(key)
            if actual is not None and expected is not None and actual != expected:
                inconsistencies.append('unit_producer_disagreement:' + unit.unit_id + ':' + key)
        if not unit.provenance_is_recorded:
            unknown.append('unit_provenance_unavailable:' + unit.unit_id)
        elif run.artifact and unit.provenance != run.artifact.content_digest:
            inconsistencies.append('unit_provenance_mismatch:' + unit.unit_id)
        if run.artifact and unit.artifact_id != run.artifact.artifact_id:
            inconsistencies.append('unit_artifact_mismatch:' + unit.unit_id)
        if unit.self_errors:
            unknown.append('unit_errors:' + unit.unit_id)
        if not unit.producer.backend_id or not unit.producer.backend_version:
            unknown.append('unit_producer_unknown:' + unit.unit_id)
    if len({u.source_id for u in normalized}) > 1:
        inconsistencies.append('conflicting_source_ids')
    for kind in (TableLossKind.UNKNOWN, TableLossKind.NOT_DETECTED, TableLossKind.UNSUPPORTED, TableLossKind.FAILED):
        if kind in surfaced:
            unknown.append('unresolved_loss:' + kind)
    unknown.extend('unsurfaced_risk:' + x for x in unsurfaced)
    unknown.extend('unsupported_capability:' + x for x in diag['unsupported_capabilities'])
    justified = run.is_complete_success and not (inconsistencies or unknown)
    return _identify(LossAccountingResult('luohai-loss-accounting/1.0.0', 'ACCOUNT_LOSS',
        'inconsistent' if inconsistencies else ('unknown' if unknown else 'accounted'),
        input_digest, summary, tuple(dict(unit_id=u.unit_id, loss=list(u.loss),
            cell_loss_declarations=list(cell_declarations[u.unit_id]),
            self_errors=list(u.self_errors)) for u in normalized),
        tuple(sorted(declared)), tuple(sorted(unsurfaced)),
        tuple(sorted(set(diag['unsupported_capabilities']))), tuple(sorted(set(inconsistencies))),
        tuple(sorted(set(unknown))), run.is_complete_success, justified, diag))


RECONSTRUCT_VERIFY = reconstruct_verify
ACCOUNT_LOSS = account_loss
