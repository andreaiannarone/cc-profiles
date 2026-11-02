# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: automatic exports of every profile into a folder (iCloud Drive when there is one),
the last KEEP of each kept, and a profile whose folder is gone restored from its latest export."""

import os
import re
import shutil
import threading
import time

from .core import (CONFIG_FILE, DATA_DIR, HOME, ApiError, Backup, folder_missing, load_config, pretty,
                   profile, profiles, read_json, write_json)
from .sharing import link_shared, primary, share_items
from .launchers import launcher_path, write_launcher
from .health import list_profiles
from .transfer import export_profile, open_export, unpack_export

EVERY = {"day": 86400, "week": 7 * 86400}
KEEP = 3  # exports kept per profile: a problem noticed a few days late still has a good copy
# The app's own record of the last run, not a Claude Code file: no backup.
STATE_FILE = os.path.join(DATA_DIR, "auto-export.json")
ICLOUD = os.path.join(HOME, "Library", "Mobile Documents", "com~apple~CloudDocs")
FOLDER_NAME = "cc-profiles exports"
NAME = re.compile(r"cc-profile-(.+)-(\d{4}-\d{2}-\d{2})\.zip")
_run_lock = threading.Lock()
_now = {"running": False, "profile": ""}


def export_dir():
    """Where the exports go: iCloud Drive when there is one (a copy off this computer), else
    ~/.cc-profiles/exports. CC_PROFILES_EXPORT_DIR overrides it (tests)."""
    if os.environ.get("CC_PROFILES_EXPORT_DIR"):
        return os.path.expanduser(os.environ["CC_PROFILES_EXPORT_DIR"])
    if os.path.isdir(ICLOUD):
        return os.path.join(ICLOUD, FOLDER_NAME)
    return os.path.join(DATA_DIR, "exports")


def every():
    """"day", "week" or None (off: the default, since the exports hold the conversations)."""
    v = load_config().get("auto_export")
    return v if v in EVERY else None


def exports_of(pid):
    """[(day, path)] of the profile's exports in export_dir(), newest first."""
    folder = export_dir()
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found = []
    for n in names:
        m = NAME.fullmatch(n)
        if m and m.group(1) == pid:
            found.append((m.group(2), os.path.join(folder, n)))
    return sorted(found, reverse=True)


def prune(pid):
    """Remove the profile's exports beyond the newest KEEP. Only files named like ours are touched."""
    for _, path in exports_of(pid)[KEEP:]:
        try:
            os.remove(path)
        except OSError:
            pass


def run_exports():
    """Export every profile with its conversations, one zip each, written whole or not at all.
    A profile whose folder is gone is skipped, and its older exports are kept."""
    if not _run_lock.acquire(blocking=False):
        raise ApiError("An export is already running: wait for it to finish")
    try:
        _now["running"] = True
        folder = export_dir()
        results = {}
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError as e:
            results = {p["id"]: {"error": f"cannot create {pretty(folder)}: {e.strerror or e}"} for p in profiles()}
        day = time.strftime("%Y-%m-%d")
        for p in profiles() if not results else []:
            _now["profile"] = p["label"]
            if folder_missing(p):
                results[p["id"]] = {"error": "its folder is missing: not exported, the older exports are kept"}
                continue
            dst = os.path.join(folder, f"cc-profile-{p['id']}-{day}.zip")
            part = dst + ".part"
            tmp = None
            try:
                tmp, _ = export_profile(p["id"], True)
                shutil.copyfile(tmp, part)
                os.replace(part, dst)
                results[p["id"]] = {"file": dst, "size": os.path.getsize(dst)}
                prune(p["id"])
            except (ApiError, OSError) as e:
                results[p["id"]] = {"error": str(e) if isinstance(e, ApiError) else (e.strerror or str(e))}
            finally:
                for f in (tmp, part):
                    if f and os.path.exists(f):
                        os.remove(f)
        state = {"last": time.time(), "dir": folder, "results": results}
        write_json(STATE_FILE, state)
        return state
    finally:
        _now.update(running=False, profile="")
        _run_lock.release()


def due():
    e = every()
    return bool(e) and time.time() - ((read_json(STATE_FILE, {}) or {}).get("last") or 0) >= EVERY[e]


def auto_export_loop():
    """From a background thread: export when due, checking every 15 minutes (it runs only while
    cc-profiles does, so a day missed is made up at the next start). CC_PROFILES_EXPORT_TICK in tests."""
    tick = float(os.environ.get("CC_PROFILES_EXPORT_TICK") or 900)
    time.sleep(min(60, tick))
    while True:
        try:
            if due():
                run_exports()
        except Exception:  # never a reason to stop the server
            pass
        time.sleep(tick)


def export_status():
    state = read_json(STATE_FILE, {}) or {}
    e, last = every(), state.get("last")
    labels = {p["id"]: p["label"] for p in profiles()}
    results = [dict(r, id=pid, label=labels.get(pid, pid), file=os.path.basename(r["file"]) if r.get("file") else "")
               for pid, r in (state.get("results") or {}).items() if pid in labels]
    return {"every": e, "dir": pretty(export_dir()), "icloud": export_dir().startswith(ICLOUD), "keep": KEEP,
            "running": _now["running"], "profile": _now["profile"], "last": last,
            "next": (last or time.time()) + EVERY[e] if e and last else None, "results": results}


def op_auto_export(value):
    """Turn the automatic export on ("day" or "week") or off ("auto_export" in config.json)."""
    value = value if value in EVERY else None
    if every() == value:
        raise ApiError("Nothing to change")
    bk = Backup("auto-export", f"Automatic export: {'every ' + value if value else 'off'}")
    bk.copy(CONFIG_FILE, "config.json")
    cfg = load_config()
    if value:
        cfg["auto_export"] = value
    else:
        cfg.pop("auto_export", None)
    write_json(CONFIG_FILE, cfg)
    if not value:
        msg = "Automatic export off. The exports already made stay in " + pretty(export_dir()) + "."
    else:
        msg = (f"Every profile is exported every {value} to {pretty(export_dir())}, conversations included; "
               f"the last {KEEP} of each are kept. The first export starts within 15 minutes.")
    return {"message": msg, "backup": bk.close()}


def op_run_export():
    """Export now, in the background: the page follows it through export_status()."""
    if _now["running"]:
        raise ApiError("An export is already running: wait for it to finish")
    _now["running"] = True  # at once: the next status already says so

    def go():
        try:
            run_exports()
        except Exception:
            _now["running"] = False
    threading.Thread(target=go, daemon=True).start()
    return {"message": f"Exporting every profile to {pretty(export_dir())}…"}


def profiles_with_exports():
    """The profile list, with the latest export of each profile whose folder is gone."""
    out = list_profiles()
    for p in out:
        if p.get("missing"):
            ex = exports_of(p["id"])
            p["restore_from"] = {"day": ex[0][0], "file": pretty(ex[0][1])} if ex else None
    return out


def op_restore_export(pid):
    """Put back the folder of a profile that is gone, from its latest export (conversations
    included, never the login). Shared items are linked again to the source profile."""
    prof = profile(pid)
    if not folder_missing(prof):
        raise ApiError(f"The folder of {prof['label']} exists: nothing to restore. "
                       "To go back to an export, import it as a new profile.")
    found = exports_of(pid)
    if not found:
        raise ApiError(f"There is no export of {prof['label']} in {pretty(export_dir())}")
    day, path = found[0]
    z, man = open_export(path)
    with z:
        if man.get("id") != pid:
            raise ApiError(f"{pretty(path)} is the export of another profile ({man.get('id')})")
        share = [] if pid == primary()["id"] else share_items(man.get("shared") or [])
        new, config = prof["dir_abs"], prof["config_abs"]
        bk = Backup("restore-export", f"Restore {prof['label']} from the export of {day}")
        bk.created(new)  # journaled first: undoing removes the folder again
        os.makedirs(new)
        inside = os.path.dirname(config) == new
        if not inside and not os.path.exists(config):
            bk.copy(config, ".claude.json")
        # a .claude.json outside the folder (the default profile's) that still exists keeps its login
        unpack_export(z, new, {i: set() for i in share}, config if inside or not os.path.exists(config) else False)
        link_shared(new, share, bk)
    cmd = prof.get("command", "")
    if cmd and cmd != "claude" and not os.path.lexists(launcher_path(cmd)):
        write_launcher(cmd, prof["dir"], prof["label"], bk)
    bk.note(f"from {pretty(path)}" + (f", shared again: {', '.join(share)}" if share else ""))
    return {"message": f"{prof['label']} restored from the export of {day}. It is not logged in: "
                       f"run {cmd or 'claude'} and log in with /login.", "backup": bk.close()}
