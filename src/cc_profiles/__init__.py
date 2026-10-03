# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: a local web UI to manage multiple Claude Code profiles."""
from .server import __version__, main

__all__ = ["__version__", "main"]
