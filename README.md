<p align="center">
  <img src="docs/assets/luohai-header.png" alt="LuoHai（海珞）" />
</p>

[English](README.md) | [简体中文](README.zh-CN.md)

# LuoHai（海珞）

**Tabular Evidence Skill**

LuoHai is an independently usable open-source Skill for structured tabular
evidence extraction and citation. It reads OOXML workbooks with the standard
library, detects table regions, and records worksheet and table context. It emits
cell and range evidence, keeps raw and rendered values distinct, and reconstructs
citations that can be re-checked. Ambiguity and loss are reported, never resolved
by first match.

Nothing is inferred silently: a cell that is present but blank, a cell that is
not in the sheet at all, a formula with no cached value and a value that could
not be read are four different facts, and they are reported as four different
things.

* **LuoHai does not require the private SeaFlow base for standalone use.** It can
  be cloned, tested and used on its own.
* **SeaFlow integration is optional.** When used with SeaFlow, LuoHai acts as an
  official SeaFlow Skill/plugin — but that integration is implemented on
  SeaFlow's side.

---

<p align="center">
  <img src="docs/assets/luohai-comic.png" alt="LuoHai（海珞）Skill comic" />
</p>

## Capabilities

These are the capabilities the Skill declares at runtime. Anything not listed is
not implemented.

| Capability | Support | What it does |
| --- | --- | --- |
| Tabular evidence units | supported | one evidence unit per detected table region, each with its worksheet and table context |
| Citation reconstruction | supported | the unit payload carries per-cell addresses, row labels and column headers sufficient to rebuild a native citation |
| Range location | supported | a rectangular range resolves to a citation covering every coordinate — a rectangle keeps its holes |
| Declared-table observation | partial | OOXML table parts (`xl/tables`) are read and compared with the inferred regions; declared metadata is never treated as authority |
| Merged-cell state | partial | merged ranges are read; a covered address is reported as merged-from rather than as a value |
| Rich-text runs | partial | inline and shared-string text is flattened; run-level formatting is lost |
| Confidence scoring | unsupported | uncertainty and loss states are recorded, but evidence is not scored or ranked |
| CSV input | unsupported | this slice is XLSX only, by architecture decision |
| Formula evaluation | unsupported | read-only; formula text is read from `<f>` and kept separate from the cached value, which is never evaluated |
| Number-format display | unsupported | no style or number-format rendering; rendered equals raw for numbers |
| Cell comments | unsupported | comments and threaded comments are not read |
| Embedded objects | unsupported | charts, images, OLE objects and pivot tables are not read |
| Large-file streaming | unknown | there is no streaming path; the whole package is read into memory |

LuoHai reads the format it implements and refuses the rest rather than guessing.

## Installation

Standard library only for the deterministic path. There is no package to install
and no service to start:

```bash
git clone https://github.com/HuDeyi-66/Luo_Hai_Tables_Skill
cd Luo_Hai_Tables_Skill
python --version        # qualified on Windows with CPython 3.13.14
```

That is the whole installation.

## Minimal standalone example

One function is the whole required surface:

```python
from skills.luohai import run_tabular_evidence

result = run_tabular_evidence("throughput.xlsx", source_id="ports")

print(result.is_complete_success)          # False if anything was lost
for unit in result.units:
    print(unit.address.value, unit.loss)   # e.g. "A1:C3", ('empty', 'absent')
```

`run_tabular_evidence` accepts a filesystem path, raw bytes, or a `TableArtifact`
you build yourself. It returns a run result carrying the evidence units, the run
diagnostics, and an honest assessment of whether the read was complete. A
workbook the Skill cannot read still returns a result — with the loss or the
refusal recorded — rather than raising.

Lower-level entry points are available if you want to drive the pieces:

```python
from skills.luohai import TabularEvidenceSkill, TableArtifact, FixtureXlsxBackend

artifact = TableArtifact.from_file("throughput.xlsx", "ports")
result = TabularEvidenceSkill(FixtureXlsxBackend()).run(artifact, source_id="ports")
```

There is also a runnable example in the repository:

```bash
python examples/luohai_table_example.py
```

## Testing

```bash
python tests/run_all.py --quiet
python fixtures/rebuild_and_diff.py --runs 3
python fixtures/rebuild_and_diff_table_context.py --runs 3
```

No runtime, service, sibling checkout or external path is required. A dedicated
isolation suite proves it: it fails if any module under `skills/` acquires an
import of a private runtime, it checks that importing the package loads no such
module, and it runs the entry point, the example and both determinism harnesses
from a fresh interpreter whose path contains **only this repository**.

### The optional comparison backend

The locked `python-calamine` wheel is **not distributed with this repository**
and is not a runtime dependency. If you place the recorded wheel at
`.spike/python_calamine-0.8.2-cp313-cp313-win_amd64.whl`, its SHA-256 and its
extension's SHA-256 are re-checked before use. Without it the comparison tests
skip, which is what a clean checkout reports.

```bash
python tests/run_all.py                  # optional comparison tests skip
python tests/run_all.py --no-calamine    # same, stated explicitly
```

## Known limitations

* **OOXML workbooks only.** `.xlsx` and `.xlsm` are read; a legacy `.xls` is
  declared unsupported rather than attempted. No CSV, PDF or OCR.
* **No formula evaluation.** Formula text is read; the cached value is not an
  evaluation, and LuoHai does not compute one.
* **No number-format rendering.** A cell's rendered value equals its raw value
  for numbers.
* **No declared-table authority.** Declared table metadata is compared with what
  was observed; neither is treated as authoritative.
* **Unread package parts are reported, not ignored.** Comments, drawings, charts,
  media, pivot tables and VBA are surfaced as unread content.
* **No cross-Skill ranking.** Nothing here ranks a table against anything else.
* **Platform qualification.** Qualified on Windows with CPython 3.13.14. The
  deterministic path is standard-library only, so nothing pins it to that
  environment, but other versions and platforms have not been qualified.

## Relationship with SeaFlow

LuoHai is one of two independently published open-source Skills. SeaFlow can
integrate it as an official Skill/plugin; standalone use does not require access
to the private SeaFlow base runtime.

The dependency runs one way only:

```
SeaFlow (private runtime)  ---adapts--->  LuoHai (this repository)
```

LuoHai never imports SeaFlow. Nothing here changes if you never use SeaFlow.

* SeaFlow public informational entry point:
  <https://github.com/HuDeyi-66/SeaFlow>

The links in this section are **discovery links**, not runtime dependency
declarations.

## Relationship with ShanHai

ShanHai（海珊） — Legal Text Evidence Skill — is LuoHai's **sibling Skill**, not a
dependency. Neither Skill imports the other, in either direction, and that
isolation is asserted by test.

* ShanHai repository: <https://github.com/HuDeyi-66/Shan_Hai_Code_Skill>

## License

MIT. See `LICENSE`.

```
Copyright (c) 2026 Peng Wang (Hu Deyi)
```

This license covers this repository. It does not extend to the private SeaFlow
base runtime, which is separately maintained; this repository makes no licensing
statement about it. See `DEPENDENCIES.md`.
