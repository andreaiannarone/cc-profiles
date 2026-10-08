# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: New profile."""

import glob
import os
import re
import shutil

from .core import (
    ApiError,
    Backup,
    CONFIG_FILE,
    HOME,
    LAUNCHER_DIR,
    fault_point,
    load_config,
    pretty,
    profile,
    profiles,
    read_json,
    san,
    write_json,
    write_text,
)
from .sharing import link_shared, primary, share_items
from .command import command_state, command_wanted, write_command
from .launchers import command_conflict, launcher_dir_in_path, write_launcher
from .github import new_profile_folder

# ---------------------------------------------------------------------------
# New profile
# ---------------------------------------------------------------------------
RUNTIME = {"daemon", "ide", "sessions", "session-env", "shell-snapshots", "cache",
           "telemetry", "statsig", ".credentials.json"}
PROJECT_DATA = {"projects", "history.jsonl", "file-history", "paste-cache", "backups",
                "jobs", "downloads", "todos"}


def check_new_profile(label, pid):
    """Validate the name and id of a profile about to be created (or imported).
    Returns (label, id, folder, command)."""
    label, pid = (label or "").strip(), (pid or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", pid):
        raise ApiError("Invalid id: lowercase letters, digits and dashes only")
    profs = profiles()
    if not label or any(p["label"].lower() == label.lower() or p["id"] == pid for p in profs):
        raise ApiError("A profile with this name or id already exists")
    new = os.path.join(HOME, f".claude-{pid}")
    if os.path.lexists(new):
        raise ApiError(f"The folder {pretty(new)} already exists")
    command = f"claude-{pid}"
    err = command_conflict(command, profs)
    if err:
        raise ApiError(err)
    return label, pid, new, command


def add_profile_to_config(label, pid, command):
    cfg = load_config()
    cfg["profiles"].append({"id": pid, "label": label, "dir": f"~/.claude-{pid}",
                            "config": f"~/.claude-{pid}/.claude.json", "command": command})
    write_json(CONFIG_FILE, cfg)


def op_create_profile(label, pid, base, include_projects, share):
    label, pid, new, command = check_new_profile(label, pid)
    share = share_items(share)
    bk = Backup("new-profile", f"New profile {label} ({pretty(new)})")
    bk.copy(CONFIG_FILE, "config.json")
    src = profile(base) if base else None
    if src:
        # Login credentials are never copied: each profile logs in on its own,
        # a copied token can be invalidated when the original refreshes it.
        skip = RUNTIME | set(share) | (set() if include_projects else PROJECT_DATA)
        bk.created(new)  # journaled first: a failure while copying leaves a folder that Restore removes
        shutil.copytree(src["dir_abs"], new, symlinks=True,
                        ignore=lambda d, names: [n for n in names if n in skip] if d == src["dir_abs"] else [])
        fault_point("create-profile-after-copy")
        if not include_projects:  # the general (home) memory comes along anyway
            hm = os.path.join(src["dir_abs"], "projects", san(HOME), "memory")
            if os.path.isdir(hm):
                shutil.copytree(hm, os.path.join(new, "projects", san(HOME), "memory"))
        cfg = read_json(src["config_abs"])
        if cfg is not None:
            for k in ("oauthAccount", "userID"):  # account data belongs to the login
                cfg.pop(k, None)
            write_json(os.path.join(new, ".claude.json"), cfg)
        if "plugins" not in share and not os.path.islink(os.path.join(new, "plugins")):
            for f in glob.glob(os.path.join(new, "plugins", "*.json")):  # absolute paths point to the copy
                write_text(f, open(f).read().replace(src["dir_abs"] + "/plugins/", new + "/plugins/"))
    else:
        bk.created(new)
        os.makedirs(new)
        if "settings.json" not in share:  # a shared settings.json is linked below instead
            settings = {}
            sl = (read_json(os.path.join(primary()["dir_abs"], "settings.json"), {}) or {}).get("statusLine")
            if sl:
                settings["statusLine"] = sl
            write_json(os.path.join(new, "settings.json"), settings)
    link_shared(new, share, bk)
    # every new profile gets /cc-profiles, unless it was turned off (a cc-profiles.md written by someone else is left alone)
    if command_wanted() and command_state(new) in ("missing", "outdated"):
        write_command(new, bk, pid)
    write_launcher(command, f"~/.claude-{pid}", label, bk)
    gh = new_profile_folder(new, pid, bk)
    add_profile_to_config(label, pid, command)
    bk.note(f"base: {src['label'] if src else 'empty'}, projects: {'yes' if include_projects else 'no'}, "
            f"shared: {', '.join(share) or 'nothing'}")
    msg = f"Profile {label} created. Run {command} and log in with /login." + (f" {gh[0].upper()}{gh[1:]}." if gh else "")
    if not launcher_dir_in_path():
        msg += f" Note: {pretty(LAUNCHER_DIR)} is not in your PATH yet."
    return {"message": msg, "backup": bk.close()}
