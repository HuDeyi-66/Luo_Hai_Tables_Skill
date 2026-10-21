# LuoHai evidence operators 1.0.0 — frozen C contract

Opt-in module: `skills.luohai.operators_v1`. Existing modules and interfaces are
unchanged. Transport schemas: `schemas/operators/1.0.0/`.

## RECONSTRUCT_VERIFY

Typed mapping:

    TableArtifact × TableEvidenceUnit × CitationSelector × VerificationPolicy
        -> VerificationResult

The domain is the canonical LuoHai types. Policy.level is artifact, address,
observations (default), or interpretation; max_cells is 1..10000. Original input
is immutable artifact.payload_bytes when supplied, otherwise one snapshot read
from artifact.location. This same snapshot is verified with TableArtifact's
verify_bytes and passed to ooxml.read_package through BytesIO; no second file
read can race the digest check. SHA-256 and exact recorded byte length must
match. Unit artifact_id and digest provenance must match the artifact. Source
identity and producer metadata remain recorded declarations.

Verification levels are independent flags:

1. artifact_identity_verified: original snapshot digest and length checked.
2. citation_address_reconstructable: native resolve_citation returned Citation
   or RangeCitation from the supplied evidence. This level alone does not
   verify that the address or labels describe the original workbook.
3. stored_observations_verified: each selected stored cell field was compared
   with the original OOXML snapshot. verified_cell_fields lists exactly the
   checked projection: row, column, value, value_kind, formula, merged_from,
   hidden. Original observations also retain element presence, raw kind,
   formula text, stored/cache value and merge-anchor information separately.
4. interpretation: unsupported, including Excel display equivalence, format
   rendering, formula evaluation and whether a stored formula cache is current.
   Requesting it returns unsupported, retaining any lower levels checked.

Byte identity, native address reconstruction and original-cell comparison must
not be collapsed into one success boolean. verified_cell_fields is empty until
level 3 succeeds. A verified error cell is an observed error value, and a
verified missing formula cache is absence of a stored cache, never a computed
result. Native Ambiguous and Unresolved records are retained with their
candidates/problem states; ambiguous selectors never become verified targets.

Level 3 supports the canonical fixture.ooxml-stdlib projection for XLSX/XLSM.
ooxml.read_package owns decoding. Existing FixtureXlsxBackend._observe_sheet
owns the canonical cell projection; the wrapper does not evaluate values or
perform extraction. Native address/range helpers handle coordinate semantics.
An envelope guard rejects duplicate worksheet/cell addresses, unsupported cell
encodings, malformed boolean values, special/shared/array formula attributes,
invalid/overlapping merge declarations and unsupported namespaces. These are
guards on cases where the canonical reader may collapse distinctions, not a
second workbook parser. Other backends and unsupported encodings return typed
unsupported outcomes. Bad ZIP/XML returns corrupt. Unavailable originals,
binding failures and source/evidence mismatches are distinct typed outcomes.

Point/range selectors cannot be mixed or combined with additional value/header
constraints, since the native resolver does not conjunctively check those.
Duplicate stored cell addresses are ambiguous. Range verification covers every
selected coordinate in native row-major order, including absent, present-empty,
merged and error cells. A missing stored cell can only verify as truly absent;
it cannot conceal a present empty cell or merge coverage.

Claim limits: selected raw/canonical fields only. Inferred headers, table
boundaries, formatted display and the truth of a table interpretation are not
verified. Verifying one citation never proves complete workbook extraction.
Budget overflow and unsupported interpretation produce typed non-success,
not partial success disguised as verification.

## ACCOUNT_LOSS

Typed mapping:

    TableRunResult -> LossAccountingResult

This is a read-only accounting of recorded declarations, not new extraction.
The operator snapshots run.as_dict, reuses TableLossKind, table_summarise_loss,
run.unsurfaced_risks, run.is_complete_success and diagnostic/backend declarations.
It never invokes downgrade_for_declared_risk or edits diagnostics. Output
diagnostics are detached copies. A result carries the full input snapshot hash.

Counts mean unique-unit loss declarations, not independent physical source-loss
events. Repeated kinds within a unit and repeated identical unit records are
deduplicated. Recorded cell losses are included in the unit's accounting union;
missing unit aggregation is reported as inconsistent. Duplicate unit IDs with
conflicting contents, producer skill/backend/version/run disagreements, artifact
or digest-provenance mismatches, and conflicting source IDs are inconsistent.

Unknown losses, unavailable provenance, missing units/artifact/producer metadata,
run/unit errors, unsupported capability declarations and unsurfaced risks remain
explicit unresolved states. Canonical unsurfaced_risks is retained and augmented
with every known declaration absent from both observed diagnostics and unit/cell
signals; an unsupported-capability exemption cannot conceal an unsurfaced risk.
Lists are deterministically sorted and repeated declarations are not event counts.

declared_complete_success is exactly the original property. A complete-success
claim is justified only within the recorded contract when that property is true
and there are no additional inconsistencies or unresolved states. Unsupported
capabilities conservatively prevent justification. Regardless of this result,
workbook_observation_completeness is always unknown. No recorded losses does
not prove all workbook content was observed.

## Preconditions, invariants and determinism

Correctly typed canonical domain values are required. ACCOUNT_LOSS returns an
explicit unknown with unavailable input_digest for non-JSON backend values
(such as dates) instead of inventing a serialization; its accounting cannot be
completed for that input in v1. The operators do not register source identities, acquire sources,
orchestrate Skills, import siblings/private Core or modify original workbooks.
For fixed inputs and canonical implementation versions, result IDs are SHA-256
of sorted canonical UTF-8 JSON excluding result_id. JSON tuples become arrays.
The original run ordering is part of its recorded input snapshot; accounting
lists/counts are normalized. Unsupported floating-point non-finite values are
refused before making an original-observation claim.

Schema validation constrains serialization. It does not establish source truth.
The source comparisons and non-mutation properties have executable oracle and
negative tests; no mathematical proof or universal workbook completeness claim
is offered.

## Acceptance gates

C1: four levels, independent literal OOXML oracle, original digest/value/formula
mutation detection, missing/empty/merged/error distinctions, ambiguity,
unsupported/corrupt/unavailable outcomes and canonical extraction integration.
C2: declaration deduplication, unsurfaced risks, producer/provenance conflicts,
cell-loss aggregation, unknown completeness and zero input mutation.
Both: schema checks, original standalone suite, deliberate implementation
mutants and preservation of all baseline files. Optional Calamine execution
may skip when absent; level 3 explicitly refuses that unsupported projection.
C is evaluated independently of B; missing required gates mean INCOMPLETE.
