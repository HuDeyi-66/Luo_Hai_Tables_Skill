"""Table-region detection over an ``ObservedSheet``.

Kept separate from the Skill so the heuristic can be tested and replaced
without touching evidence construction. The heuristic is deliberately simple
and its limits are declared in the capability statement rather than hidden:

* one contiguous rectangular region per worksheet;
* a gap of at most ``gap_tolerance`` blank rows splits sheets into components,
  and more than one component is reported as an ambiguity warning instead of
  being silently merged or silently dropped.

V2.1 does not claim general table recognition. Formal table context
(``table`` parts, named ranges, repeated headers) is on the TODO list.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from .contracts import TableLossKind

from .backends import ObservedCell, ObservedSheet
from . import ooxml

__all__ = [
    "TableRegion",
    "detect_regions",
    "is_populated",
    "region_ambiguity",
]


def is_populated(cell: ObservedCell) -> bool:
    """True when the cell carries table content.

    A cell counts as content when it holds any non-empty value, when it carries
    formula text, or when the backend recorded a non-blank *loss* about it
    (an error value, an unknown state, a merge). A cell that is merely
    ``empty`` or ``absent`` is a gap, not content -- that is what makes
    empty-vs-absent observable instead of self-fulfilling.
    """
    if cell.formula:
        return True
    if cell.value_kind == "error":
        return True
    if cell.loss:
        return not (set(cell.loss) <= {TableLossKind.EMPTY, TableLossKind.ABSENT})
    if cell.value is None:
        return False
    if isinstance(cell.value, str) and cell.value == "":
        return False
    return True


@dataclass
class TableRegion:
    """A rectangular candidate table inside one worksheet.

    ``region_id`` is a run-local container handle: worksheet plus bounds. It is
    context for resolving a repeated row label, not a persistent identity.
    """

    sheet_name: str
    sheet_index: int
    min_row: int
    max_row: int
    min_col: int
    max_col: int
    header_row: int
    label_cell_ref: str | None = None
    label_cell_value: Any = None
    label_row: int | None = None
    ragged_rows: tuple[int, ...] = ()
    empty_cells: tuple[str, ...] = ()
    absent_cells: tuple[str, ...] = ()
    loss: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    PROVISIONAL = True

    @property
    def region_id(self) -> str:
        """Context-bearing container handle: worksheet plus bounds.

        Bounds are part of the handle because a worksheet may legitimately
        contain more than one region. Two regions in the same sheet therefore
        never share an id, which is what lets a citation name one of them
        unambiguously.
        """
        return f"table:{self.sheet_name}:{self.bounds}"

    @property
    def bounds(self) -> str:
        return (
            f"{ooxml.format_cell_reference(self.min_row, self.min_col)}:"
            f"{ooxml.format_cell_reference(self.max_row, self.max_col)}"
        )

    @property
    def width(self) -> int:
        return self.max_col - self.min_col + 1

    @property
    def height(self) -> int:
        return self.max_row - self.min_row + 1

    def as_dict(self) -> dict[str, Any]:
        return {
            "region_id": self.region_id,
            "sheet_name": self.sheet_name,
            "sheet_index": self.sheet_index,
            "bounds": self.bounds,
            "min_row": self.min_row,
            "max_row": self.max_row,
            "min_col": self.min_col,
            "max_col": self.max_col,
            "header_row": self.header_row,
            "label_cell_ref": self.label_cell_ref,
            "label_cell_value": self.label_cell_value,
            "label_row": self.label_row,
            "width": self.width,
            "height": self.height,
            "ragged_rows": list(self.ragged_rows),
            "empty_cells": list(self.empty_cells),
            "absent_cells": list(self.absent_cells),
            "loss": list(self.loss),
            "notes": list(self.notes),
        }


def _components(rows: Sequence[int], gap_tolerance: int) -> list[list[int]]:
    """Split sorted row numbers into groups separated by more than the gap."""
    groups: list[list[int]] = []
    for row in rows:
        if groups and row - groups[-1][-1] <= gap_tolerance + 1:
            groups[-1].append(row)
        else:
            groups.append([row])
    return groups


def region_ambiguity(sheet: ObservedSheet, gap_tolerance: int = 0) -> tuple[int, ...]:
    """Row components found at this tolerance. More than one means ambiguity."""
    populated = [c for c in sheet.cells.values() if is_populated(c)]
    rows = sorted({c.row for c in populated})
    return tuple(len(g) for g in _components(rows, gap_tolerance))


def detect_regions(
    sheet: ObservedSheet, *, gap_tolerance: int = 0
) -> tuple[list[TableRegion], list[str]]:
    """Detect table regions in one worksheet.

    Returns ``(regions, warnings)``. When a sheet splits into several row
    components at this tolerance, one region per component is emitted *and* a
    warning is returned: the caller is told the layout is ambiguous rather than
    being handed a silent guess.
    """
    warnings: list[str] = []
    populated = [c for c in sheet.cells.values() if is_populated(c)]
    if not populated:
        return [], warnings

    rows = sorted({c.row for c in populated})
    groups = _components(rows, gap_tolerance)
    if len(groups) > 1:
        warnings.append(
            f"sheet {sheet.name!r}: {len(groups)} row-separated blocks detected at "
            f"gap_tolerance={gap_tolerance}; each is emitted as its own region and "
            f"table context is bounds-based, not declared"
        )

    regions: list[TableRegion] = []
    for group in groups:
        region = _region_from_rows(sheet, group)
        if region is not None:
            regions.append(region)
    return regions, warnings


def _region_from_rows(sheet: ObservedSheet, rows: Sequence[int]) -> TableRegion | None:
    row_set = set(rows)
    group_cells = [c for c in sheet.cells.values() if c.row in row_set and is_populated(c)]
    if not group_cells:
        return None

    min_row, max_row = min(rows), max(rows)
    min_col = min(c.column for c in group_cells)
    max_col = max(c.column for c in group_cells)
    header_row = min_row

    warnings: list[str] = []
    loss: list[str] = list(sheet.loss)

    # Ragged rows: a populated row inside the region that does not reach the
    # region's right edge. The span comes from all populated rows, so a short
    # row is visible rather than being redefined as "the table is narrower".
    ragged_rows = tuple(
        row for row in rows if max(c.column for c in group_cells if c.row == row) < max_col
    )
    if ragged_rows:
        loss.append(TableLossKind.ABSENT)
        warnings.append(
            f"sheet {sheet.name!r}: rows {list(ragged_rows)} do not span the full "
            f"region width; cells inside the bounds may be absent rather than empty"
        )

    # Empty/absent classification for every coordinate inside the bounds.
    empty_cells: list[str] = []
    absent_cells: list[str] = []
    for row in range(min_row, max_row + 1):
        for col in range(min_col, max_col + 1):
            ref = ooxml.format_cell_reference(row, col)
            cell = sheet.cells.get(ref)
            if cell is None:
                absent_cells.append(ref)
                continue
            if cell.value_kind == "empty":
                empty_cells.append(ref)
            elif cell.value_kind == "absent":
                absent_cells.append(ref)
            elif cell.merged_from:
                absent_cells.append(ref)
    if empty_cells or absent_cells:
        loss.append(TableLossKind.EMPTY)

    # Label cell: the cell immediately above the bounds when it holds text.
    label_cell_ref: str | None = None
    label_cell_value: Any = None
    label_row: int | None = None
    probe = sheet.cells.get(ooxml.format_cell_reference(min_row - 1, min_col))
    if probe is not None and is_populated(probe) and isinstance(probe.value, str):
        label_cell_ref = probe.ref
        label_cell_value = probe.value
        label_row = probe.row

    return TableRegion(
        sheet_name=sheet.name,
        sheet_index=sheet.index,
        min_row=min_row,
        max_row=max_row,
        min_col=min_col,
        max_col=max_col,
        header_row=header_row,
        label_cell_ref=label_cell_ref,
        label_cell_value=label_cell_value,
        label_row=label_row,
        ragged_rows=ragged_rows,
        empty_cells=tuple(empty_cells),
        absent_cells=tuple(absent_cells),
        loss=tuple(dict.fromkeys(loss)),
        notes=tuple(warnings),
    )
