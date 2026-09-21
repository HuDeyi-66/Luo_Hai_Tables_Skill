"""Minimal deterministic XLSX writer used by the SeaFlow V2.1 fixtures.

Extracted from ``build_fixture.py`` in V2.1.1 so that a second fixture (the
table-identity boundary fixture) can reuse the exact same writer. The
extraction is output-preserving: the V2.1 fixture rebuilds to the same SHA-256
as before, which ``tests/test_fixture_harness.py`` and
``fixtures/rebuild_and_diff.py`` both assert.

Why hand-written OOXML instead of a workbook library: a fixture must contain
the exact constructs under test -- an error cell, a formula with no cached
value, a present-but-blank cell, a coordinate with no cell element, hidden rows
and columns, merged ranges -- and it must be readable by an independent stdlib
reader *and* by the C06/C07 binding. A library would decide some of those for
us.
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = [
    "XML_DECL",
    "SheetSpec",
    "ColumnSpec",
    "DeclaredTableSpec",
    "SheetDef",
    "XlsxSpec",
    "escape",
    "escape_attr",
    "column_letter",
    "build_parts",
    "build_workbook_bytes",
]

XML_DECL = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'

#: Fixed ZIP member timestamp (the DOS epoch). Keeps rebuilds byte-identical.
ZIP_DATE = (1980, 1, 1, 0, 0, 0)

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

#: Cell specification:
#:   ``int|float``                  -> numeric cell
#:   ``bool``                       -> boolean cell
#:   ``str``                        -> shared string
#:   ``("inline", text)``           -> inline string
#:   ``("error", code)``            -> ``t="e"`` error value
#:   ``("formula", text, cached)``  -> formula with a cached value
#:   ``("formula", text, None)``    -> formula with no cached value
#:   ``("empty",)``                 -> present ``<c/>`` element with no value
#:   ``None``                       -> no cell element at all (absent)
SheetSpec = Sequence[Sequence[Any]]


@dataclass
class ColumnSpec:
    """Worksheet column metadata written into ``<cols>``.

    ``width`` is written only when supplied. ``hidden`` writes
    ``hidden="1"``; ``outline_level`` writes ``outlineLevel``.
    """

    min_index: int
    max_index: int
    width: float | None = None
    hidden: bool = False
    outline_level: int | None = None

    def as_xml(self) -> str:
        attrs = [f'min="{self.min_index}"', f'max="{self.max_index}"']
        if self.width is not None:
            attrs.append(f'width="{self.width}"')
            attrs.append('customWidth="1"')
        if self.hidden:
            attrs.append('hidden="1"')
        if self.outline_level is not None:
            attrs.append(f'outlineLevel="{self.outline_level}"')
        return f"<col {' '.join(attrs)}/>"


@dataclass
class DeclaredTableSpec:
    """A native OOXML table object (``xl/tables/tableN.xml``).

    This is *author-declared* structure, not inference: Excel writes a name and
    a range, so a reader that parses it does not have to guess where a table
    starts and ends. The V2.1.1 closure patch uses it purely to observe how
    declared metadata compares with the inferred table context.

    ``column_names`` are the table's column labels. Excel normally mirrors them
    from the header row cells, but the two can legitimately disagree, which is
    one of the things the observation reports.
    """

    table_id: int
    name: str
    display_name: str
    ref: str
    column_names: tuple[str, ...]
    header_row_count: int = 1
    totals_row_count: int = 0
    totals_row_shown: bool = False
    style_name: str | None = "TableStyleMedium2"

    def range_parts(self) -> tuple[str, str]:
        if ":" in self.ref:
            start, end = self.ref.split(":", 1)
            return start.upper(), end.upper()
        return self.ref.upper(), self.ref.upper()


@dataclass
class SheetDef:
    """One worksheet: a cell matrix plus optional visibility and table metadata."""

    name: str
    rows: SheetSpec = ()
    columns: tuple[ColumnSpec, ...] = ()
    hidden_rows: tuple[int, ...] = ()
    #: Merged ranges as ``"A1:C1"`` (or ``"A1"`` for a single cell).
    merged_ranges: tuple[str, ...] = ()
    state: str = "visible"  # visible | hidden | veryHidden
    #: Native OOXML table objects declared on this worksheet.
    declared_tables: tuple[DeclaredTableSpec, ...] = ()

    #: Declared-but-unwritten coordinates. Only used to widen ``<dimension>``;
    #: they are *not* emitted as cell elements.
    extra_extent: tuple[int, int] | None = None


@dataclass
class XlsxSpec:
    """A complete workbook specification."""

    sheets: tuple[SheetDef, ...]
    shared_strings: tuple[str, ...] = ()
    #: Set to override the ``date1904`` workbook property.
    date1904: bool = False
    workbook_properties: Mapping[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------
# XML helpers
# --------------------------------------------------------------------------


def escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def escape_attr(text: str) -> str:
    return escape(text).replace("'", "&apos;")


def column_letter(index: int) -> str:
    """1 -> ``A``, 27 -> ``AA``."""
    if index < 1:
        raise ValueError("column index is 1-based")
    letters = ""
    while index:
        index, rem = divmod(index - 1, 26)
        letters = chr(ord("A") + rem) + letters
    return letters


# --------------------------------------------------------------------------
# cell and sheet serialisation
# --------------------------------------------------------------------------


def _shared_index(spec: XlsxSpec, text: str) -> int:
    try:
        return spec.shared_strings.index(text)
    except ValueError:
        raise KeyError(
            f"string not interned in shared_strings: {text!r}"
        ) from None


def _cell_xml(spec: XlsxSpec, ref: str, cell: Any) -> str:
    if cell is None:
        return ""  # absent: no element at all
    if isinstance(cell, bool):
        return f'<c r="{ref}" t="b"><v>{1 if cell else 0}</v></c>'
    if isinstance(cell, (int, float)):
        return f'<c r="{ref}" t="n"><v>{cell}</v></c>'
    if isinstance(cell, str):
        return f'<c r="{ref}" t="s"><v>{_shared_index(spec, cell)}</v></c>'
    if isinstance(cell, tuple):
        kind = cell[0]
        if kind == "empty":
            return f'<c r="{ref}"/>'
        if kind == "inline":
            return f'<c r="{ref}" t="inlineStr"><is><t>{escape(cell[1])}</t></is></c>'
        if kind == "error":
            return f'<c r="{ref}" t="e"><v>{escape(cell[1])}</v></c>'
        if kind == "formula":
            _, text, cached = cell
            formula = f"<f>{escape(text)}</f>"
            if cached is None:
                return f'<c r="{ref}">{formula}</c>'
            return f'<c r="{ref}" t="n">{formula}<v>{cached}</v></c>'
    raise TypeError(f"unsupported cell specification for {ref}: {cell!r}")


def _sheet_xml(spec: XlsxSpec, sheet: SheetDef) -> str:
    hidden_rows = set(sheet.hidden_rows)
    rows_xml: list[str] = []
    max_col = 0
    max_row = len(sheet.rows)

    for row_index, row in enumerate(sheet.rows, start=1):
        cells = []
        for col_offset, cell in enumerate(row):
            ref = f"{column_letter(col_offset + 1)}{row_index}"
            xml = _cell_xml(spec, ref, cell)
            if xml:
                cells.append(xml)
            max_col = max(max_col, col_offset + 1)
        row_attr = f' r="{row_index}"'
        if row_index in hidden_rows:
            row_attr += ' hidden="1"'
        if cells:
            rows_xml.append(f"<row{row_attr}>{''.join(cells)}</row>")
        elif row_index in hidden_rows:
            # A hidden row with no cells still needs its attribute recorded.
            rows_xml.append(f"<row{row_attr}/>")

    if sheet.extra_extent is not None:
        max_row = max(max_row, sheet.extra_extent[0])
        max_col = max(max_col, sheet.extra_extent[1])

    dimension = "A1" if max_col == 0 or max_row == 0 else (
        f"A1:{column_letter(max_col)}{max_row}"
    )

    cols_xml = ""
    if sheet.columns:
        cols_xml = "<cols>" + "".join(c.as_xml() for c in sheet.columns) + "</cols>"

    merges_xml = ""
    if sheet.merged_ranges:
        entries = "".join(
            f'<mergeCell ref="{escape_attr(ref)}"/>' for ref in sheet.merged_ranges
        )
        merges_xml = f'<mergeCells count="{len(sheet.merged_ranges)}">{entries}</mergeCells>'

    # Declared table objects: the worksheet references them through r:id, which
    # resolves via xl/worksheets/_rels/sheetN.xml.rels to xl/tables/tableN.xml.
    table_parts_xml = ""
    if sheet.declared_tables:
        entries = "".join(
            f'<tablePart r:id="rIdTable{index}"/>'
            for index, _ in enumerate(sheet.declared_tables, start=1)
        )
        table_parts_xml = f"<tableParts count=\"{len(sheet.declared_tables)}\">{entries}</tableParts>"

    sheet_attr = "" if sheet.state == "visible" else f' state="{sheet.state}"'

    # The relationship namespace is declared only when the worksheet actually
    # references a table part. Declaring it unconditionally would rewrite every
    # existing worksheet and change the byte output of fixtures that have no
    # declared tables at all -- including the sealed V2.1 fixture.
    rels_ns_attr = f' xmlns:r="{REL_NS}"' if sheet.declared_tables else ""

    # Attribute order follows what Excel writes; it does not affect parsing, but
    # keeping it stable keeps rebuilds byte-identical.
    return (
        f"{XML_DECL}\n"
        f'<worksheet xmlns="{MAIN_NS}"{rels_ns_attr}{sheet_attr}>'
        f'<dimension ref="{dimension}"/>'
        f"{cols_xml}"
        f'<sheetData>{"".join(rows_xml)}</sheetData>'
        f"{merges_xml}"
        f"{table_parts_xml}"
        "</worksheet>"
    )


def _table_xml(table: DeclaredTableSpec, column_count: int) -> str:
    """One ``xl/tables/tableN.xml`` part."""
    start_cell, _ = table.range_parts()
    start_row, start_col = _split_ref(start_cell)
    column_names = list(table.column_names) or [
        f"Column{n}" for n in range(1, column_count + 1)
    ]
    columns_xml = "".join(
        f'<tableColumn id="{index}" name="{escape_attr(name)}"/>'
        for index, name in enumerate(column_names, start=1)
    )
    totals_attr = ' totalsRowShown="0"' if not table.totals_row_shown else ""
    style_attr = (
        f' tableStyleInfo="{escape_attr(table.style_name)}"'
        if table.style_name
        else ""
    )
    style_info = (
        f'<tableStyleInfo name="{escape_attr(table.style_name)}" showFirstColumn="0" '
        'showLastColumn="0" showRowStripes="1" showColumnStripes="0"/>'
        if table.style_name
        else ""
    )
    del style_attr
    return (
        f"{XML_DECL}\n"
        f'<table xmlns="{MAIN_NS}" id="{table.table_id}" '
        f'name="{escape_attr(table.name)}" displayName="{escape_attr(table.display_name)}" '
        f'ref="{escape_attr(table.ref)}" headerRowCount="{table.header_row_count}" '
        f'totalsRowCount="{table.totals_row_count}"{totals_attr}>'
        f'<tableColumns count="{len(column_names)}">{columns_xml}</tableColumns>'
        f"{style_info}"
        "</table>"
    )


def _split_ref(ref: str) -> tuple[int, int]:
    letters = "".join(ch for ch in ref if ch.isalpha())
    digits = "".join(ch for ch in ref if ch.isdigit())
    index = 0
    for ch in letters.upper():
        index = index * 26 + (ord(ch) - ord("A") + 1)
    return int(digits or "1"), index


def _content_types_xml(spec: XlsxSpec) -> str:
    overrides = [
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.'
        'openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>',
    ]
    for index in range(1, len(spec.sheets) + 1):
        overrides.append(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.'
            'worksheet+xml"/>'
        )
    for table in _all_declared_tables(spec):
        overrides.append(
            f'<Override PartName="/xl/tables/table{table.table_id}.xml" ContentType='
            '"application/vnd.openxmlformats-officedocument.spreadsheetml.table+xml"/>'
        )
    return (
        f"{XML_DECL}\n"
        f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-'
        'package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'{"".join(overrides)}'
        "</Types>"
    )


def _all_declared_tables(spec: XlsxSpec) -> tuple[DeclaredTableSpec, ...]:
    return tuple(
        table for sheet in spec.sheets for table in sheet.declared_tables
    )


def _root_rels_xml() -> str:
    return (
        f"{XML_DECL}\n"
        f'<Relationships xmlns="{PKG_REL_NS}">'
        f'<Relationship Id="rId1" Type="{REL_NS}/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _workbook_xml(spec: XlsxSpec) -> str:
    entries = "".join(
        f'<sheet name="{escape_attr(sheet.name)}" sheetId="{index}" '
        f'r:id="rId{index}"'
        + ("" if sheet.state == "visible" else f' state="{sheet.state}"')
        + "/>"
        for index, sheet in enumerate(spec.sheets, start=1)
    )
    properties = ""
    if spec.date1904:
        properties = '<workbookPr date1904="1"/>'
    return (
        f"{XML_DECL}\n"
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}">'
        f"{properties}"
        f"<sheets>{entries}</sheets>"
        "</workbook>"
    )


def _workbook_rels_xml(sheet_count: int) -> str:
    entries = "".join(
        f'<Relationship Id="rId{index}" Type="{REL_NS}/worksheet" '
        f'Target="worksheets/sheet{index}.xml"/>'
        for index in range(1, sheet_count + 1)
    )
    shared_rel = (
        f'<Relationship Id="rId{sheet_count + 1}" Type="{REL_NS}/sharedStrings" '
        'Target="sharedStrings.xml"/>'
    )
    return f'{XML_DECL}\n<Relationships xmlns="{PKG_REL_NS}">{entries}{shared_rel}</Relationships>'


def _shared_strings_xml(spec: XlsxSpec) -> str:
    items = "".join(
        f"<si><t>{escape(text)}</t></si>" if text else "<si><t/></si>"
        for text in spec.shared_strings
    )
    return (
        f"{XML_DECL}\n"
        f'<sst xmlns="{MAIN_NS}" count="{len(spec.shared_strings)}" '
        f'uniqueCount="{len(spec.shared_strings)}">{items}</sst>'
    )


# --------------------------------------------------------------------------
# package assembly
# --------------------------------------------------------------------------


def _sheet_rels_xml(sheet: SheetDef) -> str:
    """``xl/worksheets/_rels/sheetN.xml.rels``: worksheet -> table parts."""
    entries = "".join(
        f'<Relationship Id="rIdTable{index}" Type="{REL_NS}/table" '
        f'Target="../tables/table{table.table_id}.xml"/>'
        for index, table in enumerate(sheet.declared_tables, start=1)
    )
    return f'{XML_DECL}\n<Relationships xmlns="{PKG_REL_NS}">{entries}</Relationships>'


def build_parts(spec: XlsxSpec) -> dict[str, bytes]:
    """Return every package part as ``{name: bytes}`` in a fixed order."""
    parts: dict[str, bytes] = {
        "[Content_Types].xml": _content_types_xml(spec).encode("utf-8"),
        "_rels/.rels": _root_rels_xml().encode("utf-8"),
        "xl/workbook.xml": _workbook_xml(spec).encode("utf-8"),
        "xl/_rels/workbook.xml.rels": _workbook_rels_xml(len(spec.sheets)).encode(
            "utf-8"
        ),
        "xl/sharedStrings.xml": _shared_strings_xml(spec).encode("utf-8"),
    }
    for index, sheet in enumerate(spec.sheets, start=1):
        parts[f"xl/worksheets/sheet{index}.xml"] = _sheet_xml(spec, sheet).encode(
            "utf-8"
        )
        if sheet.declared_tables:
            parts[f"xl/worksheets/_rels/sheet{index}.xml.rels"] = (
                _sheet_rels_xml(sheet).encode("utf-8")
            )
    for table in _all_declared_tables(spec):
        parts[f"xl/tables/table{table.table_id}.xml"] = _table_xml(
            table, column_count=_column_count_for(spec, table)
        ).encode("utf-8")
    return parts


def _column_count_for(spec: XlsxSpec, table: DeclaredTableSpec) -> int:
    """Number of columns the declared ref spans, used only as a fallback."""
    start, end = table.range_parts()
    _, start_col = _split_ref(start)
    _, end_col = _split_ref(end)
    return max(end_col - start_col + 1, 1)


def build_workbook_bytes(spec: XlsxSpec) -> bytes:
    """Serialise the package deterministically."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, payload in build_parts(spec).items():
            info = zipfile.ZipInfo(name, date_time=ZIP_DATE)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload)
    return buffer.getvalue()
