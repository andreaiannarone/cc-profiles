# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Edit and delete profiles."""

import glob
import os

from .core import (
    ApiError,
    Backup,
    CONFIG_FILE,
    active_session,
    load_config,
    pretty,
    profile,
    write_json,
)
from .paths import memory_files, path_index
from .projects import move_history, move_project_into
from .sharing import primary
from .launchers import command_conflict, is_our_launcher, launcher_path, rewrite_alias, write_launcher

# ---------------------------------------------------------------------------
# Edit and delete profiles
# ---------------------------------------------------------------------------
def op_update_profile(pid, label, command):
    cfg = load_config()
    entry = next((p for p in cfg["profiles"] if p["id"] == pid), None)
    if not entry:
        raise ApiError(f"Unknown profile: {pid}")
    is_primary = cfg["profiles"][0]["id"] == pid
    label = (label or "").strip()
    command = (command or "").strip() or entry.get("command", "")
    others = [p for p in cfg["profiles"] if p["id"] != pid]
    if not label:
        raise ApiError("The name cannot be empty")
    if any(p["label"].lower() == label.lower() for p in others):
        raise ApiError("A profile with this name already exists")
    old_cmd = entry.get("command", "")
    if command != old_cmd:
        if is_primary:
            raise ApiError("The source profile's command is Claude Code itself and cannot change")
        err = command_conflict(command, others)
        if err:
            raise ApiError(err)
    bk = Backup("edit-profile", f"Edit profile {entry['label']}")
    bk.copy(CONFIG_FILE, "config.json")
    changes = []
    label_changed = label != entry["label"]
    if label_changed:
        changes.append(f"name {entry['label']} → {label}")
        entry["label"] = label
    if command != old_cmd:
        old_launcher = launcher_path(old_cmd)
        if is_our_launcher(old_launcher):
            bk.stash(old_launcher, f"launcher-{old_cmd}")
            write_launcher(command, entry["dir"], label, bk)
        elif not rewrite_alias(old_cmd, f"alias {command}='CLAUDE_CONFIG_DIR={entry['dir']} claude'", bk):
            write_launcher(command, entry["dir"], label, bk)
        changes.append(f"command {old_cmd} → {command}")
        entry["command"] = command
    elif label_changed and is_our_launcher(launcher_path(old_cmd)):
        write_launcher(old_cmd, entry["dir"], label, bk)  # keep the label in the script comment current
    if not changes:
        raise ApiError("Nothing to change")
    write_json(CONFIG_FILE, cfg)
    for c in changes:
        bk.note(c)
    msg = "Profile updated: " + ", ".join(changes) + "."
    if command != old_cmd:
        msg += f" Open a new terminal to use {command}."
    return {"message": msg, "backup": bk.close()}


def op_delete_profile(pid, merge_into=None, force=False):
    prof = profile(pid)
    if pid == primary()["id"]:
        raise ApiError(f"{prof['label']} is the source profile: the others share from it, so it cannot be deleted")
    if active_session(prof) and not force:
        raise ApiError(f"A session is open in {prof['label']}: close it before deleting the profile", 409)
    dst = profile(merge_into) if merge_into else None
    if dst and dst["id"] == pid:
        raise ApiError("A profile cannot be merged into itself")
    bk = Backup(f"delete-profile-{pid}", f"Delete profile {prof['label']} ({pretty(prof['dir_abs'])})")
    bk.copy(CONFIG_FILE, "config.json")
    moved = conv = hist = 0
    if dst:
        idx = path_index()
        for d in sorted(glob.glob(os.path.join(prof["dir_abs"], "projects", "*", ""))):
            name = os.path.basename(d.rstrip("/"))
            if not glob.glob(os.path.join(d, "*.jsonl")) and not memory_files(d, fresh=True):
                continue
            c, _, h, _ = move_project_into(name, prof, dst, bk, idx.get(name))
            moved, conv, hist = moved + 1, conv + c, hist + h
        hist += move_history(prof, dst, None, bk)  # prompts of projects without a folder
        bk.note(f"merged into {dst['label']}: {moved} projects, {conv} conversations, {hist} prompts")
    cfg = load_config()
    cfg["profiles"] = [p for p in cfg["profiles"] if p["id"] != pid]
    write_json(CONFIG_FILE, cfg)
    cmd = prof.get("command", "")
    removed = []
    if cmd and is_our_launcher(launcher_path(cmd)):
        bk.stash(launcher_path(cmd), f"launcher-{cmd}")
        removed.append(f"launcher {pretty(launcher_path(cmd))}")
    if cmd and rewrite_alias(cmd, None, bk):
        removed.append("shell alias")
    bk.stash(prof["dir_abs"], f"profile-{pid}")
    bk.note(f"folder {pretty(prof['dir_abs'])} kept in the backup" + (f", removed {', '.join(removed)}" if removed else ""))
    msg = f"Profile {prof['label']} deleted"
    msg += f": {moved} projects merged into {dst['label']}." if dst else "."
    msg += " The folder is in the backup and can be restored."
    return {"message": msg, "backup": bk.close()}
