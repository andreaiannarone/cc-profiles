# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Installing Claude Code."""

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time

from .core import ApiError, find_tool, pretty, tool_env
from .info import claude_version

# ---------------------------------------------------------------------------
# Installing Claude Code
# ---------------------------------------------------------------------------
# Official commands only (code.claude.com/docs/en/setup): the client picks a
# method id from this list, never sends a command of its own.
INSTALL_METHODS = {
    "native": {"label": "Official installer (recommended)",
               "command": "curl -fsSL https://claude.ai/install.sh | bash",
               "note": "Updates itself in the background. Installs into ~/.local/bin."},
    "brew": {"label": "Homebrew, stable channel", "requires": "brew",
             "command": "brew install --cask claude-code",
             "note": "About a week behind, skips releases with regressions. Update with brew upgrade claude-code."},
    "brew-latest": {"label": "Homebrew, latest channel", "requires": "brew",
                    "command": "brew install --cask claude-code@latest",
                    "note": "Every release as soon as it ships. Update with brew upgrade claude-code@latest."},
    "npm": {"label": "npm", "requires": "npm",
            "command": "npm install -g @anthropic-ai/claude-code",
            "note": "Needs Node.js 22 or later. Update with npm install -g @anthropic-ai/claude-code@latest."},
}
_job = {"running": False, "method": None, "lines": [], "code": None, "started": None}
_job_lock = threading.Lock()


def node_major():
    n = find_tool("node")
    if not n:
        return None
    try:
        out = subprocess.run([n, "--version"], capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().lstrip("v").split(".")[0])
    except Exception:
        return None


def claude_status():
    b = find_tool("claude")
    methods = []
    for k, m in INSTALL_METHODS.items():
        ok, why = True, ""
        if m.get("requires") == "brew" and not find_tool("brew"):
            ok, why = False, "Homebrew is not installed"
        if m.get("requires") == "npm":
            nm = node_major()
            if not find_tool("npm"):
                ok, why = False, "npm is not installed"
            elif nm is not None and nm < 22:
                ok, why = False, f"needs Node.js 22 or later (you have {nm})"
        if k == "native" and not find_tool("curl"):
            ok, why = False, "curl is not available"
        methods.append({"id": k, "label": m["label"], "command": m["command"], "note": m["note"],
                        "available": ok, "why": why})
    return {"installed": bool(b), "path": pretty(os.path.realpath(b)) if b else None,
            "version": claude_version() if b else None,
            "in_path": bool(shutil.which("claude")), "platform": sys.platform,
            "supported": sys.platform in ("darwin", "linux"),
            "methods": methods, "job": job_state()}


def job_state():
    with _job_lock:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in _job.items()}


def _run_job(cmd):
    try:
        p = subprocess.Popen(["/bin/bash", "-lc", cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, env=tool_env(), bufsize=1)
        for line in p.stdout:
            with _job_lock:
                _job["lines"].append(re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line.rstrip("\n")))
                del _job["lines"][:-400]  # keep the last 400 lines
        code = p.wait()
    except Exception as e:  # noqa: BLE001
        with _job_lock:
            _job["lines"].append(f"Error: {e}")
        code = -1
    with _job_lock:
        _job["code"], _job["running"] = code, False


def op_install(method):
    m = INSTALL_METHODS.get(method)
    if not m:
        raise ApiError("Unknown install method")
    if sys.platform not in ("darwin", "linux"):
        raise ApiError("Installing from here is only supported on macOS and Linux")
    st = next(x for x in claude_status()["methods"] if x["id"] == method)
    if not st["available"]:
        raise ApiError(f"{m['label']} is not available: {st['why']}")
    with _job_lock:
        if _job["running"]:
            raise ApiError("An installation is already running")
        _job.update(running=True, method=method, lines=[f"$ {m['command']}"], code=None, started=time.time())
    cmd = m["command"]
    if os.environ.get("CC_PROFILES_INSTALL_DRYRUN"):  # tests only: installs nothing
        cmd = f"echo {json.dumps(cmd)}; sleep 1; echo dry run ok; exit ${{CC_PROFILES_INSTALL_DRYRUN_CODE:-0}}"
    threading.Thread(target=_run_job, args=(cmd,), daemon=True).start()
    return {"message": f"Installation started: {m['label']}."}
