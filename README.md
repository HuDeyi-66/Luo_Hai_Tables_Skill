# LuoHai — Tabular Evidence Skill

LuoHai is the official SeaFlow Skill for **tabular evidence**. It reads OOXML
workbooks with the standard library, detects table regions, records worksheet and
table context, emits cell and range evidence, reconstructs citations that can be
re-checked, and reports declared capability and loss instead of guessing.

This repository is one of the three public SeaFlow repositories. It is a
**sibling** Skill: it depends on SeaFlow Core and on nothing else in the SeaFlow
family.

| Repository | Role |
| --- | --- |
| [SeaFlow](https://github.com/HuDeyi-66/SeaFlow) | Core runtime and application integration |
| [ShanHai](https://github.com/HuDeyi-66/Shan_Hai_Code_Skill) | Legal-text evidence Skill |
| **LuoHai** (this repository) | Tabular evidence Skill |

---

## What LuoHai owns

* `skills/luohai/xlsx_extraction.py` — the Skill (`LuoHai.TabularEvidence`) and evidence-unit construction.
* `skills/luohai/ooxml.py` — the deterministic standard-library OOXML package reader.
* `skills/luohai/table.py` — table-region detection.
* `skills/luohai/table_context.py` — context candidates and ambiguity measurement.
* `skills/luohai/table_observe.py` — declared-table metadata observation.
* `skills/luohai/citation.py` — cell, range and value citation reconstruction.
* `skills/luohai/backends.py` — reader contracts, loss declarations and the optional comparison backend.
* `fixtures/` — deterministic workbook fixtures, truth data, their builders and the rebuild-and-diff harnesses.
* `tests/luohai/`, `tests/test_fixture_harness.py`, `tests/test_skill_interface.py` — the LuoHai suites.
* `examples/luohai_table_example.py`, `docs/TABULAR_EVIDENCE.md`, `tools/table_context_experiment.py`.

## What LuoHai does not own

* **Core is not vendored here.** `core/` has exactly one authoritative
  implementation, in the SeaFlow repository. This repository depends on it and
  never copies it.
* **No ShanHai code, fixtures or imports.** ShanHai and LuoHai are siblings and
  are mutually isolated; neither may import the other.
* **No application orchestration.** Query planning, branch routing, evidence
  composition, refusal policy and the Citation Packet belong to SeaFlow's `app/`
  layer. LuoHai does not import it.
* No legal-text ingestion, no authority finding, no cross-Skill ranking, no
  private corpus.

## Install and run

LuoHai is standard-library only for its deterministic path; there is no package
to install. Core is supplied explicitly at test time — never by a hidden
sibling-directory guess.

```bash
git clone https://github.com/HuDeyi-66/SeaFlow        # the Core + runtime repository
git clone https://github.com/HuDeyi-66/Luo_Hai_Tables_Skill         # this repository
cd Luo_Hai_Tables_Skill
```

Point the suite at the SeaFlow checkout root (the directory that contains
`core/`), then run it:

```bash
python tests/run_all.py --core-root ../<seaflow-checkout> --quiet
# or
SEAFLOW_CORE_ROOT=../<seaflow-checkout> python tests/run_all.py --quiet
```

Run the example and the two determinism harnesses:

```bash
SEAFLOW_CORE_ROOT=../<seaflow-checkout> python examples/luohai_table_example.py
python fixtures/rebuild_and_diff.py --runs 3
python fixtures/rebuild_and_diff_table_context.py --runs 3
```

The public import name is stable:

```python
from skills.luohai import TabularEvidenceSkill, FixtureXlsxBackend
```

## Optional comparison backend

The locked `python-calamine` wheel is **not distributed with this repository**
and is not a runtime dependency. If a caller places the recorded wheel at
`.spike/python_calamine-0.8.2-cp313-cp313-win_amd64.whl`, its SHA-256 and its
extension's SHA-256 are re-checked before use. Without it the comparison tests
skip, which is what a clean checkout reports. `--no-calamine` states the
standard-library-only path explicitly.

## Verify

| Level | Command |
| --- | --- |
| LuoHai alone (Core supplied explicitly) | `python tests/run_all.py --core-root <root> --quiet` |
| Fixture + extraction determinism | `python fixtures/rebuild_and_diff.py --runs 3` |
| | `python fixtures/rebuild_and_diff_table_context.py --runs 3` |
| Composite (SeaFlow + ShanHai + LuoHai) | the composite gate in the SeaFlow repository |

## Compatibility

See `SKILL_REFERENCES.json` in the SeaFlow repository — the machine-readable
publication reference that pins this Skill to a SeaFlow baseline commit and
records the compatible SeaFlow revision. It is an informational baseline
document: there is no registry, no dynamic discovery, no marketplace, no
installation metadata and no runtime network fetch anywhere in SeaFlow.

## License

LuoHai-authored code is **licensed under the MIT License**; see `LICENSE`.

```
Copyright (c) 2026 Peng Wang (Hu Deyi)
```

Third-party components keep their own licenses and are not relicensed by this
project. See `DEPENDENCIES.md`.
