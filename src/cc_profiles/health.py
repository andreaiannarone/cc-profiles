# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Profiles and health."""

import glob
import json
import os
import subprocess
import time

from .core import (
    DEFAULT_SEARCH_ROOTS,
    HOME,
    SEARCH_SKIP,
    active_session,
    expand,
    find_tool,
    load_config,
    pretty,
    profiles,
    read_json,
    tool_env,
)
from .paths import history_lines, memory_files
from .projects import list_projects
from .memories import memory_list

def list_profiles():
    out = []
    profs = profiles()
    for p in profs:
        cfg = read_json(p["config_abs"], {}) or {}
        projs = glob.glob(os.path.join(p["dir_abs"], "projects", "*", ""))
        out.append({
            "id": p["id"], "label": p["label"], "dir": pretty(p["dir_abs"]),
            "primary": p["id"] == profs[0]["id"],
            "command": p.get("command", ""),
            "email": (cfg.get("oauthAccount") or {}).get("emailAddress", ""),
            "projects": len(projs),
            "conv": len(glob.glob(os.path.join(p["dir_abs"], "projects", "*", "*.jsonl"))),
            "memories": sum(len(memory_files(d)) for d in projs),
            "active": active_session(p),
        })
    return out


_cand_cache = {}


def candidates(basename):
    """Folders with the same name under the search roots (depth 5)."""
    if not basename:
        return []
    hit = _cand_cache.get(basename)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    found = []
    for root in load_config().get("search_roots", DEFAULT_SEARCH_ROOTS):
        root = expand(root)
        base = root.rstrip("/").count("/")
        for cur, dirs, _ in os.walk(root):
            depth = cur.count("/") - base
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SEARCH_SKIP]
            if depth >= 5:
                dirs[:] = []
            if os.path.basename(cur) == basename and cur != root:
                found.append(pretty(cur))
            if len(found) >= 10:
                break
    _cand_cache[basename] = (time.time(), found)
    return found


def auth_status(p):
    env = tool_env()
    if p["dir_abs"] != os.path.join(HOME, ".claude"):
        env["CLAUDE_CONFIG_DIR"] = p["dir_abs"]
    else:
        env.pop("CLAUDE_CONFIG_DIR", None)
    b = find_tool("claude")
    if not b:
        return None
    try:
        r = subprocess.run([b, "auth", "status"], env=env, capture_output=True, text=True, timeout=20)
        return json.loads(r.stdout)
    except Exception:
        return None


def health():
    report = []
    projects = list_projects()
    for p in profiles():
        checks = []

        def add(ok, text, level=None):
            checks.append({"level": level or ("ok" if ok else "error"), "text": text})

        a = auth_status(p)
        add(bool(a and a.get("loggedIn")),
            f"Logged in: {a.get('email')}" if a and a.get("loggedIn") else "Not logged in")
        for f, lab in [(p["config_abs"], ".claude.json"),
                       (os.path.join(p["dir_abs"], "settings.json"), "settings.json"),
                       (os.path.join(p["dir_abs"], "settings.local.json"), "settings.local.json")]:
            if os.path.exists(f):
                ok = read_json(f) is not None
                add(ok, f"{lab} {'is valid' if ok else 'is NOT valid JSON'}")
        lines = history_lines(p)
        bad = 0
        for l in lines:
            try:
                json.loads(l)
            except ValueError:
                bad += 1
        add(bad == 0, f"Prompt history: {len(lines)} prompts" + (f", {bad} broken lines" if bad else ""))
        for sub in ("skills", "plugins"):
            d = os.path.join(p["dir_abs"], sub)
            if os.path.isdir(d):
                add(True, f"{sub} reachable" + (f" (shared → {os.readlink(d)})" if os.path.islink(d) else ""))
            elif os.path.lexists(d):
                add(False, f"{sub} is a broken link")
        sk = glob.glob(os.path.join(p["dir_abs"], "skills", "*", "SKILL.md"))
        add(True, f"{len(sk)} readable skills")
        inst = read_json(os.path.join(p["dir_abs"], "plugins", "installed_plugins.json"), {}) or {}
        for key, entries in (inst.get("plugins") or {}).items():
            for e in entries if isinstance(entries, list) else [entries]:
                ip = e.get("installPath", "")
                add(os.path.isdir(ip), f"Plugin {key}" + ("" if os.path.isdir(ip) else ": files missing"))
        for d in glob.glob(os.path.join(p["dir_abs"], "projects", "*", "memory")):
            name = os.path.basename(os.path.dirname(d))
            ml = memory_list(p["id"], name)
            for f in ml["missing"]:
                add(False, f"Index of {name}: {f} is missing")
            for it in ml["items"]:
                if not it["indexed"]:
                    add(False, f"{name}: {it['file']} is not in MEMORY.md", "warn")
        if active_session(p):
            add(True, "A session is open right now: writes are atomic, but avoid heavy operations", "warn")
        orphans = []
        for r in projects:
            if p["id"] in r["in"] and not r["exists"]:
                base = os.path.basename(r["path"]) if r["path"] else ""
                orphans.append({"name": r["name"], "pretty": r["pretty"],
                                "conv": r["in"][p["id"]]["conv"], "mem": r["in"][p["id"]]["mem"],
                                "candidates": candidates(base)})
        report.append({"id": p["id"], "label": p["label"], "checks": checks, "orphans": orphans})
    return report
