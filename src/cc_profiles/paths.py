# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Classification and path resolution."""

import glob
import json
import os

from .core import expand, load_config, profiles, read_json, san

# ---------------------------------------------------------------------------
# Classification and path resolution
# ---------------------------------------------------------------------------
def classify(path, dirname):
    """Expected profile for a project: a profile id, 'shared' or None."""
    rules = load_config()["rules"]
    for r in rules:
        if "exact" in r:
            target = expand(r["exact"]).rstrip("/") or "/"
            if path == target or (path is None and dirname == san(target)):
                return r["profile"]
    for r in rules:
        m = r.get("match")
        if not m:
            continue
        if path is not None and m in path:
            return r["profile"]
        if path is None and san(m) in dirname:
            return r["profile"]
    return None


def history_lines(prof):
    path = os.path.join(prof["dir_abs"], "history.jsonl")
    try:
        with open(path) as f:
            return [l.rstrip("\n") for l in f if l.strip()]
    except OSError:
        return []


def first_cwds(jsonl, limit=60):
    """Working directories mentioned in the first lines of a conversation."""
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
    return found


def known_paths():
    """Every project path mentioned by config files, prompt history and conversations."""
    paths = set()
    for p in profiles():
        cfg = read_json(p["config_abs"], {}) or {}
        paths |= set((cfg.get("projects") or {}).keys())
        for l in history_lines(p):
            try:
                pr = json.loads(l).get("project")
            except ValueError:
                continue
            if pr:
                paths.add(pr)
        for f in glob.glob(os.path.join(p["dir_abs"], "projects", "*", "*.jsonl")):
            paths |= first_cwds(f)
    return paths


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
    missing one; names no file mentions are rebuilt by looking on disk."""
    idx = {}
    for k in known_paths():
        s = san(k)
        if s not in idx or (not os.path.isdir(idx[s]) and os.path.isdir(k)):
            idx[s] = k
    for p in profiles():
        for d in glob.glob(os.path.join(p["dir_abs"], "projects", "*", "")):
            name = os.path.basename(d.rstrip("/"))
            if name not in idx or not os.path.isdir(idx[name]):
                hit = resolve_on_disk(name)
                if hit:
                    idx[name] = hit
    return idx


def memory_files(d):
    md = os.path.join(d, "memory")
    if not os.path.isdir(md):
        return []
    return sorted(f for f in os.listdir(md) if f.endswith(".md") and f != "MEMORY.md")
