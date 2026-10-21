# Pre-3.6 qualification and reproducibility

This repository publishes the current bounded implementation from SeaFlow's
internal V3.5 engineering work. Tests and synthetic fixtures exercise contracts,
identity/refusal behavior and retained uncertainty. They are internal technical
checks, not independent external review, real-corpus accuracy, production
acceptance, expert legal validation or a V3.6 benchmark.

From a supported CPython 3.13 environment at the repository root:

```sh
python -m pip install -r requirements-pre36.txt
python -B tools/run_pre36.py showcase
python -B tools/run_pre36.py essential
```

The showcase selects eight native cases per Skill (six workflow smoke cases for
private Core). Essential mode runs the retained modules' safety cases. These
repository-local counts are distinct from the internal combined selection of
150 unique cases / 156 invocations and the historical 1,064-case inventory.
Historical evidence archives, optional backend wheels and private real material
are not distributed by this synchronization. Small synthetic fixtures remain.

Standalone native runtime does not require private Core, local WenHai or sibling
Skill repositories. Installation is checkout-based for ShanHai/LuoHai; JueHai and
XianHai also declare their package metadata and package-owned JSON schema data.
