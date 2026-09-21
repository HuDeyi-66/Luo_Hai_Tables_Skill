"""LuoHai Skill test runner.

    python tests/run_all.py --core-root <seaflow-root> [--quiet]

SeaFlow Core is required and must be supplied explicitly, either as
``--core-root`` or through the ``SEAFLOW_CORE_ROOT`` environment variable. Core
is not vendored into this repository. There is no sibling-directory fallback.

The optional locked ``python-calamine`` comparison binding is not distributed
with this repository::

    python tests/run_all.py --core-root <root>                  # optional tests skip
    python tests/run_all.py --core-root <root> --no-calamine    # same, stated explicitly
    python tests/run_all.py --core-root <root> --with-calamine  # use the wheel if present
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the LuoHai Skill test suite")
    parser.add_argument(
        "--core-root",
        default=None,
        help="directory containing core/ (a SeaFlow checkout root or a staged Core root)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--with-calamine",
        action="store_true",
        help="use the optional locked binding for the comparison tests when present",
    )
    group.add_argument(
        "--no-calamine",
        action="store_true",
        help="treat the optional binding as unavailable; proves the standard-library path",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="one line per module instead of per test",
    )
    args = parser.parse_args(argv)

    # The bootstrap validates Core at import time, so the explicit root has to
    # be in the environment before it is imported.
    if args.core_root:
        os.environ["SEAFLOW_CORE_ROOT"] = str(Path(args.core_root).resolve())

    import _bootstrap  # noqa: E402  (path bootstrap; validates Core)

    if args.no_calamine:
        os.environ[_bootstrap.DISABLE_OPTIONAL_BACKEND_ENV] = "1"
        print("[runner] optional locked binding treated as UNAVAILABLE")

    print(f"[runner] SeaFlow Core root: {_bootstrap.CORE_ROOT}")

    report = _bootstrap.ensure_calamine_on_path()
    if args.with_calamine and not report["available"]:
        print(f"[runner] optional locked binding not used: {report['reason']}")
    elif report["available"]:
        print(
            "[runner] optional locked binding ready: wheel sha256 OK, "
            f"extension sha256 OK ({report['extract_dir']})"
        )

    loader = unittest.TestLoader()
    suite = loader.discover(str(TESTS_DIR), pattern="test_*.py")
    result = unittest.TextTestRunner(verbosity=1 if args.quiet else 2).run(suite)

    summary = {
        "ran": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "skipped": len(result.skipped),
        "ok": result.wasSuccessful(),
    }
    print("RUN_ALL_SUMMARY " + json.dumps(summary, sort_keys=True))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
