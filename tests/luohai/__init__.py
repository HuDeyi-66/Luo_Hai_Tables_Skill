"""LuoHai Skill tests.

Grouped in a subpackage so the layout mirrors ``skills/luohai/``: these tests
exercise ``LuoHai.TabularEvidence`` and its private support modules, while the
tests directly under ``tests/`` cover the generic Core and Skill boundary.

Discovery note: ``unittest discover`` only recurses into directories that are
importable packages, which is why this ``__init__.py`` exists. Without it the
LuoHai tests are silently skipped, and a silently skipped test is worse than a
failing one.
"""
