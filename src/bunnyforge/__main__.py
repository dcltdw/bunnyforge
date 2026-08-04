"""python3 -m bunnyforge — the module door to the dispatcher.

Same standard exit block as every tool module, so every door into the
package behaves identically at the process boundary.
"""

import sys

from bunnyforge import cli

if __name__ == "__main__":
    try:
        raise SystemExit(cli.main())
    except BrokenPipeError:
        sys.stderr.close()
        raise SystemExit(0)
