# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Memories."""

import glob
import os
import re
import shutil

from .core import (
    ApiError,
    Backup,
    parse_memory,
    pid_label,
    pretty,
    profile,
    project_dir,
    write_text,
)
from .paths import memory_files, path_index

def index_lines(md):
    p = os.path.join(md, "MEMORY.md")
    return open(p).read().splitlines() if os.path.exists(p) else []


def memory_projects(pid):
    prof = profile(pid)
    idx = path_index()
    out = []
    for d in glob.glob(os.path.join(prof["dir_abs"], "projects", "*", "")):
        name = os.path.basename(d.rstrip("/"))
        path = idx.get(name)
        out.append({"name": name, "pretty": pretty(path) if path else name,
                    "count": len(memory_files(d)),
                    "conv": len(glob.glob(os.path.join(d, "*.jsonl")))})
    out.sort(key=lambda r: (r["pretty"] != "~", r["pretty"].lower()))
    return out


def memory_list(pid, name):
    d = project_dir(profile(pid), name)
    md = os.path.join(d, "memory")
    index = "\n".join(index_lines(md))
    items = []
    for f in memory_files(d):
        text = open(os.path.join(md, f)).read()
        meta = parse_memory(text)
        items.append({"file": f, "name": meta.get("name") or f[:-3],
                      "description": meta.get("description", ""),
                      "type": meta.get("type", ""), "indexed": f"({f})" in index})
    missing = sorted(set(re.findall(r"\]\(([^)]+\.md)\)", index)) - set(memory_files(d)))
    return {"items": items, "missing": missing}


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
