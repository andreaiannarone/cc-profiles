# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Sharing between profiles."""

import os
import shutil

from .core import ApiError, Backup, profile, profiles, write_text

# ---------------------------------------------------------------------------
# Sharing between profiles
# ---------------------------------------------------------------------------
SHARE_ITEMS = [
    ("skills", "dir", "Local skills"),
    ("plugins", "dir", "Installed plugins (files)"),
    ("agents", "dir", "Custom subagents"),
    ("commands", "dir", "Custom slash commands"),
    ("CLAUDE.md", "file", "Global instructions (CLAUDE.md)"),
    ("settings.json", "file", "Settings: status line, enabled plugins, permissions, hooks"),
]


def primary():
    return profiles()[0]


def share_state(prof, item, kind):
    t = os.path.join(prof["dir_abs"], item)
    s = os.path.join(primary()["dir_abs"], item)
    shared = os.path.islink(t) and os.path.realpath(t) == os.path.realpath(s)
    own = os.path.lexists(t) and not shared
    only_own = []
    if own and kind == "dir" and os.path.isdir(t):
        theirs = set(os.listdir(s)) if os.path.isdir(s) else set()
        only_own = sorted(n for n in os.listdir(t) if n not in theirs and not n.startswith("."))
    return {"shared": shared, "own": own, "only_own": only_own, "source_exists": os.path.lexists(s)}


def list_sharing():
    src = primary()
    out = []
    for p in profiles()[1:]:
        items = []
        for item, kind, desc in SHARE_ITEMS:
            st = share_state(p, item, kind)
            st.update({"item": item, "kind": kind, "desc": desc})
            items.append(st)
        out.append({"id": p["id"], "label": p["label"], "source": src["label"], "items": items})
    return out


def op_share(pid, item, on):
    kinds = {i: k for i, k, _ in SHARE_ITEMS}
    if item not in kinds:
        raise ApiError("This item cannot be shared")
    prof, src = profile(pid), primary()
    if prof["id"] == src["id"]:
        raise ApiError(f"{src['label']} is the source profile: the others share from it")
    kind = kinds[item]
    t = os.path.join(prof["dir_abs"], item)
    s = os.path.join(src["dir_abs"], item)
    st = share_state(prof, item, kind)
    bk = Backup("share", f"{item} of {prof['label']}: {'shared' if on else 'separated'}")
    if on:
        if st["shared"]:
            raise ApiError("Already shared")
        if not os.path.lexists(s):  # the source does not exist yet: create it empty
            if kind == "dir":
                bk.mkdir(s)
            else:
                bk.copy(s)
                write_text(s, "{}\n" if item.endswith(".json") else "")
        bk.stash(t, f"{item}-{prof['id']}")
        os.symlink(os.path.relpath(s, os.path.dirname(t)), t)
        bk.created(t)
        if st["own"]:
            bk.note(f"the own copy of {prof['label']} is kept in the backup")
        msg = f"{item}: {prof['label']} now uses the one from {src['label']}."
    else:
        if not st["shared"]:
            raise ApiError("Not shared")
        bk.stash(t, f"{item}-link")  # the link itself: restoring puts it back
        if kind == "dir":
            shutil.copytree(s, t, symlinks=True)
        else:
            shutil.copy2(s, t)
        bk.created(t)
        msg = f"{item}: {prof['label']} now has its own independent copy."
    return {"message": msg, "backup": bk.close()}
