# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: the console script.

`which` and `shell-init` run on every `claude` launch once the shell function is
installed, so they skip loading the server (see byfolder.py). Everything else goes
to cli.main.
"""

import sys

FAST = ("which", "shell-init")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] and argv[0] in FAST:
        from .byfolder import main as fast
        sys.exit(fast(argv))
    from .cli import main as full
    return full(argv)
