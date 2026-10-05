# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Backups and restore."""

import os
import shutil
import time

from .core import ApiError, BACKUP_DIR, Backup, CONFIG_FILE, cached_read, load_config, pretty, read_json, write_json

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


def prune(days, keep_incomplete=False):
    """Permanently delete the backups created more than `days` days ago. Returns (count, bytes)."""
    limit = time.time() - days * 86400
    old = [b for b in list_backups() if b["created"] < limit
           and not (keep_incomplete and b["failed"] and not b["restored"])]
    freed = sum(b["size"] for b in old)
    for b in old:
        shutil.rmtree(backup_path(b["name"]))
    return len(old), freed


def op_backup_prune(days):
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ApiError("Pick a number of days, 1 or more")
    n, freed = prune(days)
    if not n:
        return {"message": f"No backups older than {days} days."}
    return {"message": f"Deleted {n} backup{'s' if n != 1 else ''} older than {days} days, {freed // 1024} KB freed."}


# Automatic cleanup, off by default: "backup_keep_days" in config.json. The server prunes
# when it starts and once a day while it runs. It never deletes a backup from the last
# 24 hours, nor an incomplete one (a failed operation) that has not been restored yet.
AUTO_PRUNE_CHOICES = (30, 90, 180, 365)
AUTO_PRUNE = {"last": None, "message": ""}  # the last automatic cleanup in this process


def keep_days():
    days = load_config().get("backup_keep_days")
    return days if days in AUTO_PRUNE_CHOICES else None


def auto_prune():
    """Run the automatic cleanup if it is on. Returns the number of backups deleted."""
    days = keep_days()
    if not days:
        return 0
    n, freed = prune(max(days, 1), keep_incomplete=True)
    AUTO_PRUNE["last"] = time.time()
    AUTO_PRUNE["message"] = (f"Deleted {n} backup{'s' if n != 1 else ''} older than {days} days, {freed // 1024} KB freed."
                             if n else f"No backups older than {days} days.")
    return n


def backup_auto():
    return {"days": keep_days(), "choices": list(AUTO_PRUNE_CHOICES), "last": AUTO_PRUNE["last"],
            "message": AUTO_PRUNE["message"], "config": pretty(CONFIG_FILE)}


def op_backup_auto(days):
    if days is not None and days not in AUTO_PRUNE_CHOICES:
        raise ApiError("Pick 30, 90, 180 or 365 days, or turn the cleanup off")
    if days == keep_days():
        raise ApiError("Nothing to change")
    bk = Backup("backup-cleanup", "Automatic backup cleanup: " + (f"older than {days} days" if days else "off"))
    bk.copy(CONFIG_FILE, "config.json")
    cfg = load_config()
    if days:
        cfg["backup_keep_days"] = days
    else:
        cfg.pop("backup_keep_days", None)
    write_json(CONFIG_FILE, cfg)
    backup = bk.close()
    if not days:
        return {"message": "Automatic cleanup off: backups are kept until you delete them.", "backup": backup}
    auto_prune()
    return {"message": f"Backups older than {days} days are deleted automatically. {AUTO_PRUNE['message']}",
            "backup": backup}
