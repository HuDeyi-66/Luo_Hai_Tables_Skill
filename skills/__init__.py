"""LuoHai package surface.

This repository publishes exactly one Skill package, ``skills.luohai``. LuoHai
has no dependency on ShanHai and must not acquire one, so this package
deliberately aggregates only LuoHai.

Unlike an earlier revision, this file no longer describes a shared runtime
aggregator: LuoHai is standalone, and a runtime that integrates it does so from
its own side. The isolation guarantee is that neither Skill *package* imports the
other, and it is asserted by test.
"""

from pkgutil import extend_path

# Passive package-path composition; no sibling import or Core dependency.
__path__ = extend_path(__path__, __name__)

from .luohai import *  # noqa: F401,F403
from .luohai import __all__  # noqa: F401
