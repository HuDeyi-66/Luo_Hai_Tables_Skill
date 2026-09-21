"""LuoHai test bootstrap.

Two jobs:

1. make this repository's root importable as ``skills`` / ``fixtures``;
2. locate **SeaFlow Core**, which is not vendored here.

Core composition is explicit by design. This repository has exactly one
supported way to obtain Core at test time: a directory containing ``core/``,
supplied either as ``--core-root <dir>`` (handled by ``tests/run_all.py``) or as
the ``SEAFLOW_CORE_ROOT`` environment variable. There is no sibling-directory
guessing and no machine-specific path anywhere in the suite: a hidden fallback
would make the result depend on checkout layout, which is precisely what
cross-repository verification must not do.

Optional locked backend
-----------------------
The ``python-calamine`` wheel is **not distributed with this repository** and is
not a runtime dependency. If a caller places the recorded wheel at the pinned
path below, ``ensure_calamine_on_path()`` re-checks its SHA-256 and its
extension's SHA-256 before putting it on ``sys.path``; nothing is installed and
nothing outside this repository is written. Without that wheel the optional
comparison tests skip, which is what a clean checkout reports.
"""

from __future__ import annotations

import hashlib
import os
import sys
import zipfile
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent

CORE_ROOT_ENV = "SEAFLOW_CORE_ROOT"
_core_root = os.environ.get(CORE_ROOT_ENV)
if not _core_root:
    raise RuntimeError(
        "SeaFlow Core was not supplied. Pass --core-root <dir> to "
        "tests/run_all.py, or set "
        f"{CORE_ROOT_ENV} to a directory containing core/. Core is not "
        "vendored into this repository: it has one authoritative "
        "implementation, in the SeaFlow repository."
    )
CORE_ROOT = Path(_core_root).resolve()
if not (CORE_ROOT / "core" / "__init__.py").is_file():
    raise RuntimeError(
        f"{CORE_ROOT_ENV}={CORE_ROOT} does not contain core/__init__.py, so it "
        "is not a SeaFlow checkout root or a staged Core root."
    )

#: LuoHai-owned fixture locations. These are the paths the LuoHai suites and the
#: fixture harness assert against, so they are part of the Skill's public test
#: contract.
FIXTURE_DIR = PROJECT_ROOT / "fixtures" / "generated"
TRUTH_DIR = PROJECT_ROOT / "fixtures" / "truth"
FIXTURE_PATH = FIXTURE_DIR / "luohai_tabular_controlled.xlsx"
MANIFEST_PATH = FIXTURE_DIR / "fixture_manifest.json"
TRUTH_PATH = TRUTH_DIR / "citation_truth.json"

SPIKE_DIR = PROJECT_ROOT / ".spike"
WHEEL_PATH = SPIKE_DIR / "python_calamine-0.8.2-cp313-cp313-win_amd64.whl"
EXTRACT_DIR = SPIKE_DIR / "site-packages"

#: Values recorded in the original build provenance. Re-verified, never updated
#: from a different build.
WHEEL_SHA256 = "4ee356e1da29f994b9f29b74058ed0a35f6a818f88b8bb1b890576f90866e4f4"
EXTENSION_MEMBER = "python_calamine/_python_calamine.cp313-win_amd64.pyd"
EXTENSION_SHA256 = "93e83059e6f512c4006dbc21d43ab54dea4d6efb161826fa9360294e80e5d777"
LOCKED_BINDING_SHA = "0a7998e50a7586f308a2d455170ec63c8135dfd3"
LOCKED_CALAMINE_SHA = "0af05f4f6030351e3b8a999ea0810c8618368776"

#: Environment switch that treats the optional backend as unavailable, proving
#: the deterministic standard-library path.
DISABLE_OPTIONAL_BACKEND_ENV = "SEAFLOW_DISABLE_OPTIONAL_CALAMINE"

#: This repository's root must win over the Core root for ``skills`` and
#: ``fixtures``; Core is appended underneath so ``core`` resolves.
if str(CORE_ROOT) not in sys.path:
    sys.path.append(str(CORE_ROOT))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


#: Scratch directory for tests that must write bytes to disk. Created once and
#: reused; a freshly created directory per test is avoided on purpose because
#: some sandboxed Windows setups make a new directory unwritable by the same
#: process, turning cleanup into a spurious failure.
ARTIFACTS_DIR = PROJECT_ROOT / "artifacts"


def artifacts_dir() -> Path:
    """Return the scratch directory, creating it if needed."""
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    return ARTIFACTS_DIR


def calamine_disabled() -> bool:
    """True when the run asked for the standard-library-only proof."""
    return os.environ.get(DISABLE_OPTIONAL_BACKEND_ENV) == "1"


def wheel_is_verified() -> bool:
    """True when the optional wheel is present and matches the recorded digest."""
    if not WHEEL_PATH.is_file():
        return False
    return hashlib.sha256(WHEEL_PATH.read_bytes()).hexdigest() == WHEEL_SHA256


def extension_is_verified(extract_dir: Path | None = None) -> bool:
    target = (extract_dir or EXTRACT_DIR) / EXTENSION_MEMBER
    if not target.is_file():
        return False
    return hashlib.sha256(target.read_bytes()).hexdigest() == EXTENSION_SHA256


def ensure_calamine_on_path() -> dict[str, Any]:
    """Extract the optional locked binding and put it on ``sys.path``.

    Returns a dict describing what happened. Never installs anything. When the
    wheel is absent -- the normal case for a clean checkout -- the returned
    report says so and the optional tests skip.
    """
    report: dict[str, Any] = {
        "available": False,
        "reason": None,
        "wheel": str(WHEEL_PATH),
        "wheel_sha256_ok": False,
        "extension_sha256_ok": False,
        "extract_dir": str(EXTRACT_DIR),
        "locked_binding_sha": LOCKED_BINDING_SHA,
        "locked_calamine_sha": LOCKED_CALAMINE_SHA,
    }

    if calamine_disabled():
        report["reason"] = f"disabled by {DISABLE_OPTIONAL_BACKEND_ENV}=1"
        return report

    if not WHEEL_PATH.is_file():
        report["reason"] = (
            "optional locked wheel is not present; the standard-library path is "
            "used instead"
        )
        return report

    actual_wheel = hashlib.sha256(WHEEL_PATH.read_bytes()).hexdigest()
    if actual_wheel != WHEEL_SHA256:
        report["reason"] = (
            f"locked wheel SHA mismatch: {actual_wheel} != {WHEEL_SHA256}; "
            f"refusing to load it"
        )
        return report
    report["wheel_sha256_ok"] = True

    if not extension_is_verified():
        # Extract. Idempotent: the same wheel always produces the same files.
        EXTRACT_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(WHEEL_PATH, "r") as archive:
            for member in archive.namelist():
                # Skip build tooling; keep the dist-info so importlib.metadata
                # can resolve the version without a pip install.
                if member.startswith("python_calamine-") and "/" not in member:
                    continue
                archive.extract(member, EXTRACT_DIR)
        # A minimal, deterministic metadata record so version lookup works.
        # The directory name must be exactly the wheel's dist-info name
        # ("python_calamine-0.8.2.dist-info"); importlib.metadata resolves
        # `python-calamine` by normalising that name, not by string equality.
        dist_info = EXTRACT_DIR / "python_calamine-0.8.2.dist-info"
        dist_info.mkdir(parents=True, exist_ok=True)
        (dist_info / "METADATA").write_text(
            "Metadata-Version: 2.1\nName: python-calamine\nVersion: 0.8.2\n",
            encoding="utf-8",
        )
    if not extension_is_verified():
        report["reason"] = "extracted extension does not match the recorded SHA-256"
        return report
    report["extension_sha256_ok"] = True

    extracted = str(EXTRACT_DIR)
    if extracted not in sys.path:
        sys.path.insert(0, extracted)
    report["available"] = True
    return report
