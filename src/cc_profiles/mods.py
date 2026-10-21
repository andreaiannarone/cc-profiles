# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Claude Code mods, recognised among the installed plugins (read-only)."""

import os
import re

from .core import read_json

# ---------------------------------------------------------------------------
# Mods
# ---------------------------------------------------------------------------
# A mod is a plugin of function hooks: hooks/hooks.json names a hooks module under "modules"
# (a plugin of command hooks has "hooks" there instead), a TypeScript or JavaScript file that
# exports register(on, options). What a mod does is read from its source, never by running it:
# the events it hooks, on('tool.call', …), and the engine calls it makes, $.ui.status(…).
# A description, not a guarantee: code can reach the same calls in ways a pattern does not see.
CODE_SUFFIXES = (".ts", ".tsx", ".jsx", ".js", ".mjs", ".cjs", ".mts", ".cts")
MAX_FILES, MAX_BYTES = 50, 1024 * 1024  # a mod is a few files: stop reading a folder that is not

# What it shows or adds, from the engine calls in its source
FEATURES = [
    ("Pane", r"\$\.ui\.open\s*\(|component\s*:\s*['\"]Pane['\"]"),
    ("Band above the prompt", r"['\"]AbovePrompt['\"]"),
    ("Status line", r"\$\.ui\.status\s*\("),
    ("Notifications", r"\$\.ui\.(toast|notify)\s*\("),
    ("Sounds", r"\$\.audio\.(play|speak)\s*\("),
    ("Tools for Claude", r"\$\.tool\.register\s*\("),
    ("Subagent types", r"\$\.agent\.register\s*\("),
]
# What it can reach outside the session: worth knowing before turning a mod on
REACH = [
    ("Network", r"\$\.http\.fetch\s*\(|\$\.mcp\.(connect|call)\s*\("),
    ("Runs programs", r"\$\.process\.(run|spawn)\s*\("),
    ("Writes files", r"\$\.fs\.write\s*\("),
    ("Model calls", r"\$\.model\.(complete|classify|fork)\s*\("),
]
# The events it hooks, in words; any other event is listed by its name
EVENTS = {
    "tool.call": "Tool calls (can block or change them)",
    "prompt.submit": "Prompts you send (can change them)",
    "prompt.compose": "The system prompt",
    "session.start": "Session start",
    "session.end": "Session end",
    "turn.start": "Turn start",
    "turn.complete": "Turn end",
    "ui.render": "Drawing",
    "command.run": "Slash commands",
}
ON = re.compile(r"\bon\s*\(\s*['\"]([A-Za-z]+(?:\.[A-Za-z*]+)+)['\"]")
COMMAND = re.compile(r"\$\.command\.register\s*\(\s*\{[^}]*?\bname\s*:\s*['\"]([^'\"]+)['\"]", re.S)


def hooks_modules(install_path):
    """The hooks modules a plugin's hooks/hooks.json names, or [] when it is not a mod."""
    data = read_json(os.path.join(install_path, "hooks", "hooks.json"))
    mods = data.get("modules") if isinstance(data, dict) else None
    return [m for m in mods if isinstance(m, str)] if isinstance(mods, list) else []


def mod_source(install_path):
    """The text of the mod's code files under hooks/, up to MAX_FILES and MAX_BYTES."""
    hooks, texts, size = os.path.join(install_path, "hooks"), [], 0
    for cur, dirs, files in os.walk(hooks):
        dirs[:] = sorted(d for d in dirs if d not in ("node_modules", ".git"))
        for f in sorted(files):
            if not f.endswith(CODE_SUFFIXES) or len(texts) >= MAX_FILES or size >= MAX_BYTES:
                continue
            try:
                with open(os.path.join(cur, f), encoding="utf-8", errors="replace") as fh:
                    text = fh.read(MAX_BYTES - size)
            except OSError:
                continue
            texts.append(text)
            size += len(text)
    return "\n".join(texts)


def mod_info(install_path):
    """None for a plugin that is not a mod; else what its source says it does."""
    if not install_path or not hooks_modules(install_path):
        return None
    src = mod_source(install_path)
    events = sorted(set(ON.findall(src)))
    return {"features": [label for label, pat in FEATURES if re.search(pat, src)],
            "commands": sorted(set(COMMAND.findall(src))),
            "events": [{"name": e, "label": EVENTS.get(e, e)} for e in events],
            "reach": [label for label, pat in REACH if re.search(pat, src)]}


def installed_plugins(plugins_dir):
    """name -> list of installs, from installed_plugins.json (an older format had one install)."""
    data = read_json(os.path.join(plugins_dir, "installed_plugins.json"), {}) or {}
    out = {}
    for name, installs in (data.get("plugins") or {}).items():
        out[name] = [installs] if isinstance(installs, dict) else [i for i in installs or [] if isinstance(i, dict)]
    return out


def mod_names(prof):
    """The installed plugins of a profile that are mods."""
    plugins = installed_plugins(os.path.join(prof["dir_abs"], "plugins"))
    return sorted(n for n, installs in plugins.items()
                  if any(mod_info(i.get("installPath", "")) for i in installs))

