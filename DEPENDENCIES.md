# Dependencies

## Runtime

| Component | Classification | Required | Redistributed here |
| --- | --- | --- | --- |
| Python standard library | RUNTIME | yes | no (part of the interpreter) |
| SeaFlow Core (`core/`) | RUNTIME, sibling repository | yes | **no** — obtained from the SeaFlow repository |
| `python-calamine` 0.8.2 | OPTIONAL comparison reference | no | **no** — not distributed |

LuoHai's deterministic path imports only the Python standard library and SeaFlow
Core. It has no required third-party runtime dependency, so there is no
third-party notice to reproduce here. Core is deliberately **not** vendored: it
has one authoritative implementation, in the SeaFlow repository.

The `python-calamine` comparison binding is inert when absent, is selected only
explicitly, and is never installed by this repository. No third-party source,
wheel, binary or license file is vendored.

## Test-only

| Component | Classification | Required | Redistributed here |
| --- | --- | --- | --- |
| `openpyxl` | TEST_DEVELOPMENT — one independent cross-check of the fixture | no | no |
| SeaFlow Core (`core/`) | TEST, supplied at run time | yes | **no** |

`openpyxl` is an independent-reader cross-check in `tests/test_fixture_harness.py`
and `tests/test_citation_reconstruction.py`-style checks. When it is absent those
checks skip; the suite stays standard-library-only by default.

## Explicit Core composition

LuoHai never guesses where Core is. The suite requires one of:

* `--core-root <dir>` on `tests/run_all.py`, or
* the `SEAFLOW_CORE_ROOT` environment variable pointing at a directory that
  contains `core/` (normally a SeaFlow checkout root).

The standalone `fixtures/rebuild_and_diff*.py` harnesses import `core` through
the ordinary import path, so run them with the SeaFlow checkout root on
`PYTHONPATH` after pointing `SEAFLOW_CORE_ROOT` at it:

```bash
SEAFLOW_CORE_ROOT=../<seaflow-checkout> PYTHONPATH=../<seaflow-checkout> \
  python fixtures/rebuild_and_diff.py --runs 3
```

There is no sibling-directory fallback and no machine-specific path in this
repository. If Core cannot be found, the suite fails immediately with an
explicit message rather than silently skipping.
