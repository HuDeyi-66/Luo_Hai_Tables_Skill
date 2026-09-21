"""LuoHai Skill surface.

This repository publishes exactly one Skill package, ``skills.luohai``. The
LuoHai repository has no dependency on ShanHai and must not acquire one, so this
package deliberately aggregates only LuoHai.

In the composite three-repository checkout, SeaFlow provides a ``skills``
package that aggregates both Skills. That aggregator is an integration
convenience; the isolation guarantee is that neither Skill *package* imports the
other, and it is asserted by test.
"""

from .luohai import *  # noqa: F401,F403
from .luohai import __all__  # noqa: F401
