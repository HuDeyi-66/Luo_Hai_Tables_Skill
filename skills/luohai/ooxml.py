"""Stdlib-only XLSX package reader used by the deterministic fixture backend.

WHY THIS EXISTS
---------------
The V2.1 architecture review allows a "fixture backend" when the locked
C06/C07 build cannot be reproduced (review section 2, item 5). To make that
backend a genuinely *independent* observation rather than a second reading
through the same library, it reads the OOXML package directly with
``zipfile`` + ``xml.etree`` and no third-party dependency.

SCOPE -- deliberately narrow
----------------------------
It targets the controlled V2.1 fixture and exposes exactly the structural facts
the extraction path needs:

* sheet names, order and file paths (plus hidden state),
* cell text/values by address, including shared and inline strings,
* formula text and cached values as *separate* facts,
* error cells as errors,
* blank-cell presence vs. absence,
* merged ranges.

It implements **no** evaluation, **no** number-format rendering, **no**
styles, **no** charts, comments or embedded objects, and it does not attempt to
survive hostile input. It is a fixture backend, not a general parser -- see
``skills/TODO.md``.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from typing import Any, Iterator
from xml.etree import ElementTree as ET

__all__ = [
    "XlsxPackageError",
    "RawCell",
    "RawSheet",
    "RawPackage",
    "DeclaredTable",
    "read_package",
    "column_letter_to_index",
    "column_index_to_letter",
    "parse_cell_reference",
    "format_cell_reference",
]

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"

_REL_SHEET = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"
)

_CELL_RE = re.compile(r"^([A-Z]+)([0-9]+)$")
_RANGE_RE = re.compile(r"^([A-Z]+[0-9]+)(?::([A-Z]+[0-9]+))?$")


class XlsxPackageError(ValueError):
    """The package is not a readable XLSX container."""


def _q(tag: str, ns: str = NS_MAIN) -> str:
    return f"{{{ns}}}{tag}"


# --------------------------------------------------------------------------
# address helpers
# --------------------------------------------------------------------------


def column_letter_to_index(letters: str) -> int:
    """``"A"`` -> 1, ``"AA"`` -> 27."""
    value = 0
    for char in letters.upper():
        if not "A" <= char <= "Z":
            raise ValueError(f"invalid column letters: {letters!r}")
        value = value * 26 + (ord(char) - ord("A") + 1)
    if value == 0:
        raise ValueError("empty column letters")
    return value


def column_index_to_letter(index: int) -> str:
    """1 -> ``"A"``, 27 -> ``"AA"``."""
    if index < 1:
        raise ValueError("column index is 1-based")
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


def parse_cell_reference(ref: str) -> tuple[int, int]:
    """``"C12"`` -> ``(12, 3)`` as ``(row, column)``, both 1-based."""
    match = _CELL_RE.match(ref.upper().replace("$", ""))
    if not match:
        raise ValueError(f"invalid cell reference: {ref!r}")
    return int(match.group(2)), column_letter_to_index(match.group(1))


def format_cell_reference(row: int, column: int) -> str:
    """``(2, 3)`` -> ``"C2"``."""
    return f"{column_index_to_letter(column)}{row}"


# --------------------------------------------------------------------------
# raw model -- structure only, no interpretation
# --------------------------------------------------------------------------


@dataclass
class RawCell:
    """One cell as written in the package.

    ``formula`` and ``raw`` are kept apart on purpose. ``raw`` is the cached
    value the writer stored; it is NOT the result of evaluating ``formula``.
    """

    ref: str
    row: int
    column: int
    kind: str  # "blank" | "string" | "inline_string" | "number" | "boolean"
    #           | "error" | "date" | "unknown"
    value: Any = None
    formula: str | None = None
    #: True when the XML contains a ``<c>`` element for this address at all.
    element_present: bool = True
    #: True when the element was ``<c r="C5"/>`` with no child at all.
    structurally_blank: bool = False
    style_index: int | None = None

    @property
    def is_error(self) -> bool:
        return self.kind == "error"

    @property
    def is_blank(self) -> bool:
        return self.kind == "blank"


@dataclass
class DeclaredTable:
    """A native OOXML table object read from ``xl/tables/tableN.xml``.

    This is **author-declared** structure: the workbook states a name and a
    range, so nothing has to be inferred. V2.1.1 observes it but does not
    depend on it -- a workbook without table parts is completely normal.

    ``column_names`` come from the table definition. They normally mirror the
    header row cells but are not required to, which is why the observation
    compares them rather than assuming equality.
    """

    table_id: int
    name: str
    display_name: str
    ref: str
    column_names: tuple[str, ...] = ()
    header_row_count: int = 1
    totals_row_count: int = 0
    totals_row_shown: bool = False
    part_path: str = ""

    @property
    def range_start(self) -> str:
        return self.ref.split(":", 1)[0].upper()

    @property
    def range_end(self) -> str:
        return (self.ref.split(":", 1)[1] if ":" in self.ref else self.ref).upper()

    def as_dict(self) -> dict[str, Any]:
        return {
            "table_id": self.table_id,
            "name": self.name,
            "display_name": self.display_name,
            "ref": self.ref,
            "column_names": list(self.column_names),
            "header_row_count": self.header_row_count,
            "totals_row_count": self.totals_row_count,
            "totals_row_shown": self.totals_row_shown,
            "part_path": self.part_path,
        }


@dataclass
class RawSheet:
    """One worksheet: descriptor, visibility, cells, merges, hidden axes.

    ``hidden_rows`` and ``hidden_columns`` are sheet-level visibility facts
    taken from ``<row hidden="1">`` and ``<cols><col hidden="1">``. They are the
    only visibility signal OOXML exposes; a hidden row or column is content the
    reader *does* return but the workbook author chose not to display.
    """

    name: str
    index: int  # 1-based position in the workbook
    part_path: str
    state: str = "visible"  # "visible" | "hidden" | "veryHidden"
    cells: dict[str, RawCell] = field(default_factory=dict)
    merged_ranges: list[str] = field(default_factory=list)
    #: Merged ranges that are NOT the anchor cell, i.e. addresses whose value
    #: is supplied by a merge rather than written.
    merged_covered: frozenset[str] = frozenset()
    #: Anchor address -> the full merge range it anchors.
    merge_anchors: dict[str, str] = field(default_factory=dict)
    hidden_rows: frozenset[int] = frozenset()
    hidden_columns: frozenset[int] = frozenset()
    #: Native OOXML table objects declared on this worksheet.
    declared_tables: tuple[DeclaredTable, ...] = ()
    declared_dimension: str | None = None

    @property
    def is_hidden(self) -> bool:
        return self.state != "visible"

    def has_element(self, ref: str) -> bool:
        cell = self.cells.get(ref)
        return bool(cell and cell.element_present)

    def is_hidden_address(self, row: int, column: int) -> bool:
        """True when the row or the column of this address is hidden."""
        return row in self.hidden_rows or column in self.hidden_columns

    def sorted_cells(self) -> list[RawCell]:
        return sorted(self.cells.values(), key=lambda c: (c.row, c.column))


@dataclass
class RawPackage:
    """A parsed XLSX container."""

    part_names: tuple[str, ...]
    sheets: tuple[RawSheet, ...]
    shared_strings: tuple[str, ...]
    date_system: str = "1900"

    def sheet_by_name(self, name: str) -> RawSheet | None:
        for sheet in self.sheets:
            if sheet.name == name:
                return sheet
        return None


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def _read_xml(archive: zipfile.ZipFile, name: str) -> ET.Element:
    try:
        payload = archive.read(name)
    except KeyError:
        raise XlsxPackageError(f"missing part in package: {name}") from None
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise XlsxPackageError(f"malformed XML in {name}: {exc}") from exc


def _parse_shared_strings(archive: zipfile.ZipFile) -> tuple[str, ...]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return ()
    root = _read_xml(archive, "xl/sharedStrings.xml")
    return tuple("".join(node.itertext()) for node in root.findall(_q("si")))


def _parse_workbook_sheets(archive: zipfile.ZipFile) -> list[tuple[str, str, str]]:
    """Return ``(name, state, part_path)`` in workbook order."""
    workbook = _read_xml(archive, "xl/workbook.xml")
    rels: dict[str, str] = {}
    if "xl/_rels/workbook.xml.rels" in archive.namelist():
        rel_root = _read_xml(archive, "xl/_rels/workbook.xml.rels")
        for rel in rel_root.findall(_q("Relationship", NS_PKG_REL)):
            target = rel.get("Target", "")
            if not target.startswith("/"):
                target = "xl/" + target.lstrip("./")
            rels[rel.get("Id", "")] = target.lstrip("/")

    sheets_node = workbook.find(_q("sheets"))
    if sheets_node is None:
        raise XlsxPackageError("workbook.xml has no <sheets> element")

    out: list[tuple[str, str, str]] = []
    for position, sheet in enumerate(sheets_node.findall(_q("sheet")), start=1):
        name = sheet.get("name") or f"Sheet{position}"
        state = sheet.get("state") or "visible"
        rel_id = sheet.get(f"{{{NS_REL}}}id") or ""
        part = rels.get(rel_id) or f"xl/worksheets/sheet{position}.xml"
        out.append((name, state, part))
    return out


def _parse_date_system(archive: zipfile.ZipFile) -> str:
    if "xl/workbook.xml" not in archive.namelist():
        return "1900"
    workbook = _read_xml(archive, "xl/workbook.xml")
    pr = workbook.find(_q("workbookPr"))
    if pr is None:
        return "1900"
    return "1904" if pr.get("date1904") in ("1", "true") else "1900"


def _cell_value(
    cell: ET.Element, shared: tuple[str, ...]
) -> tuple[str, Any, str | None]:
    """Return ``(kind, value, formula)`` for one ``<c>`` element."""
    type_attr = cell.get("t")
    formula: str | None = None
    formula_node = cell.find(_q("f"))
    if formula_node is not None:
        formula = formula_node.text or ""

    value_node = cell.find(_q("v"))
    inline_node = cell.find(_q("is"))

    if type_attr == "inlineStr":
        text = "".join(inline_node.itertext()) if inline_node is not None else ""
        return "inline_string", text, formula
    if type_attr == "s":
        if value_node is None or value_node.text is None:
            return "blank", None, formula
        try:
            idx = int(value_node.text)
        except ValueError:
            return "unknown", value_node.text, formula
        if 0 <= idx < len(shared):
            return "string", shared[idx], formula
        # Out-of-range shared string index: an unresolved reference. Reported
        # as unknown rather than as empty.
        return "unknown", f"shared_string_index_out_of_range:{idx}", formula
    if type_attr == "str":
        return "string", (value_node.text if value_node is not None else ""), formula
    if type_attr == "e":
        return "error", (value_node.text if value_node is not None else None), formula
    if type_attr == "b":
        text = value_node.text if value_node is not None else None
        return "boolean", (text == "1"), formula
    if type_attr in ("n", None):
        if value_node is None or value_node.text is None:
            return "blank", None, formula
        try:
            return "number", float(value_node.text), formula
        except ValueError:
            return "unknown", value_node.text, formula
    return "unknown", (value_node.text if value_node is not None else None), formula


def _parse_sheet(
    archive: zipfile.ZipFile,
    name: str,
    index: int,
    part_path: str,
    state: str,
    shared: tuple[str, ...],
) -> RawSheet:
    sheet = RawSheet(name=name, index=index, part_path=part_path, state=state)
    try:
        payload = archive.read(part_path)
    except KeyError:
        raise XlsxPackageError(f"missing worksheet part: {part_path}") from None
    root = ET.fromstring(payload)

    dimension = root.find(_q("dimension"))
    if dimension is not None:
        sheet.declared_dimension = dimension.get("ref")

    for cell in root.iter(_q("c")):
        ref = cell.get("r")
        if not ref:
            continue
        try:
            row, column = parse_cell_reference(ref)
        except ValueError:
            continue
        kind, value, formula = _cell_value(cell, shared)
        style = cell.get("s")
        sheet.cells[ref.upper()] = RawCell(
            ref=ref.upper(),
            row=row,
            column=column,
            kind=kind,
            value=value,
            formula=formula,
            element_present=True,
            structurally_blank=(kind == "blank"),
            style_index=int(style) if style and style.isdigit() else None,
        )

    # Hidden columns: <cols><col min="3" max="3" hidden="1"/></cols>. The min/max
    # pair is an inclusive 1-based span, so one element can hide many columns.
    hidden_columns: set[int] = set()
    cols_node = root.find(_q("cols"))
    if cols_node is not None:
        for col in cols_node.findall(_q("col")):
            if col.get("hidden") not in ("1", "true"):
                continue
            try:
                low = int(col.get("min", "0"))
                high = int(col.get("max", str(low)))
            except ValueError:
                continue
            for index in range(low, high + 1):
                hidden_columns.add(index)
    sheet.hidden_columns = frozenset(hidden_columns)

    # Hidden rows: <row r="4" hidden="1">.
    hidden_rows: set[int] = set()
    sheet_data = root.find(_q("sheetData"))
    if sheet_data is not None:
        for row_node in sheet_data.findall(_q("row")):
            if row_node.get("hidden") not in ("1", "true"):
                continue
            try:
                hidden_rows.add(int(row_node.get("r", "0")))
            except ValueError:
                continue
    sheet.hidden_rows = frozenset(hidden_rows)

    covered: set[str] = set()
    anchors: dict[str, str] = {}
    merges = root.find(_q("mergeCells"))
    if merges is not None:
        for merge in merges.findall(_q("mergeCell")):
            ref = merge.get("ref")
            if not ref:
                continue
            sheet.merged_ranges.append(ref)
            match = _RANGE_RE.match(ref)
            if not match:
                continue
            start, end = match.group(1), match.group(2)
            if not end:
                anchors[start] = ref
                continue
            anchors[start] = ref
            start_row, start_col = parse_cell_reference(start)
            end_row, end_col = parse_cell_reference(end)
            for r in range(start_row, end_row + 1):
                for c in range(start_col, end_col + 1):
                    address = format_cell_reference(r, c)
                    if address != start:
                        covered.add(address)
    sheet.merged_covered = frozenset(covered)
    sheet.merge_anchors = anchors
    sheet.declared_tables = _parse_declared_tables(archive, sheet.index)
    return sheet


def _parse_declared_tables(
    archive: zipfile.ZipFile, sheet_index: int
) -> tuple[DeclaredTable, ...]:
    """Read ``xl/tables/tableN.xml`` parts referenced by one worksheet.

    A worksheet references its tables through ``r:id`` attributes on
    ``<tablePart>``, resolved by ``xl/worksheets/_rels/sheetN.xml.rels``. A
    worksheet with no such part simply has no declared tables, which is the
    common case.
    """
    rels_path = f"xl/worksheets/_rels/sheet{sheet_index}.xml.rels"
    if rels_path not in archive.namelist():
        return ()

    rel_root = _read_xml(archive, rels_path)
    targets: list[str] = []
    for rel in rel_root.findall(_q("Relationship", NS_PKG_REL)):
        rel_type = rel.get("Type", "")
        if not rel_type.endswith("/table"):
            continue
        target = rel.get("Target", "")
        if target.startswith("/"):
            resolved = target.lstrip("/")
        else:
            resolved = "xl/" + target.replace("../", "").lstrip("./")
        targets.append(resolved)

    tables: list[DeclaredTable] = []
    for target in targets:
        if target not in archive.namelist():
            continue
        tables.append(_parse_table_part(archive, target))
    return tuple(tables)


def _parse_table_part(archive: zipfile.ZipFile, part_path: str) -> DeclaredTable:
    root = _read_xml(archive, part_path)
    columns_node = root.find(_q("tableColumns"))
    column_names: list[str] = []
    if columns_node is not None:
        for column in columns_node.findall(_q("tableColumn")):
            column_names.append(column.get("name") or "")

    def _int(attribute: str, default: int) -> int:
        raw = root.get(attribute)
        if raw is None:
            return default
        try:
            return int(raw)
        except ValueError:
            return default

    name = root.get("name") or root.get("displayName") or ""
    return DeclaredTable(
        table_id=_int("id", 0),
        name=name,
        display_name=root.get("displayName") or name,
        ref=root.get("ref") or "",
        column_names=tuple(column_names),
        header_row_count=_int("headerRowCount", 1),
        totals_row_count=_int("totalsRowCount", 0),
        totals_row_shown=root.get("totalsRowShown") not in ("0", "false", None),
        part_path=part_path,
    )


def read_package(path: str) -> RawPackage:
    """Parse an XLSX container with the standard library only."""
    try:
        archive = zipfile.ZipFile(path, "r")
    except (zipfile.BadZipFile, OSError) as exc:
        raise XlsxPackageError(f"not a readable ZIP/XLSX container: {exc}") from exc

    with archive:
        names = tuple(archive.namelist())
        if "xl/workbook.xml" not in names:
            raise XlsxPackageError("package has no xl/workbook.xml")
        shared = _parse_shared_strings(archive)
        date_system = _parse_date_system(archive)
        sheets = tuple(
            _parse_sheet(archive, name, index, part, state, shared)
            for index, (name, state, part) in enumerate(
                _parse_workbook_sheets(archive), start=1
            )
        )
    return RawPackage(
        part_names=names,
        sheets=sheets,
        shared_strings=shared,
        date_system=date_system,
    )


def iter_package_members(path: str) -> Iterator[str]:
    """Names of package parts. Used to detect content the skill does not read."""
    with zipfile.ZipFile(path, "r") as archive:
        yield from archive.namelist()
