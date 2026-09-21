"""V2.1.1 closure -- experimental table context.

TERMINOLOGY (V2.1 closure patch)
--------------------------------
This module previously used "table identity" language. Independent review
correctly objected: the experiments established **address**, **context** and
**location reconstruction**, and never established equality, duplicate
semantics, revision semantics or persistent identity. Calling the result an
"identity" overstated the capability. The neutral term used throughout is now
**table context**, and the candidate keys are *hints* attached to a context,
not names for a thing.

PROBLEM
-------
V2.1 proved a citation can be rebuilt to a *cell*. It did not solve the step
before that: deciding *which table* a cell belongs to. A table address
(worksheet + bounds) is not sufficient to describe a table, because:

* the same bounds can describe different tables across re-parses,
* the same header values can occur in several tables,
* two tables can have byte-identical content at different addresses.

WHAT THIS MODULE IS
-------------------
Three candidate contexts, evaluated side by side. It deliberately does **not**
pick a winner:

``A``  worksheet + range
``B``  worksheet + range + header/row-label values
``C``  worksheet + range + full header context + content fingerprint

Each candidate is a *hint*: a value a caller can supply to ask for a specific
table. ``compare_contexts`` reports which candidates separate two tables and
which collapse them. Collapsing candidates are the dangerous ones, because a
resolver that used them would have to guess.

WHAT IT IS NOT
--------------
Not an identity framework, not an identity module, not a schema, not a
registry. Nothing here claims two tables are "the same". No field is frozen.
Everything is marked ``PROVISIONAL``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

from .contracts import TableEvidenceUnit, TableLossKind
from .contracts import TableCapability, TableSupport

__all__ = [
    "CANDIDATE_KEYS",
    "TABLE_CONTEXT_METADATA_KEY",
    "CandidateRelation",
    "ContextProblem",
    "TableCandidate",
    "Unresolved",
    "TableContextQuery",
    "TableResolution",
    "TableContext",
    "build_table_context",
    "context_hint",
    "compare_contexts",
    "compare_resolvability",
    "candidate_components",
    "query_key",
    "query_for_context",
    "resolve_table_query",
    "measurement_for_candidate",
    "collapsed_pairs_for_candidate",
    "build_ambiguity_matrix",
    "build_collision_matrix",
    "make_capability",
    "unit_table_context",
    "unit_context_hints",
    "CELL_VALUE_KINDS_FOR_FINGERPRINT",
]

#: The metadata key under which a Skill may attach experimental table context.
#: This is a *convention between this module and the Skill that writes it*, not
#: a Core concept: ``core/evidence.py`` neither knows nor requires it.
TABLE_CONTEXT_METADATA_KEY = "table_context"

#: The three candidates, in increasing strength. Order matters only for
#: reporting; no candidate is preferred by this module.
CANDIDATE_KEYS: tuple[str, ...] = ("A", "B", "C")


# --------------------------------------------------------------------------
# reading context off a unit -- SKILL side, deliberately not Core
# --------------------------------------------------------------------------


def unit_table_context(unit: TableEvidenceUnit) -> dict[str, Any] | None:
    """The experimental table context attached to a unit, or ``None``.

    This lives here rather than on ``TableEvidenceUnit`` on purpose. A generic
    evidence record must not grow table-specific accessors: Core understands
    ``TableEvidenceUnit``, ``TableRunResult``, generic references and diagnostics, and
    nothing about tables. The context is a convention between this module and
    the Skill that writes it, read out of the unit's generic ``metadata``.

    ``None`` means "no context attached", which is a normal state -- a
    worksheet-level unit, a non-tabular unit, or a unit produced by a Skill
    that does not implement this convention.
    """
    context = (unit.metadata or {}).get(TABLE_CONTEXT_METADATA_KEY)
    return dict(context) if isinstance(context, Mapping) else None


def unit_context_hints(unit: TableEvidenceUnit) -> dict[str, Any] | None:
    """The candidate context hints attached to a unit, or ``None``.

    ``{"A": ..., "B": ..., "C": ...}``. Read-only and unfrozen.
    """
    context = unit_table_context(unit)
    if not context:
        return None
    hints = context.get("context_hints")
    return dict(hints) if isinstance(hints, Mapping) else None


@dataclass
class Unresolved:
    """Nothing matched. Returning this is a valid outcome, not a failure.

    Shared by the table-level and cell-level resolvers so that "no candidate
    matched" has exactly one representation across the Skill.
    ``unit_id`` is empty for a table-level query, which spans units.
    """

    unit_id: str
    problem: str
    message: str
    candidates: tuple[str, ...] = ()

    PROVISIONAL = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": "unresolved",
            "unit_id": self.unit_id,
            "problem": self.problem,
            "message": self.message,
            "candidates": list(self.candidates),
        }


def resolve_table_context(
    units: Sequence[TableEvidenceUnit],
    *,
    hint: str,
    candidate: str | None = None,
) -> TableResolution | Unresolved:
    """Decide *which table* a hint refers to. Never decides a cell.

    This is the table-level entry point for the "which table is this?" question,
    and it returns a **table-level** result only:

    * exactly one match  -> ``TableResolution(unique=True, table=...)``
    * more than one      -> ``TableResolution(unique=False,
                            problem="ambiguous", candidates=(...))``
    * no match           -> ``Unresolved``
    * bad candidate key  -> ``Unresolved``

    It deliberately does **not** return a citation. An earlier revision
    manufactured a citation to the region's own anchor cell when a hint matched
    a single table. That silently chose evidence: the caller asked which table,
    got a cell, and had no way to tell that the cell was a syntactically
    convenient one rather than a meaningful one. A cell citation requires an
    explicit cell selector through ``skills.luohai.citation.resolve_citation``.

    This function lives here rather than in ``citation`` because it never
    produces a citation. ``citation`` depends on this module, not the reverse.
    """
    if not hint:
        return Unresolved(
            unit_id="",
            problem=ContextProblem.MALFORMED_QUERY,
            message="hint must be a non-empty context string",
        )

    key = (candidate or "").strip().upper() or None
    if key is not None and key not in CANDIDATE_KEYS:
        return Unresolved(
            unit_id="",
            problem=ContextProblem.MALFORMED_QUERY,
            message=(
                f"unknown context candidate {candidate!r}; expected one of "
                f"{list(CANDIDATE_KEYS)}"
            ),
        )

    matches: list[TableCandidate] = []
    address_only = False
    for unit in units:
        hints = unit_context_hints(unit)
        if not hints:
            continue
        if key is not None:
            if hints.get(key) == hint:
                matches.append(_resolved_table_candidate(unit, key, hint, "exact"))
            continue
        for candidate_key in CANDIDATE_KEYS:
            if hints.get(candidate_key) == hint:
                matches.append(
                    _resolved_table_candidate(unit, candidate_key, hint, "exact")
                )
                break
        else:
            # Candidate A is the address component of B and C, so an A-shaped
            # hint can legitimately match any candidate. Recorded as weaker so
            # the caller can see why it matched.
            if hint in {str(v) for v in hints.values()}:
                matches.append(_resolved_table_candidate(unit, "?", hint, "address_only"))
                address_only = True

    query = TableContextQuery(
        candidate=key or ("A" if address_only else "?"), scope="artifact"
    )
    if not matches:
        return Unresolved(
            unit_id="",
            problem=ContextProblem.UNRESOLVED,
            message=f"no table matched the context hint {hint!r}",
        )
    if len(matches) > 1:
        return TableResolution(
            unique=False,
            query=query,
            candidates=tuple(matches),
            problem=ContextProblem.AMBIGUOUS,
            message=(
                f"{len(matches)} tables match this context; no single table is "
                f"described. Supply a distinguishing hint, or address the unit "
                f"directly."
            ),
        )
    return TableResolution(unique=True, query=query, table=matches[0])


def _resolved_table_candidate(
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

#: Cell kinds that contribute content to the fingerprint. Empty and absent
#: coordinates contribute a placeholder so that *shape* is part of the
#: fingerprint: two tables with the same values but different gaps are not
#: identical tables.
CELL_VALUE_KINDS_FOR_FINGERPRINT = (
    "number",
    "string",
    "inline_string",
    "boolean",
    "error",
    "empty",
    "absent",
    "unknown",
)


class CandidateRelation:
    """How one candidate context behaves across two tables."""

    #: The two contexts differ: the candidate can tell the tables apart.
    DISTINGUISHES = "distinguishes"
    #: The two contexts are equal: the candidate collapses the tables, so a
    #: resolver relying on it alone would be forced to guess.
    COLLAPSES = "collapses"
    #: At least one context is missing the data this candidate needs.
    UNDETERMINED = "undetermined"

    ALL = (DISTINGUISHES, COLLAPSES, UNDETERMINED)


def _fingerprint_grid(cells: Sequence[Mapping[str, Any]]) -> str:
    """A content hash that ignores addresses but keeps shape.

    Addresses are excluded deliberately. Including them would make the
    "fingerprint" a restatement of the range, which would hide exactly the
    collision this candidate exists to detect.
    """
    if not cells:
        return "empty"
    rows = sorted({int(c["row"]) for c in cells})
    cols = sorted({int(c["column"]) for c in cells})
    row_index = {value: position for position, value in enumerate(rows)}
    col_index = {value: position for position, value in enumerate(cols)}
    grid: list[list[str]] = [["" for _ in cols] for _ in rows]
    for cell in cells:
        kind = str(cell.get("value_kind", "unknown"))
        # A formula contributes its text, not its cache: two tables that differ
        # only in formula text are different tables.
        formula = cell.get("formula")
        if formula:
            token = f"formula:{formula}"
        elif kind in ("empty", "absent"):
            token = f"<{kind}>"
        else:
            token = f"{kind}:{cell.get('value')!r}"
        grid[row_index[int(cell["row"])]][col_index[int(cell["column"])]] = token
    canonical = json.dumps(grid, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class TableContext:
    """The three candidate contexts for one detected table.

    ``candidate_a/b/c`` are opaque string keys. ``values`` keeps the components
    so a caller can inspect *why* a candidate collapses or distinguishes,
    instead of only learning that it did.
    """

    region_id: str
    sheet_name: str
    bounds: str
    candidate_a: str
    candidate_b: str
    candidate_c: str
    values: dict[str, Any] = field(default_factory=dict)

    PROVISIONAL = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "provisional": True,
            "region_id": self.region_id,
            "sheet_name": self.sheet_name,
            "bounds": self.bounds,
            "candidate_a": self.candidate_a,
            "candidate_b": self.candidate_b,
            "candidate_c": self.candidate_c,
            "values": self.values,
        }

    def hint(self, candidate: str) -> str:
        """The hint string for one candidate key."""
        key = candidate.strip().upper()
        if key == "A":
            return self.candidate_a
        if key == "B":
            return self.candidate_b
        if key == "C":
            return self.candidate_c
        raise ValueError(f"unknown context candidate: {candidate!r}")

    def matches(self, candidate: str, hint: str) -> bool:
        return self.hint(candidate) == hint


def _header_row_values(cells: Sequence[Mapping[str, Any]], header_row: int) -> list[Any]:
    return [
        cell.get("value")
        for cell in cells
        if int(cell["row"]) == header_row and cell.get("is_header")
    ]


def _row_label_values(
    cells: Sequence[Mapping[str, Any]], label_column: int, header_row: int
) -> list[Any]:
    return [
        cell.get("value")
        for cell in cells
        if int(cell["column"]) == label_column
        and int(cell["row"]) != header_row
        and cell.get("value") is not None
    ]


def _duplicates(values: Iterable[Any]) -> list[Any]:
    seen: dict[Any, int] = {}
    for value in values:
        if value is None:
            continue
        seen[value] = seen.get(value, 0) + 1
    return sorted(
        (value for value, count in seen.items() if count > 1), key=lambda v: str(v)
    )


def build_table_context(
    block: Mapping[str, Any],
    *,
    hidden_rows: Sequence[int] = (),
    hidden_columns: Sequence[int] = (),
    merged_ranges: Sequence[str] = (),
) -> TableContext:
    """Build the three candidate contexts from a tabular payload block.

    ``block`` is the ``payload["tabular"]`` mapping produced by the Skill. The
    extra arguments carry sheet-level structural facts that the region alone
    does not know (hidden axes, merge ranges); they are recorded as *context*
    for candidate C, never as part of the address.
    """
    sheet_name = str(block.get("sheet_name"))
    bounds = str(block.get("bounds"))
    header_row = int(block.get("header_row") or 1)
    label_column = int(block.get("label_column_index") or 1)
    cells = [c for c in block.get("cells", ()) if isinstance(c, Mapping)]

    header_values = _header_row_values(cells, header_row)
    row_labels = _row_label_values(cells, label_column, header_row)
    fingerprint = _fingerprint_grid(cells)

    header_columns = {
        str(letter): value
        for letter, value in (block.get("column_headers") or {}).items()
    }
    header_context = {
        "bounds": bounds,
        "header_row": header_row,
        "header_row_values": header_values,
        "header_column_values": row_labels,
        "header_columns": header_columns,
        "width": block.get("width"),
        "height": block.get("height"),
        "ragged_rows": list(block.get("ragged_rows") or ()),
        "hidden_rows": sorted(int(r) for r in hidden_rows),
        "hidden_columns": sorted(int(c) for c in hidden_columns),
        "merged_ranges": sorted(str(m) for m in merged_ranges),
        "duplicate_column_headers": _duplicates(header_columns.values()),
        "duplicate_row_labels": _duplicates(row_labels),
    }

    #: The full candidate hints, for reference.
    candidate_a = f"sheet:{sheet_name}|range:{bounds}"
    candidate_b = (
        f"{candidate_a}|headers:"
        + json.dumps(
            {"columns": header_columns, "rows": row_labels},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    candidate_c = (
        f"{candidate_b}|context:"
        + json.dumps(header_context, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + f"|fingerprint:{fingerprint}"
    )

    return TableContext(
        region_id=str(block.get("region_id")),
        sheet_name=sheet_name,
        bounds=bounds,
        candidate_a=candidate_a,
        candidate_b=candidate_b,
        candidate_c=candidate_c,
        values={
            "header_row": header_row,
            "header_row_values": header_values,
            "header_column_values": row_labels,
            "header_columns": header_columns,
            "content_fingerprint": fingerprint,
            "header_context": header_context,
            "structural": {
                "hidden_rows": sorted(int(r) for r in hidden_rows),
                "hidden_columns": sorted(int(c) for c in hidden_columns),
                "merged_ranges": sorted(str(m) for m in merged_ranges),
            },
        },
    )


def candidate_components(context: TableContext, candidate: str) -> tuple[Any, ...]:
    """The part of a candidate that decides *which table* it is.

    Comparing full candidate strings only asks "are these two contexts
    identical?". The question a resolver faces is different: "would a caller
    supplying this candidate's query still be able to tell the tables apart?".
    These components are the answer, and they must contain no address-derived
    detail beyond the address itself.

    An earlier version of this function used the per-column header *mapping*
    (``{"A": "Port", "B": "2023"}``). That mapping contains column letters, so
    it smuggled the address back in and made two byte-identical tables look
    distinguishable. The header *row values* are used instead: they describe the
    table's shape without naming where it sits.
    """
    key = candidate.strip().upper()
    values = context.values
    address = (context.sheet_name, context.bounds)
    header_row_values = tuple(values.get("header_row_values") or ())
    row_labels = tuple(values.get("header_column_values") or ())
    if key == "A":
        return address
    if key == "B":
        return address + (header_row_values, row_labels)
    if key == "C":
        return address + (header_row_values, row_labels, values.get("content_fingerprint"))
    raise ValueError(f"unknown context candidate: {candidate!r}")


def compare_resolvability(
    left: TableContext, right: TableContext
) -> dict[str, str]:
    """Per candidate: can a caller using it tell these two tables apart?

    ``COLLAPSES`` means a resolver restricted to that candidate would find two
    tables matching one hint and must therefore return ambiguity rather than a
    guess.
    """
    outcome: dict[str, str] = {}
    for key in CANDIDATE_KEYS:
        outcome[key] = (
            CandidateRelation.COLLAPSES
            if candidate_components(left, key) == candidate_components(right, key)
            else CandidateRelation.DISTINGUISHES
        )
    return outcome


def context_hint(
    candidate: str,
    *,
    sheet_name: str | None = None,
    bounds: str | None = None,
    header_columns: Mapping[str, Any] | None = None,
    row_labels: Sequence[Any] | None = None,
) -> str:
    """Build a caller-supplied hint for a candidate.

    This exists so a caller can *ask* for a table using a candidate without
    having the full ``TableContext`` in hand -- for example when the
    context came out of a stored evidence record.

    Candidate C cannot be rebuilt from these parts alone, because it includes a
    content fingerprint. ``context_hint('C', ...)`` therefore raises rather
    than returning something that looks like a C hint but is not one.
    """
    key = candidate.strip().upper()
    if key == "A":
        if sheet_name is None or bounds is None:
            raise ValueError("candidate A hint needs sheet_name and bounds")
        return f"sheet:{sheet_name}|range:{bounds}"
    if key == "B":
        if sheet_name is None or bounds is None:
            raise ValueError("candidate B hint needs sheet_name and bounds")
        base = f"sheet:{sheet_name}|range:{bounds}|headers:"
        return base + json.dumps(
            {"columns": dict(header_columns or {}), "rows": list(row_labels or [])},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if key == "C":
        raise ValueError(
            "candidate C includes a content fingerprint and cannot be rebuilt "
            "from sheet/range/headers; use a stored TableContext"
        )
    raise ValueError(f"unknown context candidate: {candidate!r}")


def compare_contexts(
    left: TableContext, right: TableContext
) -> dict[str, str]:
    """Report, per candidate, whether it separates these two tables.

    A ``COLLAPSES`` result is the important one: it means a resolver restricted
    to that candidate could not tell the tables apart and would have to guess.
    """
    outcome: dict[str, str] = {}
    for key in CANDIDATE_KEYS:
        try:
            left_value = left.hint(key)
            right_value = right.hint(key)
        except ValueError:
            outcome[key] = CandidateRelation.UNDETERMINED
            continue
        outcome[key] = (
            CandidateRelation.COLLAPSES
            if left_value == right_value
            else CandidateRelation.DISTINGUISHES
        )
    return outcome


def collapsed_pairs_for_candidate(
    contexts: Mapping[str, TableContext], candidate: str
) -> list[list[str]]:
    """Named table pairs that a single candidate cannot separate.

    Only meaningful for candidates that *omit* the address; every candidate in
    this experiment contains worksheet and range, so this is empty by
    construction. It is kept because the question is worth being able to ask
    once a candidate without an address exists.
    """
    names = sorted(contexts)
    collapsed: list[list[str]] = []
    for i, left_name in enumerate(names):
        for right_name in names[i + 1 :]:
            if candidate_components(contexts[left_name], candidate) == (
                candidate_components(contexts[right_name], candidate)
            ):
                collapsed.append([left_name, right_name])
    return collapsed


def query_key(context: TableContext, candidate: str) -> tuple[Any, ...]:
    """The *query* a caller would issue to ask for this table.

    This is the decisive difference from :func:`candidate_components`. Every
    candidate hint contains worksheet and range, so as a full-string comparison
    no two tables ever collide. What a caller can actually write, though, is
    weaker than the full hint:

    * candidate A's query is the address -- the range itself;
    * candidate B's query is the header values;
    * candidate C's query is the header values plus the content fingerprint.

    A query that matches several tables cannot identify one of them, and that
    is the ambiguity this experiment is about.
    """
    key = candidate.strip().upper()
    values = context.values
    if key == "A":
        return (context.sheet_name, context.bounds)
    if key == "B":
        columns = tuple(sorted((values.get("header_columns") or {}).items()))
        rows = tuple(values.get("header_column_values") or ())
        return (columns, rows)
    if key == "C":
        columns = tuple(sorted((values.get("header_columns") or {}).items()))
        rows = tuple(values.get("header_column_values") or ())
        return (columns, rows, values.get("content_fingerprint"))
    raise ValueError(f"unknown context candidate: {candidate!r}")


@dataclass
class TableContextQuery:
    """A caller's attempt to name one table.

    ``candidate`` says *how* the caller is naming it; ``scope`` says how much of
    the workbook the name is supposed to be unambiguous within. Both matter:
    naming two tables by their headers is useless workbook-wide but can be
    sufficient inside a single worksheet, and the same query text means
    different things at the two scopes.

    * ``candidate="A"``: the caller supplies worksheet + range, i.e. ``range``.
    * ``candidate="B"``: the caller supplies ``headers`` / ``row_labels``.
    * ``candidate="C"``: the caller supplies those plus ``fingerprint``.
    """

    candidate: str
    scope: str = "artifact"  # "artifact" | "sheet"
    sheet_name: str | None = None
    bounds: str | None = None
    headers: Mapping[str, Any] | None = None
    row_labels: Sequence[Any] | None = None
    fingerprint: str | None = None

    PROVISIONAL = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "scope": self.scope,
            "sheet_name": self.sheet_name,
            "bounds": self.bounds,
            "headers": list(self.headers or ()),
            "row_labels": list(self.row_labels or ()),
            "fingerprint": self.fingerprint,
        }


@dataclass
class TableCandidate:
    """One table that matched a requested context.

    Returned instead of picking one. This is the table-level counterpart of a
    cell-level candidate: it says *which table*, never *which cell*.
    ``context_hint`` is the hint that matched; ``score`` records how strongly it
    matched -- ``"exact"`` when one of the candidate hints is equal,
    ``"address_only"`` when only a weaker component matched.
    """

    unit_id: str
    region_id: str
    sheet_name: str
    bounds: str
    candidate: str
    context_hint: str
    score: str  # "exact" | "address_only"
    row_count: int = 0
    header_row_values: tuple[Any, ...] = ()

    PROVISIONAL = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id,
            "region_id": self.region_id,
            "sheet_name": self.sheet_name,
            "bounds": self.bounds,
            "candidate": self.candidate,
            "context_hint": self.context_hint,
            "score": self.score,
            "row_count": self.row_count,
            "header_row_values": list(self.header_row_values),
        }


@dataclass
class TableResolution:
    """The outcome of naming a table. Ambiguity is a first-class result.

    ``status`` is one of ``resolved`` / ``ambiguous`` / ``unresolved`` /
    ``malformed_query``. There is deliberately no ``selected`` field and no
    first-match behaviour: a resolution either names one table or reports every
    table that matched.
    """

    unique: bool
    query: TableContextQuery
    table: "TableContext | TableCandidate | None" = None
    candidates: tuple[Any, ...] = ()
    problem: str | None = None
    message: str = ""

    PROVISIONAL = True

    @property
    def status(self) -> str:
        if self.unique:
            return "resolved"
        return self.problem or "unresolved"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "unique": self.unique,
            "query": self.query.as_dict(),
            "table": (
                self.table.as_dict()
                if self.table is not None and hasattr(self.table, "as_dict")
                else None
            ),
            "candidates": [
                c.as_dict() if hasattr(c, "as_dict") else dict(c)
                for c in self.candidates
            ],
            "problem": self.problem,
            "message": self.message,
        }


class ContextProblem:
    AMBIGUOUS = "ambiguous"
    UNRESOLVED = "unresolved"
    MALFORMED_QUERY = "malformed_query"


def _query_matches(context: TableContext, query: TableContextQuery) -> bool:
    # The worksheet is never part of the *key* in this experiment: it defines the
    # pool (see ``resolve_table_query``), which keeps the measurement from
    # double-counting the address. ``sheet_name`` on the query is therefore a
    # scope carrier, not a matcher.
    values = context.values
    candidate = query.candidate.strip().upper()
    if candidate == "A":
        if query.bounds is None:
            return False
        return context.bounds == query.bounds
    if candidate in ("B", "C"):
        # Header *row values*, not the per-letter mapping: the mapping carries
        # column letters, which is address-derived and would smuggle position
        # into the context query it is supposed to be independent of.
        expected_headers = tuple(_normalise_sequence(query.headers))
        actual_headers = tuple(values.get("header_row_values") or ())
        if expected_headers and expected_headers != actual_headers:
            return False
        expected_rows = tuple(query.row_labels or ())
        actual_rows = tuple(values.get("header_column_values") or ())
        if expected_rows and expected_rows != actual_rows:
            return False
        if candidate == "C":
            if query.fingerprint is None:
                return False
            return values.get("content_fingerprint") == query.fingerprint
        return True
    raise ValueError(f"unknown context candidate: {query.candidate!r}")


def _normalise_sequence(value: Any) -> list[Any]:
    """Accept a mapping or a sequence and return a comparable sequence."""
    if value is None:
        return []
    if isinstance(value, Mapping):
        return list(value.values())
    return list(value)


def resolve_table_query(
    contexts: Mapping[str, TableContext] | Sequence[TableContext],
    query: TableContextQuery,
) -> TableResolution:
    """Name one table, or report why the name does not identify one.

    Never returns a first match. A query matching several tables returns every
    candidate and ``unique=False``.
    """
    pool = (
        list(contexts.values())
        if isinstance(contexts, Mapping)
        else list(contexts)
    )
    if query.scope == "sheet" and query.sheet_name:
        pool = [c for c in pool if c.sheet_name == query.sheet_name]

    candidate_key = query.candidate.strip().upper()
    if candidate_key not in CANDIDATE_KEYS:
        return TableResolution(
            unique=False,
            query=query,
            problem=ContextProblem.MALFORMED_QUERY,
            message=f"unknown context candidate {query.candidate!r}",
        )

    matched = [c for c in pool if _query_matches(c, query)]
    if not matched:
        return TableResolution(
            unique=False,
            query=query,
            problem=ContextProblem.UNRESOLVED,
            message=(
                f"no table matched context candidate {candidate_key} at "
                f"{query.scope} scope"
            ),
        )
    if len(matched) > 1:
        return TableResolution(
            unique=False,
            query=query,
            candidates=tuple(sorted(matched, key=lambda c: (c.sheet_name, c.bounds))),
            problem=ContextProblem.AMBIGUOUS,
            message=(
                f"{len(matched)} tables match this context at {query.scope} "
                f"scope; the table is not identified"
            ),
        )
    return TableResolution(unique=True, query=query, table=matched[0])


def query_for_context(
    context: TableContext, candidate: str, scope: str = "artifact"
) -> TableContextQuery:
    """The query a caller would issue to ask for this table, per candidate.

    The model, stated plainly so the numbers are readable:

    * the **scope** says where the query is evaluated -- across the whole
      workbook, or within one worksheet;
    * the **candidate** says what the query is built from.

    The worksheet is never part of the key. It only narrows the pool, which is
    what :func:`measurement_for_candidate` compares. Counting the sheet in both
    places would make every candidate look perfect and would hide the very
    collisions this experiment exists to measure.
    """
    key = candidate.strip().upper()
    values = context.values
    return TableContextQuery(
        candidate=key,
        scope=scope,
        # The sheet restricts the pool only at sheet scope. At artifact scope it
        # is deliberately absent, otherwise a caller building a multi-table pool
        # by name would filter it away.
        sheet_name=context.sheet_name if scope == "sheet" else None,
        bounds=context.bounds if key == "A" else None,
        headers=(
            list(values.get("header_row_values") or ()) if key in ("B", "C") else None
        ),
        row_labels=(
            list(values.get("header_column_values") or ())
            if key in ("B", "C")
            else None
        ),
        fingerprint=values.get("content_fingerprint") if key == "C" else None,
    )


def measurement_for_candidate(
    contexts: Mapping[str, TableContext],
    candidate: str,
    *,
    scopes: Sequence[str] = ("artifact", "sheet"),
) -> dict[str, Any]:
    """Measure one candidate by actually running its queries.

    This is the honest form of the experiment: it does not reason about what a
    candidate *should* do, it asks the resolver and counts the outcomes.
    """
    per_scope: dict[str, Any] = {}
    for scope in scopes:
        unique: list[str] = []
        ambiguous: list[dict[str, Any]] = []
        unresolved: list[str] = []
        for name in sorted(contexts):
            context = contexts[name]
            query = query_for_context(context, candidate, scope)
            outcome = resolve_table_query(contexts, query)
            if outcome.unique and outcome.table is not None:
                unique.append(name)
            elif outcome.problem == ContextProblem.AMBIGUOUS:
                ambiguous.append(
                    {
                        "table": name,
                        "matching_tables": [
                            f"{c.sheet_name}!{c.bounds}" for c in outcome.candidates
                        ],
                    }
                )
            else:
                unresolved.append(name)
        per_scope[scope] = {
            "scope": scope,
            "candidate": candidate,
            "unique_count": len(unique),
            "unique_tables": unique,
            "ambiguous_count": len(ambiguous),
            "ambiguous": ambiguous,
            "unresolved_tables": unresolved,
        }
    return {"candidate": candidate, "by_scope": per_scope}


def build_ambiguity_matrix(
    contexts: Mapping[str, TableContext],
    *,
    scopes: Sequence[str] = ("artifact", "sheet"),
) -> dict[str, Any]:
    """For each candidate, count how many tables its query identifies.

    ``artifact`` scope asks the workbook-wide question (can this query name one
    table anywhere?). ``sheet`` scope asks the narrower question (can it name
    one table within its own worksheet?). Reporting both matters: a candidate
    can be adequate inside a sheet and useless across a workbook.
    """
    return {
        "provisional": True,
        "scopes": list(scopes),
        "note": (
            "measured by running each candidate's query through "
            "resolve_table_query, not by reasoning about the candidate; a query "
            "matching more than one table cannot identify a table"
        ),
        "by_candidate": {
            candidate: measurement_for_candidate(contexts, candidate, scopes=scopes)
            for candidate in CANDIDATE_KEYS
        },
    }


def build_collision_matrix(
    contexts: Mapping[str, TableContext],
) -> dict[str, Any]:
    """Pairwise context relations for a set of named tables.

    Reports two different questions per pair:

    * ``relations``  -- are the two full contexts equal?
    * ``resolvable`` -- could a caller using that candidate tell the tables
      apart, given that every candidate hint contains the address?

    Because worksheet and range are part of every candidate, both are expected
    to be empty here. That emptiness is itself the finding: *the address is what
    makes tables distinguishable, and the address is not what a natural-language
    query supplies.* The useful measurement is
    :func:`build_ambiguity_matrix`.
    """
    names = sorted(contexts)
    pairs: list[dict[str, Any]] = []
    collapsed_contexts: dict[str, list[list[str]]] = {key: [] for key in CANDIDATE_KEYS}
    collapsed_resolution: dict[str, list[list[str]]] = {
        key: [] for key in CANDIDATE_KEYS
    }
    for i, left_name in enumerate(names):
        for right_name in names[i + 1 :]:
            relations = compare_contexts(contexts[left_name], contexts[right_name])
            resolvable = compare_resolvability(
                contexts[left_name], contexts[right_name]
            )
            pairs.append(
                {
                    "left": left_name,
                    "right": right_name,
                    "relations": relations,
                    "resolvable": resolvable,
                }
            )
            for key in CANDIDATE_KEYS:
                if relations[key] == CandidateRelation.COLLAPSES:
                    collapsed_contexts[key].append([left_name, right_name])
                if resolvable[key] == CandidateRelation.COLLAPSES:
                    collapsed_resolution[key].append([left_name, right_name])
    return {
        "provisional": True,
        "question": (
            "can these two specific tables be told apart? expected empty, "
            "because worksheet+range is part of every candidate"
        ),
        "table_count": len(names),
        "pair_count": len(pairs),
        "pairs": pairs,
        "collapsed_context_pairs": collapsed_contexts,
        "collapsed_resolution_pairs": collapsed_resolution,
        "candidates": list(CANDIDATE_KEYS),
    }


def make_capability() -> TableCapability:
    """Declare the context experiment's support honestly."""
    return TableCapability(
        name="table_context_candidates",
        support=TableSupport.PARTIAL,
        detail=(
            "three candidate table contexts (A: sheet+range, B: +header "
            "values, C: +header context + content fingerprint) are produced and "
            "compared; none is adopted"
        ),
        collapse_risks=(TableLossKind.COLLAPSE_RISK,),
    )
