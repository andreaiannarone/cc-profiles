# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: disk space of a profile, and freeing it."""

import os
import time

from .core import ApiError, Backup, pretty, profile
from .backups import keep_days
from .settings import effective

# ---------------------------------------------------------------------------
# Disk space
# ---------------------------------------------------------------------------
# What fills a profile's folder, and what can go: conversations and the files Claude Code
# keeps beside them (file snapshots, task lists, shell environment), plus caches and logs.
# Only items untouched for the chosen number of days are offered (never fewer than 1, so a
# running session is never touched), and the files of a session that still has its
# conversation stay. Nothing is deleted: items go into the backup, so the space comes back
# when that backup is deleted (Backups tab, or the automatic cleanup).
CATEGORIES = [
    ("conversations", "Conversations", "projects/*/*.jsonl",
     "Conversations, with their subagent replies, file snapshots and task lists. Memories stay."),
    ("file-history", "File snapshots", "file-history/",
     "Snapshots of the files Claude edited, for /rewind: only those of conversations that no longer exist"),
    ("session-env", "Session environments", "session-env/", "Only those of conversations that no longer exist"),
    ("todos", "Task lists", "todos/", "Only those of conversations that no longer exist"),
    ("shell-snapshots", "Shell snapshots", "shell-snapshots/", "Your shell's setup, saved at the start of each session"),
    ("debug", "Debug logs", "debug/", "Logs written with --debug"),
    ("paste-cache", "Pasted text", "paste-cache/", "Long pastes, kept to show them again"),
    ("image-cache", "Pasted images", "image-cache/", "Images pasted into prompts"),
]
CAT_IDS = [c[0] for c in CATEGORIES]
DEFAULT_DAYS = 30  # Claude Code's own cleanupPeriodDays when unset


def human(n):
    for unit, size in (("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if n >= size:
            return f"{n / size:.1f} {unit}"
    return f"{n} B"


def measure(path):
    """(size, newest mtime) of a file or a folder, without following links."""
    try:
        st = os.lstat(path)
    except OSError:
        return 0, 0
    if not os.path.isdir(path) or os.path.islink(path):
        return st.st_size, st.st_mtime
    size, newest = 0, st.st_mtime
    for cur, dirs, files in os.walk(path):
        for f in files + dirs:
            try:
                s = os.lstat(os.path.join(cur, f))
            except OSError:
                continue
            newest = max(newest, s.st_mtime)
            if f in files:
                size += s.st_size
    return size, newest


def entries(d):
    try:
        return sorted(e for e in os.listdir(d) if not e.startswith("."))
    except OSError:
        return []


def owner_session(name):
    """The session id a file or folder of file-history, session-env or todos belongs to."""
    base = name[:-5] if name.endswith(".json") else name
    return base.split("-agent-")[0]


def conversations(prof):
    """session id → [paths]: the conversation file, its folder of subagent replies, and the
    file snapshots, session environment and task lists of the same session."""
    d = prof["dir_abs"]
    out = {}
    projects = os.path.join(d, "projects")
    for p in entries(projects):
        pd = os.path.join(projects, p)
        if os.path.islink(pd) or not os.path.isdir(pd):
            continue
        for f in entries(pd):
            if f.endswith(".jsonl"):
                sid = f[:-6]
                paths = [os.path.join(pd, f)]
                if os.path.isdir(os.path.join(pd, sid)):
                    paths.append(os.path.join(pd, sid))
                out[sid] = paths
    for cat in ("file-history", "session-env", "todos"):
        folder = os.path.join(d, cat)
        if os.path.islink(folder):
            continue
        for n in entries(folder):
            if owner_session(n) in out:
                out[owner_session(n)].append(os.path.join(folder, n))
    return out


def items(prof):
    """category → list of (label, [paths]): what each category holds, as units that go together."""
    d = prof["dir_abs"]
    convs = conversations(prof)
    out = {"conversations": [(sid, paths) for sid, paths in sorted(convs.items())]}
    for cat in CAT_IDS[1:]:
        folder = os.path.join(d, cat)
        if os.path.islink(folder):
            out[cat] = None  # shared: its owner cleans it
            continue
        units = []
        for n in entries(folder):
            if cat in ("file-history", "session-env", "todos") and owner_session(n) in convs:
                continue  # it goes with its conversation
            units.append((n, [os.path.join(folder, n)]))
        out[cat] = units
    return out


def check_days(days, prof=None):
    if days in (None, ""):
        v, _ = effective(prof, "cleanupPeriodDays") if prof else (None, None)
        return v if isinstance(v, int) and not isinstance(v, bool) and v >= 1 else DEFAULT_DAYS
    try:
        days = int(days)
    except (TypeError, ValueError):
        days = 0
    if days < 1:
        raise ApiError("Days: a whole number, 1 or more")
    return days


def plan(prof, days, cats=None):
    """Every category with its size, and what is older than days."""
    cutoff = time.time() - days * 86400
    out, held = [], items(prof)
    for cat_id, label, where, desc in CATEGORIES:
        units = held[cat_id] if cats is None or cat_id in cats else []
        row = {"id": cat_id, "label": label, "where": where, "desc": desc, "size": 0, "count": 0,
               "old_size": 0, "old_count": 0, "shared": units is None, "old": []}
        for name, paths in units or []:
            size = newest = 0
            for p in paths:
                s, m = measure(p)
                size, newest = size + s, max(newest, m)
            row["size"] += size
            row["count"] += 1
            if newest < cutoff:
                row["old_size"] += size
                row["old_count"] += 1
                row["old"].append(paths)
        out.append(row)
    return out


def get_storage(pid, days=None):
    prof = profile(pid)
    days = check_days(days, prof)
    rows = plan(prof, days)
    total, _ = measure(prof["dir_abs"])
    setting, _ = effective(prof, "cleanupPeriodDays")
    return {"profile": prof["id"], "dir": pretty(prof["dir_abs"]), "days": days, "total": total,
            "cleanup_days": setting if isinstance(setting, int) else None, "default_cleanup_days": DEFAULT_DAYS,
            "keep_days": keep_days(), "categories": [{k: v for k, v in r.items() if k != "old"} for r in rows]}


def op_storage_clean(pid, days, categories):
    prof = profile(pid)
    days = check_days(days)
    if not isinstance(categories, list) or not categories or any(c not in CAT_IDS for c in categories):
        raise ApiError("Pick what to clean up")
    rows = [r for r in plan(prof, days, set(categories)) if r["id"] in categories]
    count = sum(r["old_count"] for r in rows)
    if not count:
        raise ApiError(f"Nothing older than {days} day{'s' if days != 1 else ''} to clean up")
    size = sum(r["old_size"] for r in rows)
    bk = Backup("free-space", f"Free {human(size)} in {prof['label']}")
    for r in rows:
        for paths in r["old"]:
            for p in paths:
                bk.stash(p)
        if r["old_count"]:
            bk.note(f"{r['label']}: {r['old_count']} ({human(r['old_size'])}) untouched for {days}+ days")
    return {"message": f"{count} item{'s' if count != 1 else ''} ({human(size)}) moved to the backup. The space comes back "
                       f"when you delete the backup in Backups, or by itself after {keep_days()} days.",
            "backup": bk.close(), "freed": size}
