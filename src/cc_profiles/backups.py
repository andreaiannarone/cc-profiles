# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Backups and restore."""

import os
import shutil
import time

from .core import ApiError, BACKUP_DIR, Backup, cached_read, pretty, read_json, write_json

# ---------------------------------------------------------------------------
# Backups and restore
# ---------------------------------------------------------------------------
def backup_path(name):
    if not name or "/" in name or name.startswith("."):
        raise ApiError("Invalid backup name")
    d = os.path.join(BACKUP_DIR, name)
    if not os.path.isdir(d):
        raise ApiError("Backup not found", 404)
    return d


def dir_size(d):
    total = 0
    for cur, _, files in os.walk(d):
        for f in files:
            try:
                total += os.lstat(os.path.join(cur, f)).st_size
            except OSError:
                pass
    return total


_size_cache = {}


def recent_dir_size(d, max_age=60):
    """dir_size for display, reused for up to max_age seconds."""
    hit = _size_cache.get(d)
    if hit and time.time() - hit[0] < max_age:
        return hit[1]
    size = dir_size(d)
    _size_cache[d] = (time.time(), size)
    return size


def list_backups():
    out = []
    if not os.path.isdir(BACKUP_DIR):
        return out
    for name in os.listdir(BACKUP_DIR):
        d = os.path.join(BACKUP_DIR, name)
        if not os.path.isdir(d):
            continue
        mf = os.path.join(d, "manifest.json")
        man = cached_read("manifest", mf, read_json) or {}
        # A closed backup (it has a manifest) changes only by replacing files at its top
        # level, which changes the folder's own mtime: its size is reused until then.
        size = cached_read("backup-size", d, dir_size) if man else dir_size(d)
        out.append({"name": name, "path": pretty(d), "size": size,
                    "title": man.get("title", name),
                    "created": man.get("created", os.path.getmtime(d)),
                    "log": man.get("log", []),
                    "steps": len(man.get("journal", [])),
                    "restorable": bool(man.get("journal")) and not man.get("restored"),
                    "failed": man.get("failed"),
                    "restored": man.get("restored")})
    out.sort(key=lambda b: b["created"], reverse=True)  # chronological: names only have seconds
    return out


def op_restore(name):
    d = backup_path(name)
    man = read_json(os.path.join(d, "manifest.json"))
    if not man or not man.get("journal"):
        raise ApiError("This backup has no journal: it cannot be restored automatically")
    if man.get("restored"):
        raise ApiError("Backup already restored")
    # A restore is itself an operation with a backup, so it can be undone too.
    nb = Backup("restore", f"Before restoring: {man.get('title', name)}")
    problems, done = [], 0
    for e in reversed(man["journal"]):
        op = e["op"]
        path = e.get("path") or e.get("from")
        try:
            if op == "copy":
                nb.copy(e["path"])
                os.makedirs(os.path.dirname(e["path"]), exist_ok=True)
                tmp = e["path"] + f".tmp-{os.getpid()}"
                shutil.copy2(os.path.join(d, e["file"]), tmp)
                os.replace(tmp, e["path"])
            elif op in ("absent", "created"):
                nb.stash(e["path"])
            elif op == "stash":
                nb.stash(e["path"])
                os.makedirs(os.path.dirname(e["path"]), exist_ok=True)
                shutil.move(os.path.join(d, e["file"]), e["path"])
                nb.created(e["path"])
            elif op == "move":
                if not os.path.lexists(e["to"]):
                    problems.append(f"no longer there: {pretty(e['to'])}")
                    continue
                if os.path.lexists(e["from"]):
                    problems.append(f"already taken: {pretty(e['from'])}")
                    continue
                os.makedirs(os.path.dirname(e["from"]), exist_ok=True)
                shutil.move(e["to"], e["from"])
                nb.moved(e["to"], e["from"])
            elif op == "mkdir":
                if os.path.isdir(e["path"]) and not os.listdir(e["path"]):
                    os.rmdir(e["path"])
            done += 1
        except Exception as ex:  # noqa: BLE001 - keep going with the next steps
            problems.append(f"{op} {pretty(path)}: {ex}")
    man["restored"] = time.time()
    write_json(os.path.join(d, "manifest.json"), man)
    nb.note(f"restored {done} of {len(man['journal'])} steps")
    for p in problems:
        nb.note("problem: " + p)
    msg = f"Restored: {done} of {len(man['journal'])} steps."
    if problems:
        msg += f" {len(problems)} could not be restored (details in the restore backup)."
    return {"message": msg, "backup": nb.close(), "problems": problems}


def op_backup_delete(name):
    shutil.rmtree(backup_path(name))
    return {"message": "Backup permanently deleted."}


def op_backup_prune(days):
    """Permanently delete the backups created more than `days` days ago."""
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ApiError("Pick a number of days, 1 or more")
    limit = time.time() - days * 86400
    old = [b for b in list_backups() if b["created"] < limit]
    freed = sum(b["size"] for b in old)
    for b in old:
        shutil.rmtree(backup_path(b["name"]))
    if not old:
        return {"message": f"No backups older than {days} days."}
    n = len(old)
    return {"message": f"Deleted {n} backup{'s' if n != 1 else ''} older than {days} days, {freed // 1024} KB freed."}
