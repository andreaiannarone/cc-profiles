# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Classification and path resolution."""

import glob
import json
import os

from .byfolder import match_rule
from .core import cached_read, load_config, profiles, read_json, san

# ---------------------------------------------------------------------------
# Classification and path resolution
# ---------------------------------------------------------------------------
def classify(path, dirname, rules=None):
    """Expected profile for a project: a profile id, 'shared' or None.
    Pass `rules` when classifying many projects, to read the config once.
    The matching itself is byfolder.match_rule, shared with `cc-profiles which`."""
    if rules is None:
        rules = load_config()["rules"]
    return match_rule(rules, path, dirname)


def _read_history(path):
    try:
        with open(path) as f:
            return tuple(l.rstrip("\n") for l in f if l.strip())
    except OSError:
        return ()


def history_lines(prof):
    """The prompt history, read now: use this before writing it."""
    return list(_read_history(os.path.join(prof["dir_abs"], "history.jsonl")))


def _history_summary(path):
    """(prompts, broken lines, project paths) of a prompt history."""
    lines, broken, found = 0, 0, set()
    for l in _read_history(path):
        lines += 1
        try:
            pr = json.loads(l).get("project")
        except (ValueError, AttributeError):
            broken += 1
            continue
        if pr:
            found.add(pr)
    return lines, broken, frozenset(found)


def history_stats(prof):
    """(prompts, broken lines) of a profile's prompt history, for display."""
    return cached_read("history", os.path.join(prof["dir_abs"], "history.jsonl"), _history_summary)[:2]


def history_projects(prof):
    """Project paths mentioned in a profile's prompt history."""
    return cached_read("history", os.path.join(prof["dir_abs"], "history.jsonl"), _history_summary)[2]


def _first_cwds(jsonl, limit=60):
    found = set()
    try:
        with open(jsonl) as f:
            for i, line in enumerate(f):
                if i >= limit:
                    break
                try:
                    c = json.loads(line).get("cwd")
                except ValueError:
                    continue
                if c:
                    found.add(c)
    except OSError:
        pass
    return frozenset(found)


def first_cwds(jsonl):
    """Working directories mentioned in the first lines of a conversation."""
    return cached_read("cwds", jsonl, _first_cwds)


def config_projects(prof):
    """Project paths with settings in a profile's .claude.json."""
    def read(path):
        cfg = read_json(path, {}) or {}
        return frozenset((cfg.get("projects") or {}).keys()) if isinstance(cfg, dict) else frozenset()
    return cached_read("config-projects", prof["config_abs"], read)


def resolve_on_disk(name, base="/", depth=0):
    """Rebuild a path from its projects/ directory name by walking the disk.
    The name is ambiguous ('-' may be '/', ' ', '+', '.'...), so at each level we
    try every entry whose sanitized name is a prefix of what is left."""
    rest = name[len(san(base.rstrip("/"))):] if base != "/" else name
    if rest == "":
        return base
    if depth > 12 or not rest.startswith("-"):
        return None
    try:
        entries = os.listdir(base)
    except OSError:
        return None
    for e in sorted(entries, key=len, reverse=True):  # longest names first
        s = "-" + san(e)
        if rest == s or rest.startswith(s + "-"):
            p = os.path.join(base, e)
            if os.path.isdir(p):
                hit = resolve_on_disk(name, p, depth + 1)
                if hit:
                    return hit
    return None


def path_index():
    """Map projects/ directory name -> real path. An existing path wins over a
    missing one. Config files and prompt history are read first; conversations
    are read only for names still without an existing path (most projects never
    need them), and names nothing mentions are rebuilt by looking on disk."""
    folders = {}
    for p in profiles():
        for name, d, _ in project_folders(p, conversations=False):
            folders.setdefault(name, []).append(d)
    idx, dirs_seen = {}, {}

    def isdir(k):
        if k not in dirs_seen:
            dirs_seen[k] = os.path.isdir(k)
        return dirs_seen[k]

    def offer(k):
        s = san(k)
        if s in folders and (s not in idx or (not isdir(idx[s]) and isdir(k))):
            idx[s] = k

    for p in profiles():
        for k in config_projects(p) | history_projects(p):
            offer(k)
    for name, dirs in folders.items():
        if name in idx and isdir(idx[name]):
            continue
        for d in dirs:
            for f in glob.glob(os.path.join(d, "*.jsonl")):
                for k in first_cwds(f):
                    offer(k)
        if name not in idx or not isdir(idx[name]):
            hit = resolve_on_disk(name)
            if hit:
                idx[name] = hit
    return idx


def project_folders(prof, conversations=True):
    """(name, path, conversation file names) of every folder in a profile's projects/,
    in one directory read per folder (like glob, names starting with '.' are skipped).
    conversations=False skips reading the folders: the names are then None."""
    out = []
    try:
        entries = sorted(os.scandir(os.path.join(prof["dir_abs"], "projects")), key=lambda e: e.name)
    except OSError:
        return out
    for e in entries:
        if e.name.startswith(".") or not e.is_dir():
            continue
        if not conversations:
            out.append((e.name, e.path, None))
            continue
        convs = cached_read("conversations", e.path, _conversation_names)
        if convs is not None:
            out.append((e.name, e.path, list(convs)))
    return out


# A folder's mtime changes whenever an entry is added, removed or renamed in it,
# so a listing keyed on the folder's stat() is as current as a new listing.
def _conversation_names(d):
    try:
        return tuple(f for f in os.listdir(d) if f.endswith(".jsonl") and not f.startswith("."))
    except OSError:
        return None


def _memory_names(md):
    try:
        return tuple(sorted(f for f in os.listdir(md) if f.endswith(".md") and f != "MEMORY.md"))
    except OSError:
        return ()


def memory_files(d, fresh=False):
    """Memory files of a project folder, without MEMORY.md. fresh=True lists the
    folder again even if it did not change (before deciding a write on it)."""
    md = os.path.join(d, "memory")
    if not os.path.isdir(md):
        return []
    return list(_memory_names(md) if fresh else cached_read("memories", md, _memory_names))
