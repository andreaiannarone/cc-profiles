# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Updating cc-profiles."""

import json
import os
import re
import subprocess
import sys
import threading
import time
import urllib.request

from . import __version__
from . import core
from .core import APP_DIR, ApiError, find_tool, tool_env

# ---------------------------------------------------------------------------
# Updating cc-profiles
# ---------------------------------------------------------------------------
# Only when the user asks: the check is the one request cc-profiles makes on its own
# to the internet (PyPI sees the IP address). The commands are fixed here, like
# INSTALL_METHODS: the client picks an action, never a command.
PYPI_URL = os.environ.get("CC_PROFILES_PYPI_URL", "https://pypi.org/pypi/cc-profiles/json")  # tests: a file:// URL
UPDATE_COMMANDS = {"pipx": ["pipx", "upgrade", "cc-profiles"], "uv": ["uv", "tool", "upgrade", "cc-profiles"]}


def install_kind():
    """How this copy of cc-profiles was installed: pipx, uv, or source (editable or a checkout)."""
    if "site-packages" not in APP_DIR:
        return "source"
    prefix = sys.prefix.replace(os.sep, "/")
    if "/pipx/venvs/" in prefix:
        return "pipx"
    if "/uv/tools/" in prefix:
        return "uv"
    return "pip"


def version_key(v):
    """0.10.1 > 0.9: compare the numbers; anything after them (a pre-release) sorts lower."""
    nums = re.match(r"^(\d+(?:\.\d+)*)", v or "")
    return tuple(int(x) for x in nums.group(1).split(".")) if nums else ()


def check_update():
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=10) as r:
            latest = json.loads(r.read())["info"]["version"]
    except (OSError, ValueError, KeyError) as e:
        raise ApiError(f"Could not reach PyPI: {e}. Check your connection and try again.", 502)
    kind = install_kind()
    cmd = UPDATE_COMMANDS.get(kind)
    return {"current": __version__, "latest": latest, "newer": version_key(latest) > version_key(__version__),
            "kind": kind, "command": " ".join(cmd) if cmd else None,
            "can_update": bool(cmd and find_tool(cmd[0])),
            "manual": {"source": "git pull", "pip": "python3 -m pip install --upgrade cc-profiles"}.get(kind)}


def restart_soon():
    """Replace this process with a fresh one on the same port, after the response is sent:
    the new process loads the code that was just installed."""
    def go():
        time.sleep(0.7)
        args = [sys.executable, "-m", "cc_profiles", "--port", str(core.PORT), "--no-browser"]
        os.execv(sys.executable, args)  # listening socket: not inherited (PEP 446), so the port is free
    threading.Thread(target=go, daemon=True).start()


def op_update():
    info = check_update()
    if not info["newer"]:
        return {"message": f"cc-profiles {__version__} is already the latest version.", "restarting": False}
    if not info["can_update"]:
        raise ApiError(f"This copy cannot update itself ({info['kind']}): run {info['manual'] or 'the installer'}, then restart cc-profiles")
    cmd = UPDATE_COMMANDS[info["kind"]]
    if os.environ.get("CC_PROFILES_UPDATE_DRYRUN"):  # tests only: installs nothing, does not restart
        return {"message": f"Dry run: would run {' '.join(cmd)}.", "restarting": False}
    r = subprocess.run([find_tool(cmd[0])] + cmd[1:], capture_output=True, text=True, timeout=600, env=tool_env())
    if r.returncode != 0:
        out = (r.stderr or r.stdout).strip().splitlines()[-3:]
        raise ApiError(f"The update failed ({' '.join(cmd)} ended with code {r.returncode}): {' / '.join(out)}", 500)
    restart_soon()
    return {"message": f"Updated to cc-profiles {info['latest']}. Restarting…", "restarting": True}
