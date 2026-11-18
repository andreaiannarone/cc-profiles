# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Edit and delete profiles."""

import glob
import os
import re
import shutil

from .core import (
    ApiError,
    Backup,
    CONFIG_FILE,
    active_session,
    fault_point,
    load_config,
    pretty,
    profile,
    profiles,
    write_json,
    write_text,
)
from .paths import history_lines, memory_files, memory_sharers, path_index, project_folders, project_sharers
from .projects import move_history, move_plan, move_project_into
from .sharing import item_users, primary
from .launchers import (
    alias_files,
    command_conflict,
    is_our_launcher,
    launcher_path,
    rewrite_alias,
    write_launcher,
)

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


# ---------------------------------------------------------------------------
# Rename a profile's folder
# ---------------------------------------------------------------------------
# ~/.claude-noa becomes ~/.claude-clienti. Claude Code writes the folder's absolute path into some
# of its files (settings.local.json, plugins/*.json, .claude.json), the launcher and config.json
# name it, and other profiles may link into it (shared items, projects, memories, file snapshots):
# all of them follow. The login does not: macOS keeps it in the keychain under a name made from the
# folder's path, so Claude Code asks for /login once. cc-profiles never copies a login.
FOLDER_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,40}")
REWRITE_GLOBS = ("*.json", "plugins/*.json")


def rename_target(prof, name):
    """The new folder for name ("clienti" or ".claude-clienti"), next to the current one."""
    name = (name or "").strip()
    if name.startswith(".claude-"):
        name = name[len(".claude-"):]
    if not FOLDER_NAME.fullmatch(name):
        raise ApiError("Folder name: lowercase letters, digits and dashes, e.g. clienti for ~/.claude-clienti")
    return os.path.join(os.path.dirname(prof["dir_abs"].rstrip("/")), ".claude-" + name)


def check_rename_folder(pid, name):
    prof = profile(pid)
    if pid == primary()["id"]:
        raise ApiError(f"{prof['label']} is the source profile: its folder is where Claude Code looks by default, it cannot change")
    old = prof["dir_abs"].rstrip("/")
    if not os.path.isdir(old):
        raise ApiError(f"{pretty(old)} does not exist any more")
    if os.path.islink(old):
        raise ApiError(f"{pretty(old)} is a link: rename the folder it points to instead")
    new = rename_target(prof, name)
    if new == old:
        raise ApiError("Nothing to change")
    if os.path.lexists(new):
        raise ApiError(f"{pretty(new)} already exists: pick another name")
    if any(os.path.realpath(p["dir_abs"]) == os.path.realpath(new) for p in profiles()):
        raise ApiError(f"{pretty(new)} is the folder of another profile")
    if active_session(prof):
        raise ApiError(f"A Claude Code session is open in {prof['label']}: close it first, or it would keep writing to {pretty(old)}")
    return prof, old, new


def path_pattern(old):
    """The folder's path as written in files, absolute or with ~, followed by / or the end of a string."""
    forms = [old] + ([("~" + old[len(os.path.expanduser("~")):])] if old.startswith(os.path.expanduser("~") + "/") else [])
    return re.compile("(" + "|".join(re.escape(f) for f in forms) + r')(?=[/"\'\s]|$)')


def files_naming(folder, pattern):
    """The profile's own files (not links: a shared file belongs to another profile) that name the folder."""
    out = []
    for g in REWRITE_GLOBS:
        for f in sorted(glob.glob(os.path.join(folder, g))):
            if os.path.islink(f) or os.path.islink(os.path.dirname(f)) or not os.path.isfile(f):
                continue
            try:
                with open(f, encoding="utf-8") as fh:
                    if pattern.search(fh.read()):
                        out.append(f)
            except (OSError, UnicodeDecodeError):
                pass
    return out


def links_into(old, others):
    """Links in the other profiles that lead into old: (link, target inside old, profile label)."""
    out = []
    for p in others:
        d = p["dir_abs"]
        cands = [os.path.join(d, n) for n in os.listdir(d)] if os.path.isdir(d) else []
        for sub in ("projects/*", "projects/*/memory", "file-history/*"):
            cands += glob.glob(os.path.join(d, sub))
        for c in cands:
            if not os.path.islink(c):
                continue
            t = os.path.normpath(os.path.join(os.path.dirname(c), os.readlink(c)))
            if t == old or t.startswith(old + "/"):
                out.append((c, t, p["label"]))
    return out


def rename_folder_plan(pid, name):
    prof, old, new = check_rename_folder(pid, name)
    pattern = path_pattern(old)
    others = [p for p in profiles() if p["id"] != pid]
    links = links_into(old, others)
    return {"profile": prof["label"], "from": pretty(old), "to": pretty(new), "command": prof.get("command", ""),
            "files": [os.path.relpath(f, old) for f in files_naming(old, pattern)],
            "links": sorted({label for _, _, label in links}), "link_count": len(links)}


def op_rename_folder(pid, name):
    prof, old, new = check_rename_folder(pid, name)
    pattern = path_pattern(old)
    others = [p for p in profiles() if p["id"] != pid]
    links = links_into(old, others)
    rel_files = [os.path.relpath(f, old) for f in files_naming(old, pattern)]
    bk = Backup("rename-folder", f"Folder of {prof['label']}: {pretty(old)} → {pretty(new)}")
    bk.copy(CONFIG_FILE, "config.json")
    shutil.move(old, new)
    bk.moved(old, new)
    fault_point("rename-folder-after-move")
    home = os.path.expanduser("~")
    new_tilde = "~" + new[len(home):] if new.startswith(home + "/") else new
    for rel in rel_files:
        f = os.path.join(new, rel)
        bk.copy(f, rel.replace("/", "-"))
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
        write_text(f, pattern.sub(lambda m: new_tilde if m.group(1).startswith("~") else new, text))
    for link, target, _ in links:
        bk.stash(link, "link-" + os.path.basename(link))
        os.symlink(os.path.relpath(new + target[len(old):], os.path.dirname(link)), link)
        bk.created(link)
    cfg = load_config()
    entry = next(p for p in cfg["profiles"] if p["id"] == pid)
    entry["dir"] = new_tilde
    if os.path.expanduser(entry.get("config", "")) == old + "/.claude.json":
        entry["config"] = new_tilde + "/.claude.json"
    write_json(CONFIG_FILE, cfg)
    cmd = entry.get("command", "")
    if cmd and is_our_launcher(launcher_path(cmd)):
        write_launcher(cmd, new_tilde, entry["label"], bk)
    elif cmd:
        rewrite_alias(cmd, f"alias {cmd}='CLAUDE_CONFIG_DIR={new_tilde} claude'", bk)
    bk.note(f"{len(rel_files)} file{'s' if len(rel_files) != 1 else ''} rewritten, {len(links)} link{'s' if len(links) != 1 else ''} of other profiles moved")
    return {"message": f"{prof['label']} now lives in {pretty(new)}. Run {cmd or 'Claude Code'} and log in again with /login: "
                       f"the login is kept under the folder's old name.", "backup": bk.close()}


def check_delete(pid, merge_into):
    prof = profile(pid)
    if pid == primary()["id"]:
        raise ApiError(f"{prof['label']} is the source profile: the others share from it, so it cannot be deleted")
    dst = profile(merge_into) if merge_into else None
    if dst and dst["id"] == pid:
        raise ApiError("A profile cannot be merged into itself")
    used = item_users(prof)
    if used:
        raise ApiError("; ".join(f"{u} uses {', '.join(items)}" for u, items in sorted(used.items()))
                       + f" of {prof['label']} (shared): separate them in Profiles → Sharing first")
    names = [name for name, _, _ in project_folders(prof, conversations=False)]
    users = {u["label"] for name in names for u in project_sharers(prof, name)}
    if users:
        raise ApiError(f"{' and '.join(sorted(users))} {'uses' if len(users) == 1 else 'use'} projects of "
                       f"{prof['label']} (shared project): stop sharing them in the Projects tab first")
    users = {u["label"] for name in names for u in memory_sharers(prof, name)}
    if users:
        raise ApiError(f"{' and '.join(sorted(users))} {'uses' if len(users) == 1 else 'use'} the memory of projects "
                       f"in {prof['label']} (shared memory): separate it in the Memories tab first")
    return prof, dst


def mergeable_projects(prof, fresh=False):
    """Project folders a merge moves: those with conversations or memories.
    The merge itself passes fresh=True: a write never trusts the caches."""
    out = []
    for d in sorted(glob.glob(os.path.join(prof["dir_abs"], "projects", "*", ""))):
        if os.path.islink(d.rstrip("/")):
            continue  # another profile's project (shared): it stays there
        if glob.glob(os.path.join(d, "*.jsonl")) or memory_files(d, fresh=fresh):
            out.append(os.path.basename(d.rstrip("/")))
    return out


def delete_plan(pid, merge_into=None):
    """What deleting a profile would do, without doing it: the same rules as op_delete_profile."""
    prof, dst = check_delete(pid, merge_into)
    items = []
    out = {"items": items, "projects": 0, "conversations": 0, "memories": 0, "prompts": 0, "settings": 0,
           "active": bool(active_session(prof)), "folder": pretty(prof["dir_abs"]),
           "config": pretty(CONFIG_FILE), "into": dst["label"] if dst else None}
    if dst:
        idx = path_index()
        for name in mergeable_projects(prof):
            plan = move_plan(name, pid, dst["id"], idx)
            where = os.path.basename(idx[name]) if idx.get(name) else name
            for i in plan["items"]:
                items.append(dict(i, item=f"{where}/{i['item']}"))
                out["conversations"] += i["item"].endswith(".jsonl") and "/" not in i["item"]
                out["memories"] += i["item"].startswith("memory/") and i["item"] != "memory/MEMORY.md"
            out["projects"] += 1
            out["settings"] += plan["settings"]
        out["prompts"] = len(history_lines(prof))  # the whole history goes, without duplicates
        if out["prompts"]:
            h = os.path.join(prof["dir_abs"], "history.jsonl")
            items.append({"action": "merge", "item": "history.jsonl", "from": pretty(h),
                          "to": pretty(os.path.join(dst["dir_abs"], "history.jsonl"))})
    cmd = prof.get("command", "")
    if cmd and is_our_launcher(launcher_path(cmd)):
        items.append({"action": "stash", "item": "launcher", "from": pretty(launcher_path(cmd)), "to": "backup"})
    for rc in alias_files(cmd) if cmd else []:
        items.append({"action": "edit", "item": "shell alias", "from": pretty(rc), "to": f"alias {cmd} removed"})
    items.append({"action": "edit", "item": "config entry", "from": pretty(CONFIG_FILE), "to": f"{prof['label']} removed"})
    items.append({"action": "stash", "item": "profile folder", "from": pretty(prof["dir_abs"]), "to": "backup"})
    return out


def op_delete_profile(pid, merge_into=None, force=False):
    prof, dst = check_delete(pid, merge_into)
    if active_session(prof) and not force:
        raise ApiError(f"A session is open in {prof['label']}: close it before deleting the profile", 409)
    bk = Backup(f"delete-profile-{pid}", f"Delete profile {prof['label']} ({pretty(prof['dir_abs'])})")
    bk.copy(CONFIG_FILE, "config.json")
    moved = conv = hist = 0
    if dst:
        idx = path_index()
        for name in mergeable_projects(prof, fresh=True):
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
