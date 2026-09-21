"""Standalone isolation: LuoHai must work with no runtime present.

The other suites prove the Skill is correct. This one proves it is *independent*
-- that nothing in it reaches for a private SeaFlow runtime, a sibling checkout,
or a path supplied from outside this repository.

Three checks, from weakest to strongest:

1. no module in ``skills/`` imports ``core`` or ``app`` (checked by parsing, so
   it cannot pass merely because an import happened to resolve);
2. importing the package does not pull a ``core`` module into ``sys.modules``;
3. a fresh interpreter whose path contains **only** this repository can import
   the package, run the entry point and produce evidence.

Check 3 is the one that matters: it is the same thing a user does after
``git clone``.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import _bootstrap  # noqa: E402

PROJECT_ROOT = _bootstrap.PROJECT_ROOT


def _no_private_runtime_dependency(root: Path) -> bool:
    """True when no module under ``skills/`` imports ``core`` or ``app``.

    Defined here rather than in the shared bootstrap so the check still works
    when this suite runs inside a composite checkout whose ``tests/_bootstrap.py``
    belongs to another repository. The source is parsed rather than imported, so
    it cannot pass merely because an import happened to resolve.
    """
    import ast

    for path in sorted((root / "skills").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name.split(".")[0] in ("core", "app") for a in node.names):
                    return False
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    continue
                if (node.module or "").split(".")[0] in ("core", "app"):
                    return False
    return True


class NoPrivateRuntimeDependencyTests(unittest.TestCase):
    def test_no_module_in_this_repository_imports_a_private_runtime(self) -> None:
        self.assertTrue(
            _no_private_runtime_dependency(PROJECT_ROOT),
            "a module under skills/ imports core or app; LuoHai must be self-contained",
        )

    def test_importing_the_skill_does_not_load_a_core_module(self) -> None:
        probe = (
            "import json, sys\n"
            f"sys.path.insert(0, {json.dumps(str(PROJECT_ROOT))})\n"
            "import skills.luohai\n"
            "loaded = sorted(m for m in sys.modules "
            "if m == 'core' or m.startswith('core.') "
            "or m == 'app' or m.startswith('app.'))\n"
            "print(json.dumps(loaded))\n"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"importing skills.luohai failed:\n"
            f"{completed.stderr.decode('utf-8', 'replace')}",
        )
        loaded = json.loads(completed.stdout.decode("utf-8").strip().splitlines()[-1])
        self.assertEqual(loaded, [], f"importing the Skill loaded {loaded}")


class StandaloneEntryPointTests(unittest.TestCase):
    def test_a_clean_interpreter_can_run_the_entry_point(self) -> None:
        """The post-``git clone`` experience, in one subprocess."""
        fixture = _bootstrap.FIXTURE_PATH
        probe = (
            "import json, sys\n"
            f"sys.path.insert(0, {json.dumps(str(PROJECT_ROOT))})\n"
            "from skills.luohai import run_tabular_evidence\n"
            f"result = run_tabular_evidence({json.dumps(str(fixture))}, source_id='probe')\n"
            "print(json.dumps({\n"
            "    'units': len(result.units),\n"
            "    'complete': result.is_complete_success,\n"
            "    'fatal': result.diagnostics.has_fatal_error,\n"
            "    'kinds': sorted({u.unit_class for u in result.units}),\n"
            "}))\n"
        )
        # PYTHONPATH is cleared so the child cannot see anything the developer
        # happened to have on the path: only the repository root is available.
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"standalone run failed:\n{completed.stderr.decode('utf-8', 'replace')}",
        )
        payload = json.loads(completed.stdout.decode("utf-8").strip().splitlines()[-1])
        self.assertGreater(payload["units"], 0)
        self.assertFalse(payload["fatal"])
        self.assertIn("content", payload["kinds"])

    def test_the_example_runs_with_only_this_repository_on_the_path(self) -> None:
        completed = subprocess.run(
            [sys.executable, str(PROJECT_ROOT / "examples" / "luohai_table_example.py")],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(PROJECT_ROOT),
            env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
        )
        self.assertEqual(
            completed.returncode,
            0,
            f"example failed:\n{completed.stderr.decode('utf-8', 'replace')}",
        )

    def test_the_determinism_harnesses_run_with_only_this_repository_on_the_path(
        self,
    ) -> None:
        """The fixture rebuilds must not reach for a runtime either."""
        for script in ("rebuild_and_diff.py", "rebuild_and_diff_table_context.py"):
            with self.subTest(script=script):
                completed = subprocess.run(
                    [sys.executable, str(PROJECT_ROOT / "fixtures" / script), "--runs", "1"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(PROJECT_ROOT),
                    env={k: v for k, v in os.environ.items() if k != "PYTHONPATH"},
                )
                self.assertEqual(
                    completed.returncode,
                    0,
                    f"{script} failed:\n{completed.stderr.decode('utf-8', 'replace')}",
                )


if __name__ == "__main__":
    unittest.main()
