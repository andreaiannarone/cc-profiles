# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Claude Code's own slash commands and bundled skills, read from its binary (read-only)."""

import json
import mmap
import os
import re

from .core import DATA_DIR, read_json, write_json
from .info import claude_binary

# ---------------------------------------------------------------------------
# Commands and skills inside the Claude Code binary
# ---------------------------------------------------------------------------
# Claude Code does not document its built-in commands: they are objects in the minified
# JavaScript compiled into the binary. A command is {type:"local"|"local-jsx"|"prompt",
# name:"…", description:"…", argumentHint:"…", aliases:[…], isHidden:!0}, in any key order;
# a bundled skill is registered with wd({name:…, menuDescription:"…", userInvocable:!0}),
# its name sometimes held in a variable (name:TJn with TJn="simplify" earlier). A
# description computed by a getter (get description(){…}) cannot be read: it stays None.
# The binary is mapped, not read (350 MB: about 1 s once in the page cache), and the
# result kept in CACHE until the binary changes. Anything unexpected gives None, and the
# caller falls back to its own list.
CACHE = os.path.join(DATA_DIR, "claude-commands.json")
CACHE_FORMAT = 1
MIN_COMMANDS = 20  # fewer means the layout changed (or a fake binary): not trusted
NAME = re.compile(rb'name:"([a-z][a-z0-9-]*)"')
SKILL_CALL = re.compile(rb'wd\(\{name:([A-Za-z_$][\w$]*),')
COMMAND_TYPE = re.compile(rb'\s*"(?:local|local-jsx|prompt)"')
STRING = re.compile(rb'\s*"((?:[^"\\\n]|\\.)*)"\s*$')
ITEM = re.compile(rb'"[a-z0-9-]*"')
VAR_WINDOW = 64 * 1024 * 1024
VERSION = re.compile(rb'VERSION:"(\d+\.\d+\.\d+)"')
_memo = {}


def object_keys(data, start):
    """The top-level keys of the object opening at start, as {key: text after the colon}.
    Getters (get key(){…}) and methods are left out."""
    out, depth, i, key_at, end = {}, 0, start, start + 1, min(len(data), start + 8000)

    def take(stop):
        m = re.match(rb"\s*([A-Za-z_$][\w$]*)\s*:", data[key_at:stop])
        if m:
            out[m.group(1).decode()] = data[key_at + m.end():stop]
    while i < end:
        c = data[i:i + 1]
        if c in (b'"', b"'", b"`"):
            j = i + 1
            while j < end and data[j:j + 1] != c:
                j += 2 if data[j:j + 1] == b"\\" else 1
            i = j + 1
            continue
        if c in (b"{", b"[", b"("):
            depth += 1
        elif c in (b"}", b"]", b")"):
            depth -= 1
            if depth == 0:
                take(i)
                break
        elif depth == 1 and c == b",":
            take(i)
            key_at = i + 1
        i += 1
    return out


def literal(text):
    """A plain JavaScript string literal as text, or None (a variable, a template, a call…)."""
    m = STRING.match(text or b"")
    if not m:
        return None
    try:
        return json.loads(b'"' + m.group(1) + b'"')
    except ValueError:
        return None


def string_list(text):
    """["a","b"] as a list, or [] for anything else (a variable, a call…)."""
    text = (text or b"").strip()
    if not (text.startswith(b"[") and text.endswith(b"]")):
        return []
    items = [i.strip() for i in text[1:-1].split(b",") if i.strip()]
    if not all(ITEM.fullmatch(i) for i in items):
        return []
    return [i[1:-1].decode() for i in items]


def add(target, name, keys):
    """Merge one definition into target[name]: a command can be defined twice (terminal and
    non-interactive); a readable description or hint wins, hidden only if every one is."""
    e = target.setdefault(name, {"description": None, "hint": None, "aliases": [], "hidden": True, "user": False})
    e["description"] = e["description"] or literal(keys.get("menuDescription")) or literal(keys.get("description"))
    e["hint"] = e["hint"] if e["hint"] is not None else literal(keys.get("argumentHint"))
    e["aliases"] = e["aliases"] or string_list(keys.get("aliases"))
    e["hidden"] = e["hidden"] and keys.get("isHidden", b"").strip() == b"!0"
    e["user"] = e["user"] or keys.get("userInvocable", b"!0").strip() != b"!1"


def var_value(data, var, at):
    """The name a variable holds (var="name"), from its nearest definition before at: minified
    code defines it in the same module, never more than a few MB earlier. One-letter names
    are reused everywhere: not trusted."""
    if len(var) < 2:
        return None
    lo, hi = max(0, at - VAR_WINDOW), at
    while True:
        i = data.rfind(var + b'="', lo, hi)
        if i < 0:
            return None
        m = re.match(rb'"([a-z][a-z0-9-]*)"', data[i + len(var) + 1:i + len(var) + 80])
        if m and not re.match(rb"[\w$.]", data[i - 1:i]):
            return m.group(1).decode()
        hi = i


def parse(data, texts=()):
    """{"version", "commands", "skills", "present"} from a binary's bytes. texts: names → a
    description to look for, for skills written as Markdown files (present: those found)."""
    commands, skills = {}, {}
    for m in NAME.finditer(data):
        start = data.rfind(b"{", max(0, m.start() - 2000), m.start())
        if start < 0:
            continue
        keys = object_keys(data, start)
        if not keys.get("name", b"").strip().startswith(b'"' + m.group(1) + b'"'):
            continue
        if COMMAND_TYPE.match(keys.get("type", b"")):
            add(commands, m.group(1).decode(), keys)
        elif "userInvocable" in keys or "menuDescription" in keys:
            add(skills, m.group(1).decode(), keys)
    for m in SKILL_CALL.finditer(data):
        name = var_value(data, m.group(1), m.start())
        if name:
            add(skills, name, object_keys(data, m.start() + 3))
    v = VERSION.search(data)
    present = [n for n, t in texts if n not in skills and data.find(t.encode()) >= 0]
    return {"version": v.group(1).decode() if v else None, "commands": commands, "skills": skills, "present": present}


def read_installed(texts=()):
    """parse() of the installed Claude Code, kept until the binary changes; None when there
    is none, or it cannot be read as expected."""
    b = claude_binary()
    try:
        st = os.stat(b) if b else None
    except OSError:
        st = None
    if not st or not st.st_size:
        return None
    key = [b, st.st_size, st.st_mtime, CACHE_FORMAT]
    if _memo.get("key") == key:
        return _memo["value"]
    cached = read_json(CACHE)
    if isinstance(cached, dict) and cached.get("key") == key:
        value = cached.get("value")
    else:
        try:
            with open(b, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
                value = parse(data, texts)
        except (OSError, ValueError):
            value = None
        if value and len(value["commands"]) < MIN_COMMANDS:
            value = None
        try:
            write_json(CACHE, {"key": key, "value": value})  # cc-profiles' own file: no backup
        except OSError:
            pass
    _memo.update(key=key, value=value)
    return value
