"""V2.1.1 closure -- observe declared OOXML table metadata.

PURPOSE
-------
Boundary detection in this project is *inference*: it groups populated cells and
guesses where a table starts and ends. XLSX can instead carry an
**author-declared** table object under ``xl/tables/``. The closure patch asked
one bounded question:

    when a workbook declares a table, does the inferred context agree with it?

This module answers that question and nothing else. It is **observation only**:

* it does not change the table model;
* it does not make declared metadata required or authoritative;
* it does not treat a declared name as an identity;
* it never lets declared metadata override what the cells say.

The three outcomes are deliberately distinct:

``agreement``
    a declared table exists and its range, header row and column names match
    the inferred context;
``disagreement``
    a declared table exists and something does not match -- reported per aspect,
    never smoothed over;
``unavailable``
    the workbook declares no table covering this region.

A workbook with no declared tables is ordinary, so ``unavailable`` is not a
failure and is not a loss.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from core.evidence import LossKind
from core.skill_result import Capability, Support

from . import ooxml

__all__ = [
    "ObservationStatus",
    "ObservationAspect",
    "AspectComparison",
    "DeclaredTableComparison",
    "ComparisonReport",
    "observe_declared_tables",
    "compare_observation",
    "compare_declared_and_inferred",
    "regions_from_result",
    "make_capability",
]


class ObservationStatus:
    """Closed vocabulary for the declared-vs-inferred comparison."""

    AGREEMENT = "agreement"
    DISAGREEMENT = "disagreement"
    UNAVAILABLE = "unavailable"

    ALL = (AGREEMENT, DISAGREEMENT, UNAVAILABLE)


class ObservationAspect:
    """The aspects compared. Reported individually, not as one boolean."""

    RANGE_START = "range_start"
    RANGE_END = "range_end"
    HEADER_ROW = "header_row"
    COLUMN_NAMES = "column_names"
    COLUMN_COUNT = "column_count"

    ALL = (RANGE_START, RANGE_END, HEADER_ROW, COLUMN_NAMES, COLUMN_COUNT)


@dataclass
class AspectComparison:
    """One aspect of one declared table compared with the inferred context."""

    aspect: str
    declared: Any
    inferred: Any

    @property
    def agrees(self) -> bool:
        return self.declared == self.inferred

    def as_dict(self) -> dict[str, Any]:
        return {
            "aspect": self.aspect,
            "declared": self.declared,
            "inferred": self.inferred,
            "agrees": self.agrees,
        }


@dataclass
class DeclaredTableComparison:
    """One declared table compared with one inferred context."""

    status: str
    declared: ooxml.DeclaredTable | None
    region_id: str | None
    bounds: str | None
    sheet_name: str
    aspects: tuple[AspectComparison, ...] = ()
    notes: tuple[str, ...] = ()

    PROVISIONAL = True

    @property
    def disagreements(self) -> tuple[AspectComparison, ...]:
        return tuple(a for a in self.aspects if not a.agrees)

    def as_dict(self) -> dict[str, Any]:
        return {
            "provisional": True,
            "status": self.status,
            "sheet_name": self.sheet_name,
            "region_id": self.region_id,
            "bounds": self.bounds,
            "declared": self.declared.as_dict() if self.declared else None,
            "aspects": [a.as_dict() for a in self.aspects],
            "disagreements": [a.aspect for a in self.disagreements],
            "notes": list(self.notes),
        }


@dataclass
class ComparisonReport:
    """The whole observation, plus its own provenance."""

    comparisons: tuple[DeclaredTableComparison, ...] = ()
    declared_table_count: int = 0
    sheets_with_declared_tables: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    PROVISIONAL = True

    @property
    def by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {status: 0 for status in ObservationStatus.ALL}
        for comparison in self.comparisons:
            counts[comparison.status] = counts.get(comparison.status, 0) + 1
        return counts

    def as_dict(self) -> dict[str, Any]:
        return {
            "provisional": True,
            "schema_version": "seaflow-v2.1.1-declared-table-observation/v1",
            "declared_table_count": self.declared_table_count,
            "sheets_with_declared_tables": list(self.sheets_with_declared_tables),
            "summary": self.by_status,
            "comparisons": [c.as_dict() for c in self.comparisons],
            "notes": list(self.notes),
        }


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return list(value.values())
    if isinstance(value, (str, bytes)):
        return [value]
    return list(value)


def compare_observation(
    declared: ooxml.DeclaredTable | None,
    *,
    sheet_name: str,
    region_id: str | None,
    bounds: str | None,
    header_row: int | None,
    header_row_values: Sequence[Any] | None,
    column_count: int | None,
) -> DeclaredTableComparison:
    """Compare declared table metadata with one inferred region.

    ``declared=None`` yields ``unavailable``: no declared table covers the
    region. That is a normal result for the many workbooks without table parts.
    """
    if declared is None:
        return DeclaredTableComparison(
            status=ObservationStatus.UNAVAILABLE,
            declared=None,
            region_id=region_id,
            bounds=bounds,
            sheet_name=sheet_name,
            notes=("no declared OOXML table covers this region",),
        )

    declared_start = declared.range_start
    declared_end = declared.range_end
    inferred_start = (bounds or "").split(":", 1)[0].upper() or None
    inferred_end = (
        (bounds or "").split(":", 1)[1].upper() if bounds and ":" in bounds else None
    )

    # The declared header row is the first row of the declared range.
    declared_header_row = ooxml.parse_cell_reference(declared_start)[0]
    declared_columns = tuple(declared.column_names)
    inferred_columns = tuple(str(v) for v in _as_list(header_row_values))

    aspects = (
        AspectComparison(ObservationAspect.RANGE_START, declared_start, inferred_start),
        AspectComparison(ObservationAspect.RANGE_END, declared_end, inferred_end),
        AspectComparison(
            ObservationAspect.HEADER_ROW, declared_header_row, header_row
        ),
        AspectComparison(
            ObservationAspect.COLUMN_COUNT, len(declared_columns), column_count
        ),
        AspectComparison(
            ObservationAspect.COLUMN_NAMES,
            list(declared_columns),
            list(inferred_columns),
        ),
    )

    notes: list[str] = []
    if declared.header_row_count != 1:
        notes.append(
            f"declared headerRowCount={declared.header_row_count}; the inferred "
            f"context assumes exactly one header row"
        )
    if declared.totals_row_count or declared.totals_row_shown:
        notes.append(
            "declared table has a totals row; the inferred region does not "
            "distinguish a totals row from data"
        )

    status = (
        ObservationStatus.AGREEMENT
        if all(a.agrees for a in aspects)
        else ObservationStatus.DISAGREEMENT
    )
    return DeclaredTableComparison(
        status=status,
        declared=declared,
        region_id=region_id,
        bounds=bounds,
        sheet_name=sheet_name,
        aspects=aspects,
        notes=tuple(notes),
    )


def observe_declared_tables(
    *,
    sheet_name: str,
    declared_tables: Sequence[ooxml.DeclaredTable],
    regions: Sequence[Mapping[str, Any]],
) -> tuple[DeclaredTableComparison, ...]:
    """Compare every inferred region of one worksheet with its declared tables.

    Matching is by *containment of the inferred start cell*, not by string
    equality of ranges. That is what makes a disagreement visible instead of
    turning it into "no declared table found": a declared ``A1:C5`` against an
    inferred ``A1:C3`` must report a disagreement, not an absence.
    """
    comparisons: list[DeclaredTableComparison] = []
    for region in regions:
        bounds = str(region.get("bounds") or "")
        start_ref = bounds.split(":", 1)[0] or "A1"
        try:
            start_row, start_col = ooxml.parse_cell_reference(start_ref)
        except ValueError:
            start_row, start_col = 1, 1

        match: ooxml.DeclaredTable | None = None
        for declared in declared_tables:
            try:
                d_start_row, d_start_col = ooxml.parse_cell_reference(
                    declared.range_start
                )
                d_end_row, d_end_col = ooxml.parse_cell_reference(declared.range_end)
            except ValueError:
                continue
            if (
                d_start_row <= start_row <= d_end_row
                and d_start_col <= start_col <= d_end_col
            ):
                match = declared
                break

        comparisons.append(
            compare_observation(
                match,
                sheet_name=sheet_name,
                region_id=region.get("region_id"),
                bounds=bounds or None,
                header_row=region.get("header_row"),
                header_row_values=region.get("header_row_values"),
                column_count=region.get("column_count"),
            )
        )
    return tuple(comparisons)


def compare_declared_and_inferred(
    *,
    declared_tables_by_sheet: Mapping[str, Sequence[ooxml.DeclaredTable]],
    regions_by_sheet: Mapping[str, Sequence[Mapping[str, Any]]],
) -> ComparisonReport:
    """Build the whole report from a per-sheet mapping of both sides."""
    comparisons: list[DeclaredTableComparison] = []
    for sheet_name in sorted(set(regions_by_sheet) | set(declared_tables_by_sheet)):
        comparisons.extend(
            observe_declared_tables(
                sheet_name=sheet_name,
                declared_tables=declared_tables_by_sheet.get(sheet_name, ()),
                regions=regions_by_sheet.get(sheet_name, ()),
            )
        )

    declared_count = sum(
        len(tables) for tables in declared_tables_by_sheet.values()
    )
    sheets_with = tuple(
        sorted(name for name, tables in declared_tables_by_sheet.items() if tables)
    )

    notes: list[str] = []
    if declared_count == 0:
        notes.append(
            "this workbook declares no OOXML table objects; every comparison is "
            "'unavailable', which is the ordinary case and not a loss"
        )
    if declared_count:
        notes.append(
            "declared metadata is reported for observation only; it does not "
            "override what the cells say and is not treated as an identity"
        )
    return ComparisonReport(
        comparisons=tuple(comparisons),
        declared_table_count=declared_count,
        sheets_with_declared_tables=sheets_with,
        notes=tuple(notes),
    )


def regions_from_result(result: Any) -> dict[str, list[dict[str, Any]]]:
    """Extract the inferred-region descriptions from a ``SkillResult``.

    Only the fields the comparison needs, taken from the Skill's own payload.
    The Skill does not need to know this observer exists.
    """
    by_sheet: dict[str, list[dict[str, Any]]] = {}
    for unit in result.units:
        block = (unit.payload or {}).get("tabular")
        if not isinstance(block, Mapping):
            continue
        by_sheet.setdefault(str(block.get("sheet_name")), []).append(
            {
                "region_id": block.get("region_id"),
                "bounds": block.get("bounds"),
                "header_row": block.get("header_row"),
                "header_row_values": [
                    cell.get("value")
                    for cell in block.get("cells", ())
                    if isinstance(cell, Mapping)
                    and cell.get("is_header")
                    and int(cell.get("row", 0)) == int(block.get("header_row") or 0)
                ],
                "column_count": len(block.get("column_headers") or {}),
            }
        )
    return by_sheet


def make_capability() -> Capability:
    """Declare the observation's support honestly."""
    return Capability(
        name="declared_table_observation",
        support=Support.PARTIAL,
        detail=(
            "native xl/tables metadata is read and compared with the inferred "
            "table context, reporting agreement / disagreement / unavailable; "
            "it is observation only and never overrides inferred boundaries"
        ),
        collapse_risks=(LossKind.SILENT_LOSS_RISK,),
    )
