# LuoHai — Tabular Evidence

LuoHai is an **independent open-source component** for extracting traceable
evidence from spreadsheets. It reads OOXML workbooks with the standard library,
detects table regions, records worksheet and table context, and emits cell and
range evidence. It reconstructs citations that can be re-checked, and reports
declared capability and loss instead of guessing.

Nothing is inferred silently: a cell that is present but blank, a cell that is
not in the sheet at all, a formula with no cached value and a value that could
not be read are four different facts, and they are reported as four different
things.

**LuoHai needs nothing but itself.** It has no dependency on any SeaFlow
component, does not import one, and does not require one to be present in any
form. A SeaFlow runtime can integrate it as an official Skill, but that
integration is implemented inside SeaFlow — see [Using it with
SeaFlow](#using-it-with-seaflow).

---

## Install

Standard library only for the deterministic path. There is no package to install
and no service to start:

```bash
git clone https://github.com/HuDeyi-66/Luo_Hai_Tables_Skill
cd Luo_Hai_Tables_Skill
python --version        # qualified on Windows with CPython 3.13.14
```

That is the whole installation.

## Use it

One function is the whole required surface:

```python
from skills.luohai import run_tabular_evidence

result = run_tabular_evidence("throughput.xlsx", source_id="ports")

print(result.is_complete_success)          # False if anything was lost
for unit in result.units:
    print(unit.address.value, unit.loss)   # e.g. "A1:C3", ('empty', 'absent')
```

`run_tabular_evidence` accepts a path, raw bytes, or a `TableArtifact` you build
yourself. It returns a `TableRunResult` carrying the evidence units, the run
diagnostics, and an honest assessment of whether the read was complete.

Lower-level entry points are available if you want to drive the pieces:

```python
from skills.luohai import TabularEvidenceSkill, TableArtifact, FixtureXlsxBackend

artifact = TableArtifact.from_file("throughput.xlsx", "ports")
result = TabularEvidenceSkill(FixtureXlsxBackend()).run(artifact, source_id="ports")
```

### What comes back

* table-region detection, with worksheet and table context for every region;
* evidence units per region carrying per-cell raw *and* rendered values,
  including `empty`, `absent` and `merged` states kept distinct;
* cell citations, range citations (a rectangle keeps its holes: every coordinate
  is returned) and value citations;
* declared-table metadata observed and compared with inferred regions, with
  neither treated as authority;
* ambiguity and loss refused or reported, never resolved by first match.

### The contract

The types LuoHai returns are **its own**, declared in
`skills/luohai/contracts.py`: `TableArtifact`, `TableEvidenceUnit`,
`TableLossKind`, `TableUnitClass`, `TableCitationAddress`, `TableProducer`,
`TableRunResult`, `TableCapability`, `TableSupport`. They describe this Skill's
domain and nothing else. The loss and unit-class vocabularies are stable strings,
so you can compare against them without importing anything.

## Run the tests and the example

```bash
python tests/run_all.py --quiet
python examples/luohai_table_example.py
python fixtures/rebuild_and_diff.py --runs 3
python fixtures/rebuild_and_diff_table_context.py --runs 3
```

No runtime, service, sibling checkout or external path is required. A dedicated
isolation suite proves it: it checks that no module under `skills/` imports a
private runtime, that importing the package loads no such module, and that a
fresh interpreter with **only this repository on its path** can run the entry
point, the example and both determinism harnesses.

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

## Using it with SeaFlow

When a SeaFlow runtime is present, LuoHai operates as an **official SeaFlow
Skill**. The integration is implemented in SeaFlow, which adapts this Skill's
public interface into its own internal model.

The dependency therefore points one way only:

```
SeaFlow (private runtime)  ---adapts--->  LuoHai (this repository)
```

LuoHai never imports SeaFlow, and nothing here changes if you never use SeaFlow
at all.

## Related repositories

| Repository | Role |
| --- | --- |
| [SeaFlow](https://github.com/HuDeyi-66/SeaFlow) | Public informational entry point for the project. Documentation only. |
| [ShanHai](https://github.com/HuDeyi-66/Shan_Hai_Code_Skill) | The sibling Skill, for legal and textual evidence. |

ShanHai is a **sibling**, not a dependency. Neither Skill imports the other, in
either direction, and that isolation is asserted by test. The links above are for
discovery only.

## Scope and limitations

* **OOXML workbooks only.** `.xlsx` and `.xlsm` are read; a legacy `.xls` is
  declared unsupported rather than attempted; no CSV, PDF or OCR.
* **No evaluation.** A formula's text is read; its cached value is not an
  evaluation, and LuoHai does not compute one.
* **No authority.** Declared table metadata is compared, never trusted.
* **No cross-Skill ranking.** Nothing here ranks a table against anything else.
* **Qualified on Windows with CPython 3.13.14.** The deterministic path is
  standard-library only, so nothing pins it to that environment, but other
  versions and platforms have not been qualified.

## License

MIT. See `LICENSE`.

```
Copyright (c) 2026 Peng Wang (Hu Deyi)
```

This license covers this repository. It does not extend to the private SeaFlow
base runtime, which is separately maintained and about which this repository
makes no licensing statement. See `DEPENDENCIES.md`.
