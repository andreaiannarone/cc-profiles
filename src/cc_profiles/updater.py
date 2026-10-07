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
from .core import (APP_DIR, CONFIG_FILE, DATA_DIR, STATIC_DIR, ApiError, Backup, find_tool, load_config, read_json,
                   tool_env, write_json)

# ---------------------------------------------------------------------------
# Updating cc-profiles
# ---------------------------------------------------------------------------
# The check asks PyPI for the latest version (PyPI sees the IP address): when the user
# clicks, and automatically at most once a day unless "update_check" is false in
# config.json. Updating itself happens only on click. The commands are fixed here,
# like INSTALL_METHODS: the client picks an action, never a command.
PYPI_URL = os.environ.get("CC_PROFILES_PYPI_URL", "https://pypi.org/pypi/cc-profiles/json")  # tests: a file:// URL
UPDATE_COMMANDS = {"pipx": ["pipx", "upgrade", "cc-profiles"], "uv": ["uv", "tool", "upgrade", "cc-profiles"],
                   "brew": ["brew", "upgrade", "cc-profiles"]}
# PyPI's JSON API lists a release minutes before the index pip and uv download from
# does. An update in those minutes fails with one of these, or "succeeds" without
# changing anything: the user is told to try again shortly, not shown pip's output.
INDEX_LAG_SIGNS = ("no matching distribution found", "could not find a version that satisfies",
                   "already at latest version", "nothing to upgrade", "no solution found",
                   "already installed")  # brew, while the tap does not have the new version yet


def install_kind():
    """How this copy of cc-profiles was installed: pipx, uv, brew, pip, or source (editable or a checkout)."""
    if os.environ.get("CC_PROFILES_INSTALL_KIND"):  # tests only, with a fake pipx or uv on PATH
        return os.environ["CC_PROFILES_INSTALL_KIND"]
    if "site-packages" not in APP_DIR:
        return "source"
    prefix = sys.prefix.replace(os.sep, "/")
    if "/pipx/venvs/" in prefix:
        return "pipx"
    if "/uv/tools/" in prefix:
        return "uv"
    if "/Cellar/cc-profiles/" in prefix:  # Homebrew: <prefix>/Cellar/cc-profiles/<version>/libexec
        return "brew"
    return "pip"


def version_key(v):
    """0.10.1 > 0.9: compare the numbers; anything after them (a pre-release) sorts lower."""
    nums = re.match(r"^(\d+(?:\.\d+)*)", v or "")
    return tuple(int(x) for x in nums.group(1).split(".")) if nums else ()


# The answer of the last check, kept between starts so the app asks PyPI at most once a day. A cache
# like server.log, not the user's data: written without a backup.
UPDATE_STATE = os.path.join(DATA_DIR, "update-check.json")
CHECK_EVERY = 86400


def check_update():
    try:
        with urllib.request.urlopen(PYPI_URL, timeout=10) as r:
            latest = json.loads(r.read())["info"]["version"]
    except (OSError, ValueError, KeyError) as e:
        raise ApiError(f"Could not reach PyPI: {e}. Check your connection and try again.", 502)
    try:
        write_json(UPDATE_STATE, {"checked": time.time(), "latest": latest})
    except OSError:
        pass
    return update_info(latest)


def update_info(latest):
    """What the page needs to offer an update to `latest`: how this copy updates itself, or the command to run."""
    kind = install_kind()
    cmd = UPDATE_COMMANDS.get(kind)
    return {"current": __version__, "latest": latest, "newer": bool(latest) and version_key(latest) > version_key(__version__),
            "kind": kind, "command": " ".join(cmd) if cmd else None,
            "can_update": bool(cmd and find_tool(cmd[0])),
            "manual": {"source": "git pull", "pip": "python3 -m pip install --upgrade cc-profiles"}.get(kind)}


def installed_version():
    """The cc-profiles version installed in this environment now, which an update may have
    changed under the running server; None if it cannot be read."""
    code = "from importlib.metadata import version; print(version('cc-profiles'))"
    try:
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return (r.stdout.strip() or None) if r.returncode == 0 else None


def index_lag(returncode, output, latest):
    """Whether an update failed, or did nothing, because PyPI's download index does not
    have the new version yet."""
    if any(sign in output.lower() for sign in INDEX_LAG_SIGNS):
        return True
    if returncode == 0:
        now = installed_version()
        return now is not None and version_key(now) < version_key(latest)
    return False


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
    output = "\n".join(x.strip() for x in (r.stdout, r.stderr) if x and x.strip())
    if index_lag(r.returncode, output, info["latest"]):
        return {"message": f"cc-profiles {info['latest']} was published only minutes ago, and PyPI's download index "
                           "takes a few minutes to catch up. Nothing was changed: try again in a few minutes.",
                "restarting": False, "retry": True, "details": f"$ {' '.join(cmd)}\n{output}".strip()}
    if r.returncode != 0:
        out = (r.stderr or r.stdout).strip().splitlines()[-3:]
        raise ApiError(f"The update failed ({' '.join(cmd)} ended with code {r.returncode}): {' / '.join(out)}", 500)
    restart_soon()
    return {"message": f"Updated to cc-profiles {info['latest']}. Restarting…", "restarting": True}


def whats_new():
    """This version and the release notes shipped with it (static/whatsnew.json, written by
    scripts/release.py from CHANGELOG.md). The page shows the ones newer than the version it
    saw last, so after an update you see what changed; nothing is fetched from the internet."""
    try:
        with open(os.path.join(STATIC_DIR, "whatsnew.json")) as f:
            releases = json.load(f).get("releases") or []
    except (OSError, ValueError):
        releases = []
    return {"version": __version__, "releases": releases}


def update_check_enabled():
    if os.environ.get("CC_PROFILES_UPDATE_CHECK") == "0":  # tests: never reach PyPI on their own
        return False
    return load_config().get("update_check") is not False


def auto_check():
    """The automatic check, from a background thread: asks PyPI only when the last answer is
    more than a day old. A failure (offline) is retried at the next round."""
    state = read_json(UPDATE_STATE, {}) or {}
    if update_check_enabled() and time.time() - (state.get("checked") or 0) >= CHECK_EVERY:
        try:
            check_update()
        except ApiError:
            pass


def update_status():
    """What the page shows without asking PyPI: the last known version, and whether it is newer."""
    state = read_json(UPDATE_STATE, {}) or {}
    return dict(update_info(state.get("latest")), enabled=update_check_enabled(), checked=state.get("checked"))


def op_update_check(enabled):
    """Turn the automatic check on or off ("update_check" in config.json)."""
    enabled = bool(enabled)
    if (load_config().get("update_check") is not False) == enabled:
        raise ApiError("Nothing to change")
    bk = Backup("update-check", f"Automatic update check: {'on' if enabled else 'off'}")
    bk.copy(CONFIG_FILE, "config.json")
    cfg = load_config()
    cfg["update_check"] = enabled
    write_json(CONFIG_FILE, cfg)
    return {"message": "cc-profiles checks for updates once a day." if enabled
            else "cc-profiles checks for updates only when you click.", "backup": bk.close()}
