# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Sharing between profiles."""

import filecmp
import os
import shutil

from .core import ApiError, Backup, active_session, pretty, profile, profiles, write_text
from .paths import memory_sharers, path_index, project_folders, project_holder, project_sharers
from .projects import share_project_into

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


def share_items(share):
    """The valid items of a list of item names sent by the client, in SHARE_ITEMS order."""
    share = set(share or []) if isinstance(share, list) else set()
    return [i for i, _, _ in SHARE_ITEMS if i in share]


def link_shared(new, share, bk):
    """Link the items of a profile being created (folder new, already journaled with
    bk.created) to the source profile. Items the source does not have yet are created
    there, empty, as op_share does, so every link works."""
    kinds = {i: k for i, k, _ in SHARE_ITEMS}
    for item in share:
        s = os.path.join(primary()["dir_abs"], item)
        if not os.path.lexists(s):
            if kinds[item] == "dir":
                bk.mkdir(s)
            else:
                bk.copy(s)
                write_text(s, "{}\n" if item.endswith(".json") else "")
        os.symlink(os.path.relpath(s, new), os.path.join(new, item))


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


def check_share(pid, item):
    kinds = {i: k for i, k, _ in SHARE_ITEMS}
    if item not in kinds:
        raise ApiError("This item cannot be shared")
    prof, src = profile(pid), primary()
    if prof["id"] == src["id"]:
        raise ApiError(f"{src['label']} is the source profile: the others share from it")
    return prof, src, kinds[item]


def share_plan(pid, item, on):
    """What sharing (on) or separating an item would do, without doing it: the same rules as op_share."""
    prof, src, kind = check_share(pid, item)
    t = os.path.join(prof["dir_abs"], item)
    s = os.path.join(src["dir_abs"], item)
    st = share_state(prof, item, kind)
    items = []
    if on:
        if st["shared"]:
            raise ApiError("Already shared")
        if not os.path.lexists(s):
            items.append({"action": "create", "item": item, "from": "", "to": pretty(s)})
        if st["own"]:
            items.append({"action": "stash", "item": item, "from": pretty(t), "to": "backup"})
            for n in st["only_own"]:
                items.append({"action": "only-here", "item": f"{item}/{n}", "from": pretty(os.path.join(t, n)),
                              "to": "backup"})
        items.append({"action": "link", "item": item, "from": pretty(t), "to": pretty(s)})
    else:
        if not st["shared"]:
            raise ApiError("Not shared")
        items.append({"action": "stash", "item": f"{item} (the link)", "from": pretty(t), "to": "backup"})
        n = sum(len(fs) for _, _, fs in os.walk(s)) if kind == "dir" else 1
        items.append({"action": "copy", "item": item, "from": pretty(s), "to": pretty(t), "files": n})
    return {"items": items, "source": src["label"], "profile": prof["label"], "only_own": st["only_own"] if on else []}


def op_share(pid, item, on):
    prof, src, kind = check_share(pid, item)
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


# ---------------------------------------------------------------------------
# Share everything: a profile that differs from the source profile only by its account
# ---------------------------------------------------------------------------
# Every item of SHARE_ITEMS but settings.json (it holds the profile's GitHub account and commit
# identity, see github.py), and every project of the two profiles (shared project). What the
# profile has only for itself joins the source's first: skills, agents and commands it alone has
# move there, its conversations and memories join the project's; the rest (a clash, its own
# CLAUDE.md or plugins) goes to the backup. One backup for all of it.
EVERYTHING_ITEMS = [(i, k, d) for i, k, d in SHARE_ITEMS if i != "settings.json"]
MERGED_ITEMS = ("skills", "agents", "commands")


def same_tree(a, b):
    """Whether a file or folder has the same content as another (then nothing is lost replacing it)."""
    if os.path.isdir(a) and os.path.isdir(b) and not os.path.islink(a):
        cmp = filecmp.dircmp(a, b)
        if cmp.left_only or cmp.right_only or cmp.funny_files:
            return False
        _, mismatch, errors = filecmp.cmpfiles(a, b, cmp.common_files, shallow=False)
        return not mismatch and not errors and all(same_tree(os.path.join(a, d), os.path.join(b, d)) for d in cmp.common_dirs)
    if os.path.isfile(a) and os.path.isfile(b):
        return filecmp.cmp(a, b, shallow=False)
    return False


def everything_plan(pid):
    """What Share everything would do for the profile, without doing it."""
    prof, src = profile(pid), primary()
    if prof["id"] == src["id"]:
        raise ApiError(f"{src['label']} is the source profile: share everything from another profile")
    items = []
    for item, kind, desc in EVERYTHING_ITEMS:
        st = share_state(prof, item, kind)
        if st["shared"]:
            items.append({"item": item, "desc": desc, "action": "already"})
            continue
        row = {"item": item, "desc": desc, "action": "share", "join": [], "backup": []}
        t = os.path.join(prof["dir_abs"], item)
        if st["own"] and os.path.islink(t):  # a link to a folder elsewhere: never move files out of it
            row["backup"] = [item]
        elif st["own"] and kind == "dir" and item in MERGED_ITEMS:
            row["join"] = st["only_own"]
            theirs = os.path.join(src["dir_abs"], item)
            row["backup"] = sorted(n for n in os.listdir(t) if not n.startswith(".") and n not in st["only_own"]
                                   and os.path.lexists(os.path.join(theirs, n))
                                   and not same_tree(os.path.join(t, n), os.path.join(theirs, n)))
        elif st["own"]:
            s_path = os.path.join(src["dir_abs"], item)
            row["backup"] = [] if same_tree(t, s_path) or (kind == "dir" and not os.listdir(t)) else [item]
        items.append(row)
    projects = []
    idx = path_index()
    names = sorted({n for n, _, _ in project_folders(src, conversations=False)}
                   | {n for n, _, _ in project_folders(prof, conversations=False)})
    for name in names:
        row = {"name": name, "pretty": pretty(idx.get(name)) or name}
        mine = os.path.join(prof["dir_abs"], "projects", name)
        theirs = os.path.join(src["dir_abs"], "projects", name)
        holder = project_holder(src, name) or src
        if os.path.islink(mine):
            same = os.path.realpath(mine) == os.path.realpath(theirs)
            row.update(action="already" if same else "skip",
                       reason="" if same else "it uses this project from another profile")
        elif project_sharers(prof, name) or memory_sharers(prof, name):
            row.update(action="skip", reason="other profiles use it, or its memory, from here")
        elif holder["id"] == prof["id"]:
            row.update(action="already")
        elif os.path.lexists(mine) and not os.path.isdir(mine):
            row.update(action="skip", reason="not a folder")
        else:
            convs = [e for e in os.listdir(mine) if e.endswith(".jsonl")] if os.path.isdir(mine) else []
            row.update(action="share", holder=holder["label"], joins=len(convs), new=not os.path.lexists(theirs)
                       and holder["id"] == src["id"])
        projects.append(row)
    return {"profile": prof["label"], "source": src["label"], "items": items, "projects": projects,
            "active": bool(active_session(prof) or active_session(src))}


def op_share_everything(pid):
    plan = everything_plan(pid)
    prof, src = profile(pid), primary()
    todo_items = [r for r in plan["items"] if r["action"] == "share"]
    todo_projects = [r for r in plan["projects"] if r["action"] == "share"]
    if not todo_items and not todo_projects:
        raise ApiError(f"{prof['label']} already shares everything it can with {src['label']}")
    bk = Backup("share-everything", f"{prof['label']} shares everything with {src['label']}")
    kinds = {i: k for i, k, _ in SHARE_ITEMS}
    for r in todo_items:
        item, kind = r["item"], kinds[r["item"]]
        t, s = os.path.join(prof["dir_abs"], item), os.path.join(src["dir_abs"], item)
        if not os.path.lexists(s):
            if kind == "dir":
                bk.mkdir(s)
            else:
                bk.copy(s)
                write_text(s, "")
        for n in r["join"]:  # what only this profile has moves to the source
            a, b = os.path.join(t, n), os.path.join(s, n)
            shutil.move(a, b)
            bk.moved(a, b)
        bk.stash(t, f"{item}-{prof['id']}")
        os.symlink(os.path.relpath(s, os.path.dirname(t)), t)
        bk.created(t)
        if r["join"]:
            bk.note(f"{item}: {len(r['join'])} of {prof['label']} joined {src['label']}'s")
    joined = 0
    for r in todo_projects:
        name = r["name"]
        holder = project_holder(src, name) or src
        hd = os.path.join(holder["dir_abs"], "projects", name)
        if not os.path.lexists(hd):  # only this profile has it: the source holds it from now on
            bk.mkdir(hd)
        joined += share_project_into(prof, holder, name, bk)
    parts = []
    if todo_items:
        parts.append(", ".join(r["item"] for r in todo_items))
    if todo_projects:
        parts.append(f"{len(todo_projects)} project{'s' if len(todo_projects) != 1 else ''}")
    msg = f"{prof['label']} now shares {' and '.join(parts)} with {src['label']}."
    if joined:
        msg += f" {joined} of its conversations joined them."
    msg += (" settings.json stays its own (GitHub account and commit identity). Projects opened later in one"
            " profile only: run Share everything again.")
    return {"message": msg, "backup": bk.close()}
