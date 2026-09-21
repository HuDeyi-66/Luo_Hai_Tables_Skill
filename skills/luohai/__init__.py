"""LuoHai -- the official SeaFlow Skill for tabular evidence.

LuoHai is an **independent open-source component**. It reads OOXML workbooks with
the standard library, detects table regions, records worksheet and table context,
emits cell and range evidence, reconstructs citations that can be re-checked, and
reports declared capability and loss instead of guessing.

Standalone use needs nothing but this package::

    from skills.luohai import run_tabular_evidence

    result = run_tabular_evidence("throughput.xlsx", source_id="ports")

It does not import a private runtime, and it carries its own contract in
``skills/luohai/contracts.py``.

ShanHai, the sibling legal-text Skill, is likewise independent: nothing in this
package imports ``skills.shanhai``, and nothing in ``skills.shanhai`` imports
this package. That isolation is asserted by test rather than left to discipline.

When a SeaFlow runtime is present it may integrate this Skill as an official
plugin. That integration is implemented **on the runtime's side** -- LuoHai
exposes this API and the runtime adapts it -- so the dependency never points from
this public package into private code.

Package layout
--------------
::

    skills/luohai/
      api.py             run_tabular_evidence -- the standalone entry point
      contracts.py       this Skill's own evidence contract
      xlsx_extraction.py the Skill implementation
      ooxml.py           deterministic standard-library OOXML reader
      table.py           table-region detection
      table_context.py   context candidates and ambiguity measurement
      table_observe.py   declared-table metadata observation
      citation.py        cell, range and value citation reconstruction
      backends.py        reader contracts, loss declarations, optional comparison
"""

from .api import evidence_skill, run_tabular_evidence, workbook_artifact
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
from .contracts import (
    TableArtifact,
    TableCapability,
    TableCitationAddress,
    TableContractError,
    TableEvidenceSkill,
    TableEvidenceUnit,
    TableLossKind,
    TableProducer,
    TableRunDiagnostics,
    TableRunError,
    TableRunResult,
    TableRunWarning,
    TableSupport,
    TableUnitClass,
    detect_table_media_type,
    find_table_units,
    table_digest_bytes,
    table_digest_path,
    table_summarise_loss,
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
    # the standalone entry point
    "run_tabular_evidence",
    "workbook_artifact",
    "evidence_skill",
    # this Skill's own contract
    "TableEvidenceSkill",
    "TableRunResult",
    "TableEvidenceUnit",
    "TableArtifact",
    "TableCitationAddress",
    "TableProducer",
    "TableLossKind",
    "TableUnitClass",
    "TableCapability",
    "TableSupport",
    "TableRunDiagnostics",
    "TableRunWarning",
    "TableRunError",
    "TableContractError",
    "find_table_units",
    "table_summarise_loss",
    "table_digest_bytes",
    "table_digest_path",
    "detect_table_media_type",
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
