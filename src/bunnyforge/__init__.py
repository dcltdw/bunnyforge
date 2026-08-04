"""bunnyforge — tools for running a TTRPG campaign workspace.

The workspace is data (campaign.toml and content directories); this package
is the tool that reads it. There is no aggregate CLI: each tool is invoked
as its own module, e.g.

    python3 -m bunnyforge.review checkup
    python3 -m bunnyforge.generate_names --list
    python3 -m bunnyforge.run_tests -v
"""

from __future__ import annotations
