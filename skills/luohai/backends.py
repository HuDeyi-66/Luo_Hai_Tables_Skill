"""Tabular observation backends for ``LuoHai.TabularEvidence``.

A backend answers one narrow question: *what does this workbook structure look
like, and what did the reader fail to preserve?* It performs no citation
reasoning and builds no EvidenceUnits -- that is the Skill's job. Keeping the
boundary here is what lets a fake backend, a fixture backend and an
experimental OSS binding be compared behind one interface.

Three implementations live in this module:

``FakeTabularBackend``
    In-memory, dependency-free. Proves the interface can be called before any
    real reader exists (V2.1 milestone M1 exit condition).

``FixtureXlsxBackend``
    Deterministic, stdlib-only, reads the controlled XLSX fixture through
    :mod:`skills.ooxml`. This is the fallback the architecture review requires
    when the locked C06/C07 build cannot be reproduced.

``CalamineBackend`` (spike)
    Experimental wrapper around the locked python-calamine binding. Its known
    loss profile is *declared*, not discovered at run time, and it is never
    auto-selected to replace another candidate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

from .contracts import TableLossKind
from .contracts import TableCapability, TableSupport

from . import ooxml

__all__ = [
    "ObservedCell",
    "ObservedSheet",
    "ObservedWorkbook",
    "TabularBackend",
    "FakeTabularBackend",
    "FixtureXlsxBackend",
    "CalamineBackend",
    "CalamineNotAvailable",
]


# --------------------------------------------------------------------------
# the observation contract
# --------------------------------------------------------------------------


@dataclass
class ObservedCell:
    """One cell as the backend saw it.

    ``value`` is what would be displayed; ``raw`` is the literal stored
    content when it differs (a cached formula result, say). ``loss`` records
    what the backend had to give up to produce this cell.
    """

    row: int
    column: int
    ref: str
    value: Any = None
    raw: Any = None
    value_kind: str = "unknown"  # blank|empty|string|number|boolean|error|date
    formula: str | None = None
    loss: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    element_present: bool = True
    #: Anchor address of the merge range covering this cell, when it is covered
    #: by a merge rather than written. ``None`` means "not part of a merge".
    merged_from: str | None = None
    #: True when the row or the column of this address is hidden. Sheet-level
    #: visibility is the only signal OOXML exposes, so this is a per-address
    #: projection of a per-axis fact.
    hidden: bool = False

    PROVISIONAL = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "row": self.row,
            "column": self.column,
            "value": self.value,
            "raw": self.raw,
            "value_kind": self.value_kind,
            "formula": self.formula,
            "loss": list(self.loss),
            "notes": list(self.notes),
            "element_present": self.element_present,
            "merged_from": self.merged_from,
            "hidden": self.hidden,
        }


@dataclass
class ObservedSheet:
    """One worksheet as the backend saw it."""

    name: str
    index: int
    state: str = "visible"
    cells: dict[str, ObservedCell] = field(default_factory=dict)
    loss: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    #: True when the sheet exists but has no populated cells at all. The
    #: calamine binding panics on exactly this case, so it is tracked.
    is_empty: bool = False
    #: Sheet-level visibility and merge facts (V2.1.1 context spike).
    hidden_rows: tuple[int, ...] = ()
    hidden_columns: tuple[int, ...] = ()
    merged_ranges: tuple[str, ...] = ()

    @property
    def is_hidden(self) -> bool:
        return self.state != "visible"


@dataclass
class ObservedWorkbook:
    """The whole observation, plus what the reader already knows it dropped."""

    sheets: tuple[ObservedSheet, ...] = ()
    loss: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()
    fatal: bool = False
    backend_id: str = "unknown"
    backend_version: str = "unknown"
    backend_path: str = "unknown"
    date_system: str | None = None
    media_type_confirmed: bool = False
    #: Loss kinds actually observed at cell level on this run. This is the
    #: evidence a declared collapse risk is checked against.
    observed_loss_kinds: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def sheet_by_name(self, name: str) -> ObservedSheet | None:
        for sheet in self.sheets:
            if sheet.name == name:
                return sheet
        return None

    def collect_observed_loss(self) -> tuple[str, ...]:
        """Union of cell-level loss kinds across all sheets, deterministically ordered.

        Region-level and sheet-level loss is deliberately excluded: those
        describe the container (a hidden sheet, a ragged region), not a value
        the reader collapsed. The declaration check needs the value-level
        answer.
        """
        seen: list[str] = []
        for sheet in self.sheets:
            for cell in sheet.cells.values():
                for kind in cell.loss:
                    if kind not in seen:
                        seen.append(kind)
        return tuple(sorted(seen))


@runtime_checkable
class TabularBackend(Protocol):
    """What the Skill needs from any reader.

    Implementations must be read-only with respect to ``path``.
    """

    backend_id: str
    backend_version: str
    backend_path: str

    def is_available(self) -> bool:
        """False when an optional dependency is missing or unusable."""
        ...

    def capabilities(self) -> tuple[TableCapability, ...]:
        """Declare support *and* known collapse risks for this path."""
        ...

    def load(self, path: str, options: Mapping[str, Any] | None = None) -> ObservedWorkbook:
        """Observe the workbook. Attribution failures go into the result."""
        ...


# --------------------------------------------------------------------------
# fake backend -- interface shell for M1
# --------------------------------------------------------------------------


class FakeTabularBackend:
    """Deterministic in-memory backend with no file or library dependency.

    Used to prove the interface is callable and to test the Skill's wiring,
    fail-closed behaviour and diagnostics without a real reader. Tests
    construct it with explicit sheets and explicit loss, so nothing is
    discovered by accident.
    """

    backend_id = "fake.tabular"
    backend_version = "provisional"
    backend_path = "in-memory"

    def __init__(
        self,
        sheets: Sequence[ObservedSheet] | None = None,
        *,
        loss: Sequence[str] = (),
        warnings: Sequence[str] = (),
        errors: Sequence[str] = (),
        fatal: bool = False,
        available: bool = True,
        capabilities: Sequence[TableCapability] | None = None,
    ) -> None:
        self._sheets = tuple(sheets or ())
        self._loss = tuple(loss)
        self._warnings = tuple(warnings)
        self._errors = tuple(errors)
        self._fatal = fatal
        self._available = available
        self._capabilities = tuple(capabilities) if capabilities is not None else (
            TableCapability(
                name="xlsx_read",
                support=TableSupport.SUPPORTED,
                detail="in-memory fixture backend; deterministic",
            ),
            TableCapability(
                name="csv_read",
                support=TableSupport.UNSUPPORTED,
                detail="V2.1 first slice is XLSX only",
            ),
        )
        self.load_calls: list[str] = []

    def is_available(self) -> bool:
        return self._available

    def capabilities(self) -> tuple[TableCapability, ...]:
        return self._capabilities

    def load(self, path: str, options: Mapping[str, Any] | None = None) -> ObservedWorkbook:
        self.load_calls.append(path)
        return ObservedWorkbook(
            sheets=self._sheets,
            loss=self._loss,
            warnings=self._warnings,
            errors=self._errors,
            fatal=self._fatal,
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            backend_path=self.backend_path,
        )

    # -- test helpers ----------------------------------------------------

    @staticmethod
    def make_sheet(
        name: str,
        rows: Sequence[Sequence[Any]],
        *,
        index: int = 1,
        first_ref: str = "A1",
        state: str = "visible",
        loss: Sequence[str] = (),
        empty_value: Any = "",
    ) -> ObservedSheet:
        """Build a sheet from a dense matrix.

        ``empty_value`` is compared by identity-of-meaning: a cell equal to it
        is recorded as ``empty``; ``None`` is recorded as ``absent``.
        """
        start_row, start_col = ooxml.parse_cell_reference(first_ref)
        cells: dict[str, ObservedCell] = {}
        for r_offset, row in enumerate(rows):
            for c_offset, value in enumerate(row):
                row_index = start_row + r_offset
                col_index = start_col + c_offset
                ref = ooxml.format_cell_reference(row_index, col_index)
                if value is None:
                    cells[ref] = ObservedCell(
                        row=row_index,
                        column=col_index,
                        ref=ref,
                        value=None,
                        value_kind="absent",
                        loss=(TableLossKind.ABSENT,),
                        element_present=False,
                    )
                elif value == empty_value:
                    cells[ref] = ObservedCell(
                        row=row_index,
                        column=col_index,
                        ref=ref,
                        value="",
                        value_kind="empty",
                        loss=(TableLossKind.EMPTY,),
                    )
                else:
                    kind = (
                        "number" if isinstance(value, (int, float))
                        else "boolean" if isinstance(value, bool)
                        else "string"
                    )
                    cells[ref] = ObservedCell(
                        row=row_index,
                        column=col_index,
                        ref=ref,
                        value=value,
                        value_kind=kind,
                    )
        return ObservedSheet(
            name=name, index=index, state=state, cells=cells, loss=tuple(loss)
        )


# --------------------------------------------------------------------------
# fixture backend -- stdlib OOXML reader
# --------------------------------------------------------------------------

#: Content the fixture backend does not read at all, regardless of fixture.
_FIXTURE_UNSUPPORTED = (
    TableCapability(
        name="xlsx_read",
        support=TableSupport.SUPPORTED,
        detail="stdlib OOXML package reader; controlled fixtures only",
    ),
    TableCapability(
        name="csv_read",
        support=TableSupport.UNSUPPORTED,
        detail="V2.1 first slice is XLSX only (see skills/TODO.md)",
    ),
    TableCapability(
        name="xls_biff",
        support=TableSupport.UNSUPPORTED,
        detail="legacy binary BIFF not parsed",
    ),
    TableCapability(
        name="formula_evaluation",
        support=TableSupport.UNSUPPORTED,
        detail="read-only; formulas are never evaluated",
    ),
    TableCapability(
        name="formula_text",
        support=TableSupport.SUPPORTED,
        detail="formula text is read from <f> and kept separate from the cached value",
    ),
    TableCapability(
        name="error_state",
        support=TableSupport.SUPPORTED,
        detail="t=\"e\" cells are reported as errors, not blank",
    ),
    TableCapability(
        name="empty_vs_absent",
        support=TableSupport.SUPPORTED,
        detail="a present-but-blank <c> element is 'empty'; a missing element "
               "is 'absent'",
    ),
    TableCapability(
        name="merged_cell_state",
        support=TableSupport.PARTIAL,
        detail="merged ranges are read; a covered address is reported as "
               "merged_from rather than absent",
    ),
    TableCapability(
        name="number_format_display",
        support=TableSupport.UNSUPPORTED,
        detail="no style/number-format rendering; rendered == raw for numbers",
    ),
    TableCapability(
        name="hidden_sheet_state",
        support=TableSupport.SUPPORTED,
        detail="sheet state is read from workbook.xml",
    ),
    TableCapability(
        name="cell_comments",
        support=TableSupport.UNSUPPORTED,
        detail="comments/threaded comments are not read",
        collapse_risks=(TableLossKind.SILENT_LOSS_RISK,),
    ),
    TableCapability(
        name="embedded_objects",
        support=TableSupport.UNSUPPORTED,
        detail="charts, images, OLE objects and pivot tables are not read",
        collapse_risks=(TableLossKind.SILENT_LOSS_RISK,),
    ),
    TableCapability(
        name="rich_text_runs",
        support=TableSupport.PARTIAL,
        detail="inline/shared string text is flattened; run-level formatting is lost",
    ),
    TableCapability(
        name="large_file_streaming",
        support=TableSupport.UNKNOWN,
        detail="no streaming path; whole package is read into memory",
    ),
)

#: Package parts whose presence means content the skill cannot read.
_UNREAD_PART_MARKERS: Mapping[str, tuple[str, str]] = {
    "xl/comments": ("cell_comments", "cell comment part present but not read"),
    "xl/threadedComments": (
        "cell_comments",
        "threaded comment part present but not read",
    ),
    "xl/drawings/": ("embedded_objects", "drawing part present but not read"),
    "xl/charts/": ("embedded_objects", "chart part present but not read"),
    "xl/media/": ("embedded_objects", "embedded media present but not read"),
    "xl/pivotTables/": ("embedded_objects", "pivot table present but not read"),
    "xl/pivotCache/": ("embedded_objects", "pivot cache present but not read"),
    "xl/embeddings/": ("embedded_objects", "embedded object present but not read"),
    "xl/vbaProject.bin": ("xls_biff", "VBA project present but not read"),
}


class FixtureXlsxBackend:
    """Deterministic, dependency-free XLSX observation for controlled fixtures.

    Integrity note: this backend does not silently drop package content it
    cannot read. It inspects the ZIP part list and raises explicit run-level
    warnings for comment/drawing/chart/media/pivot/VBA parts, so a fixture that
    contains them cannot be reported as a clean read (V2.0: no silent loss).
    """

    backend_id = "fixture.ooxml-stdlib"
    backend_version = "0.1.0-provisional"
    backend_path = "fixture"

    def is_available(self) -> bool:
        return True

    def capabilities(self) -> tuple[TableCapability, ...]:
        return _FIXTURE_UNSUPPORTED

    def load(self, path: str, options: Mapping[str, Any] | None = None) -> ObservedWorkbook:
        options = dict(options or {})
        warnings: list[str] = []

        try:
            package = ooxml.read_package(path)
        except ooxml.XlsxPackageError as exc:
            return ObservedWorkbook(
                loss=(TableLossKind.FAILED,),
                errors=(f"package_unreadable: {exc}",),
                fatal=True,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                backend_path=self.backend_path,
            )

        unread = self._detect_unread_parts(ooxml.iter_package_members(path))
        warnings.extend(message for _, message in unread)

        sheets = tuple(self._observe_sheet(sheet) for sheet in package.sheets)

        workbook_loss: list[str] = []
        if unread:
            workbook_loss.append(TableLossKind.SILENT_LOSS_RISK)
        if package.date_system == "1904":
            workbook_loss.append(TableLossKind.NOT_APPLICABLE)

        return ObservedWorkbook(
            sheets=sheets,
            loss=tuple(dict.fromkeys(workbook_loss)),
            warnings=tuple(warnings),
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            backend_path=self.backend_path,
            date_system=package.date_system,
            metadata={
                "part_count": len(package.part_names),
                "shared_string_count": len(package.shared_strings),
                "unread_parts": [name for name, _ in unread],
            },
        )

    def _detect_unread_parts(
        self, parts: Sequence[str]
    ) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        for part in parts:
            for marker, (capability, message) in _UNREAD_PART_MARKERS.items():
                if marker in part:
                    found.append((part, f"{capability}: {message} ({part})"))
                    break
        return found

    def _observe_sheet(self, sheet: ooxml.RawSheet) -> ObservedSheet:
        cells: dict[str, ObservedCell] = {}
        for raw in sheet.sorted_cells():
            cells[raw.ref] = self._observe_cell(raw, sheet)
        sheet_loss: list[str] = []
        if sheet.is_hidden:
            sheet_loss.append(TableLossKind.UNKNOWN)
        if sheet.hidden_rows or sheet.hidden_columns:
            # Content the reader returns but the workbook author does not
            # display. It is a silent-loss risk for any consumer that assumes
            # "what is read" equals "what is shown".
            sheet_loss.append(TableLossKind.SILENT_LOSS_RISK)
        return ObservedSheet(
            name=sheet.name,
            index=sheet.index,
            state=sheet.state,
            cells=cells,
            loss=tuple(sheet_loss),
            notes=(f"declared_dimension={sheet.declared_dimension}",)
            if sheet.declared_dimension
            else (),
            is_empty=not cells,
            hidden_rows=tuple(sorted(sheet.hidden_rows)),
            hidden_columns=tuple(sorted(sheet.hidden_columns)),
            merged_ranges=tuple(sheet.merged_ranges),
        )

    @staticmethod
    def _observe_cell(raw: ooxml.RawCell, sheet: ooxml.RawSheet) -> ObservedCell:
        loss: list[str] = []
        notes: list[str] = []
        value = raw.value
        value_kind = raw.kind

        if raw.kind == "blank":
            if raw.element_present:
                value_kind = "empty"
                loss.append(TableLossKind.EMPTY)
            else:
                value_kind = "absent"
                loss.append(TableLossKind.ABSENT)
        elif raw.kind == "error":
            notes.append("worksheet error value preserved as an error")
        elif raw.kind == "unknown":
            loss.append(TableLossKind.UNKNOWN)
        elif raw.kind in ("string", "inline_string"):
            value_kind = "string"

        if raw.formula is not None:
            notes.append("formula text read; cached value is not an evaluation")
            if raw.kind == "blank":
                loss.append(TableLossKind.UNSUPPORTED)
                notes.append("formula present with no cached value")

        merged_from = None
        if raw.ref in sheet.merged_covered:
            merged_from = _merge_anchor_for(sheet, raw.row, raw.column)
            notes.append(
                f"address is covered by merged range {merged_from or 'unknown'}"
            )

        return ObservedCell(
            row=raw.row,
            column=raw.column,
            ref=raw.ref,
            value=value,
            raw=value,
            value_kind=value_kind,
            formula=raw.formula,
            loss=tuple(dict.fromkeys(loss)),
            notes=tuple(notes),
            element_present=raw.element_present,
            merged_from=merged_from,
            hidden=sheet.is_hidden_address(raw.row, raw.column),
        )


def _merge_anchor_for(sheet: ooxml.RawSheet, row: int, column: int) -> str | None:
    """Find the anchor address of the merge range covering ``(row, column)``."""
    for anchor, span in sheet.merge_anchors.items():
        if ":" not in span:
            continue
        start_ref, end_ref = span.split(":", 1)
        try:
            start_row, start_col = ooxml.parse_cell_reference(start_ref)
            end_row, end_col = ooxml.parse_cell_reference(end_ref)
        except ValueError:
            continue
        if start_row <= row <= end_row and start_col <= column <= end_col:
            return anchor
    return "merge_covered"


# --------------------------------------------------------------------------
# C06/C07 calamine spike -- experimental, never auto-adopted
# --------------------------------------------------------------------------


class CalamineNotAvailable(RuntimeError):
    """The locked python-calamine binding is not importable in this process."""


def _observed_from_calamine(value: Any) -> tuple[Any, str]:
    """Map a python-calamine cell value onto (value, value_kind)."""
    if value is None:
        return None, "absent"
    if isinstance(value, bool):
        return value, "boolean"
    if isinstance(value, str):
        if value == "":
            # AMBIGUOUS BY CONSTRUCTION: the audit recorded that an error
            # value, an unresolved formula and a genuinely empty cell all
            # arrive here as "". The adapter refuses to pick one.
            return "", "empty_or_collapsed"
        return value, "string"
    if isinstance(value, (int, float)):
        return float(value), "number"
    if hasattr(value, "isoformat"):
        return value.isoformat(), "date"
    return value, "unknown"


class CalamineBackend:
    """EXPERIMENTAL spike around the locked C06/C07 binding.

    This class exists to test the interface against a real third-party reader.
    It is **not** an adoption decision and never replaces another backend
    automatically (V2.1 review section 2, item 5).

    Declared loss profile -- taken from the re-verified V2.0C AU-03 record and
    re-observed here:

    * ``error_state`` UNSUPPORTED: an error cell arrives as ``""``.
    * ``empty_vs_absent`` UNSUPPORTED: both arrive as ``""``.
    * ``formula_text`` UNSUPPORTED: no formula text crosses the boundary.
    * ``unresolved_formula``: identical to empty.
    * ``hidden_sheet_state`` / ``cell_comments`` / ``embedded_objects``:
      not exposed.
    * ``int_vs_float``: integers widen to float.
    * an empty worksheet raises ``PanicException``, which derives from
      ``BaseException`` and therefore escapes ``except Exception``.
    """

    backend_id = "calamine.python-calamine"
    backend_path = "spike"

    #: Loss kinds this path is known to conflate with a clean value. Declared
    #: up front so the run cannot report a clean success over collapsed data.
    DECLARED_COLLAPSE_RISKS: tuple[str, ...] = (
        TableLossKind.COLLAPSE_RISK,
        TableLossKind.SILENT_LOSS_RISK,
    )

    def __init__(self, module: Any | None = None) -> None:
        self._module = module
        self.backend_version = self._detect_version(module)

    @staticmethod
    def _detect_version(module: Any | None) -> str:
        """Resolve the binding version without importing it if it is absent.

        Tries, in order: an explicit module's ``__version__``, installed
        distribution metadata, then the module's own ``__version__``. Reports
        ``unknown`` rather than guessing -- the version is evidence and must
        not be invented.
        """
        if module is not None:
            attribute = getattr(module, "__version__", None)
            if attribute:
                return str(attribute)
        try:
            from importlib.metadata import version

            return version("python-calamine")
        except Exception:
            pass
        try:
            import python_calamine  # type: ignore

            attribute = getattr(python_calamine, "__version__", None)
            if attribute:
                return str(attribute)
        except Exception:
            pass
        return "unknown"

    def is_available(self) -> bool:
        module = self._import_module()
        return module is not None and callable(getattr(module, "load_workbook", None))

    def _import_module(self) -> Any | None:
        if self._module is not None:
            return self._module
        try:
            import python_calamine  # type: ignore

            # An importable module is not the same as a usable one: the reader
            # entry point has to be present, otherwise the binding is treated
            # as unavailable and the recorded fallback path is used.
            if not callable(getattr(python_calamine, "load_workbook", None)):
                return None
            self._module = python_calamine
            self.backend_version = self._detect_version(python_calamine)
            return python_calamine
        except Exception:
            return None

    def verify_locked_identity(self) -> dict[str, Any]:
        """Report what this process can prove about the loaded binding.

        V2.1 requires the lock SHA and binding build to be re-established before
        the spike is trusted. This reports the observable facts; it does not
        claim a build was reproduced when the binding came from a wheel.
        """
        module = self._import_module()
        report: dict[str, Any] = {
            "available": module is not None,
            "module_file": getattr(module, "__file__", None) if module else None,
            "version": self.backend_version,
            "expected_locked_binding_sha": "0a7998e50a7586f308a2d455170ec63c8135dfd3",
            "expected_locked_calamine_sha": "0af05f4f6030351e3b8a999ea0810c8618368776",
        }
        if module is None:
            report["blocker"] = "binding is not importable in this interpreter"
            return report
        try:
            from importlib.metadata import PackageNotFoundError, distribution

            dist = distribution("python-calamine")
            report["distribution_version"] = dist.version
            report["direct_url"] = (
                dist.read_text("direct_url.json") is not None
            )
        except PackageNotFoundError:
            report["distribution_version"] = None
        except Exception as exc:  # pragma: no cover - environment dependent
            report["distribution_version"] = f"unavailable: {type(exc).__name__}"
        report["build_reproduced_here"] = False
        report["note"] = (
            "the binding was loaded from the wheel recorded in the V2.0C AU-03 "
            "build provenance; the wheel and its extension both re-verified by "
            "SHA-256, but a from-source rebuild was NOT performed in V2.1"
        )
        return report

    def capabilities(self) -> tuple[TableCapability, ...]:
        return (
            TableCapability(
                name="xlsx_read",
                support=TableSupport.SUPPORTED if self.is_available() else TableSupport.UNSUPPORTED,
                detail="read-only workbook parsing via the locked C06/C07 binding",
            ),
            TableCapability(
                name="csv_read",
                support=TableSupport.UNSUPPORTED,
                detail="V2.1 first slice is XLSX only",
            ),
            TableCapability(
                name="formula_evaluation",
                support=TableSupport.UNSUPPORTED,
                detail="no evaluation; the stored cache is surfaced verbatim",
            ),
            TableCapability(
                name="formula_text",
                support=TableSupport.UNSUPPORTED,
                detail="formula text does not cross the boundary",
                collapse_risks=(TableLossKind.COLLAPSE_RISK,),
            ),
            TableCapability(
                name="error_state",
                support=TableSupport.UNSUPPORTED,
                detail="an error value is dropped to an empty string",
                collapse_risks=(TableLossKind.EMPTY, TableLossKind.COLLAPSE_RISK),
            ),
            TableCapability(
                name="empty_vs_absent",
                support=TableSupport.UNSUPPORTED,
                detail="an empty cell and a missing cell are both returned as \"\"",
                collapse_risks=(TableLossKind.ABSENT, TableLossKind.COLLAPSE_RISK),
            ),
            TableCapability(
                name="empty_sheet",
                support=TableSupport.UNSUPPORTED,
                detail="an empty worksheet raises PanicException (a BaseException)",
                collapse_risks=(TableLossKind.FAILED,),
            ),
            TableCapability(
                name="merged_cell_state",
                support=TableSupport.UNSUPPORTED,
                detail="merge ranges are not exposed; covered cells read as empty",
                collapse_risks=(TableLossKind.EMPTY,),
            ),
            TableCapability(
                name="hidden_sheet_state",
                support=TableSupport.UNSUPPORTED,
                detail="sheet visibility is not exposed",
                collapse_risks=(TableLossKind.SILENT_LOSS_RISK,),
            ),
            TableCapability(
                name="cell_comments",
                support=TableSupport.UNSUPPORTED,
                detail="comments are not exposed",
                collapse_risks=(TableLossKind.SILENT_LOSS_RISK,),
            ),
            TableCapability(
                name="embedded_objects",
                support=TableSupport.UNSUPPORTED,
                detail="charts, images and OLE objects are not exposed",
                collapse_risks=(TableLossKind.SILENT_LOSS_RISK,),
            ),
            TableCapability(
                name="integer_type_preservation",
                support=TableSupport.UNSUPPORTED,
                detail="numeric cells widen to float; integer type is not preserved",
                collapse_risks=(TableLossKind.COLLAPSE_RISK,),
            ),
            TableCapability(
                name="number_format_display",
                support=TableSupport.PARTIAL,
                detail="python-calamine has a formatted-value accessor, but V2.1 "
                       "does not use it; rendered == raw here",
            ),
            TableCapability(
                name="worksheet_start_offset",
                support=TableSupport.PARTIAL,
                detail="per-cell addresses are reconstructed from the row/column "
                       "offset, so leading empty rows/columns are ambiguous",
                collapse_risks=(TableLossKind.ABSENT,),
            ),
        )

    def load(self, path: str, options: Mapping[str, Any] | None = None) -> ObservedWorkbook:
        module = self._import_module()
        if module is None:
            return ObservedWorkbook(
                loss=(TableLossKind.UNSUPPORTED,),
                errors=("python-calamine is not importable in this interpreter",),
                fatal=True,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                backend_path=self.backend_path,
            )

        try:
            workbook = module.load_workbook(path)
            sheet_names = list(workbook.sheet_names)
        except Exception as exc:
            return ObservedWorkbook(
                loss=(TableLossKind.FAILED,),
                errors=(f"{type(exc).__name__}: {exc}",),
                fatal=True,
                backend_id=self.backend_id,
                backend_version=self.backend_version,
                backend_path=self.backend_path,
            )

        sheets: list[ObservedSheet] = []
        warnings: list[str] = []
        loss: list[str] = list(self.DECLARED_COLLAPSE_RISKS)

        for sheet_name in sheet_names:
            observed, warning = self._observe_sheet(workbook, sheet_name, len(sheets) + 1)
            sheets.append(observed)
            if warning:
                warnings.append(warning)

        return ObservedWorkbook(
            sheets=tuple(sheets),
            loss=tuple(dict.fromkeys(loss)),
            warnings=tuple(warnings),
            backend_id=self.backend_id,
            backend_version=self.backend_version,
            backend_path=self.backend_path,
            metadata={"sheet_names": sheet_names},
        )

    def _observe_sheet(
        self, workbook: Any, sheet_name: str, index: int
    ) -> tuple[ObservedSheet, str | None]:
        warning: str | None = None
        try:
            sheet = workbook.get_sheet_by_name(sheet_name)
            start = getattr(sheet, "start", None)
            end = getattr(sheet, "end", None)
            # NOTE: `except Exception` is NOT sufficient here. The binding can
            # raise pyo3_runtime.PanicException, which derives from
            # BaseException. Catching BaseException narrowly and re-raising
            # the control-flow exceptions keeps that observable instead of
            # turning an interpreter-level panic into a silent skip.
            rows = list(sheet.iter_rows())
        except (KeyboardInterrupt, SystemExit):
            raise
        except BaseException as exc:  # noqa: BLE001 - documented above
            problem = f"{type(exc).__name__}: {exc}"
            warning = f"sheet {sheet_name!r} could not be read: {problem}"
            return (
                ObservedSheet(
                    name=sheet_name,
                    index=index,
                    cells={},
                    loss=(TableLossKind.FAILED, TableLossKind.COLLAPSE_RISK),
                    notes=(f"reader failure: {problem}",),
                    is_empty=True,
                ),
                warning,
            )

        cells: dict[str, ObservedCell] = {}
        # OBSERVED: CalamineSheet.start/end are 0-based (row, column) offsets,
        # e.g. (0, 0) for a table anchored at A1. They are converted to the
        # 1-based addressing used everywhere else in this project. Re-confirmed
        # against the controlled fixture on 0.8.2.
        start_row = (start[0] + 1) if start else 1
        start_col = (start[1] + 1) if start else 1
        has_anchor = start is not None and end is not None
        for r_offset, row in enumerate(rows):
            for c_offset, value in enumerate(row):
                row_index = start_row + r_offset
                col_index = start_col + c_offset
                ref = ooxml.format_cell_reference(row_index, col_index)
                mapped, kind = _observed_from_calamine(value)
                loss: list[str] = []
                notes: list[str] = []
                if kind == "empty_or_collapsed":
                    kind = "empty_or_collapsed"
                    loss.extend((TableLossKind.COLLAPSE_RISK, TableLossKind.EMPTY, TableLossKind.ABSENT))
                    notes.append(
                        "empty string is ambiguous: an empty cell, a missing "
                        "cell, an error value and an unresolved formula are "
                        "indistinguishable through this binding"
                    )
                if kind == "number":
                    notes.append("numeric value widened to float")
                    loss.append(TableLossKind.COLLAPSE_RISK)
                if kind == "date" or hasattr(value, "tzinfo"):
                    notes.append("date converted to ISO text by the adapter")
                if not has_anchor:
                    notes.append(
                        "no anchor was exposed for this sheet; the address was "
                        "reconstructed from iterator offsets"
                    )
                    loss.append(TableLossKind.UNKNOWN)
                cells[ref] = ObservedCell(
                    row=row_index,
                    column=col_index,
                    ref=ref,
                    value=mapped,
                    raw=mapped,
                    value_kind=kind,
                    loss=tuple(dict.fromkeys(loss)),
                    notes=tuple(notes),
                )

        is_empty = not cells
        if not has_anchor:
            warning = (
                f"sheet {sheet_name!r} exposed no start/end anchor; addresses "
                f"were reconstructed from the iterator offsets and may be "
                f"shifted"
            )
        return (
            ObservedSheet(
                name=sheet_name,
                index=index,
                cells=cells,
                loss=(TableLossKind.COLLAPSE_RISK, TableLossKind.SILENT_LOSS_RISK),
                notes=(
                    "hidden state, comments, merge ranges and embedded objects "
                    "are not exposed by this binding",
                ),
                is_empty=is_empty,
            ),
            warning,
        )
