# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Projects."""

import glob
import json
import os
import shutil

from .core import (
    ApiError,
    Backup,
    CONFIG_FILE,
    HOME,
    active_session,
    expand,
    load_config,
    pid_label,
    pretty,
    profile,
    profiles,
    project_dir,
    read_json,
    san,
    write_json,
    write_text,
)
from .paths import classify, history_lines, memory_files, path_index, project_folders

# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def list_projects():
    profs = profiles()
    idx = path_index()
    rows = {}
    for p in profs:
        for name, d, convs in project_folders(p):
            mtime = 0
            for c in convs:
                try:
                    mtime = max(mtime, os.path.getmtime(os.path.join(d, c)))
                except OSError:  # removed while listing
                    pass
            row = rows.setdefault(name, {"name": name, "in": {}})
            row["in"][p["id"]] = {"conv": len(convs), "mem": len(memory_files(d)), "mtime": mtime}
    ids = [p["id"] for p in profs]
    rules = load_config()["rules"]
    labels = {p["id"]: p["label"] for p in profs}
    out = []
    for name, row in rows.items():
        path = idx.get(name)
        exists = bool(path) and os.path.isdir(path)
        expected = classify(path, name, rules)
        issues = []
        if not exists:
            issues.append({"kind": "orphan", "text": "folder not found on disk" if path else "unknown path"})
        if expected in ids:
            for pid, st in row["in"].items():
                if pid != expected and (st["conv"] or st["mem"]):
                    issues.append({"kind": "profile", "from": pid, "to": expected,
                                   "text": f"also in {labels[pid]}, but belongs to {labels[expected]}"})
        if expected is None:
            issues.append({"kind": "unclassified", "text": "not assigned to a profile"})
        row.update({"path": path, "pretty": pretty(path) if path else name,
                    "exists": exists, "expected": expected, "issues": issues,
                    "last": max(st["mtime"] for st in row["in"].values())})
        out.append(row)
    out.sort(key=lambda r: r["pretty"].lower())
    return out


def merge_dir(src, dst, bk, label):
    """Merge src into dst. Memories are merged with their index; conflicts go to the backup."""
    bk.mkdir(dst)
    moved = 0
    for e in os.listdir(src):
        s, d = os.path.join(src, e), os.path.join(dst, e)
        if e == "memory" and os.path.isdir(s):
            bk.mkdir(d)
            for m in os.listdir(s):
                ms, mdst = os.path.join(s, m), os.path.join(d, m)
                if m == "MEMORY.md":
                    with open(ms) as f:
                        extra = [l for l in f.read().splitlines() if l.startswith("- [")]
                    old = open(mdst).read() if os.path.exists(mdst) else ""
                    add = [l for l in extra if l not in old]
                    if add:
                        bk.copy(mdst, f"{label}-MEMORY-target.md")
                        write_text(mdst, old.rstrip("\n") + ("\n" if old else "") + "\n".join(add) + "\n")
                    bk.stash(ms, f"{label}-MEMORY-source.md")
                elif os.path.exists(mdst):
                    bk.stash(ms, f"{label}-conflict-{m}")
                    bk.note(f"memory already present, original kept in the backup: {m}")
                else:
                    shutil.move(ms, mdst)
                    bk.moved(ms, mdst)
            if not os.listdir(s):
                os.rmdir(s)
        elif os.path.exists(d):
            bk.stash(s, f"{label}-conflict-{e}")
            bk.note(f"already present in the target, original kept in the backup: {e}")
        else:
            shutil.move(s, d)
            bk.moved(s, d)
            moved += e.endswith(".jsonl")
    if not os.listdir(src):
        os.rmdir(src)
    return moved


def matches(project, path):
    """path=None matches the whole history (merging an entire profile)."""
    if path is None:
        return True
    return project == path or (project or "").startswith(path + "/")


def move_history(src, dst, path, bk):
    """Move a project's prompts from one history to another, without duplicates."""
    sh = os.path.join(src["dir_abs"], "history.jsonl")
    dh = os.path.join(dst["dir_abs"], "history.jsonl")
    bk.copy(sh, f"history-{src['id']}.jsonl")
    bk.copy(dh, f"history-{dst['id']}.jsonl")
    keep, moved = [], []
    for l in history_lines(src):
        try:
            j = json.loads(l)
        except ValueError:
            keep.append(l)
            continue
        (moved if matches(j.get("project"), path) else keep).append(l)
    if not moved:
        return 0
    dl = history_lines(dst)
    seen = set()
    for l in dl:
        try:
            j = json.loads(l)
            seen.add((j.get("timestamp"), j.get("display")))
        except ValueError:
            pass
    for l in moved:
        j = json.loads(l)
        if (j.get("timestamp"), j.get("display")) not in seen:
            dl.append(l)

    def ts(l):
        try:
            return json.loads(l).get("timestamp") or 0
        except ValueError:
            return 0

    dl.sort(key=ts)  # stable sort: lines without a timestamp stay on top
    write_text(dh, "\n".join(dl) + "\n")
    write_text(sh, "\n".join(keep) + "\n")
    return len(moved)


def rewrite_history(prof, old, new, bk):
    hp = os.path.join(prof["dir_abs"], "history.jsonl")
    bk.copy(hp, f"history-{prof['id']}.jsonl")
    out, n = [], 0
    for l in history_lines(prof):
        try:
            j = json.loads(l)
        except ValueError:
            out.append(l)
            continue
        pr = j.get("project")
        if matches(pr, old):
            j["project"] = new + pr[len(old):]
            n += 1
            l = json.dumps(j, ensure_ascii=False, separators=(",", ":"))
        out.append(l)
    if n:
        write_text(hp, "\n".join(out) + "\n")
    return n


def move_config_entry(src, dst, path, bk):
    sc, dc = read_json(src["config_abs"]), read_json(dst["config_abs"])
    if not sc or dc is None or path not in (sc.get("projects") or {}):
        return False
    bk.copy(src["config_abs"], f"config-{src['id']}.json")
    bk.copy(dst["config_abs"], f"config-{dst['id']}.json")
    entry = sc["projects"].pop(path)
    dc.setdefault("projects", {}).setdefault(path, entry)
    write_json(dst["config_abs"], dc)
    write_json(src["config_abs"], sc)
    return True


def rename_config_entry(prof, old, new, bk):
    c = read_json(prof["config_abs"])
    if not c or old not in (c.get("projects") or {}):
        return False
    bk.copy(prof["config_abs"], f"config-{prof['id']}.json")
    entry = c["projects"].pop(old)
    c["projects"].setdefault(new, entry)
    write_json(prof["config_abs"], c)
    return True


def sessions_of(d):
    return [os.path.basename(f)[:-6] for f in glob.glob(os.path.join(d, "*.jsonl"))]


def op_move(name, src_id, dst_id):
    src, dst = profile(src_id), profile(dst_id)
    if src_id == dst_id:
        raise ApiError("Source and target are the same profile")
    project_dir(src, name)
    path = path_index().get(name)
    bk = Backup(f"move-{src_id}-{dst_id}", f"Move {pretty(path) or name}: {src['label']} → {dst['label']}")
    conv, fh, hist, cfg = move_project_into(name, src, dst, bk, path)
    bk.note(f"conversations {conv}, snapshots {fh}, prompts {hist}, settings {'yes' if cfg else 'no'}")
    msg = f"Moved to {dst['label']}: {conv} conversations, {hist} prompts, {fh} snapshots."
    open_in = [p["label"] for p in (src, dst) if active_session(p)]
    if cfg and open_in:
        msg += (f" Restart the open Claude Code sessions in {' and '.join(open_in)}: they keep .claude.json"
                " in memory and could write the old project settings back.")
    return {"message": msg, "backup": bk.close()}


def move_plan(name, src_id, dst_id):
    """What moving a project would do, without doing it: the same rules as move_project_into."""
    src, dst = profile(src_id), profile(dst_id)
    if src_id == dst_id:
        raise ApiError("Source and target are the same profile")
    S = project_dir(src, name)
    D = project_dir(dst, name, must_exist=False)
    path = path_index().get(name)
    items = []

    def add(action, a, b):
        # "item": short, relative to the project folder (or to the profile, for file snapshots)
        base = S if a.startswith(S + os.sep) else src["dir_abs"]
        items.append({"action": action, "item": os.path.relpath(a, base), "from": pretty(a), "to": pretty(b)})

    for e in sorted(os.listdir(S)):
        s, d = os.path.join(S, e), os.path.join(D, e)
        if e == "memory" and os.path.isdir(s):
            for m in sorted(os.listdir(s)):
                ms, md = os.path.join(s, m), os.path.join(d, m)
                if m == "MEMORY.md":
                    add("merge", ms, md)
                else:
                    add("conflict" if os.path.exists(md) else "move", ms, md)
        else:
            add("conflict" if os.path.exists(d) else "move", s, d)
    for sid in sessions_of(S):
        a = os.path.join(src["dir_abs"], "file-history", sid)
        b = os.path.join(dst["dir_abs"], "file-history", sid)
        if os.path.isdir(a) and not os.path.exists(b):
            add("move", a, b)
    prompts = sum(1 for l in history_lines(src) if path and matches((json.loads(l) if l.startswith("{") else {}).get("project"), path))
    sc = read_json(src["config_abs"], {}) or {}
    settings = bool(path and path in (sc.get("projects") or {}))
    return {"items": items, "prompts": prompts, "settings": settings,
            "history": pretty(os.path.join(src["dir_abs"], "history.jsonl")),
            "config": pretty(src["config_abs"])}


def move_project_into(name, src, dst, bk, path):
    """Move a project between profiles inside an open backup: conversations and
    memories, file snapshots, prompt history and per-project settings."""
    S = project_dir(src, name)
    sids = sessions_of(S)
    conv = merge_dir(S, project_dir(dst, name, must_exist=False), bk, "project")
    fh = 0
    for sid in sids:
        a = os.path.join(src["dir_abs"], "file-history", sid)
        b = os.path.join(dst["dir_abs"], "file-history", sid)
        if os.path.isdir(a) and not os.path.exists(b):
            bk.mkdir(os.path.dirname(b))
            shutil.move(a, b)
            bk.moved(a, b)
            fh += 1
    hist = move_history(src, dst, path, bk) if path else 0
    cfg = move_config_entry(src, dst, path, bk) if path else False
    return conv, fh, hist, cfg


def op_delete(name, pid):
    prof = profile(pid)
    S = project_dir(prof, name)
    bk = Backup(f"delete-{pid}", f"Delete {pretty(path_index().get(name)) or name} from {prof['label']}")
    for sid in sessions_of(S):
        bk.stash(os.path.join(prof["dir_abs"], "file-history", sid), f"file-history-{sid}")
    bk.stash(S, f"project-{name}")
    return {"message": f"Deleted from {prof['label']} (kept in the backup).", "backup": bk.close()}


def op_relink(name, pid, new_path):
    prof = profile(pid)
    new_path = expand(new_path.strip()).rstrip("/")
    if not os.path.isdir(new_path):
        raise ApiError(f"Folder does not exist: {pretty(new_path)}")
    S = project_dir(prof, name)
    new_name = san(new_path)
    if new_name == name:
        raise ApiError("The project is already linked to this folder")
    old = path_index().get(name)
    bk = Backup(f"relink-{pid}", f"Relink {pretty(old) or name} → {pretty(new_path)} ({prof['label']})")
    conv = merge_dir(S, project_dir(prof, new_name, must_exist=False), bk, "project")
    hist = rewrite_history(prof, old, new_path, bk) if old else 0
    cfg = rename_config_entry(prof, old, new_path, bk) if old else False
    return {"message": f"Linked to {pretty(new_path)}: {conv} conversations, {hist} prompts"
                       f"{', settings moved' if cfg else ''}.", "backup": bk.close()}


def op_rule(match, prof_id):
    if prof_id not in [p["id"] for p in profiles()] + ["shared"]:
        raise ApiError("Invalid profile")
    match = match.strip()
    if not match:
        raise ApiError("Empty rule")
    cfg = load_config()
    if match.startswith(HOME):
        match = "~" + match[len(HOME):] if match == HOME else match[len(HOME):].lstrip("/")
    bk = Backup("rule", f"Rule “{match}” → {pid_label(prof_id)}")
    bk.copy(CONFIG_FILE, "config.json")
    cfg["rules"] = [r for r in cfg["rules"] if r.get("match") != match]
    cfg["rules"].insert(0, {"match": match, "profile": prof_id})  # new rules win
    write_json(CONFIG_FILE, cfg)
    return {"message": f"Rule added: “{match}” → {pid_label(prof_id)}", "backup": bk.close()}
