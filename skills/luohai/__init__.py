"""LuoHai Skill package -- ``LuoHai.TabularEvidence``.

The public entry point is
:class:`~skills.luohai.xlsx_extraction.TabularEvidenceSkill`.
Everything else in this package is that Skill's private support code.
"""

from .backends import (
    CalamineBackend,
    CalamineNotAvailable,
    FakeTabularBackend,
    FixtureXlsxBackend,
    ObservedCell,
    ObservedSheet,
    ObservedWorkbook,
    TabularBackend,
)
from .citation import (
    Ambiguous,
    Citation,
    CitationProblem,
    CitationSelector,
    ResolvedCell,
    Unresolved,
    resolve_citation,
)
from .xlsx_extraction import DEFAULT_OPTIONS, TabularEvidenceSkill
from .table_context import (
    CANDIDATE_KEYS,
    ContextProblem,
    TableCandidate,
    TableContext,
    TableContextQuery,
    TableResolution,
    build_ambiguity_matrix,
    build_collision_matrix,
    build_table_context,
    compare_contexts,
    compare_resolvability,
    context_hint,
    resolve_table_context,
    resolve_table_query,
    unit_context_hints,
    unit_table_context,
)
from .table_observe import (
    ComparisonReport,
    DeclaredTableComparison,
    ObservationStatus,
    compare_declared_and_inferred,
    compare_observation,
    make_capability as make_observation_capability,
    observe_declared_tables,
    regions_from_result,
)

__all__ = [
    # backends
    "CalamineBackend",
    "CalamineNotAvailable",
    "FakeTabularBackend",
    "FixtureXlsxBackend",
    "ObservedCell",
    "ObservedSheet",
    "ObservedWorkbook",
    "TabularBackend",
    # citation
    "Ambiguous",
    "Citation",
    "CitationProblem",
    "CitationSelector",
    "ResolvedCell",
    "Unresolved",
    "resolve_citation",
    # table context
    "CANDIDATE_KEYS",
    "ContextProblem",
    "TableCandidate",
    "TableContext",
    "TableContextQuery",
    "TableResolution",
    "build_ambiguity_matrix",
    "build_collision_matrix",
    "build_table_context",
    "compare_contexts",
    "compare_resolvability",
    "context_hint",
    "resolve_table_context",
    "resolve_table_query",
    "unit_context_hints",
    "unit_table_context",
    # declared-table observation
    "ComparisonReport",
    "DeclaredTableComparison",
    "ObservationStatus",
    "compare_declared_and_inferred",
    "compare_observation",
    "make_observation_capability",
    "observe_declared_tables",
    "regions_from_result",
    # the Skill
    "DEFAULT_OPTIONS",
    "TabularEvidenceSkill",
]
