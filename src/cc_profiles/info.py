# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Claude Code information."""

import glob
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from . import __version__
from . import core
from .core import (
    APP_DIR,
    BACKUP_DIR,
    CONFIG_FILE,
    find_tool,
    load_settings,
    pretty,
    profiles,
    read_json,
    tool_env,
)
from .paths import history_stats, memory_files
from .sharing import SHARE_ITEMS
from .settings import SCHEMA_VERSION
from .health import auth_status
from .github import profile_github
from .backups import list_backups, recent_dir_size

# ---------------------------------------------------------------------------
# Claude Code information
# ---------------------------------------------------------------------------
PLANS = {"max": "Max", "pro": "Pro", "team": "Team", "enterprise": "Enterprise", "free": "Free"}


def claude_binary():
    b = find_tool("claude")
    return os.path.realpath(b) if b else None


def claude_version():
    b = find_tool("claude")
    if not b:
        return None
    try:
        r = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=10, env=tool_env())
        return r.stdout.strip().split(" ")[0] or None
    except Exception:
        return None


def names_in(d, suffix=None, dirs=False):
    if not os.path.isdir(d):
        return []
    out = []
    for n in sorted(os.listdir(d)):
        if n.startswith("."):
            continue
        p = os.path.join(d, n)
        if dirs and os.path.isdir(p):
            out.append(n)
        elif not dirs and (suffix is None or n.endswith(suffix)) and os.path.isfile(p):
            out.append(n[: -len(suffix)] if suffix else n)
    return out


def github_line(p):
    """The GitHub account of a profile's Claude Code sessions, and the GitHub CLI folder it comes from."""
    g = profile_github(p)
    return f"{g['user'] or 'not signed in'} · {g['dir']}"


def about():
    binary = claude_binary()
    primary_cfg = read_json(profiles()[0]["config_abs"], {}) or {}
    profs = []
    with ThreadPoolExecutor(max_workers=8) as pool:  # `claude auth status` takes ~0.5 s each
        auths = list(pool.map(auth_status, profiles()))
    for p, a in zip(profiles(), auths):
        a = a or {}
        cfg = read_json(p["config_abs"], {}) or {}
        sett, _ = load_settings(os.path.join(p["dir_abs"], "settings.json"))
        local, _ = load_settings(os.path.join(p["dir_abs"], "settings.local.json"))
        inst = read_json(os.path.join(p["dir_abs"], "plugins", "installed_plugins.json"), {}) or {}
        mcp_user = sorted((cfg.get("mcpServers") or {}).keys())
        mcp_proj = sorted({k for pr in (cfg.get("projects") or {}).values()
                           for k in ((pr or {}).get("mcpServers") or {}).keys()})
        hooks = sorted(set((sett.get("hooks") or {}).keys()) | set((local.get("hooks") or {}).keys()))
        projs = glob.glob(os.path.join(p["dir_abs"], "projects", "*", ""))
        convs = glob.glob(os.path.join(p["dir_abs"], "projects", "*", "*.jsonl"))
        first = cfg.get("firstStartTime")
        profs.append({
            "id": p["id"], "label": p["label"], "command": p.get("command", ""),
            "dir": pretty(p["dir_abs"]), "config": pretty(p["config_abs"]),
            "account": {
                "Account": a.get("email") or (cfg.get("oauthAccount") or {}).get("emailAddress", ""),
                "Login": ("active" if a.get("loggedIn") else "not logged in")
                         + (f" · {a['authMethod']}" if a.get("authMethod") and a.get("authMethod") != "none" else ""),
                "Plan": PLANS.get(a.get("subscriptionType"), a.get("subscriptionType") or "—"),
                "Organization": a.get("orgName") or "—",
                "API provider": a.get("apiProvider") or "—",
                "GitHub": github_line(p),
                "Analytics": "off" if a.get("analyticsDisabled") else "on",
            },
            "usage": {
                "Startups": cfg.get("numStartups", "—"),
                "First started": first[:10] if isinstance(first, str) else "—",
                "Saved conversations": len(convs),
                "Projects": len(projs),
                "Memories": sum(len(memory_files(d)) for d in projs),
                "Prompts in history": history_stats(p)[0],
                "Disk usage": recent_dir_size(p["dir_abs"]),
            },
            "contents": {
                "Skills": names_in(os.path.join(p["dir_abs"], "skills"), dirs=True),
                "Plugins": sorted((inst.get("plugins") or {}).keys()),
                "Subagents": names_in(os.path.join(p["dir_abs"], "agents"), ".md"),
                "Slash commands": names_in(os.path.join(p["dir_abs"], "commands"), ".md"),
                "Output styles": names_in(os.path.join(p["dir_abs"], "output-styles"), ".md"),
                "MCP servers (user)": mcp_user,
                "MCP servers (projects)": mcp_proj,
                "Hooks": hooks,
            },
            "shared": [i for i, _, _ in SHARE_ITEMS if os.path.islink(os.path.join(p["dir_abs"], i))],
            "claude_md": os.path.exists(os.path.join(p["dir_abs"], "CLAUDE.md")),
        })
    return {
        "claude": {
            "Version": claude_version() or "not found",
            "Binary": pretty(binary) if binary else "claude is not in PATH",
            "Install method": primary_cfg.get("installMethod", "—"),
            "Auto-updates": "on" if primary_cfg.get("autoUpdates") else "off",
            "Settings schema checked against": SCHEMA_VERSION,
        },
        "profiles": profs,
        "app": {
            "cc-profiles": __version__,
            "Code": pretty(APP_DIR),
            "Config and rules": pretty(CONFIG_FILE),
            "Backups": f"{len(list_backups())} · {pretty(BACKUP_DIR)}",
            "Backup disk usage": recent_dir_size(BACKUP_DIR) if os.path.isdir(BACKUP_DIR) else 0,
            "Address": f"http://127.0.0.1:{core.PORT}",
            "Python": sys.version.split(" ")[0],
            "System": core.system_name(),
        },
    }
