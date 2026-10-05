# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: every public name of the app in one place.

The code lives in one module per area (core, projects, memories, ...); this module
re-exports them, so `from cc_profiles import server` and the console script keep working.
"""
from . import __version__  # noqa: F401
from .core import *  # noqa: F401,F403
from .paths import *  # noqa: F401,F403
from .projects import *  # noqa: F401,F403
from .memories import *  # noqa: F401,F403
from .sharing import *  # noqa: F401,F403
from .settings import *  # noqa: F401,F403
from .health import *  # noqa: F401,F403
from .backups import *  # noqa: F401,F403
from .info import *  # noqa: F401,F403
from .extensions import *  # noqa: F401,F403
from .conversations import *  # noqa: F401,F403
from .search import *  # noqa: F401,F403
from .command import *  # noqa: F401,F403
from .launchers import *  # noqa: F401,F403
from .newprofile import *  # noqa: F401,F403
from .transfer import *  # noqa: F401,F403
from .plugins import *  # noqa: F401,F403
from .editprofile import *  # noqa: F401,F403
from .installer import *  # noqa: F401,F403
from .updater import *  # noqa: F401,F403
from .web import *  # noqa: F401,F403
from .cli import *  # noqa: F401,F403
from .cli import main  # noqa: F401  (the console script entry point)
