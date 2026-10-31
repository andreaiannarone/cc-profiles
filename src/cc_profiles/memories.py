# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Memories."""

import os
import re
import shutil

from .core import (
    ApiError,
    Backup,
    cached_read,
    parse_memory,
    pid_label,
    pretty,
    profile,
    profiles,
    project_dir,
    write_text,
)
from .paths import memory_files, memory_holder, memory_sharers, path_index, project_folders
from .projects import merge_memory

def index_lines(md):
    p = os.path.join(md, "MEMORY.md")
    return open(p).read().splitlines() if os.path.exists(p) else []


def memory_projects(pid):
    prof = profile(pid)
    idx = path_index()
    out = []
    profs = profiles()
    for name, d, convs in project_folders(prof):
        path = idx.get(name)
        holder = memory_holder(prof, name, profs)
        out.append({"name": name, "pretty": pretty(path) if path else name,
                    "count": len(memory_files(d)), "conv": len(convs),
                    "shared": bool(holder or memory_sharers(prof, name, profs))})
    out.sort(key=lambda r: (r["pretty"] != "~", r["pretty"].lower()))
    return out


def index_check(d):
    """Memory files of a project folder that MEMORY.md does not list, and files it
    lists that do not exist. Reads only the index, not the memories."""
    def read(path):
        try:
            with open(path) as f:
                return f.read()
        except OSError:
            return ""
    index = cached_read("index", os.path.join(d, "memory", "MEMORY.md"), read)
    files = memory_files(d)
    unindexed = [f for f in files if f"({f})" not in index]
    missing = sorted(set(re.findall(r"\]\(([^)]+\.md)\)", index)) - set(files))
    return unindexed, missing


def memory_list(pid, name):
    d = project_dir(profile(pid), name)
    md = os.path.join(d, "memory")
    unindexed, missing = index_check(d)
    items = []
    for f in memory_files(d):
        text = open(os.path.join(md, f)).read()
        meta = parse_memory(text)
        items.append({"file": f, "name": meta.get("name") or f[:-3],
                      "description": meta.get("description", ""),
                      "type": meta.get("type", ""), "indexed": f not in unindexed})
    return {"items": items, "missing": missing, "sharing": memory_sharing(profile(pid), name)}


# ---------------------------------------------------------------------------
# Shared memory: a profile uses another profile's memory of the same project
# ---------------------------------------------------------------------------
def memory_sharing(prof, name):
    """Who this project's memory is shared with, or where it comes from; and, for each other
    profile, whether it could use it: its own memories there would join this one."""
    profs = profiles()
    holder = memory_holder(prof, name, profs)
    if holder:
        return {"from": holder["id"], "with": [], "others": []}
    users = {p["id"] for p in memory_sharers(prof, name, profs)}
    others = []
    for p in profs:
        if p["id"] == prof["id"] or p["id"] in users:
            continue
        elsewhere = memory_holder(p, name, profs) or os.path.islink(os.path.join(p["dir_abs"], "projects", name, "memory"))
        others.append({"id": p["id"], "own": len(memory_files(os.path.join(p["dir_abs"], "projects", name))),
                       "elsewhere": bool(elsewhere)})
    return {"from": None, "with": sorted(users), "others": others}


def check_memory_share(pid, name, from_pid):
    """(profile that will use the memory, holder, its memory/, the profile's memory/)."""
    prof, holder = profile(pid), profile(from_pid)
    if prof["id"] == holder["id"]:
        raise ApiError("Pick another profile to share the memory with")
    project_dir(holder, name)
    if memory_holder(holder, name):
        raise ApiError(f"{holder['label']} uses the memory of another profile: share it from there")
    md = os.path.join(holder["dir_abs"], "projects", name, "memory")
    mine = os.path.join(prof["dir_abs"], "projects", name, "memory")
    if os.path.islink(mine):
        if os.path.realpath(mine) == os.path.realpath(md):
            raise ApiError(f"{prof['label']} already uses this memory")
        raise ApiError(f"{prof['label']} uses the memory of another profile for this project: separate it there first")
    return prof, holder, md, mine


def memory_share_plan(pid, name, from_pid):
    """What sharing would do to the profile's own memories of the project, without doing it."""
    prof, holder, md, mine = check_memory_share(pid, name, from_pid)
    own = memory_files(os.path.dirname(mine), fresh=True)
    theirs = set(memory_files(os.path.dirname(md), fresh=True))
    return {"profile": prof["label"], "from": holder["label"], "join": [f for f in own if f not in theirs],
            "conflicts": [f for f in own if f in theirs]}


def op_memory_share(pid, name, from_pid=None, on=True):
    """pid uses (on) the memory of the project in from_pid, or gets its own copy again (off)."""
    if not on:
        prof = profile(pid)
        mine = os.path.join(project_dir(prof, name), "memory")
        holder = memory_holder(prof, name)
        if not holder:
            raise ApiError(f"The memory of this project in {prof['label']} is not shared")
        bk = Backup("memory-share", f"Memory of {pretty(path_index().get(name)) or name}: {prof['label']} separated")
        real = os.path.realpath(mine)
        bk.stash(mine, "memory-link")  # the link: restoring puts it back
        shutil.copytree(real, mine, symlinks=True)
        bk.created(mine)
        return {"message": f"{prof['label']} now has its own copy of this memory: changes no longer reach "
                           f"{holder['label']}.", "backup": bk.close()}
    prof, holder, md, mine = check_memory_share(pid, name, from_pid)
    where = pretty(path_index().get(name)) or name
    bk = Backup("memory-share", f"Memory of {where}: {prof['label']} uses {holder['label']}'s")
    joined = clashes = 0
    if os.path.isdir(mine):  # its own memories join the shared ones; a clash keeps the shared one
        theirs = set(memory_files(os.path.dirname(md), fresh=True))
        own = memory_files(os.path.dirname(mine), fresh=True)
        joined, clashes = sum(f not in theirs for f in own), sum(f in theirs for f in own)
        merge_memory(mine, md, bk, "share")
        if os.path.lexists(mine):  # anything merge_memory could not move
            bk.stash(mine, "memory-own")
    else:
        bk.mkdir(md)
        bk.mkdir(os.path.dirname(mine))
    os.symlink(os.path.relpath(md, os.path.dirname(mine)), mine)
    bk.created(mine)
    if joined:
        bk.note(f"{joined} memories of {prof['label']} joined the shared ones")
    msg = f"{prof['label']} now uses the memory of {where} from {holder['label']}"
    msg += f": {joined} of its memories joined it." if joined else "."
    if clashes:
        msg += f" {clashes} with a name already there {'is' if clashes == 1 else 'are'} kept in the backup."
    return {"message": msg, "backup": bk.close()}


def memory_path(pid, name, f):
    if not f or "/" in f or not f.endswith(".md") or f == "MEMORY.md":
        raise ApiError("Invalid file name")
    return os.path.join(project_dir(profile(pid), name), "memory", f)


def memory_read(pid, name, f):
    p = memory_path(pid, name, f)
    if not os.path.exists(p):
        raise ApiError("Memory not found", 404)
    return {"content": open(p).read()}


def drop_index_line(md, f, bk):
    lines = index_lines(md)
    keep = [l for l in lines if f"({f})" not in l]
    if len(keep) != len(lines):
        bk.copy(os.path.join(md, "MEMORY.md"), "MEMORY-source.md")
        write_text(os.path.join(md, "MEMORY.md"), "\n".join(keep) + "\n")
    return [l for l in lines if f"({f})" in l]


def op_memory_save(pid, name, f, content):
    p = memory_path(pid, name, f)
    bk = Backup("memory-edit", f"Edit memory {f} ({pid_label(pid)})")
    bk.copy(p, f)
    write_text(p, content if content.endswith("\n") else content + "\n")
    bk.note(f"in {name}")
    return {"message": "Memory saved.", "backup": bk.close()}


def op_memory_move(pid, name, f, to_pid, to_name):
    src = memory_path(pid, name, f)
    if not os.path.exists(src):
        raise ApiError("Memory not found", 404)
    dst_dir = os.path.join(project_dir(profile(to_pid), to_name), "memory")
    dst = os.path.join(dst_dir, f)
    if os.path.exists(dst):
        raise ApiError("The target already has a memory with this file name")
    bk = Backup("memory-move", f"Move memory {f}: {pid_label(pid)} → {pid_label(to_pid)}")
    bk.mkdir(dst_dir)
    lines = drop_index_line(os.path.dirname(src), f, bk)
    shutil.move(src, dst)
    bk.moved(src, dst)
    meta = parse_memory(open(dst).read())
    line = lines[0] if lines else f"- [{meta.get('name') or f[:-3]}]({f}) — {meta.get('description', '')}"
    idx = os.path.join(dst_dir, "MEMORY.md")
    bk.copy(idx, "MEMORY-target.md")
    old = open(idx).read() if os.path.exists(idx) else ""
    write_text(idx, old.rstrip("\n") + ("\n" if old else "") + line + "\n")
    bk.note(f"from {name} to {to_name}")
    return {"message": "Memory moved.", "backup": bk.close()}


def op_memory_delete(pid, name, f):
    p = memory_path(pid, name, f)
    bk = Backup("memory-delete", f"Delete memory {f} ({pid_label(pid)})")
    drop_index_line(os.path.dirname(p), f, bk)
    bk.stash(p, f)
    bk.note(f"from {name}")
    return {"message": "Memory deleted (kept in the backup).", "backup": bk.close()}
