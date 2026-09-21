# Dependencies

## Runtime

| Component | Classification | Required | Redistributed here |
| --- | --- | --- | --- |
| Python standard library | RUNTIME | yes | no (part of the interpreter) |
| `python-calamine` 0.8.2 | OPTIONAL comparison reference | no | **no** — not distributed |

**No SeaFlow component is required.** LuoHai has no dependency on any SeaFlow
package, does not import one, and does not need one present in any form.

Earlier revisions of this file recorded a dependency on a shared SeaFlow Core
package. That dependency is gone: LuoHai now carries its own contract in
`skills/luohai/contracts.py`, which is the interface its own capability needs and
nothing more.

The `python-calamine` comparison binding is inert when absent, is selected only
explicitly, and is never installed by this repository. No third-party source,
wheel, binary or license file is vendored.

## Test-only

| Component | Classification | Required | Redistributed here |
| --- | --- | --- | --- |
| `openpyxl` | TEST_DEVELOPMENT — one independent cross-check of the fixture | no | no |
| Python standard library (`unittest`) | TEST | yes | no |

`openpyxl` is an independent-reader cross-check of the committed fixture. When it
is absent that check skips; the suite stays standard-library-only by default.

No test in this repository requires an external checkout, an environment
variable pointing outside the repository, or a network connection.

## Composition

There is nothing to compose. A fresh clone is a complete, runnable Skill:

```bash
git clone https://github.com/HuDeyi-66/Luo_Hai_Tables_Skill
cd Luo_Hai_Tables_Skill
python tests/run_all.py --quiet
```

The standalone-isolation suite enforces this: it fails if any module under
`skills/` acquires an import of a private runtime, and it runs the entry point,
the example and both determinism harnesses from a fresh interpreter whose path
contains only this repository.

## Licensing

LuoHai-authored code is licensed under the MIT License with the notice
`Copyright (c) 2026 Peng Wang (Hu Deyi)`; see `LICENSE`.

No third-party component is bundled, so there is no third-party notice to
reproduce. This license does not extend to the private SeaFlow base runtime,
which is separately maintained; this repository makes no licensing statement
about it.
