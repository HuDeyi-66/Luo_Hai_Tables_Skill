"""Citation reconstruction from an ``TableEvidenceUnit``.

This module is the payoff test for the whole slice. It answers one question:

    given an TableEvidenceUnit that claims to locate something, can an independent
    caller rebuild a *unique, checkable* citation to it -- or does the unit
    learn that it cannot?

It is not retrieval. It does not rank, search a corpus, or touch a vector
store. It reads a structured payload that the Skill already produced and
resolves a selector against it.

The fixture that motivates the design (``fixtures/truth/citation_truth.json``)
carries three distinct cells holding ``42`` and two rows labelled
``Shanghai``. Therefore:

* a bare value selector cannot resolve -- three candidates;
* a bare row-label selector cannot resolve -- two candidates;
* worksheet + bounds + row label + column header resolves exactly one cell;
* dropping the table context re-introduces the ambiguity.

The resolver returns ``Ambiguous`` or ``Unresolved`` rather than guessing. A
resolver that picks "the first match" would silently convert an ambiguous
evidence record into a confident wrong citation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .contracts import TableEvidenceUnit, TableLossKind

from . import ooxml
from .table_context import (
    TableCandidate,
    TableContextQuery,
    TableResolution,
    Unresolved,
    resolve_table_context,
    unit_context_hints,
    unit_table_context,
)

__all__ = [
    "CitationSelector",
    "ResolvedCell",
    "Citation",
    "CitationProblem",
    "TableCandidate",
    "TableResolution",
    "TableContextQuery",
    "Unresolved",
    "Ambiguous",
    "CONTEXT_CANDIDATES",
    "blocked_by_loss",
    "resolve_citation",
    "resolve_table_context",
    "iter_cells",
]

#: Candidate context keys understood by ``CitationSelector.context_hint``.
#: These mirror ``skills.table_context.CANDIDATE_KEYS``. Kept as a plain tuple
#: so a caller can validate a key without importing the experiment module.
CONTEXT_CANDIDATES: tuple[str, ...] = ("A", "B", "C")


class CitationProblem:
    """Why a citation could not be rebuilt."""

    NO_TABULAR_PAYLOAD = "no_tabular_payload"
    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    #: More than one *table* matched the requested context. Distinct from
    #: ``AMBIGUOUS``, which is about cells inside one table.
    TABLE_CONTEXT_AMBIGUOUS = "table_context_ambiguous"
    BLOCKED_BY_LOSS = "blocked_by_loss"
    MALFORMED_SELECTOR = "malformed_selector"

    ALL = (
        NO_TABULAR_PAYLOAD,
        UNRESOLVED,
        AMBIGUOUS,
        TABLE_CONTEXT_AMBIGUOUS,
        BLOCKED_BY_LOSS,
        MALFORMED_SELECTOR,
    )


@dataclass
class CitationSelector:
    """What the caller is trying to point at.

    ``require_table_context`` defaults to True on purpose. Turning it off is a
    deliberate act of accepting a weaker citation, and the resulting
    ``Citation`` records that it was weaker.
    """

    value: Any = None
    sheet_name: str | None = None
    region_id: str | None = None
    row_header: str | None = None
    column_header: str | None = None
    row_index: int | None = None
    column_index: int | None = None
    ref: str | None = None
    #: V2.2: a rectangular range, e.g. ``"B2:D5"`` or a single ``"C2"``. Resolved
    #: to a :class:`RangeCitation` carrying every coordinate in the rectangle,
    #: including empty, absent and merged ones.
    ref_range: str | None = None
    #: EXPERIMENTAL (V2.1.1). A table context hint produced by
    #: ``skills.luohai.table_context``, e.g.
    #: ``"sheet:CitationTable|range:A1:C3"``. When set, the resolver requires
    #: the *table* to be identified before it will locate a cell.
    context_hint: str | None = None
    require_table_context: bool = True
    first_row_is_header: bool = True
    #: When True, only cells whose ``value_kind`` matches the Python type of the
    #: requested value are considered. This is what makes "three cells hold the
    #: number 42" a testable claim instead of also matching the *text* "42".
    strict_value_kind: bool = True

    PROVISIONAL = True


@dataclass
class ResolvedCell:
    """One candidate coordinate inside a unit's payload."""

    sheet_name: str
    region_id: str
    region_bounds: str
    ref: str
    row_index: int
    column_index: int
    value: Any
    value_kind: str
    row_header: str | None
    column_header: str | None
    loss: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "sheet_name": self.sheet_name,
            "region_id": self.region_id,
            "region_bounds": self.region_bounds,
            "ref": self.ref,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "value": self.value,
            "value_kind": self.value_kind,
            "row_header": self.row_header,
            "column_header": self.column_header,
            "loss": list(self.loss),
            "notes": list(self.notes),
        }


@dataclass
class Citation:
    """A rebuilt, checkable citation.

    ``context_path`` is the human- and machine-readable disambiguation chain
    that makes the cell unique: artifact -> worksheet -> region -> row/column
    headers -> coordinate. ``uniqueness`` records which context was supplied
    so a consumer can tell a strong citation from a weak one.
    """

    artifact_id: str
    source_id: str
    unit_id: str
    sheet_name: str
    sheet_index: int | None
    region_id: str
    region_bounds: str
    ref: str
    row_index: int
    column_index: int
    value: Any
    value_kind: str
    row_header: str | None
    column_header: str | None
    context_path: tuple[str, ...]
    uniqueness: str  # "table_context" | "sheet_context"
    loss: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    producer_backend_id: str | None = None

    PROVISIONAL = True

    @property
    def is_weak(self) -> bool:
        """True when the citation was resolved without table context."""
        return self.uniqueness != "table_context"

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "source_id": self.source_id,
            "unit_id": self.unit_id,
            "sheet_name": self.sheet_name,
            "sheet_index": self.sheet_index,
            "region_id": self.region_id,
            "region_bounds": self.region_bounds,
            "ref": self.ref,
            "row_index": self.row_index,
            "column_index": self.column_index,
            "value": self.value,
            "value_kind": self.value_kind,
            "row_header": self.row_header,
            "column_header": self.column_header,
            "context_path": list(self.context_path),
            "uniqueness": self.uniqueness,
            "loss": list(self.loss),
            "notes": list(self.notes),
            "producer_backend_id": self.producer_backend_id,
        }


@dataclass
class RangeCitation:
    """A rebuilt citation to a *rectangular region of cells*.

    Cells are not covered by ``Citation``: a citation to ``B2:D5`` is a
    different kind of claim from a citation to one cell, and collapsing the two
    would let a consumer read a range as a point. This record therefore carries
    the whole rectangle plus a per-cell breakdown.

    Every coordinate inside the range is reported, including ones that are
    ``empty``, ``absent`` or ``merged``. A range citation with holes must show
    the holes rather than present a tidy grid, so ``cells`` always has exactly
    ``row_count * column_count`` entries.
    """

    artifact_id: str
    source_id: str
    unit_id: str
    sheet_name: str
    sheet_index: int | None
    region_id: str
    region_bounds: str
    ref: str  # normalized "B2:D5"
    range_start: str
    range_end: str
    min_row: int
    max_row: int
    min_col: int
    max_col: int
    cells: tuple[ResolvedCell, ...]
    context_path: tuple[str, ...]
    uniqueness: str
    loss: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    producer_backend_id: str | None = None

    PROVISIONAL = True

    @property
    def row_count(self) -> int:
        return self.max_row - self.min_row + 1

    @property
    def column_count(self) -> int:
        return self.max_col - self.min_col + 1

    @property
    def cell_count(self) -> int:
        return len(self.cells)

    @property
    def is_weak(self) -> bool:
        return self.uniqueness != "table_context"

    @property
    def lossy_cells(self) -> tuple[ResolvedCell, ...]:
        """Cells in the range that are not simply present.

        The test for "is this range fully populated" is deliberately about the
        cell's own state, not about whether any loss kind was attached.
        """
        return tuple(
            cell
            for cell in self.cells
            if cell.loss or cell.value_kind in ("empty", "absent", "merged")
        )

    @property
    def values(self) -> tuple[tuple[Any, ...], ...]:
        """The range as a dense grid, row-major, holes included."""
        grid: list[list[Any]] = []
        by_ref = {cell.ref: cell for cell in self.cells}
        for row in range(self.min_row, self.max_row + 1):
            row_values: list[Any] = []
            for col in range(self.min_col, self.max_col + 1):
                ref = ooxml.format_cell_reference(row, col)
                cell = by_ref.get(ref)
                row_values.append(None if cell is None else cell.value)
            grid.append(row_values)
        return tuple(tuple(r) for r in grid)

    def as_dict(self) -> dict[str, Any]:
        return {
            "artifact_id": self.artifact_id,
            "source_id": self.source_id,
            "unit_id": self.unit_id,
            "sheet_name": self.sheet_name,
            "sheet_index": self.sheet_index,
            "region_id": self.region_id,
            "region_bounds": self.region_bounds,
            "ref": self.ref,
            "range_start": self.range_start,
            "range_end": self.range_end,
            "min_row": self.min_row,
            "max_row": self.max_row,
            "min_col": self.min_col,
            "max_col": self.max_col,
            "row_count": self.row_count,
            "column_count": self.column_count,
            "cell_count": self.cell_count,
            "values": [list(row) for row in self.values],
            "cells": [cell.as_dict() for cell in self.cells],
            "context_path": list(self.context_path),
            "uniqueness": self.uniqueness,
            "loss": list(self.loss),
            "lossy_cells": [cell.ref for cell in self.lossy_cells],
            "notes": list(self.notes),
            "producer_backend_id": self.producer_backend_id,
        }


@dataclass
class Ambiguous:
    """Several candidates matched; the citation is NOT decided."""

    unit_id: str
    problem: str
    message: str
    candidates: tuple[ResolvedCell, ...] = ()
    candidate_refs: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "ambiguous",
            "unit_id": self.unit_id,
            "problem": self.problem,
            "message": self.message,
            "candidates": [c.as_dict() for c in self.candidates],
            "candidate_refs": list(self.candidate_refs),
        }


def _region_block(unit: TableEvidenceUnit) -> Mapping[str, Any] | None:
    payload = unit.payload or {}
    block = payload.get("tabular")
    if not isinstance(block, Mapping):
        return None
    return block


def blocked_by_loss(unit: TableEvidenceUnit) -> str | None:
    """Return a reason string when the unit cannot support a citation.

    A unit that already reports ``FAILED`` or ``SILENT_LOSS_RISK`` must not be
    used to produce a confident citation.
    """
    if TableLossKind.FAILED in unit.loss:
        return "unit reports extraction failure"
    if unit.self_errors:
        return "unit carries an extraction error"
    return None


def iter_cells(unit: TableEvidenceUnit) -> tuple[Mapping[str, Any], ...]:
    """Yield the cell dictionaries of a tabular payload, if any."""
    block = _region_block(unit)
    if block is None:
        return ()
    cells = block.get("cells")
    if not isinstance(cells, Sequence):
        return ()
    return tuple(c for c in cells if isinstance(c, Mapping))


def _has_positional_target(selector: CitationSelector) -> bool:
    """True when the selector says *which cell*, not only *which table*."""
    return any(
        value is not None
        for value in (
            selector.ref,
            selector.ref_range,
            selector.row_header,
            selector.column_header,
            selector.row_index,
            selector.column_index,
            selector.value,
        )
    )


def _parse_range(text: str) -> tuple[str, str, int, int, int, int]:
    """Normalize ``"B2:D5"`` (or ``"C2"``) to its corners and bounds.

    Raises ``ValueError`` with a caller-facing message on anything malformed.
    """
    cleaned = (text or "").strip().upper().replace("$", "")
    if not cleaned:
        raise ValueError("range is empty")
    parts = cleaned.split(":")
    if len(parts) > 2:
        raise ValueError(f"range has more than two corners: {text!r}")
    start = parts[0]
    end = parts[1] if len(parts) == 2 else parts[0]
    try:
        start_row, start_col = ooxml.parse_cell_reference(start)
        end_row, end_col = ooxml.parse_cell_reference(end)
    except ValueError as exc:
        raise ValueError(f"invalid range {text!r}: {exc}") from None

    # A reversed range is normalized rather than rejected: "D5:B2" names an
    # unambiguous rectangle, and silently reading it as empty would be worse.
    min_row, max_row = sorted((start_row, end_row))
    min_col, max_col = sorted((start_col, end_col))
    normalized_start = ooxml.format_cell_reference(min_row, min_col)
    normalized_end = ooxml.format_cell_reference(max_row, max_col)
    return (
        f"{normalized_start}:{normalized_end}",
        normalized_start,
        min_row,
        max_row,
        min_col,
        max_col,
    )


def _resolve_range(
    unit: TableEvidenceUnit,
    block: Mapping[str, Any],
    cells: tuple[Mapping[str, Any], ...],
    selector: CitationSelector,
    row_labels: Mapping[int, Any],
    column_labels: Mapping[int, Any],
) -> "RangeCitation | Unresolved":
    """Resolve a rectangular range to every coordinate it covers.

    There is no partial success. A range that falls outside the region, or that
    contains a coordinate the region cannot describe, is ``unresolved`` -- a
    range citation claiming four cells while holding three would be a silent
    loss of exactly the kind this project forbids.
    """
    try:
        normalized, start_ref, min_row, max_row, min_col, max_col = _parse_range(
            selector.ref_range or ""
        )
    except ValueError as exc:
        return Unresolved(
            unit_id=unit.unit_id,
            problem=CitationProblem.MALFORMED_SELECTOR,
            message=str(exc),
        )

    if not _ref_within(block, start_ref) or not _ref_within(
        block, ooxml.format_cell_reference(max_row, max_col)
    ):
        return Unresolved(
            unit_id=unit.unit_id,
            problem=CitationProblem.UNRESOLVED,
            message=(
                f"range {normalized} is not contained in region bounds "
                f"{block.get('bounds')!r}"
            ),
        )

    resolved: list[ResolvedCell] = []
    loss: list[str] = list(unit.loss)
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            ref = ooxml.format_cell_reference(row, col)
            found = next(
                (c for c in cells if str(c.get("ref", "")).upper() == ref), None
            )
            if found is None:
                # The region declares this coordinate but the package has no
                # cell for it: an explicit absent, not a skipped cell.
                cell = {
                    "ref": ref,
                    "row": row,
                    "column": col,
                    "value": None,
                    "value_kind": "absent",
                    "loss": [TableLossKind.ABSENT],
                    "notes": ["no cell element at this inside-bounds address"],
                }
            else:
                cell = found
            entry = _as_resolved(block, cell, row_labels, column_labels)
            resolved.append(entry)
            for kind in entry.loss:
                if kind not in loss:
                    loss.append(kind)

    notes: list[str] = []
    expected = (max_row - min_row + 1) * (max_col - min_col + 1)
    if len(resolved) != expected:
        # Defensive: the loop above cannot produce this, but a range citation
        # that under-reports its own cell count must fail loudly rather than
        # quietly look complete.
        return Unresolved(
            unit_id=unit.unit_id,
            problem=CitationProblem.UNRESOLVED,
            message=(
                f"range {normalized} resolved {len(resolved)} of {expected} "
                f"expected coordinates"
            ),
        )
    holes = [c.ref for c in resolved if c.value_kind in ("empty", "absent", "merged")]
    if holes:
        notes.append(
            f"{len(holes)} coordinate(s) in this range are not simply present: "
            f"{holes}"
        )
    if selector.require_table_context and not (selector.region_id or selector.sheet_name):
        notes.append("range resolved without an explicit table context")

    sheet_name = str(block.get("sheet_name"))
    citation = RangeCitation(
        artifact_id=unit.artifact_id,
        source_id=unit.source_id,
        unit_id=unit.unit_id,
        sheet_name=sheet_name,
        sheet_index=block.get("sheet_index"),
        region_id=str(block.get("region_id")),
        region_bounds=str(block.get("bounds")),
        ref=normalized,
        range_start=ooxml.format_cell_reference(min_row, min_col),
        range_end=ooxml.format_cell_reference(max_row, max_col),
        min_row=min_row,
        max_row=max_row,
        min_col=min_col,
        max_col=max_col,
        cells=tuple(resolved),
        context_path=(
            f"artifact:{unit.artifact_id}",
            f"source:{unit.source_id}",
            f"sheet:{sheet_name}",
            f"region:{block.get('region_id')}",
            f"range:{normalized}",
        ),
        uniqueness=_uniqueness(selector),
        loss=tuple(loss),
        notes=tuple(notes),
        producer_backend_id=unit.producer.backend_id,
    )
    return citation


def _selector_invalid(selector: CitationSelector) -> str | None:
    if not _has_positional_target(selector):
        return "selector is empty; it cannot identify anything"
    if (
        selector.row_header is not None
        and selector.require_table_context
        and not (selector.sheet_name or selector.region_id or selector.context_hint)
    ):
        return (
            "a header-only selector cannot be unique across a workbook; supply "
            "sheet_name, region_id or an context_hint, or set "
            "require_table_context=False and resolve unit by unit to see the "
            "ambiguity explicitly"
        )
    if (
        selector.column_header is not None
        and selector.require_table_context
        and not (selector.sheet_name or selector.region_id or selector.context_hint)
    ):
        return (
            "a column-header-only selector cannot be unique across a workbook; "
            "supply sheet_name, region_id or an context_hint, or set "
            "require_table_context=False and resolve unit by unit"
        )
    return None


def _context_hints(unit: TableEvidenceUnit) -> Mapping[str, Any] | None:
    """The candidate context hints a unit carries, or ``None``.

    Reads the experimental ``metadata["table_context"]`` convention through a
    Skill-side helper. Core is not involved: this module never asks
    ``TableEvidenceUnit`` for anything table-shaped, and never writes to a unit.
    """
    return unit_context_hints(unit)


def _table_candidate(
    unit: TableEvidenceUnit, candidate: str, hint: str, score: str
) -> TableCandidate:
    context = unit_table_context(unit) or {}
    values = context.get("context_values") or {}
    container = context.get("container") or {}
    boundary = context.get("boundary") or {}
    return TableCandidate(
        unit_id=unit.unit_id,
        region_id=unit.address.container_id or "",
        sheet_name=str(container.get("sheet_name") or ""),
        bounds=str(boundary.get("bounds") or ""),
        candidate=candidate,
        context_hint=hint,
        score=score,
        header_row_values=tuple(values.get("header_row_values") or ()),
    )


def _label_maps(
    block: Mapping[str, Any], cell: Mapping[str, Any]
) -> tuple[Mapping[int, Any], Mapping[int, Any]]:
    """Build ``(row_label_by_row, column_label_by_column)`` for the region.

    The canonical label of a row is the value in the region's *label column*;
    the canonical label of a column is the value in the region's *header row*.
    Each cell also carries a denormalised copy of those labels, but matching
    against the copy would let a data cell masquerade as its own row group, so
    the lookup tables are what the resolver uses.
    """
    rows_block = block.get("rows")
    label_column = block.get("label_column_index")
    header_row = block.get("header_row")

    row_labels: dict[int, Any] = {}
    for key, row in (rows_block or {}).items():
        if not isinstance(row, Mapping):
            continue
        label_cells = row.get("cells")
        label = None
        if isinstance(label_cells, Mapping) and label_column is not None:
            entry = label_cells.get(ooxml.column_index_to_letter(int(label_column)))
            if isinstance(entry, Mapping):
                label = entry.get("value")
        row_labels[int(row.get("row", key))] = label

    column_labels: dict[int, Any] = {}
    if isinstance(rows_block, Mapping) and header_row is not None:
        header = rows_block.get(str(header_row))
        if isinstance(header, Mapping):
            for letter, entry in (header.get("cells") or {}).items():
                if isinstance(entry, Mapping):
                    column_labels[ooxml.column_letter_to_index(letter)] = entry.get(
                        "value"
                    )
    return row_labels, column_labels


def _matches(
    cell: Mapping[str, Any],
    selector: CitationSelector,
    region: Mapping[str, Any],
    row_labels: Mapping[int, Any],
    column_labels: Mapping[int, Any],
) -> bool:
    # The header row supplies labels; it is not itself a data row. Matching it
    # as one would make ``row_header="Port"`` a hit, which is a category error.
    if selector.first_row_is_header and cell.get("is_header"):
        return False
    if selector.ref is not None:
        if str(cell.get("ref", "")).upper() != selector.ref.upper():
            return False
    if selector.row_index is not None and cell.get("row") != selector.row_index:
        return False
    if selector.column_index is not None and cell.get("column") != selector.column_index:
        return False
    if selector.row_header is not None:
        label = row_labels.get(int(cell.get("row", 0)))
        if label is None or str(label) != selector.row_header:
            return False
    if selector.column_header is not None:
        header = column_labels.get(int(cell.get("column", 0)))
        if header is None or str(header) != selector.column_header:
            return False
    if selector.value is not None:
        cell_kind = str(cell.get("value_kind", ""))
        allowed = _expected_kinds(selector.value)
        if allowed:
            if selector.strict_value_kind:
                if cell_kind not in allowed:
                    return False
            elif cell_kind in ("empty", "absent", "empty_or_collapsed"):
                return False
        if not _value_matches(cell.get("value"), selector.value, selector.strict_value_kind):
            return False
    return True


def _expected_kinds(value: Any) -> tuple[str, ...]:
    """Value kinds a Python literal of this type is allowed to match."""
    if isinstance(value, bool):
        return ("boolean",)
    if isinstance(value, (int, float)):
        return ("number",)
    if isinstance(value, str):
        return ("string", "inline_string")
    return ()


def _value_matches(actual: Any, expected: Any, strict_kind: bool = True) -> bool:
    """Equality that never lets a textual cell stand in for a number.

    A cell containing the *text* ``"42"`` is not the number 42 and must not
    satisfy a numeric query. Kind strictness makes that distinction explicit
    rather than incidental.
    """
    if isinstance(actual, bool) != isinstance(expected, bool):
        return False
    if isinstance(actual, str) and isinstance(expected, (int, float)) and not isinstance(expected, bool):
        return False
    if isinstance(actual, (int, float)) and isinstance(expected, str):
        return False
    if actual == expected:
        return True
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if isinstance(actual, bool) or isinstance(expected, bool):
            return actual is expected
        return float(actual) == float(expected)
    return False


def resolve_citation(
    unit: TableEvidenceUnit,
    selector: CitationSelector,
) -> Citation | Ambiguous | Unresolved:
    """Rebuild a citation from one unit, or explain why it cannot be rebuilt."""
    problem = _selector_invalid(selector)
    if problem:
        return Unresolved(
            unit_id=unit.unit_id,
            problem=CitationProblem.MALFORMED_SELECTOR,
            message=problem,
        )

    block = _region_block(unit)
    if block is None:
        return Unresolved(
            unit_id=unit.unit_id,
            problem=CitationProblem.NO_TABULAR_PAYLOAD,
            message="unit carries no tabular payload to resolve against",
        )

    block_reason = blocked_by_loss(unit)
    if block_reason and selector.ref is None:
        # A whole-unit failure blocks positional resolution, but an explicit
        # address request still gets a precise, loss-aware answer below.
        return Unresolved(
            unit_id=unit.unit_id,
            problem=CitationProblem.BLOCKED_BY_LOSS,
            message=block_reason,
        )

    # EXPERIMENTAL (V2.1.1): the context hint must match this unit's table.
    if selector.context_hint is not None:
        hints = _context_hints(unit)
        hint_values = {str(v) for v in (hints or {}).values()}
        if selector.context_hint not in hint_values:
            return Unresolved(
                unit_id=unit.unit_id,
                problem=CitationProblem.UNRESOLVED,
                message=(
                    f"unit {unit.address.container_id!r} does not match the "
                    f"requested table context"
                ),
            )
        if not _has_positional_target(selector):
            return Unresolved(
                unit_id=unit.unit_id,
                problem=CitationProblem.MALFORMED_SELECTOR,
                message=(
                    "the requested table is identified, but no cell within it "
                    "was requested; add a row/column header, a coordinate or a "
                    "value"
                ),
            )

    if selector.sheet_name is not None and selector.sheet_name != block.get("sheet_name"):
        return Unresolved(
            unit_id=unit.unit_id,
            problem=CitationProblem.UNRESOLVED,
            message=(
                f"unit is for sheet {block.get('sheet_name')!r}, selector asked "
                f"for {selector.sheet_name!r}"
            ),
        )
    if selector.region_id is not None and selector.region_id != block.get("region_id"):
        return Unresolved(
            unit_id=unit.unit_id,
            problem=CitationProblem.UNRESOLVED,
            message=(
                f"unit is for region {block.get('region_id')!r}, selector asked "
                f"for {selector.region_id!r}"
            ),
        )

    rows_block = block.get("rows") if isinstance(block.get("rows"), Mapping) else {}
    cells = iter_cells(unit)
    row_labels, column_labels = _label_maps(block, {})

    # V2.2: a range request resolves to a RangeCitation, never to a point. It is
    # handled before the single-cell paths so that handing back one cell could
    # never be mistaken for satisfying a range request.
    if selector.ref_range is not None:
        return _resolve_range(
            unit, block, cells, selector, row_labels, column_labels
        )

    if selector.ref is not None:
        target = selector.ref.upper()
        inside = _ref_within(block, target)
        found = next((c for c in cells if str(c.get("ref", "")).upper() == target), None)
        if found is not None:
            return _build(unit, block, found, selector, uniqueness=_uniqueness(selector))
        if inside:
            # The coordinate is inside the region bounds but has no cell: an
            # explicit 'absent' rather than a silent miss.
            loss = (TableLossKind.ABSENT,)
            synthetic = {
                "ref": target,
                "row": ooxml.parse_cell_reference(target)[0],
                "column": ooxml.parse_cell_reference(target)[1],
                "value": None,
                "value_kind": "absent",
                "loss": list(loss),
                "row_label": None,
                "column_label": None,
                "notes": ["coordinate lies inside the region but is not present"],
            }
            return _build(unit, block, synthetic, selector, uniqueness=_uniqueness(selector))
        return Unresolved(
            unit_id=unit.unit_id,
            problem=CitationProblem.UNRESOLVED,
            message=f"{target} is outside region bounds {block.get('bounds')!r}",
        )

    matched = [c for c in cells if _matches(c, selector, block, row_labels, column_labels)]

    if not matched:
        return Unresolved(
            unit_id=unit.unit_id,
            problem=CitationProblem.UNRESOLVED,
            message="no cell in this unit matches the selector",
        )
    if len(matched) > 1:
        return Ambiguous(
            unit_id=unit.unit_id,
            problem=CitationProblem.AMBIGUOUS,
            message=(
                f"{len(matched)} cells match; the citation is not decided. Add "
                f"table context (sheet_name/region_id) or a narrower selector."
            ),
            candidates=tuple(
                _as_resolved(block, c, row_labels, column_labels) for c in matched
            ),
            candidate_refs=tuple(str(c.get("ref")) for c in matched),
        )
    return _build(unit, block, matched[0], selector, uniqueness=_uniqueness(selector))


def _uniqueness(selector: CitationSelector) -> str:
    if selector.region_id or selector.sheet_name:
        return "table_context"
    return "sheet_context"


def _ref_within(block: Mapping[str, Any], ref: str) -> bool:
    bounds = block.get("bounds")
    if not isinstance(bounds, str) or ":" not in bounds:
        return False
    start, end = bounds.split(":", 1)
    try:
        row, col = ooxml.parse_cell_reference(ref)
        s_row, s_col = ooxml.parse_cell_reference(start)
        e_row, e_col = ooxml.parse_cell_reference(end)
    except ValueError:
        return False
    return s_row <= row <= e_row and s_col <= col <= e_col


def _as_resolved(
    block: Mapping[str, Any],
    cell: Mapping[str, Any],
    row_labels: Mapping[int, Any] | None = None,
    column_labels: Mapping[int, Any] | None = None,
) -> ResolvedCell:
    """A candidate coordinate, with labels resolved by coordinate."""
    if row_labels is None or column_labels is None:
        row_labels, column_labels = _label_maps(block, cell)
    return ResolvedCell(
        sheet_name=str(block.get("sheet_name")),
        region_id=str(block.get("region_id")),
        region_bounds=str(block.get("bounds")),
        ref=str(cell.get("ref")),
        row_index=int(cell.get("row", 0)),
        column_index=int(cell.get("column", 0)),
        value=cell.get("value"),
        value_kind=str(cell.get("value_kind", "unknown")),
        row_header=row_labels.get(int(cell.get("row", 0))),
        column_header=column_labels.get(int(cell.get("column", 0))),
        loss=tuple(cell.get("loss") or ()),
        notes=tuple(cell.get("notes") or ()),
    )


def _build(
    unit: TableEvidenceUnit,
    block: Mapping[str, Any],
    cell: Mapping[str, Any],
    selector: CitationSelector,
    *,
    uniqueness: str,
) -> Citation:
    resolved = _as_resolved(block, cell)
    sheet_name = str(block.get("sheet_name"))
    context_path = (
        f"artifact:{unit.artifact_id}",
        f"source:{unit.source_id}",
        f"sheet:{sheet_name}",
        f"region:{resolved.region_id}",
        f"row_header:{resolved.row_header}",
        f"column_header:{resolved.column_header}",
        f"cell:{resolved.ref}",
    )
    loss = tuple(dict.fromkeys((*unit.loss, *resolved.loss)))
    notes = list(resolved.notes)
    if uniqueness != "table_context":
        notes.append(
            "citation was resolved without declared table context; it is only "
            "unique if no other region in this artifact carries the same labels"
        )
    return Citation(
        artifact_id=unit.artifact_id,
        source_id=unit.source_id,
        unit_id=unit.unit_id,
        sheet_name=sheet_name,
        sheet_index=block.get("sheet_index"),
        region_id=resolved.region_id,
        region_bounds=resolved.region_bounds,
        ref=resolved.ref,
        row_index=resolved.row_index,
        column_index=resolved.column_index,
        value=resolved.value,
        value_kind=resolved.value_kind,
        row_header=resolved.row_header,
        column_header=resolved.column_header,
        context_path=context_path,
        uniqueness=uniqueness,
        loss=loss,
        notes=tuple(notes),
        producer_backend_id=unit.producer.backend_id,
    )
