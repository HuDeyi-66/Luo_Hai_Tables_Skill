"""``LuoHai.TabularEvidence`` -- first Skill engineering experiment (V2.1).

Read-only tabular evidence extraction from a registered XLSX artifact.

Pipeline position
-----------------
::

    registered TableArtifact
            |
        Skill (this module)
            |
        TableRunResult
            |
        TableEvidenceUnit[]

Design commitments taken from the V2.1 architecture review
---------------------------------------------------------
1. **Explicit wiring.** The backend is injected through the constructor or the
   ``backends`` option. There is no scanning, registry or dynamic loading.
2. **Known loss is declared, not discovered.** A backend that is known to
   conflate two states declares that up front, and a run that never surfaces
   the declared signal is downgraded (``TableRunResult.unsurfaced_risks``). This is
   the mechanism that stops a silent-loss fixture from being reported as a
   clean success.
3. **Fallback is recorded, never silent.** If the preferred backend is
   unavailable or fails, the fallback appears in ``diagnostics.fallbacks``
   *and* on every unit's ``producer.fallback_used``.
4. **Unsupported is a result, not an exception.** A missing dependency
   produces ``TableRunResult`` errors and a capability statement, not a crash.
5. **One unit per located thing.** Each table region becomes one
   ``TableEvidenceUnit`` with a generic Core address and Skill-owned worksheet/range
   context. The worksheet itself becomes a container unit only when it has no
   detectable region, so empty sheets are still represented.
"""

from __future__ import annotations

import uuid
from .ooxml import XlsxPackageError
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Sequence

from .contracts import TableArtifact
from .contracts import (
    TableCitationAddress,
    TableEvidenceUnit,
    TableLossKind,
    TableProducer,
    TableUnitClass,
)
from .contracts import (
    TableCapability,
    TableEvidenceSkill,
    TableRunDiagnostics,
    TableRunResult,
    TableSupport,
)

from . import ooxml
from .backends import (
    FixtureXlsxBackend,
    ObservedSheet,
    ObservedWorkbook,
    TabularBackend,
)
from .table import TableRegion, detect_regions, is_populated

__all__ = ["TabularEvidenceSkill", "DEFAULT_OPTIONS"]

DEFAULT_OPTIONS: Mapping[str, Any] = {
    "gap_tolerance": 0,
    "sheet_names": None,
    "emit_worksheet_units": True,
    "backends": None,
    "fail_closed": False,
    "first_row_is_header": True,
}

#: Text/capability inventory of the Skill itself, independent of backend.
_SKILL_CAPABILITIES: tuple[TableCapability, ...] = (
    TableCapability(
        name="tabular_evidence_units",
        support=TableSupport.SUPPORTED,
        detail="one TableEvidenceUnit per detected table region, with a generic Core "
               "address and Skill-owned worksheet/range context",
    ),
    TableCapability(
        name="citation_reconstruction",
        support=TableSupport.SUPPORTED,
        detail="payload carries per-cell addresses, row labels and column "
               "headers sufficient to rebuild a unique cell or range citation",
    ),
    TableCapability(
        name="range_location",
        support=TableSupport.SUPPORTED,
        detail="a rectangular range resolves to a RangeCitation covering every "
               "coordinate in it, including empty, absent and merged cells; a "
               "range that cannot be described completely is unresolved",
    ),
    TableCapability(
        name="confidence_scoring",
        support=TableSupport.UNSUPPORTED,
        detail="V2.1 records uncertainty/loss states but does not score or rank "
               "evidence",
    ),
    TableCapability(
        name="declared_table_observation",
        support=TableSupport.PARTIAL,
        detail="OOXML table parts (xl/tables) are read and compared with the "
               "inferred table context, reporting agreement / disagreement / "
               "unavailable. Observation only: declared metadata never "
               "overrides inferred boundaries and is not used as a table "
               "persistent identity, and it is not yet carried on evidence "
               "(skills/TODO.md)",
    ),
    TableCapability(
        name="csv_read",
        support=TableSupport.UNSUPPORTED,
        detail="first slice is XLSX only, by architecture decision",
    ),
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _duplicates(values: Iterable[Any]) -> list[Any]:
    """Values that occur more than once, ignoring ``None``. Stable order."""
    counts: dict[Any, int] = {}
    for value in values:
        if value is None:
            continue
        counts[value] = counts.get(value, 0) + 1
    return sorted((v for v, n in counts.items() if n > 1), key=lambda v: str(v))


def _merge_anchor_index(sheet: ObservedSheet) -> dict[str, str]:
    """Map every merge-covered address to its anchor address.

    A covered coordinate usually has no cell element of its own, so without
    this the extractor would report it as ``absent`` when in truth its value is
    supplied by the merge.
    """
    index: dict[str, str] = {}
    for span in sheet.merged_ranges:
        text = str(span)
        if ":" not in text:
            continue
        start_ref, end_ref = text.split(":", 1)
        try:
            start_row, start_col = ooxml.parse_cell_reference(start_ref)
            end_row, end_col = ooxml.parse_cell_reference(end_ref)
        except ValueError:
            continue
        for row in range(start_row, end_row + 1):
            for col in range(start_col, end_col + 1):
                address = ooxml.format_cell_reference(row, col)
                if address != start_ref.upper():
                    index[address] = start_ref.upper()
    return index


def _overlapping_merges(sheet: ObservedSheet, region: TableRegion) -> list[str]:
    """Merge ranges that intersect the region, so context can report them."""
    overlapping: list[str] = []
    for merge in sheet.merged_ranges:
        text = str(merge)
        start = text.split(":", 1)[0]
        try:
            start_row, start_col = ooxml.parse_cell_reference(start)
        except ValueError:
            continue
        end_part = text.split(":", 1)[1] if ":" in text else start
        try:
            end_row, end_col = ooxml.parse_cell_reference(end_part)
        except ValueError:
            continue
        if (
            start_row <= region.max_row
            and end_row >= region.min_row
            and start_col <= region.max_col
            and end_col >= region.min_col
        ):
            overlapping.append(text)
    return sorted(overlapping)


def _build_table_context(
    artifact: TableArtifact,
    sheet: ObservedSheet,
    region: TableRegion,
    payload_block: Mapping[str, Any],
) -> dict[str, Any]:
    """EXPERIMENTAL (V2.1.1) table context for one detected region.

    The recommended shape from the task: ``container`` / ``boundary`` /
    ``context_hint``. The candidate hints (A/B/C) are attached alongside so the
    experiment can be evaluated without freezing a schema.

    Imported lazily: ``table_context`` imports this module's backend types, so
    a module-level import would be circular.
    """
    from . import table_context

    context = table_context.build_table_context(
        payload_block,
        hidden_rows=payload_block.get("hidden_rows", ()),
        hidden_columns=payload_block.get("hidden_columns", ()),
        merged_ranges=payload_block.get("merged_ranges", ()),
    )
    return {
        "experimental": True,
        "unfrozen": True,
        "container": {
            "artifact_id": artifact.artifact_id,
            "sheet_name": sheet.name,
            "sheet_index": sheet.index,
            "sheet_state": sheet.state,
            "region_id": region.region_id,
        },
        "boundary": {
            "kind": "detected_rectangle",
            "declared": False,
            "bounds": region.bounds,
            "header_row": region.header_row,
            "label_column_index": region.min_col,
            "header_row_values": context.values["header_row_values"],
            "header_column_values": context.values["header_column_values"],
            "ragged_rows": list(region.ragged_rows),
            "hidden_rows": list(payload_block.get("hidden_rows", ())),
            "hidden_columns": list(payload_block.get("hidden_columns", ())),
            "merged_ranges": list(payload_block.get("merged_ranges", ())),
            "duplicate_column_headers": list(
                payload_block.get("duplicate_column_headers", ())
            ),
            "duplicate_row_labels": list(
                payload_block.get("duplicate_row_labels", ())
            ),
            "note": (
                "boundaries are detected from populated-cell layout, not declared "
                "by the workbook; no OOXML table part or named range is read"
            ),
        },
        "context_hints": {
            "A": context.candidate_a,
            "B": context.candidate_b,
            "C": context.candidate_c,
        },
        "context_values": context.values,
        "context_candidates": list(table_context.CANDIDATE_KEYS),
    }


@dataclass
class _BackendChoice:
    """Outcome of backend selection, including why a fallback happened."""

    backend: TabularBackend
    fallback_from: str | None = None
    fallback_reason: str | None = None


class TabularEvidenceSkill(TableEvidenceSkill):
    """Extract provisional EvidenceUnits from an XLSX artifact.

    Parameters
    ----------
    backend:
        Explicit backend injection. When omitted, ``options['backends']`` is
        consulted; when that is absent too, the deterministic stdlib backend is
        used. The experimental C06/C07 backend is available only by explicit
        injection, so installing an optional package cannot change evidence
        semantics.
    """

    skill_id = "LuoHai.TabularEvidence"
    skill_version = "0.1.2-provisional"

    def __init__(
        self,
        backend: TabularBackend | None = None,
        *,
        backends: Sequence[TabularBackend] | None = None,
        options: Mapping[str, Any] | None = None,
    ) -> None:
        self._explicit_backend = backend
        self._backends = tuple(backends) if backends is not None else None
        self._defaults = {**DEFAULT_OPTIONS, **dict(options or {})}

    # -- capability ------------------------------------------------------

    def capabilities(self) -> tuple[TableCapability, ...]:
        """Skill capabilities plus the capabilities of every candidate backend.

        Backend names are prefixed so a caller can tell which statement came
        from where. All candidates are listed because the statement describes
        what this Skill *can* do across its configured paths.
        """
        caps = list(_SKILL_CAPABILITIES)
        seen: set[tuple[str, str]] = set()
        for backend in self._candidate_backends({}):
            prefix = backend.backend_id
            for cap in backend.capabilities():
                key = (prefix, cap.name)
                if key in seen:
                    continue
                seen.add(key)
                caps.append(
                    TableCapability(
                        name=f"{prefix}:{cap.name}",
                        support=cap.support,
                        detail=cap.detail,
                        collapse_risks=cap.collapse_risks,
                    )
                )
        return tuple(caps)

    # -- run -------------------------------------------------------------

    def run(
        self,
        artifact: TableArtifact,
        *,
        source_id: str | None = None,
        options: Mapping[str, Any] | None = None,
        source: Any = None,
    ) -> TableRunResult:
        resolved_source_id = source_id or getattr(source, "source_id", None)
        run_id = f"run-{uuid.uuid4().hex[:12]}"
        started_at = _utc_now()

        diagnostics = TableRunDiagnostics(options_echo=dict(options or {}))
        producer = TableProducer(
            skill_id=self.skill_id,
            skill_version=self.skill_version,
            run_id=run_id,
            method="read_only_extract",
        )

        if not resolved_source_id:
            diagnostics.error(
                "missing_source_identity",
                "no source identity was supplied; evidence units cannot be "
                "traced to a registered source",
                fatal=True,
            )
            return TableRunResult(
                artifact=artifact,
                skill_id=self.skill_id,
                producer=producer,
                units=(),
                diagnostics=diagnostics,
                invocation_id=run_id,
                started_at=started_at,
                finished_at=_utc_now(),
            )

        merged = {**self._defaults, **dict(options or {})}
        path = artifact.location
        payload = getattr(artifact, "payload_bytes", None)
        if not path and payload is None:
            diagnostics.error(
                "artifact_has_no_location",
                "artifact carries no readable location; nothing can be read",
                fatal=True,
            )
            return self._finish(
                artifact, producer, diagnostics, run_id, started_at, ()
            )

        try:
            integrity_matches = artifact.verify_bytes(payload) if payload is not None else artifact.verify_file(path)
        except (OSError, ValueError) as exc:
            diagnostics.error(
                "artifact_integrity_check_failed",
                f"artifact bytes could not be verified before extraction: "
                f"{type(exc).__name__}: {exc}",
                scope=artifact.artifact_id,
                fatal=True,
            )
            return self._finish(
                artifact, producer, diagnostics, run_id, started_at, ()
            )
        if not integrity_matches:
            diagnostics.error(
                "artifact_integrity_mismatch",
                "artifact bytes do not match the registered content digest; "
                "extraction was refused",
                scope=artifact.artifact_id,
                fatal=True,
            )
            return self._finish(
                artifact, producer, diagnostics, run_id, started_at, ()
            )

        if artifact.media_type not in (
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "application/vnd.ms-excel.sheet.macroEnabled.12",
        ):
            diagnostics.warn(
                "media_type_not_xlsx",
                f"artifact media type is {artifact.media_type!r}; this slice only "
                f"claims XLSX support",
                scope=artifact.artifact_id,
            )

        choice = self._select_backend(merged, diagnostics)
        observation = self._safe_load(choice.backend, path, merged, diagnostics, payload)

        # A hard backend failure with another candidate available is a
        # fallback event, not a silent downgrade.
        if observation.fatal and not merged.get("fail_closed"):
            alternate = self._first_available_excluding(
                choice.backend.backend_id, merged
            )
            if alternate is not None:
                diagnostics.fallback(
                    from_backend=choice.backend.backend_id,
                    to_backend=alternate.backend_id,
                    reason="preferred backend reported a fatal load failure",
                    detail="; ".join(observation.errors) or None,
                )
                choice = _BackendChoice(
                    backend=alternate,
                    fallback_from=choice.backend.backend_id,
                    fallback_reason="preferred backend reported a fatal load failure",
                )
                observation = self._safe_load(alternate, path, merged, diagnostics, payload)

        try:
            units = self._build_units(
                artifact=artifact,
                source_id=resolved_source_id,
                observation=observation,
                producer=producer,
                merged=merged,
                diagnostics=diagnostics,
                fallback=choice,
            )
        except XlsxPackageError as exc:
            diagnostics.error("evidence_expansion_limit", str(exc), scope=artifact.artifact_id, fatal=True)
            return self._finish(artifact, producer, diagnostics, run_id, started_at, ())

        self._record_diagnostics(observation, choice, diagnostics, units)
        result = self._finish(
            artifact, producer, diagnostics, run_id, started_at, units
        )
        result.downgrade_for_declared_risk()
        return result

    # -- backend selection -----------------------------------------------

    def _candidate_backends(self, options: Mapping[str, Any]) -> tuple[TabularBackend, ...]:
        if self._explicit_backend is not None:
            return (self._explicit_backend,)
        if self._backends is not None:
            return self._backends
        injected = options.get("backends")
        if injected:
            return tuple(injected)
        # The default is intentionally independent of optional-package
        # availability. C06/C07 remains an explicit experimental backend.
        return (FixtureXlsxBackend(),)

    def _select_backend(
        self, options: Mapping[str, Any], diagnostics: TableRunDiagnostics
    ) -> _BackendChoice:
        candidates = self._candidate_backends(options)
        diagnostics.considered_backends = [b.backend_id for b in candidates]
        for backend in candidates:
            if backend.is_available():
                return _BackendChoice(backend=backend)
        # Nothing available: hand back the last candidate so the caller gets an
        # explicit, attributable failure rather than a silent empty result.
        unavailable = candidates[-1]
        diagnostics.error(
            "no_backend_available",
            "no candidate backend is usable in this interpreter: "
            + ", ".join(b.backend_id for b in candidates),
            fatal=True,
        )
        diagnostics.unsupported_capabilities.append("xlsx_read")
        return _BackendChoice(backend=unavailable)

    def _first_available_excluding(
        self, backend_id: str, options: Mapping[str, Any]
    ) -> TabularBackend | None:
        for backend in self._candidate_backends(options):
            if backend.backend_id == backend_id:
                continue
            if backend.is_available():
                return backend
        return None

    def _safe_load(
        self,
        backend: TabularBackend,
        path: str | None,
        options: Mapping[str, Any],
        diagnostics: TableRunDiagnostics,
        payload: bytes | None = None,
    ) -> ObservedWorkbook:
        """Call ``backend.load`` and convert an unexpected exception into evidence.

        A reader that raises is not allowed to become a traceback that the
        caller cannot attribute, nor an empty result that reads as success.

        Scope note: only ``Exception`` is caught here. A binding that raises a
        ``BaseException`` subclass (pyo3's ``PanicException``, for example) must
        be contained by its own adapter, because swallowing ``BaseException`` at
        this level would also swallow process-level interruption. That
        containment is implemented and documented in ``CalamineBackend``.
        """
        try:
            if payload is not None:
                loader = getattr(backend, "load_bytes", None)
                if not callable(loader):
                    raise ValueError("selected backend does not support byte input")
                return loader(payload, options)
            return backend.load(path, options)
        except Exception as exc:
            problem = f"{type(exc).__name__}: {exc}"
            diagnostics.error(
                "backend_raised",
                f"backend {backend.backend_id!r} raised an unexpected exception: "
                f"{problem}",
                scope=backend.backend_id,
                fatal=True,
            )
            return ObservedWorkbook(
                loss=(TableLossKind.FAILED,),
                errors=(f"backend_raised: {problem}",),
                fatal=True,
                backend_id=backend.backend_id,
                backend_version=backend.backend_version,
                backend_path=backend.backend_path,
            )

    # -- evidence construction -------------------------------------------

    def _build_units(
        self,
        *,
        artifact: TableArtifact,
        source_id: str,
        observation: ObservedWorkbook,
        producer: TableProducer,
        merged: Mapping[str, Any],
        diagnostics: TableRunDiagnostics,
        fallback: _BackendChoice,
    ) -> tuple[TableEvidenceUnit, ...]:
        units: list[TableEvidenceUnit] = []
        wanted = merged.get("sheet_names")
        gap_tolerance = int(merged.get("gap_tolerance", 0))
        emit_worksheet_units = bool(merged.get("emit_worksheet_units", True))

        for sheet in observation.sheets:
            if wanted and sheet.name not in wanted:
                continue

            if sheet.is_hidden:
                diagnostics.warn(
                    "hidden_sheet_present",
                    f"sheet {sheet.name!r} is {sheet.state}; it was read anyway",
                    scope=sheet.name,
                )

            regions, region_warnings = detect_regions(
                sheet, gap_tolerance=gap_tolerance
            )
            for warning in region_warnings:
                diagnostics.warn("region_ambiguity", warning, scope=sheet.name)

            if not regions:
                if emit_worksheet_units:
                    units.append(
                        self._worksheet_unit(
                            artifact=artifact,
                            source_id=source_id,
                            sheet=sheet,
                            producer=producer,
                            fallback=fallback,
                        )
                    )
                continue

            for region in regions:
                units.append(
                    self._region_unit(
                        artifact=artifact,
                        source_id=source_id,
                        sheet=sheet,
                        region=region,
                        producer=producer,
                        fallback=fallback,
                    )
                )

        return tuple(units)

    def _producer_for(self, producer: TableProducer, fallback: _BackendChoice) -> TableProducer:
        backend = fallback.backend
        return TableProducer(
            skill_id=producer.skill_id,
            skill_version=producer.skill_version,
            backend_id=backend.backend_id,
            backend_version=backend.backend_version,
            run_id=producer.run_id,
            method=producer.method,
            fallback_used=fallback.fallback_from is not None,
            fallback_reason=fallback.fallback_reason,
        )

    def _worksheet_unit(
        self,
        *,
        artifact: TableArtifact,
        source_id: str,
        sheet: ObservedSheet,
        producer: TableProducer,
        fallback: _BackendChoice,
    ) -> TableEvidenceUnit:
        """A sheet with no detectable table region.

        This is where ``EMPTY`` and ``ABSENT`` for a whole sheet are made
        explicit. A sheet that exists and holds nothing is ``empty``; a sheet
        that is itself missing cannot be produced here at all, so the caller
        must treat its absence from the unit list as ``absent`` -- recorded in
        ``metadata.represented_sheets``.
        """
        cell_loss: list[str] = []
        for cell in sheet.cells.values():
            cell_loss.extend(cell.loss)
        loss = list(sheet.loss)
        if not sheet.cells:
            loss.append(TableLossKind.EMPTY)
        elif not any(is_populated(c) for c in sheet.cells.values()):
            loss.append(TableLossKind.EMPTY)
        loss.extend(cell_loss)

        ref = ooxml.format_cell_reference(1, 1)
        address = TableCitationAddress(
            kind="container_location",
            value=ref,
            container_id=f"worksheet:{sheet.name}",
            container_label=sheet.name,
            context_path=(f"sheet:{sheet.name}", f"cell:{ref}"),
        )
        return TableEvidenceUnit(
            unit_id=f"{artifact.artifact_id}:{sheet.name}:worksheet",
            unit_class=TableUnitClass.CONTAINER,
            source_id=source_id,
            artifact_id=artifact.artifact_id,
            producer=self._producer_for(producer, fallback),
            address=address,
            content={"sheet_name": sheet.name, "cell_count": len(sheet.cells)},
            content_raw=None,
            content_rendered=None,
            provenance=artifact.content_digest,
            loss=tuple(dict.fromkeys(loss)),
            self_warnings=sheet.notes,
            payload={
                "worksheet": {
                    "sheet_name": sheet.name,
                    "sheet_index": sheet.index,
                    "state": sheet.state,
                    "cell_count": len(sheet.cells),
                    "unread_note": "no table region was detected on this worksheet",
                }
            },
            metadata={"represented_sheets": [sheet.name]},
        )

    def _region_unit(
        self,
        *,
        artifact: TableArtifact,
        source_id: str,
        sheet: ObservedSheet,
        region: TableRegion,
        producer: TableProducer,
        fallback: _BackendChoice,
    ) -> TableEvidenceUnit:
        header_row = region.header_row
        column_headers: dict[int, Any] = {}
        for col in range(region.min_col, region.max_col + 1):
            cell = sheet.cells.get(ooxml.format_cell_reference(header_row, col))
            column_headers[col] = None if cell is None else cell.value

        row_labels: dict[int, Any] = {}
        for row in range(region.min_row, region.max_row + 1):
            cell = sheet.cells.get(ooxml.format_cell_reference(row, region.min_col))
            row_labels[row] = None if cell is None else cell.value

        cells: list[dict[str, Any]] = []
        first_data_row = header_row + 1
        merge_anchors = _merge_anchor_index(sheet)
        for row in range(region.min_row, region.max_row + 1):
            for col in range(region.min_col, region.max_col + 1):
                ref = ooxml.format_cell_reference(row, col)
                cell = sheet.cells.get(ref)
                if cell is None:
                    # Coordinate inside the declared bounds with no cell at all.
                    # It may still be *covered by a merge*, in which case its
                    # value comes from the merge anchor and calling it absent
                    # would be wrong.
                    anchor = merge_anchors.get(ref)
                    loss = [TableLossKind.ABSENT]
                    notes = ["no cell element at this inside-bounds address"]
                    value_kind = "absent"
                    value = None
                    if anchor is not None:
                        value_kind = "merged"
                        notes = [f"coordinate is covered by merged range from {anchor}"]
                    cells.append(
                        {
                            "ref": ref,
                            "row": row,
                            "column": col,
                            "value": value,
                            "value_kind": value_kind,
                            "formula": None,
                            "loss": loss,
                            "notes": notes,
                            "merged_from": anchor,
                            "hidden": row in sheet.hidden_rows
                            or col in sheet.hidden_columns,
                            "is_header": row == header_row,
                            "row_label": row_labels.get(row),
                            "column_label": column_headers.get(col),
                        }
                    )
                    continue
                cells.append(
                    {
                        "ref": cell.ref,
                        "row": cell.row,
                        "column": cell.column,
                        "value": cell.value,
                        "value_kind": cell.value_kind,
                        "formula": cell.formula,
                        "loss": list(cell.loss),
                        "notes": list(cell.notes),
                        "merged_from": cell.merged_from,
                        "hidden": cell.hidden,
                        "is_header": row == header_row,
                        "row_label": row_labels.get(row),
                        "column_label": column_headers.get(col),
                    }
                )

        rows: dict[str, dict[str, Any]] = {}
        for row in range(region.min_row, region.max_row + 1):
            row_cells: dict[str, Any] = {}
            for col in range(region.min_col, region.max_col + 1):
                ref = ooxml.format_cell_reference(row, col)
                match = next((c for c in cells if c["ref"] == ref), None)
                if match is None:
                    continue
                row_cells[ooxml.column_index_to_letter(col)] = {
                    "ref": match["ref"],
                    "value": match["value"],
                    "value_kind": match["value_kind"],
                    "loss": match["loss"],
                    "hidden": match["hidden"],
                }
            rows[str(row)] = {
                "row": row,
                "row_label": row_labels.get(row),
                "is_header": row == header_row,
                "cells": row_cells,
            }

        payload_block = {
            "region_id": region.region_id,
            "bounds": region.bounds,
            "sheet_name": sheet.name,
            "sheet_index": sheet.index,
            "sheet_state": sheet.state,
            "header_row": header_row,
            "first_data_row": first_data_row,
            "label_column_index": region.min_col,
            "label_cell_ref": region.label_cell_ref,
            "label_cell_value": region.label_cell_value,
            "column_headers": {
                ooxml.column_index_to_letter(col): value
                for col, value in column_headers.items()
            },
            "row_labels": {str(row): value for row, value in row_labels.items()},
            "rows": rows,
            "cells": cells,
            "ragged_rows": list(region.ragged_rows),
            "empty_cells": list(region.empty_cells),
            "absent_cells": list(region.absent_cells),
        }

        content = {
            "sheet_name": sheet.name,
            "bounds": region.bounds,
            "header_row": header_row,
            "column_headers": [
                column_headers.get(col) for col in sorted(column_headers)
            ],
            "data_row_count": max(region.max_row - first_data_row + 1, 0),
            "column_count": region.width,
        }

        address = TableCitationAddress(
            kind="content_location",
            value=ooxml.format_cell_reference(region.min_row, region.min_col),
            container_id=region.region_id,
            container_label=region.label_cell_value or sheet.name,
            context_path=(
                f"sheet:{sheet.name}",
                f"region:{region.bounds}",
                f"header_row:{header_row}",
            ),
        )

        unit_loss = list(region.loss)
        for cell in cells:
            unit_loss.extend(cell["loss"])

        payload_block["hidden_rows"] = sorted(
            r for r in sheet.hidden_rows if region.min_row <= r <= region.max_row
        )
        payload_block["hidden_columns"] = sorted(
            c for c in sheet.hidden_columns if region.min_col <= c <= region.max_col
        )
        payload_block["merged_ranges"] = _overlapping_merges(sheet, region)
        payload_block["duplicate_column_headers"] = _duplicates(
            column_headers.values()
        )
        payload_block["duplicate_row_labels"] = _duplicates(row_labels.values())
        payload_block["column_indices"] = {
            ooxml.column_index_to_letter(col): col for col in sorted(column_headers)
        }
        if region.min_col <= region.max_col:
            first_letter = ooxml.column_index_to_letter(region.min_col)
            last_letter = ooxml.column_index_to_letter(region.max_col)
            payload_block["column_letters"] = {
                "first": first_letter,
                "last": last_letter,
            }
        if payload_block["hidden_rows"] or payload_block["hidden_columns"]:
            unit_loss.append(TableLossKind.SILENT_LOSS_RISK)

        table_context = _build_table_context(artifact, sheet, region, payload_block)

        return TableEvidenceUnit(
            unit_id=f"{artifact.artifact_id}:{sheet.name}:{region.bounds}",
            unit_class=TableUnitClass.CONTENT,
            source_id=source_id,
            artifact_id=artifact.artifact_id,
            producer=self._producer_for(producer, fallback),
            address=address,
            content=content,
            content_raw={
                "note": "per-cell unformatted stored/cached values live in payload.tabular.cells.value"
            },
            content_rendered={
                "note": "rendered equal to raw; no number-format rendering in V2.1"
            },
            provenance=artifact.content_digest,
            loss=tuple(dict.fromkeys(unit_loss)),
            self_warnings=region.notes,
            payload={"tabular": payload_block},
            metadata={
                "representation": {
                    "kind": "worksheet_region",
                    "bounds": region.bounds,
                    "sheet_index": sheet.index,
                },
                "represented_sheets": [sheet.name],
                # EXPERIMENTAL (V2.1.1). Unfrozen, read-only by convention and
                # accessed through Skill-side helpers. Not a Core field.
                "table_context": table_context,
            },
        )

    # -- diagnostics -----------------------------------------------------

    def _record_diagnostics(
        self,
        observation: ObservedWorkbook,
        choice: _BackendChoice,
        diagnostics: TableRunDiagnostics,
        units: Sequence[TableEvidenceUnit],
    ) -> None:
        backend = choice.backend
        diagnostics.backend_id = backend.backend_id
        diagnostics.backend_version = backend.backend_version
        diagnostics.backend_path = backend.backend_path
        diagnostics.known_collapse_risks = list(
            getattr(backend, "DECLARED_COLLAPSE_RISKS", ()) or ()
        )

        # Observed loss comes from two places: what the backend recorded on the
        # cells it read, and the in-bounds coordinates that the extraction step
        # determined to be absent (those exist only once regions are known).
        observed: list[str] = list(observation.collect_observed_loss())
        for unit in units:
            block = (unit.payload or {}).get("tabular")
            if isinstance(block, Mapping):
                for cell in block.get("cells", ()):
                    if isinstance(cell, Mapping):
                        for kind in cell.get("loss", ()) or ():
                            if kind not in observed:
                                observed.append(kind)
        diagnostics.observed_loss_kinds = sorted(observed)

        for warning in observation.warnings:
            diagnostics.warn("backend_warning", warning, scope=backend.backend_id)
        for error in observation.errors:
            diagnostics.error(
                "backend_error", error, scope=backend.backend_id, fatal=observation.fatal
            )

        if not units:
            diagnostics.warn(
                "no_units_emitted",
                "the backend returned no sheets; nothing was extracted",
                scope=backend.backend_id,
            )

        for cap_name in self.unsupported_capability_names():
            if cap_name not in diagnostics.unsupported_capabilities:
                diagnostics.unsupported_capabilities.append(cap_name)
        for cap in backend.capabilities():
            if cap.support in (TableSupport.UNSUPPORTED, TableSupport.PARTIAL):
                name = f"{backend.backend_id}:{cap.name}"
                if name not in diagnostics.unsupported_capabilities:
                    diagnostics.unsupported_capabilities.append(name)

        represented = sorted(
            {
                sheet
                for unit in units
                for sheet in (unit.metadata.get("represented_sheets") or [])
            }
        )
        diagnostics.stats = {
            "unit_count": len(units),
            "workbook_date_system": observation.date_system,
            "display_value_semantics": "raw_or_cached_values_not_excel_formatted_display",
            "sheet_count": len(observation.sheets),
            "represented_sheets": represented,
            "unrepresented_sheets": sorted(
                s.name for s in observation.sheets if s.name not in represented
            ),
        }

    def _finish(
        self,
        artifact: TableArtifact,
        producer: TableProducer,
        diagnostics: TableRunDiagnostics,
        run_id: str,
        started_at: str,
        units: Sequence[TableEvidenceUnit],
    ) -> TableRunResult:
        return TableRunResult(
            artifact=artifact,
            skill_id=self.skill_id,
            producer=producer,
            units=tuple(units),
            diagnostics=diagnostics,
            invocation_id=run_id,
            started_at=started_at,
            finished_at=_utc_now(),
        )
