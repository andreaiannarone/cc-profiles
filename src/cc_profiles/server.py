#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: a local web UI to manage multiple Claude Code profiles.

Claude Code reads its configuration from ~/.claude, or from the directory in
CLAUDE_CONFIG_DIR. Each directory is a "profile" with its own memory,
conversations, prompt history and settings. This app reads and writes those
directories and serves a page on http://127.0.0.1:4777.

Every operation that changes or moves something first saves what it touches in
~/.cc-profiles/backups/<date>_<operation>/, together with a journal of its
steps, so any operation can be undone.

Standard library only, Python >= 3.9.
"""
import argparse
import glob
import http.client
import json
import os
import re
import secrets
import shutil
import socketserver
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

__version__ = "0.2.1"

HOME = os.path.expanduser("~")
APP_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(APP_DIR, "static")
DATA_DIR = os.path.expanduser(os.environ.get("CC_PROFILES_HOME", "~/.cc-profiles"))
BACKUP_DIR = os.path.join(DATA_DIR, "backups")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
LAUNCHER_DIR = os.path.join(HOME, ".local", "bin")
LAUNCHER_MARK = "# managed by cc-profiles"
PORT = int(os.environ.get("CC_PROFILES_PORT", "4777"))
TOKEN = secrets.token_hex(16)
ALLOWED_HOSTS = set()  # filled in by main() once the port is known

# Paths where seeing a project in every profile is normal (home, temp folders,
# app support files). Real project rules are created by the user from the UI.
DEFAULT_RULES = (
    [{"exact": "~", "profile": "shared"}, {"exact": "/", "profile": "shared"}]
    + [{"match": m, "profile": "shared"} for m in
       ["/private/var/folders", "/private/tmp", "/tmp/", "Library/Application Support"]]
)
DEFAULT_SEARCH_ROOTS = ["~"]
SEARCH_SKIP = {"node_modules", ".git", "vendor", "dist", ".next", "Library", "Applications",
               "__pycache__", ".venv", "venv", "target", "build"}

_lock = threading.Lock()  # one write operation at a time


# ---------------------------------------------------------------------------
# Basics
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, msg, status=400):
        super().__init__(msg)
        self.status = status


def expand(p):
    return os.path.expanduser(p)


def pretty(p):
    if not p:
        return p
    return "~" + p[len(HOME):] if p == HOME or p.startswith(HOME + "/") else p


def san(path):
    """Directory name Claude Code uses in projects/: every non-alphanumeric char -> '-'."""
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_text(path, text):
    """Atomic write: temp file in the same directory + os.replace.
    A concurrent reader (Claude Code) sees either the old file or the new one.
    If path is a symlink (a file shared between profiles) we write the real file:
    os.replace on the link would turn it into a regular file and break sharing."""
    path = os.path.realpath(path)
    tmp = f"{path}.tmp-{os.getpid()}"
    with open(tmp, "w") as f:
        f.write(text)
    if os.path.exists(path):
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def looks_like_profile(d):
    return any(os.path.exists(os.path.join(d, x))
               for x in ("settings.json", "projects", "history.jsonl", ".claude.json", "skills"))


def detect_profiles():
    """First run: ~/.claude plus every ~/.claude-<id> directory that looks like a profile."""
    found = [{"id": "default", "label": "Default", "dir": "~/.claude",
              "config": "~/.claude.json", "command": "claude"}]
    for d in sorted(glob.glob(os.path.join(HOME, ".claude-*"))):
        pid = os.path.basename(d)[len(".claude-"):].lower()
        if (not os.path.isdir(d) or os.path.islink(d)
                or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", pid) or not looks_like_profile(d)):
            continue
        found.append({"id": pid, "label": pid.replace("-", " ").title(), "dir": f"~/.claude-{pid}",
                      "config": f"~/.claude-{pid}/.claude.json", "command": f"claude-{pid}"})
    return found


def load_config():
    os.makedirs(DATA_DIR, exist_ok=True)
    cfg = read_json(CONFIG_FILE)
    if cfg is None:
        cfg = {"profiles": detect_profiles(), "rules": json.loads(json.dumps(DEFAULT_RULES)),
               "search_roots": list(DEFAULT_SEARCH_ROOTS)}
        write_json(CONFIG_FILE, cfg)
    return cfg


def profiles():
    out = []
    for p in load_config()["profiles"]:
        p = dict(p)
        p["dir_abs"] = expand(p["dir"])
        p["config_abs"] = expand(p["config"])
        out.append(p)
    return out


def profile(pid):
    for p in profiles():
        if p["id"] == pid:
            return p
    raise ApiError(f"Unknown profile: {pid}")


def project_dir(prof, name, must_exist=True):
    """Path of a directory in projects/, protected against path traversal."""
    if not name or "/" in name or name in (".", ".."):
        raise ApiError("Invalid project name")
    d = os.path.join(prof["dir_abs"], "projects", name)
    if must_exist and not os.path.isdir(d):
        raise ApiError(f"Project not found in {prof['label']}: {name}", 404)
    return d


class Backup:
    """Backup of a single operation, with a journal so it can be undone.

    Each journal entry is one step; restoring walks them in reverse:
      copy    a modified file: its original content is stored here
      absent  a file that did not exist before: restoring removes it
      stash   a file or directory moved out of the way: the original is here
      move    an item moved from 'from' to 'to'
      mkdir   a created directory: restoring removes it if still empty
      created a new item (link, profile, launcher): restoring removes it
    """

    def __init__(self, op, title=""):
        stamp = time.strftime("%Y-%m-%d_%H-%M-%S")
        base = os.path.join(BACKUP_DIR, f"{stamp}_{op}")
        d, i = base, 2
        while os.path.exists(d):
            d, i = f"{base}-{i}", i + 1
        self.dir = d
        os.makedirs(d)
        self.title = title or op
        self.journal, self.log, self.n = [], [], 0

    def _slot(self, path, label):
        self.n += 1
        rel = os.path.join("file", f"{self.n:03d}-{(label or os.path.basename(path)).replace('/', '_')}")
        os.makedirs(os.path.join(self.dir, "file"), exist_ok=True)
        return rel

    def copy(self, path, label=None):
        """Call BEFORE modifying a file. Only the first copy counts: it is the
        original state, later copies would already contain changes."""
        path = os.path.realpath(path)  # a shared file is restored into the real file, not the link
        if any(e.get("path") == path and e["op"] in ("copy", "absent") for e in self.journal):
            return
        if os.path.exists(path):
            rel = self._slot(path, label)
            shutil.copy2(path, os.path.join(self.dir, rel))
            self.journal.append({"op": "copy", "path": path, "file": rel})
        else:
            self.journal.append({"op": "absent", "path": path})

    def stash(self, path, label=None):
        """Move into the backup instead of deleting."""
        if os.path.lexists(path):
            rel = self._slot(path, label)
            shutil.move(path, os.path.join(self.dir, rel))
            self.journal.append({"op": "stash", "path": path, "file": rel})

    def moved(self, src, dst):
        self.journal.append({"op": "move", "from": src, "to": dst})

    def mkdir(self, path):
        """Create path and every missing parent, journaling each one (top first),
        so that restoring removes all of them, deepest first."""
        missing = []
        p = os.path.abspath(path)
        while not os.path.isdir(p):
            missing.append(p)
            p = os.path.dirname(p)
        for d in reversed(missing):
            os.mkdir(d)
            self.journal.append({"op": "mkdir", "path": d})

    def created(self, path):
        self.journal.append({"op": "created", "path": path})

    def note(self, msg):
        self.log.append(msg)

    def close(self):
        write_json(os.path.join(self.dir, "manifest.json"),
                   {"title": self.title, "created": time.time(), "log": self.log,
                    "journal": self.journal, "version": __version__})
        write_text(os.path.join(self.dir, "operation.txt"), "\n".join([self.title] + self.log) + "\n")
        return pretty(self.dir)


# ---------------------------------------------------------------------------
# Classification and path resolution
# ---------------------------------------------------------------------------
def classify(path, dirname):
    """Expected profile for a project: a profile id, 'shared' or None."""
    rules = load_config()["rules"]
    for r in rules:
        if "exact" in r:
            target = expand(r["exact"]).rstrip("/") or "/"
            if path == target or (path is None and dirname == san(target)):
                return r["profile"]
    for r in rules:
        m = r.get("match")
        if not m:
            continue
        if path is not None and m in path:
            return r["profile"]
        if path is None and san(m) in dirname:
            return r["profile"]
    return None


def history_lines(prof):
    path = os.path.join(prof["dir_abs"], "history.jsonl")
    try:
        with open(path) as f:
            return [l.rstrip("\n") for l in f if l.strip()]
    except OSError:
        return []


def first_cwds(jsonl, limit=60):
    """Working directories mentioned in the first lines of a conversation."""
    found = set()
    try:
        with open(jsonl) as f:
            for i, line in enumerate(f):
                if i >= limit:
                    break
                try:
                    c = json.loads(line).get("cwd")
                except ValueError:
                    continue
                if c:
                    found.add(c)
    except OSError:
        pass
    return found


def known_paths():
    """Every project path mentioned by config files, prompt history and conversations."""
    paths = set()
    for p in profiles():
        cfg = read_json(p["config_abs"], {}) or {}
        paths |= set((cfg.get("projects") or {}).keys())
        for l in history_lines(p):
            try:
                pr = json.loads(l).get("project")
            except ValueError:
                continue
            if pr:
                paths.add(pr)
        for f in glob.glob(os.path.join(p["dir_abs"], "projects", "*", "*.jsonl")):
            paths |= first_cwds(f)
    return paths


def resolve_on_disk(name, base="/", depth=0):
    """Rebuild a path from its projects/ directory name by walking the disk.
    The name is ambiguous ('-' may be '/', ' ', '+', '.'...), so at each level we
    try every entry whose sanitized name is a prefix of what is left."""
    rest = name[len(san(base.rstrip("/"))):] if base != "/" else name
    if rest == "":
        return base
    if depth > 12 or not rest.startswith("-"):
        return None
    try:
        entries = os.listdir(base)
    except OSError:
        return None
    for e in sorted(entries, key=len, reverse=True):  # longest names first
        s = "-" + san(e)
        if rest == s or rest.startswith(s + "-"):
            p = os.path.join(base, e)
            if os.path.isdir(p):
                hit = resolve_on_disk(name, p, depth + 1)
                if hit:
                    return hit
    return None


def path_index():
    """Map projects/ directory name -> real path. An existing path wins over a
    missing one; names no file mentions are rebuilt by looking on disk."""
    idx = {}
    for k in known_paths():
        s = san(k)
        if s not in idx or (not os.path.isdir(idx[s]) and os.path.isdir(k)):
            idx[s] = k
    for p in profiles():
        for d in glob.glob(os.path.join(p["dir_abs"], "projects", "*", "")):
            name = os.path.basename(d.rstrip("/"))
            if name not in idx or not os.path.isdir(idx[name]):
                hit = resolve_on_disk(name)
                if hit:
                    idx[name] = hit
    return idx


def memory_files(d):
    md = os.path.join(d, "memory")
    if not os.path.isdir(md):
        return []
    return sorted(f for f in os.listdir(md) if f.endswith(".md") and f != "MEMORY.md")


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
def list_projects():
    profs = profiles()
    idx = path_index()
    rows = {}
    for p in profs:
        for d in glob.glob(os.path.join(p["dir_abs"], "projects", "*", "")):
            name = os.path.basename(d.rstrip("/"))
            convs = glob.glob(os.path.join(d, "*.jsonl"))
            mtime = max([os.path.getmtime(c) for c in convs] or [0])
            row = rows.setdefault(name, {"name": name, "in": {}})
            row["in"][p["id"]] = {"conv": len(convs), "mem": len(memory_files(d)), "mtime": mtime}
    ids = [p["id"] for p in profs]
    out = []
    for name, row in rows.items():
        path = idx.get(name)
        exists = bool(path) and os.path.isdir(path)
        expected = classify(path, name)
        issues = []
        if not exists:
            issues.append({"kind": "orphan", "text": "folder not found on disk" if path else "unknown path"})
        if expected in ids:
            for pid, st in row["in"].items():
                if pid != expected and (st["conv"] or st["mem"]):
                    issues.append({"kind": "profile", "from": pid, "to": expected,
                                   "text": f"also in {pid_label(pid)}, but belongs to {pid_label(expected)}"})
        if expected is None:
            issues.append({"kind": "unclassified", "text": "not assigned to a profile"})
        row.update({"path": path, "pretty": pretty(path) if path else name,
                    "exists": exists, "expected": expected, "issues": issues,
                    "last": max(st["mtime"] for st in row["in"].values())})
        out.append(row)
    out.sort(key=lambda r: r["pretty"].lower())
    return out


def pid_label(pid):
    if pid == "shared":
        return "all profiles"
    try:
        return profile(pid)["label"]
    except ApiError:
        return pid


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


# ---------------------------------------------------------------------------
# Memories
# ---------------------------------------------------------------------------
def parse_memory(text):
    meta = {}
    m = re.match(r"^---\n(.*?)\n---\n?", text, re.S)
    if m:
        for line in m.group(1).splitlines():
            mm = re.match(r"^\s*(name|description|type):\s*(.*)$", line)
            if mm:
                meta[mm.group(1)] = mm.group(2).strip().strip('"')
    return meta


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


# ---------------------------------------------------------------------------
# Skills and MCP servers
# ---------------------------------------------------------------------------
# Skills are folders in <profile>/skills/<name>/ with a SKILL.md. MCP servers live
# in the profile's .claude.json: "mcpServers" (user scope, every project) and
# projects[<path>].mcpServers (one project). Servers from plugins, from a
# project's .mcp.json and claude.ai connectors are configured elsewhere.
NEW_SKILL_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
MCP_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")
MCP_TYPES = ("stdio", "http", "sse")


def skill_dir(prof, name, must_exist=True):
    """Path of a skill folder, protected against path traversal. Existing skills
    may have any plain name; new ones must match NEW_SKILL_NAME."""
    if not name or "/" in name or name.startswith("."):
        raise ApiError("Invalid skill name")
    d = os.path.join(prof["dir_abs"], "skills", name)
    if must_exist and not os.path.isfile(os.path.join(d, "SKILL.md")):
        raise ApiError(f"Skill not found in {prof['label']}: {name}", 404)
    return d


def skills_note(prof):
    """Who else sees a change to this profile's skills."""
    src = primary()
    if prof["id"] != src["id"]:
        return f"shared with {src['label']}" if share_state(prof, "skills", "dir")["shared"] else ""
    users = [p["label"] for p in profiles()[1:] if share_state(p, "skills", "dir")["shared"]]
    return f"shared with {', '.join(users)}" if users else ""


def list_skills(pid):
    prof = profile(pid)
    root = os.path.join(prof["dir_abs"], "skills")
    items = []
    for n in names_in(root, dirs=True):
        md = os.path.join(root, n, "SKILL.md")
        if not os.path.isfile(md):
            continue
        meta = parse_memory(open(md, errors="replace").read(4000))
        files = sum(len(fs) for _, _, fs in os.walk(os.path.join(root, n))) - 1
        items.append({"name": n, "title": meta.get("name") or n, "description": meta.get("description", ""),
                      "files": files, "linked": os.path.islink(os.path.join(root, n))})
    return {"skills": items, "dir": pretty(root), "shared": skills_note(prof)}


def skill_read(pid, name):
    d = skill_dir(profile(pid), name)
    files = sorted(os.path.relpath(os.path.join(r, f), d) for r, _, fs in os.walk(d) for f in fs)
    return {"content": open(os.path.join(d, "SKILL.md"), errors="replace").read(),
            "files": [f for f in files if f != "SKILL.md"][:50]}


def op_skill_save(pid, name, content):
    prof = profile(pid)
    md = os.path.join(skill_dir(prof, name), "SKILL.md")
    bk = Backup("skill-edit", f"Edit skill {name} ({prof['label']})")
    bk.copy(md, f"{name}-SKILL.md")
    write_text(md, content if content.endswith("\n") else content + "\n")
    return {"message": f"Skill {name} saved.", "backup": bk.close()}


def op_skill_create(pid, name, description):
    prof = profile(pid)
    if not NEW_SKILL_NAME.fullmatch(name or ""):
        raise ApiError("Invalid skill name: lowercase letters, digits and dashes, up to 64")
    d = skill_dir(prof, name, must_exist=False)
    if os.path.lexists(d):
        raise ApiError(f"{prof['label']} already has a skill called {name}")
    description = " ".join((description or "").split())
    if not description:
        raise ApiError("Write a description: Claude uses it to decide when to use the skill")
    bk = Backup("skill-create", f"New skill {name} ({prof['label']})")
    bk.mkdir(d)
    md = os.path.join(d, "SKILL.md")
    bk.copy(md)
    write_text(md, f"---\nname: {name}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n"
                   f"# {name}\n\nInstructions for Claude go here.\n")
    return {"message": f"Skill {name} created in {prof['label']}.", "backup": bk.close()}


def op_skill_delete(pid, name):
    prof = profile(pid)
    d = skill_dir(prof, name)
    bk = Backup("skill-delete", f"Delete skill {name} ({prof['label']})")
    linked = os.path.islink(d)
    bk.stash(d, f"skill-{name}")
    msg = f"Skill {name} removed from {prof['label']}" + (" (only the link; its folder is untouched)." if linked else ".")
    return {"message": msg, "backup": bk.close()}


def op_skill_copy(pid, name, to_pid):
    src, dst = profile(pid), profile(to_pid)
    d = skill_dir(src, name)
    if src["id"] == dst["id"]:
        raise ApiError("Pick another profile")
    t = skill_dir(dst, name, must_exist=False)
    if os.path.realpath(os.path.dirname(t)) == os.path.realpath(os.path.dirname(d)):
        raise ApiError(f"{dst['label']} already has it: the two profiles share their skills")
    if os.path.lexists(t):
        raise ApiError(f"{dst['label']} already has a skill called {name}: delete it there first")
    bk = Backup("skill-copy", f"Copy skill {name}: {src['label']} → {dst['label']}")
    bk.mkdir(os.path.dirname(t))
    shutil.copytree(os.path.realpath(d), t, symlinks=True)
    bk.created(t)
    return {"message": f"Skill {name} copied to {dst['label']}.", "backup": bk.close()}


def mcp_summary(name, conf, scope):
    conf = conf if isinstance(conf, dict) else {}
    kind = conf.get("type") or ("stdio" if "command" in conf else "http")
    target = conf.get("url") or " ".join([str(conf.get("command", ""))] + [str(a) for a in conf.get("args") or []])
    return {"name": name, "scope": scope, "type": kind, "target": target.strip(),
            "env": sorted((conf.get("env") or {}).keys()), "headers": sorted((conf.get("headers") or {}).keys())}


def load_claude_json(prof):
    cfg = read_json(prof["config_abs"])
    if cfg is None:
        raise ApiError(f"{pretty(prof['config_abs'])} cannot be read: start Claude Code in {prof['label']} once")
    return cfg


def mcp_table(cfg, scope, create=False):
    """The mcpServers dict for a scope: "user", or a project path in .claude.json."""
    if scope == "user":
        holder = cfg
    else:
        holder = (cfg.get("projects") or {}).get(scope)
        if not isinstance(holder, dict):
            raise ApiError(f"Unknown project: {scope}")
    if create:
        if not isinstance(holder.get("mcpServers"), dict):
            holder["mcpServers"] = {}
        return holder["mcpServers"]  # the dict inside cfg, even when empty: writes go into it
    return holder.get("mcpServers") or {}


def list_mcp(pid):
    prof = profile(pid)
    cfg = read_json(prof["config_abs"], {}) or {}
    servers = [mcp_summary(n, c, "user") for n, c in sorted((cfg.get("mcpServers") or {}).items())]
    for path, pr in sorted((cfg.get("projects") or {}).items()):
        for n, c in sorted(((pr or {}).get("mcpServers") or {}).items()):
            servers.append(mcp_summary(n, c, path))
    return {"servers": servers, "config": pretty(prof["config_abs"]),
            "projects": sorted((cfg.get("projects") or {}).keys())}


def mcp_server(pid, scope, name):
    servers = mcp_table(load_claude_json(profile(pid)), scope)
    if name not in servers:
        raise ApiError(f"MCP server not found: {name}", 404)
    return {"config": servers[name]}


def check_mcp_config(conf):
    if not isinstance(conf, dict):
        raise ApiError("The server configuration must be a JSON object")
    kind = conf.get("type", "stdio")
    if kind not in MCP_TYPES:
        raise ApiError(f"Unknown type {kind}: use stdio, http or sse")
    if kind == "stdio" and not (isinstance(conf.get("command"), str) and conf["command"].strip()):
        raise ApiError("A stdio server needs a command")
    if kind != "stdio" and not re.match(r"^https?://", str(conf.get("url", ""))):
        raise ApiError(f"An {kind} server needs a URL starting with http:// or https://")
    for k in ("args",):
        if k in conf and not (isinstance(conf[k], list) and all(isinstance(a, str) for a in conf[k])):
            raise ApiError("args must be a list of strings")
    for k in ("env", "headers"):
        if k in conf and not (isinstance(conf[k], dict) and all(isinstance(v, str) for v in conf[k].values())):
            raise ApiError(f"{k} must map names to text values")


def session_hint(prof):
    return f" Restart the open session in {prof['label']} to load it." if active_session(prof) else \
        f" New Claude Code sessions in {prof['label']} will use it."


def op_mcp_save(pid, scope, name, conf, old_name=None):
    prof = profile(pid)
    if not MCP_NAME.fullmatch(name or ""):
        raise ApiError("Invalid server name: letters, digits, dots, dashes and underscores")
    check_mcp_config(conf)
    cfg = load_claude_json(prof)
    servers = mcp_table(cfg, scope, create=True)
    if old_name and old_name not in servers:
        raise ApiError(f"MCP server not found: {old_name}", 404)
    if name in servers and name != old_name:
        raise ApiError(f"There is already a server called {name} here")
    bk = Backup("mcp-save", f"{'Edit' if old_name else 'Add'} MCP server {name} ({prof['label']})")
    bk.copy(prof["config_abs"], "claude.json")
    if old_name and old_name != name:
        servers.pop(old_name)
    servers[name] = conf
    write_json(prof["config_abs"], cfg)
    where = "for every project" if scope == "user" else f"for {pretty(scope)}"
    return {"message": f"MCP server {name} saved {where}." + session_hint(prof), "backup": bk.close()}


def op_mcp_delete(pid, scope, name):
    prof = profile(pid)
    cfg = load_claude_json(prof)
    servers = mcp_table(cfg, scope)
    if name not in servers:
        raise ApiError(f"MCP server not found: {name}", 404)
    bk = Backup("mcp-delete", f"Remove MCP server {name} ({prof['label']})")
    bk.copy(prof["config_abs"], "claude.json")
    servers.pop(name)
    write_json(prof["config_abs"], cfg)
    return {"message": f"MCP server {name} removed.", "backup": bk.close()}


def op_mcp_copy(pid, scope, name, to_pid):
    src, dst = profile(pid), profile(to_pid)
    if src["id"] == dst["id"]:
        raise ApiError("Pick another profile")
    conf = mcp_server(pid, scope, name)["config"]
    if os.path.realpath(src["config_abs"]) == os.path.realpath(dst["config_abs"]):
        raise ApiError("The two profiles use the same .claude.json")
    cfg = load_claude_json(dst)
    servers = mcp_table(cfg, "user", create=True)
    if name in servers:
        raise ApiError(f"{dst['label']} already has a server called {name}")
    bk = Backup("mcp-copy", f"Copy MCP server {name}: {src['label']} → {dst['label']}")
    bk.copy(dst["config_abs"], "claude.json")
    servers[name] = json.loads(json.dumps(conf))
    write_json(dst["config_abs"], cfg)
    # Only the configuration: a sign-in (OAuth) is stored with the profile's credentials, never copied.
    msg = f"MCP server {name} copied to {dst['label']} for every project."
    if conf.get("type") in ("http", "sse"):
        msg += f" If it needs a sign-in, run /mcp in {dst['label']} to authenticate."
    return {"message": msg, "backup": bk.close()}


# ---------------------------------------------------------------------------
# Profiles and health
# ---------------------------------------------------------------------------
def parse_claude_processes(entries):
    """Config folders used by claude processes. entries: (argv0, [other words of the
    command line and the environment, as NAME=value]) for each process."""
    dirs = set()
    for argv0, words in entries:
        node_cli = any("@anthropic-ai/claude-code/" in w for w in words)
        if os.path.basename(argv0) != "claude" and "/claude/versions/" not in argv0 and not node_cli:
            continue
        env = dict(w.split("=", 1) for w in words if "=" in w and not w.startswith("="))
        home = env.get("HOME") or HOME  # the process's home, not this server's (which may be a sandbox)
        cfg = env.get("CLAUDE_CONFIG_DIR") or os.path.join(home, ".claude")
        if cfg.startswith("~"):
            cfg = home + cfg[1:]
        dirs.add(os.path.realpath(cfg).rstrip("/"))
    return dirs


_running = {"at": 0.0, "dirs": None}


def running_claude_dirs():
    """Config folders of the claude processes running now for this user, or None when
    the processes cannot be read. Cached for a few seconds: every list asks for it."""
    if time.time() - _running["at"] < 3:
        return _running["dirs"]
    entries = None
    try:
        if sys.platform == "darwin":
            # -E appends each process's environment to its command line (own processes only)
            out = subprocess.run(["ps", "-Eww", "-o", "pid=,command=", "-U", str(os.getuid())],
                                 capture_output=True, text=True, timeout=5).stdout
            entries = [(w[1], w[2:]) for w in (l.split() for l in out.splitlines()) if len(w) > 1]
        elif os.path.isdir("/proc"):
            entries = []
            for pid in filter(str.isdigit, os.listdir("/proc")):
                try:
                    with open(f"/proc/{pid}/cmdline", "rb") as f:
                        argv = [a.decode(errors="replace") for a in f.read().split(b"\0") if a]
                    with open(f"/proc/{pid}/environ", "rb") as f:
                        env = [e.decode(errors="replace") for e in f.read().split(b"\0") if e]
                except OSError:
                    continue
                if argv:
                    entries.append((argv[0], argv[1:] + env))
    except (OSError, subprocess.SubprocessError):
        entries = None
    _running.update(at=time.time(), dirs=None if entries is None else parse_claude_processes(entries))
    return _running["dirs"]


def active_session(prof, window=120):
    """A claude process runs in this profile, or a conversation was written in the
    last 2 minutes (a session that is open but idle, when processes cannot be read)."""
    running = running_claude_dirs()
    if running and os.path.realpath(prof["dir_abs"]).rstrip("/") in running:
        return True
    now = time.time()
    for f in glob.glob(os.path.join(prof["dir_abs"], "projects", "*", "*.jsonl")):
        try:
            if now - os.path.getmtime(f) < window:
                return True
        except OSError:
            pass
    return False


def list_profiles():
    out = []
    profs = profiles()
    for p in profs:
        cfg = read_json(p["config_abs"], {}) or {}
        projs = glob.glob(os.path.join(p["dir_abs"], "projects", "*", ""))
        out.append({
            "id": p["id"], "label": p["label"], "dir": pretty(p["dir_abs"]),
            "primary": p["id"] == profs[0]["id"],
            "command": p.get("command", ""),
            "email": (cfg.get("oauthAccount") or {}).get("emailAddress", ""),
            "projects": len(projs),
            "conv": len(glob.glob(os.path.join(p["dir_abs"], "projects", "*", "*.jsonl"))),
            "memories": sum(len(memory_files(d)) for d in projs),
            "active": active_session(p),
        })
    return out


_cand_cache = {}


def candidates(basename):
    """Folders with the same name under the search roots (depth 5)."""
    if not basename:
        return []
    hit = _cand_cache.get(basename)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    found = []
    for root in load_config().get("search_roots", DEFAULT_SEARCH_ROOTS):
        root = expand(root)
        base = root.rstrip("/").count("/")
        for cur, dirs, _ in os.walk(root):
            depth = cur.count("/") - base
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SEARCH_SKIP]
            if depth >= 5:
                dirs[:] = []
            if os.path.basename(cur) == basename and cur != root:
                found.append(pretty(cur))
            if len(found) >= 10:
                break
    _cand_cache[basename] = (time.time(), found)
    return found


def auth_status(p):
    env = tool_env()
    if p["dir_abs"] != os.path.join(HOME, ".claude"):
        env["CLAUDE_CONFIG_DIR"] = p["dir_abs"]
    else:
        env.pop("CLAUDE_CONFIG_DIR", None)
    b = find_tool("claude")
    if not b:
        return None
    try:
        r = subprocess.run([b, "auth", "status"], env=env, capture_output=True, text=True, timeout=20)
        return json.loads(r.stdout)
    except Exception:
        return None


def health():
    report = []
    projects = list_projects()
    for p in profiles():
        checks = []

        def add(ok, text, level=None):
            checks.append({"level": level or ("ok" if ok else "error"), "text": text})

        a = auth_status(p)
        add(bool(a and a.get("loggedIn")),
            f"Logged in: {a.get('email')}" if a and a.get("loggedIn") else "Not logged in")
        for f, lab in [(p["config_abs"], ".claude.json"),
                       (os.path.join(p["dir_abs"], "settings.json"), "settings.json"),
                       (os.path.join(p["dir_abs"], "settings.local.json"), "settings.local.json")]:
            if os.path.exists(f):
                ok = read_json(f) is not None
                add(ok, f"{lab} {'is valid' if ok else 'is NOT valid JSON'}")
        lines = history_lines(p)
        bad = 0
        for l in lines:
            try:
                json.loads(l)
            except ValueError:
                bad += 1
        add(bad == 0, f"Prompt history: {len(lines)} prompts" + (f", {bad} broken lines" if bad else ""))
        for sub in ("skills", "plugins"):
            d = os.path.join(p["dir_abs"], sub)
            if os.path.isdir(d):
                add(True, f"{sub} reachable" + (f" (shared → {os.readlink(d)})" if os.path.islink(d) else ""))
            elif os.path.lexists(d):
                add(False, f"{sub} is a broken link")
        sk = glob.glob(os.path.join(p["dir_abs"], "skills", "*", "SKILL.md"))
        add(True, f"{len(sk)} readable skills")
        inst = read_json(os.path.join(p["dir_abs"], "plugins", "installed_plugins.json"), {}) or {}
        for key, entries in (inst.get("plugins") or {}).items():
            for e in entries if isinstance(entries, list) else [entries]:
                ip = e.get("installPath", "")
                add(os.path.isdir(ip), f"Plugin {key}" + ("" if os.path.isdir(ip) else ": files missing"))
        for d in glob.glob(os.path.join(p["dir_abs"], "projects", "*", "memory")):
            name = os.path.basename(os.path.dirname(d))
            ml = memory_list(p["id"], name)
            for f in ml["missing"]:
                add(False, f"Index of {name}: {f} is missing")
            for it in ml["items"]:
                if not it["indexed"]:
                    add(False, f"{name}: {it['file']} is not in MEMORY.md", "warn")
        if active_session(p):
            add(True, "A session is open right now: writes are atomic, but avoid heavy operations", "warn")
        orphans = []
        for r in projects:
            if p["id"] in r["in"] and not r["exists"]:
                base = os.path.basename(r["path"]) if r["path"] else ""
                orphans.append({"name": r["name"], "pretty": r["pretty"],
                                "conv": r["in"][p["id"]]["conv"], "mem": r["in"][p["id"]]["mem"],
                                "candidates": candidates(base)})
        report.append({"id": p["id"], "label": p["label"], "checks": checks, "orphans": orphans})
    return report


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


def list_backups():
    out = []
    if not os.path.isdir(BACKUP_DIR):
        return out
    for name in os.listdir(BACKUP_DIR):
        d = os.path.join(BACKUP_DIR, name)
        if not os.path.isdir(d):
            continue
        man = read_json(os.path.join(d, "manifest.json")) or {}
        out.append({"name": name, "path": pretty(d), "size": dir_size(d),
                    "title": man.get("title", name),
                    "created": man.get("created", os.path.getmtime(d)),
                    "log": man.get("log", []),
                    "steps": len(man.get("journal", [])),
                    "restorable": bool(man.get("journal")) and not man.get("restored"),
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


def op_backup_prune(days):
    """Permanently delete the backups created more than `days` days ago."""
    if not isinstance(days, int) or isinstance(days, bool) or days < 1:
        raise ApiError("Pick a number of days, 1 or more")
    limit = time.time() - days * 86400
    old = [b for b in list_backups() if b["created"] < limit]
    freed = sum(b["size"] for b in old)
    for b in old:
        shutil.rmtree(backup_path(b["name"]))
    if not old:
        return {"message": f"No backups older than {days} days."}
    n = len(old)
    return {"message": f"Deleted {n} backup{'s' if n != 1 else ''} older than {days} days, {freed // 1024} KB freed."}


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


# ---------------------------------------------------------------------------
# Launchers (the command that starts Claude Code in a profile)
# ---------------------------------------------------------------------------
# New profiles get a tiny script in ~/.local/bin instead of a shell alias: it works
# in every shell and right away, without editing rc files. Aliases written by
# older setups are still recognized when renaming or deleting a profile.
RC_FILES = [os.path.join(HOME, f) for f in (".zshrc", ".bashrc", ".bash_profile")]


def launcher_path(command):
    return os.path.join(LAUNCHER_DIR, command)


def launcher_script(dir_, label):
    d = '"$HOME' + dir_[1:] + '"' if dir_.startswith("~") else f'"{dir_}"'
    return (f"#!/bin/sh\n{LAUNCHER_MARK} (profile: {label}). Safe to delete.\n"
            f"CLAUDE_CONFIG_DIR={d} exec claude \"$@\"\n")


def is_our_launcher(path):
    try:
        with open(path) as f:
            return LAUNCHER_MARK in f.read(500)
    except OSError:
        return False


def write_launcher(command, dir_, label, bk):
    p = launcher_path(command)
    if os.path.lexists(p) and not is_our_launcher(p):
        raise ApiError(f"{pretty(p)} already exists and was not created by cc-profiles")
    bk.mkdir(LAUNCHER_DIR)
    bk.copy(p, f"launcher-{command}")
    write_text(p, launcher_script(dir_, label))
    os.chmod(p, 0o755)


def launcher_dir_in_path():
    return LAUNCHER_DIR in os.environ.get("PATH", "").split(":")


def rewrite_alias(old_cmd, new_line, bk):
    """Replace (new_line) or remove (None) an alias `old_cmd` in the shell rc files,
    with the '# Claude Code: …' comment line right above it. Returns whether found."""
    found_any = False
    pat = re.compile(r"^\s*alias\s+" + re.escape(old_cmd) + r"=")
    for rc in RC_FILES:
        if not os.path.exists(rc):
            continue
        lines = open(rc).read().split("\n")
        out, found = [], False
        for l in lines:
            if pat.match(l):
                found = True
                if new_line is None:
                    while out and out[-1].startswith("# Claude Code:"):
                        out.pop()
                    if out and out[-1] == "":  # the blank line that separated the block
                        out.pop()
                else:
                    out.append(new_line)
                continue
            out.append(l)
        if found:
            bk.copy(rc, os.path.basename(rc))
            write_text(rc, "\n".join(out))
            found_any = True
    return found_any


def command_conflict(command, others):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,40}", command):
        return "Invalid command: letters, digits, dashes and underscores only"
    if command == "claude" or any(p.get("command") == command for p in others):
        return f"The command {command} is already used"
    existing = shutil.which(command)
    if existing and not is_our_launcher(existing):
        return f"A program called {command} already exists: pick another name"
    return None


# ---------------------------------------------------------------------------
# Slash command (/cc-profiles inside Claude Code)
# ---------------------------------------------------------------------------
# A personal command in <profile>/commands/, so the name is just /cc-profiles
# (plugin commands always get a "plugin:" prefix). The mark is a YAML comment in
# the frontmatter: Claude Code does not show it to the model, and only files with
# it may be rewritten. plugin/commands/open.md is the same text without the mark.
COMMAND_MARK = "# managed by cc-profiles"
COMMAND_NAME = "cc-profiles.md"
COMMAND_TEXT = f"""---
{COMMAND_MARK}
description: Open the cc-profiles web UI to manage your Claude Code profiles
allowed-tools: Bash(cc-profiles open:*)
---
!`cc-profiles open`

Tell the user, in one short line, what the output above says: the URL where cc-profiles is open, or why it did not start.

If the `cc-profiles` command was not found, say that this command only opens the app and does not install it, and give this install command:

```sh
curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
```
"""


def is_our_command(path):
    try:
        with open(path) as f:
            return COMMAND_MARK in f.read(200)
    except OSError:
        return False


def command_state(dir_abs):
    """"missing", "outdated", "current" or "foreign" (a cc-profiles.md cc-profiles did not write)."""
    path = os.path.join(dir_abs, "commands", COMMAND_NAME)
    if not os.path.lexists(path):
        return "missing"
    if not is_our_command(path):
        return "foreign"
    return "current" if open(path).read() == COMMAND_TEXT else "outdated"


def write_command(dir_abs, bk, label):
    """Write /cc-profiles into a profile folder, inside an open backup. When the
    profile shares `commands`, the file is written through the link, into the source."""
    path = os.path.join(dir_abs, "commands", COMMAND_NAME)
    bk.mkdir(os.path.dirname(path))
    bk.copy(path, f"command-{label}")
    write_text(path, COMMAND_TEXT)
    bk.note(f"/cc-profiles command: {pretty(path)}")


def install_command():
    """Write /cc-profiles into every profile that does not get it through sharing.
    Returns (lines to print, backup path or None)."""
    src, lines, bk = primary(), [], None
    for p in profiles():
        if p["id"] != src["id"] and share_state(p, "commands", "dir")["shared"]:
            lines.append(f"{p['label']}: shares commands with {src['label']}")
            continue
        if not os.path.isdir(p["dir_abs"]):
            lines.append(f"{p['label']}: skipped, {pretty(p['dir_abs'])} does not exist")
            continue
        path = os.path.join(p["dir_abs"], "commands", COMMAND_NAME)
        state = command_state(p["dir_abs"])
        if state == "foreign":
            lines.append(f"{p['label']}: skipped, {pretty(path)} exists and was not created by cc-profiles")
            continue
        if state == "current":
            lines.append(f"{p['label']}: already up to date")
            continue
        if bk is None:
            bk = Backup("slash-command", "Add the /cc-profiles command")
        write_command(p["dir_abs"], bk, p["id"])
        lines.append(f"{p['label']}: added {pretty(path)}")
    return lines, (bk.close() if bk else None)


# ---------------------------------------------------------------------------
# New profile
# ---------------------------------------------------------------------------
RUNTIME = {"daemon", "ide", "sessions", "session-env", "shell-snapshots", "cache",
           "telemetry", "statsig", ".credentials.json"}
PROJECT_DATA = {"projects", "history.jsonl", "file-history", "paste-cache", "backups",
                "jobs", "downloads", "todos"}


def op_create_profile(label, pid, base, include_projects, share):
    label, pid = label.strip(), pid.strip().lower()
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
    share = [i for i in share if i in {x for x, _, _ in SHARE_ITEMS}]
    bk = Backup("new-profile", f"New profile {label} ({pretty(new)})")
    bk.copy(CONFIG_FILE, "config.json")
    src = profile(base) if base else None
    if src:
        # Login credentials are never copied: each profile logs in on its own,
        # a copied token can be invalidated when the original refreshes it.
        skip = RUNTIME | set(share) | (set() if include_projects else PROJECT_DATA)
        shutil.copytree(src["dir_abs"], new, symlinks=True,
                        ignore=lambda d, names: [n for n in names if n in skip] if d == src["dir_abs"] else [])
        bk.created(new)
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
        os.makedirs(new)
        bk.created(new)
        if "settings.json" not in share:  # a shared settings.json is linked below instead
            settings = {}
            sl = (read_json(os.path.join(primary()["dir_abs"], "settings.json"), {}) or {}).get("statusLine")
            if sl:
                settings["statusLine"] = sl
            write_json(os.path.join(new, "settings.json"), settings)
    kinds = {i: k for i, k, _ in SHARE_ITEMS}
    for item in share:
        s = os.path.join(primary()["dir_abs"], item)
        if not os.path.lexists(s):  # the source does not have it yet: create it empty, as op_share does
            if kinds[item] == "dir":
                bk.mkdir(s)
            else:
                bk.copy(s)
                write_text(s, "{}\n" if item.endswith(".json") else "")
        os.symlink(os.path.relpath(s, new), os.path.join(new, item))
    # every new profile gets /cc-profiles (a cc-profiles.md written by someone else is left alone)
    if command_state(new) in ("missing", "outdated"):
        write_command(new, bk, pid)
    write_launcher(command, f"~/.claude-{pid}", label, bk)
    cfg = load_config()
    cfg["profiles"].append({"id": pid, "label": label, "dir": f"~/.claude-{pid}",
                            "config": f"~/.claude-{pid}/.claude.json", "command": command})
    write_json(CONFIG_FILE, cfg)
    bk.note(f"base: {src['label'] if src else 'empty'}, projects: {'yes' if include_projects else 'no'}, "
            f"shared: {', '.join(share) or 'nothing'}")
    msg = f"Profile {label} created. Run {command} and log in with /login."
    if not launcher_dir_in_path():
        msg += f" Note: {pretty(LAUNCHER_DIR)} is not in your PATH yet."
    return {"message": msg, "backup": bk.close()}


# ---------------------------------------------------------------------------
# Claude Code settings
# ---------------------------------------------------------------------------
# Dropdown options come from the settings schema inside the Claude Code binary
# (version SCHEMA_VERSION): where the schema only accepts some values there is a
# dropdown, where it accepts any string a free text field.
SCHEMA_VERSION = "2.1.289"
# Built-in output styles and their descriptions, as in the Claude Code binary. "default"
# is left out: it is the same as no value ("— default —" in the UI); field_options()
# still lists it when a profile has it set explicitly.
BUILTIN_STYLES = [
    ("Proactive", "Proactive", "Executes immediately, minimizes interruptions and prefers action over planning"),
    ("Concise", "Concise", "Responds tersely, leading with results and skipping preamble and narration"),
    ("Explanatory", "Explanatory", "Explains its implementation choices and codebase patterns"),
    ("Learning", "Learning", "Pauses and asks you to write small pieces of code for hands-on practice"),
]
SETTING_FIELDS = [
    {"key": "model", "type": "text", "label": "Model",
     "help": "An alias (opus, sonnet, haiku) or a full model name", "suggest": ["opus", "sonnet", "haiku"]},
    {"key": "effortLevel", "type": "select", "label": "Effort level",
     "help": "How much the model reasons before answering",
     "options": [("low", "Low"), ("medium", "Medium"), ("high", "High"), ("xhigh", "Extra high")]},
    {"key": "outputStyle", "type": "select", "label": "Output style",
     "default_desc": "Claude Code's standard behavior",
     "help": "Built-in styles plus the profile's custom ones (output-styles/)", "options": "styles"},
    {"key": "language", "type": "text", "label": "Response language", "help": "Free text, e.g. English, Italiano",
     "suggest": []},
    {"key": "theme", "type": "select", "label": "Theme", "help": "Colors of the terminal UI; custom themes (custom:…) are kept",
     "options": [("auto", "Auto"), ("dark", "Dark"), ("light", "Light"), ("dark-daltonized", "Dark, colorblind-friendly"),
                 ("light-daltonized", "Light, colorblind-friendly"), ("dark-ansi", "Dark, ANSI colors only"),
                 ("light-ansi", "Light, ANSI colors only")]},
    {"key": "editorMode", "type": "select", "label": "Editor mode", "help": "Key bindings for the prompt input",
     "options": [("normal", "Normal"), ("vim", "Vim")]},
    {"key": "tui", "type": "select", "label": "Renderer", "help": "How the UI is drawn in the terminal",
     "options": [("default", "Classic"), ("fullscreen", "Fullscreen, flicker-free")]},
    {"key": "includeCoAuthoredBy", "type": "bool", "label": "Co-authored-by in commits", "deprecated": True,
     "help": "Deprecated by Claude Code: replaced by “attribution” (advanced editor)"},
    {"key": "cleanupPeriodDays", "type": "number", "label": "Days to keep conversations",
     "help": "Older conversations are deleted (default 30, minimum 1)"},
    {"key": "prefersReducedMotion", "type": "bool", "label": "Reduce motion", "help": "Fewer animations in the UI"},
]
GLOBAL_FIELDS = {"autoUpdates": "bool"}  # the only .claude.json keys the app edits


def custom_styles(prof):
    """Custom output styles: .md files in <profile>/output-styles, name from frontmatter."""
    out = []
    for f in sorted(glob.glob(os.path.join(prof["dir_abs"], "output-styles", "*.md"))):
        try:
            meta = parse_memory(open(f).read())
        except OSError:
            continue
        name = meta.get("name") or os.path.basename(f)[:-3]
        desc = meta.get("description") or "No description"
        out.append((name, name, f"{desc} · output-styles/{os.path.basename(f)}", "Custom"))
    return out


def field_options(fd, prof, current):
    opts = fd.get("options")
    if opts is None:
        return None
    if opts == "styles":
        opts = [o + ("Built-in",) for o in BUILTIN_STYLES] + custom_styles(prof)
        if current == "default":
            opts.insert(0, ("default", "Default", "Claude Code's standard behavior, same as no value", "Built-in"))
    opts = [tuple(o) + (None,) * (4 - len(o)) for o in opts]  # (value, label, description, group)
    if isinstance(current, str) and current not in [o[0] for o in opts]:
        opts.append((current, f"{current} (current value)", "Not a known style: kept so it is not lost", None))
    return [{"value": v, "label": l, "desc": d, "group": g} for v, l, d, g in opts]


def settings_files(prof):
    d = prof["dir_abs"]
    return {"settings": os.path.join(d, "settings.json"),
            "local": os.path.join(d, "settings.local.json"),
            "claude_md": os.path.join(d, "CLAUDE.md")}


def load_settings(path):
    """(data, error). A missing file counts as an empty object."""
    if not os.path.exists(path):
        return {}, None
    try:
        with open(path) as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}, "the file does not contain a JSON object"
        return data, None
    except ValueError as e:
        return {}, f"invalid JSON: {e}"


def effective(prof, key):
    """Value in use and the file it comes from: settings.local.json wins over settings.json."""
    f = settings_files(prof)
    local, _ = load_settings(f["local"])
    if key in local:
        return local[key], "local"
    sett, _ = load_settings(f["settings"])
    if key in sett:
        return sett[key], "settings"
    return None, None


def get_settings(pid):
    prof = profile(pid)
    f = settings_files(prof)
    files = {}
    for k in ("settings", "local"):
        _, err = load_settings(f[k])
        files[k] = {"path": pretty(f[k]), "exists": os.path.exists(f[k]), "shared": os.path.islink(f[k]),
                    "error": err, "raw": open(f[k]).read() if os.path.exists(f[k]) else "{}\n"}
    all_profs = profiles()
    others = [p for p in all_profs if p["id"] != pid]
    fields = []
    for fd in SETTING_FIELDS:
        val, src = effective(prof, fd["key"])
        seen = {v for v in [effective(o, fd["key"])[0] for o in all_profs] if isinstance(v, str)}
        fields.append(dict({k: v for k, v in fd.items() if k != "options"}, value=val, source=src,
                           options=field_options(fd, prof, val),
                           suggest=sorted(set(fd.get("suggest", [])) | seen),
                           others=[{"id": o["id"], "label": o["label"], "value": effective(o, fd["key"])[0]}
                                   for o in others]))
    sett, _ = load_settings(f["settings"])
    local, _ = load_settings(f["local"])
    perms = sett.get("permissions") or {}
    cfg = read_json(prof["config_abs"], {}) or {}
    md = f["claude_md"]
    return {
        "files": files, "fields": fields, "schema_version": SCHEMA_VERSION,
        "permissions": {k: perms.get(k, []) for k in ("allow", "ask", "deny")},
        "permissions_local": {k: (local.get("permissions") or {}).get(k, []) for k in ("allow", "ask", "deny")},
        "claude_md": {"path": pretty(md), "exists": os.path.exists(md), "shared": os.path.islink(md),
                      "content": open(md).read() if os.path.exists(md) else ""},
        "global": {"path": pretty(prof["config_abs"]),
                   "autoUpdates": cfg.get("autoUpdates"),
                   "info": {"Account": (cfg.get("oauthAccount") or {}).get("emailAddress", ""),
                            "Install method": cfg.get("installMethod", ""),
                            "Startups": cfg.get("numStartups", ""),
                            "Local MCP servers": len(cfg.get("mcpServers") or {})}},
    }


def save_settings_file(prof, which, data, bk):
    path = settings_files(prof)[which]
    _, err = load_settings(path)
    if err:
        raise ApiError(f"{os.path.basename(path)} has an error ({err}): fix it in the advanced editor")
    bk.copy(path, os.path.basename(path))
    write_json(path, data)


def shared_note(path):
    return " (shared file: applies to the other profiles too)" if os.path.islink(path) else ""


def op_setting(pid, key, value):
    prof = profile(pid)
    fd = next((x for x in SETTING_FIELDS if x["key"] == key), None)
    if not fd:
        raise ApiError("This setting is not managed here: use the advanced editor")
    if value is not None:
        if fd["type"] == "bool" and not isinstance(value, bool):
            raise ApiError("Invalid value: expected true or false")
        if fd["type"] == "number":
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ApiError("Invalid value: expected a whole number greater than zero")
        if fd["type"] == "text":
            value = str(value).strip() or None
        if fd["type"] == "select":
            allowed = [o["value"] for o in field_options(fd, prof, effective(prof, key)[0])]
            if value not in allowed:
                raise ApiError(f"Invalid value for {fd['label'].lower()}: pick one of the options")
    _, src = effective(prof, key)
    which = src or "settings"
    f = settings_files(prof)
    data, _ = load_settings(f[which])
    bk = Backup("setting", f"{fd['label']} of {prof['label']}")
    if value is None:
        data.pop(key, None)
        msg = f"{fd['label']}: back to the default."
    else:
        data[key] = value
        msg = f"Saved in {os.path.basename(f[which])}: {fd['label'].lower()} = {value}{shared_note(f[which])}."
    save_settings_file(prof, which, data, bk)
    bk.note(f"{key} = {json.dumps(value, ensure_ascii=False)} in {os.path.basename(f[which])}")
    return {"message": msg, "backup": bk.close()}


def op_permissions(pid, rules):
    prof = profile(pid)
    clean = {}
    for k in ("allow", "ask", "deny"):
        items = rules.get(k) or []
        if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
            raise ApiError("Invalid permissions format")
        clean[k] = [x.strip() for x in items if x.strip()]
    f = settings_files(prof)
    data, _ = load_settings(f["settings"])
    perms = dict(data.get("permissions") or {})  # keeps defaultMode and other keys
    for k, v in clean.items():
        if v:
            perms[k] = v
        else:
            perms.pop(k, None)
    if perms:
        data["permissions"] = perms
    else:
        data.pop("permissions", None)
    bk = Backup("permissions", f"Permissions of {prof['label']}")
    save_settings_file(prof, "settings", data, bk)
    bk.note(", ".join(f"{k}: {len(v)}" for k, v in clean.items()))
    return {"message": "Permissions saved: " + ", ".join(f"{len(v)} {k}" for k, v in clean.items())
                       + shared_note(f["settings"]) + ".", "backup": bk.close()}


def op_settings_raw(pid, which, content):
    if which not in ("settings", "local"):
        raise ApiError("Invalid file")
    prof = profile(pid)
    try:
        data = json.loads(content)
    except ValueError as e:
        raise ApiError(f"Invalid JSON at line {getattr(e, 'lineno', '?')}: {getattr(e, 'msg', e)}")
    if not isinstance(data, dict):
        raise ApiError("The file must contain a JSON object: { … }")
    path = settings_files(prof)[which]
    bk = Backup("settings-advanced", f"{os.path.basename(path)} of {prof['label']}")
    bk.copy(path, os.path.basename(path))
    write_json(path, data)
    return {"message": f"{os.path.basename(path)} saved{shared_note(path)}.", "backup": bk.close()}


def op_claude_md(pid, content):
    prof = profile(pid)
    path = settings_files(prof)["claude_md"]
    bk = Backup("claude-md", f"CLAUDE.md of {prof['label']}")
    bk.copy(path, "CLAUDE.md")
    write_text(path, content if content.endswith("\n") or not content else content + "\n")
    return {"message": "CLAUDE.md saved" + shared_note(path) + ". It applies from the next Claude Code session.",
            "backup": bk.close()}


def op_global(pid, key, value):
    if GLOBAL_FIELDS.get(key) != "bool" or not isinstance(value, bool):
        raise ApiError("This global setting cannot be changed here")
    prof = profile(pid)
    cfg = read_json(prof["config_abs"])
    if cfg is None:
        raise ApiError(f"{pretty(prof['config_abs'])} cannot be read")
    bk = Backup("global-setting", f"{key} of {prof['label']}")
    bk.copy(prof["config_abs"], "claude.json")
    cfg[key] = value
    write_json(prof["config_abs"], cfg)
    return {"message": f"{key}: {'on' if value else 'off'}.", "backup": bk.close()}


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
            if not glob.glob(os.path.join(d, "*.jsonl")) and not memory_files(d):
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


# ---------------------------------------------------------------------------
# Claude Code information
# ---------------------------------------------------------------------------
PLANS = {"max": "Max", "pro": "Pro", "team": "Team", "enterprise": "Enterprise", "free": "Free"}
EXTRA_PATH = [LAUNCHER_DIR, "/opt/homebrew/bin", "/usr/local/bin"]


def tool_env():
    """PATH plus the folders installers put programs in: the app may have been
    started from a terminal that does not have them yet (e.g. right after installing)."""
    env = dict(os.environ)
    parts = env.get("PATH", "").split(":")
    env["PATH"] = ":".join(parts + [p for p in EXTRA_PATH if p not in parts])
    return env


def find_tool(name):
    return shutil.which(name, path=tool_env()["PATH"])


def claude_binary():
    b = find_tool("claude")
    return os.path.realpath(b) if b else None


def claude_version():
    b = find_tool("claude")
    if not b:
        return None
    try:
        r = subprocess.run([b, "--version"], capture_output=True, text=True, timeout=10, env=tool_env())
        return r.stdout.strip().split(" ")[0] or None
    except Exception:
        return None


def names_in(d, suffix=None, dirs=False):
    if not os.path.isdir(d):
        return []
    out = []
    for n in sorted(os.listdir(d)):
        if n.startswith("."):
            continue
        p = os.path.join(d, n)
        if dirs and os.path.isdir(p):
            out.append(n)
        elif not dirs and (suffix is None or n.endswith(suffix)) and os.path.isfile(p):
            out.append(n[: -len(suffix)] if suffix else n)
    return out


def about():
    binary = claude_binary()
    primary_cfg = read_json(profiles()[0]["config_abs"], {}) or {}
    profs = []
    for p in profiles():
        a = auth_status(p) or {}
        cfg = read_json(p["config_abs"], {}) or {}
        sett, _ = load_settings(os.path.join(p["dir_abs"], "settings.json"))
        local, _ = load_settings(os.path.join(p["dir_abs"], "settings.local.json"))
        inst = read_json(os.path.join(p["dir_abs"], "plugins", "installed_plugins.json"), {}) or {}
        mcp_user = sorted((cfg.get("mcpServers") or {}).keys())
        mcp_proj = sorted({k for pr in (cfg.get("projects") or {}).values()
                           for k in ((pr or {}).get("mcpServers") or {}).keys()})
        hooks = sorted(set((sett.get("hooks") or {}).keys()) | set((local.get("hooks") or {}).keys()))
        projs = glob.glob(os.path.join(p["dir_abs"], "projects", "*", ""))
        convs = glob.glob(os.path.join(p["dir_abs"], "projects", "*", "*.jsonl"))
        first = cfg.get("firstStartTime")
        profs.append({
            "id": p["id"], "label": p["label"], "command": p.get("command", ""),
            "dir": pretty(p["dir_abs"]), "config": pretty(p["config_abs"]),
            "account": {
                "Account": a.get("email") or (cfg.get("oauthAccount") or {}).get("emailAddress", ""),
                "Login": ("active" if a.get("loggedIn") else "not logged in")
                         + (f" · {a['authMethod']}" if a.get("authMethod") and a.get("authMethod") != "none" else ""),
                "Plan": PLANS.get(a.get("subscriptionType"), a.get("subscriptionType") or "—"),
                "Organization": a.get("orgName") or "—",
                "API provider": a.get("apiProvider") or "—",
                "Analytics": "off" if a.get("analyticsDisabled") else "on",
            },
            "usage": {
                "Startups": cfg.get("numStartups", "—"),
                "First started": first[:10] if isinstance(first, str) else "—",
                "Saved conversations": len(convs),
                "Projects": len(projs),
                "Memories": sum(len(memory_files(d)) for d in projs),
                "Prompts in history": len(history_lines(p)),
                "Disk usage": dir_size(p["dir_abs"]),
            },
            "contents": {
                "Skills": names_in(os.path.join(p["dir_abs"], "skills"), dirs=True),
                "Plugins": sorted((inst.get("plugins") or {}).keys()),
                "Subagents": names_in(os.path.join(p["dir_abs"], "agents"), ".md"),
                "Slash commands": names_in(os.path.join(p["dir_abs"], "commands"), ".md"),
                "Output styles": names_in(os.path.join(p["dir_abs"], "output-styles"), ".md"),
                "MCP servers (user)": mcp_user,
                "MCP servers (projects)": mcp_proj,
                "Hooks": hooks,
            },
            "shared": [i for i, _, _ in SHARE_ITEMS if os.path.islink(os.path.join(p["dir_abs"], i))],
            "claude_md": os.path.exists(os.path.join(p["dir_abs"], "CLAUDE.md")),
        })
    return {
        "claude": {
            "Version": claude_version() or "not found",
            "Binary": pretty(binary) if binary else "claude is not in PATH",
            "Install method": primary_cfg.get("installMethod", "—"),
            "Auto-updates": "on" if primary_cfg.get("autoUpdates") else "off",
            "Settings schema checked against": SCHEMA_VERSION,
        },
        "profiles": profs,
        "app": {
            "cc-profiles": __version__,
            "Code": pretty(APP_DIR),
            "Config and rules": pretty(CONFIG_FILE),
            "Backups": f"{len(list_backups())} · {pretty(BACKUP_DIR)}",
            "Backup disk usage": dir_size(BACKUP_DIR) if os.path.isdir(BACKUP_DIR) else 0,
            "Address": f"http://127.0.0.1:{PORT}",
            "Python": sys.version.split(" ")[0],
        },
    }


# ---------------------------------------------------------------------------
# Installing Claude Code
# ---------------------------------------------------------------------------
# Official commands only (code.claude.com/docs/en/setup): the client picks a
# method id from this list, never sends a command of its own.
INSTALL_METHODS = {
    "native": {"label": "Official installer (recommended)",
               "command": "curl -fsSL https://claude.ai/install.sh | bash",
               "note": "Updates itself in the background. Installs into ~/.local/bin."},
    "brew": {"label": "Homebrew, stable channel", "requires": "brew",
             "command": "brew install --cask claude-code",
             "note": "About a week behind, skips releases with regressions. Update with brew upgrade claude-code."},
    "brew-latest": {"label": "Homebrew, latest channel", "requires": "brew",
                    "command": "brew install --cask claude-code@latest",
                    "note": "Every release as soon as it ships. Update with brew upgrade claude-code@latest."},
    "npm": {"label": "npm", "requires": "npm",
            "command": "npm install -g @anthropic-ai/claude-code",
            "note": "Needs Node.js 22 or later. Update with npm install -g @anthropic-ai/claude-code@latest."},
}
_job = {"running": False, "method": None, "lines": [], "code": None, "started": None}
_job_lock = threading.Lock()


def node_major():
    n = find_tool("node")
    if not n:
        return None
    try:
        out = subprocess.run([n, "--version"], capture_output=True, text=True, timeout=10).stdout
        return int(out.strip().lstrip("v").split(".")[0])
    except Exception:
        return None


def claude_status():
    b = find_tool("claude")
    methods = []
    for k, m in INSTALL_METHODS.items():
        ok, why = True, ""
        if m.get("requires") == "brew" and not find_tool("brew"):
            ok, why = False, "Homebrew is not installed"
        if m.get("requires") == "npm":
            nm = node_major()
            if not find_tool("npm"):
                ok, why = False, "npm is not installed"
            elif nm is not None and nm < 22:
                ok, why = False, f"needs Node.js 22 or later (you have {nm})"
        if k == "native" and not find_tool("curl"):
            ok, why = False, "curl is not available"
        methods.append({"id": k, "label": m["label"], "command": m["command"], "note": m["note"],
                        "available": ok, "why": why})
    return {"installed": bool(b), "path": pretty(os.path.realpath(b)) if b else None,
            "version": claude_version() if b else None,
            "in_path": bool(shutil.which("claude")), "platform": sys.platform,
            "supported": sys.platform in ("darwin", "linux"),
            "methods": methods, "job": job_state()}


def job_state():
    with _job_lock:
        return {k: (list(v) if isinstance(v, list) else v) for k, v in _job.items()}


def _run_job(cmd):
    try:
        p = subprocess.Popen(["/bin/bash", "-lc", cmd], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, env=tool_env(), bufsize=1)
        for line in p.stdout:
            with _job_lock:
                _job["lines"].append(re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", line.rstrip("\n")))
                del _job["lines"][:-400]  # keep the last 400 lines
        code = p.wait()
    except Exception as e:  # noqa: BLE001
        with _job_lock:
            _job["lines"].append(f"Error: {e}")
        code = -1
    with _job_lock:
        _job["code"], _job["running"] = code, False


def op_install(method):
    m = INSTALL_METHODS.get(method)
    if not m:
        raise ApiError("Unknown install method")
    if sys.platform not in ("darwin", "linux"):
        raise ApiError("Installing from here is only supported on macOS and Linux")
    st = next(x for x in claude_status()["methods"] if x["id"] == method)
    if not st["available"]:
        raise ApiError(f"{m['label']} is not available: {st['why']}")
    with _job_lock:
        if _job["running"]:
            raise ApiError("An installation is already running")
        _job.update(running=True, method=method, lines=[f"$ {m['command']}"], code=None, started=time.time())
    cmd = m["command"]
    if os.environ.get("CC_PROFILES_INSTALL_DRYRUN"):  # tests only: installs nothing
        cmd = f"echo {json.dumps(cmd)}; sleep 1; echo dry run ok; exit ${{CC_PROFILES_INSTALL_DRYRUN_CODE:-0}}"
    threading.Thread(target=_run_job, args=(cmd,), daemon=True).start()
    return {"message": f"Installation started: {m['label']}."}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Server(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer.server_bind also calls socket.getfqdn(), a reverse DNS lookup
        # that can take 30 s on some Macs. The name is never used: skip it.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Handler(BaseHTTPRequestHandler):
    server_version = f"cc-profiles/{__version__}"

    def log_message(self, fmt, *args):
        if os.environ.get("CC_PROFILES_QUIET"):
            return
        sys.stderr.write("  " + (fmt % args) + "\n")

    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False))

    def _guard(self):
        # A fixed Host blocks DNS rebinding; the token blocks requests from other sites.
        if self.headers.get("Host") not in ALLOWED_HOSTS:
            self._json(403, {"error": "Host not allowed"})
            return False
        if self.path.startswith("/api/") and self.headers.get("X-Token") != TOKEN:
            self._json(403, {"error": "Missing or wrong token"})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                html = open(os.path.join(STATIC_DIR, "index.html")).read().replace("__TOKEN__", TOKEN)
                return self._send(200, html, "text/html; charset=utf-8")
            routes = {
                "/api/profiles": lambda: list_profiles(),
                "/api/projects": lambda: list_projects(),
                "/api/health": lambda: health(),
                "/api/candidates": lambda: candidates(q.get("name", "")),
                "/api/memory/projects": lambda: memory_projects(q["profile"]),
                "/api/memory/list": lambda: memory_list(q["profile"], q["project"]),
                "/api/memory/file": lambda: memory_read(q["profile"], q["project"], q["file"]),
                "/api/backups": lambda: list_backups(),
                "/api/projects/move/preview": lambda: move_plan(q["project"], q["from"], q["to"]),
                "/api/sharing": lambda: list_sharing(),
                "/api/settings": lambda: get_settings(q["profile"]),
                "/api/about": lambda: about(),
                "/api/claude/status": lambda: claude_status(),
                "/api/skills": lambda: list_skills(q["profile"]),
                "/api/skills/file": lambda: skill_read(q["profile"], q["name"]),
                "/api/mcp": lambda: list_mcp(q["profile"]),
                "/api/mcp/server": lambda: mcp_server(q["profile"], q["scope"], q["name"]),
            }
            if u.path not in routes:
                return self._json(404, {"error": "Not found"})
            self._json(200, routes[u.path]())
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except KeyError as e:
            self._json(400, {"error": f"Missing parameter: {e}"})
        except Exception as e:  # noqa: BLE001 - the error is shown in the UI
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        if not self._guard():
            return
        try:
            n = int(self.headers.get("Content-Length") or 0)
            b = json.loads(self.rfile.read(n) or b"{}")
            routes = {
                "/api/projects/move": lambda: op_move(b["project"], b["from"], b["to"]),
                "/api/projects/delete": lambda: op_delete(b["project"], b["profile"]),
                "/api/projects/relink": lambda: op_relink(b["project"], b["profile"], b["path"]),
                "/api/rules": lambda: op_rule(b["match"], b["profile"]),
                "/api/memory/save": lambda: op_memory_save(b["profile"], b["project"], b["file"], b["content"]),
                "/api/memory/move": lambda: op_memory_move(b["profile"], b["project"], b["file"],
                                                           b["to_profile"], b["to_project"]),
                "/api/memory/delete": lambda: op_memory_delete(b["profile"], b["project"], b["file"]),
                "/api/backups/restore": lambda: op_restore(b["name"]),
                "/api/backups/delete": lambda: op_backup_delete(b["name"]),
                "/api/backups/prune": lambda: op_backup_prune(b.get("days")),
                "/api/sharing": lambda: op_share(b["profile"], b["item"], bool(b["shared"])),
                "/api/settings/field": lambda: op_setting(b["profile"], b["key"], b.get("value")),
                "/api/settings/permissions": lambda: op_permissions(b["profile"], b.get("rules") or {}),
                "/api/settings/raw": lambda: op_settings_raw(b["profile"], b["file"], b["content"]),
                "/api/settings/claude-md": lambda: op_claude_md(b["profile"], b.get("content", "")),
                "/api/settings/global": lambda: op_global(b["profile"], b["key"], b.get("value")),
                "/api/claude/install": lambda: op_install(b.get("method", "")),
                "/api/skills/save": lambda: op_skill_save(b["profile"], b["name"], b["content"]),
                "/api/skills/create": lambda: op_skill_create(b["profile"], b["name"], b.get("description", "")),
                "/api/skills/delete": lambda: op_skill_delete(b["profile"], b["name"]),
                "/api/skills/copy": lambda: op_skill_copy(b["profile"], b["name"], b["to"]),
                "/api/mcp/save": lambda: op_mcp_save(b["profile"], b["scope"], b["name"], b["config"],
                                                     b.get("old_name") or None),
                "/api/mcp/delete": lambda: op_mcp_delete(b["profile"], b["scope"], b["name"]),
                "/api/mcp/copy": lambda: op_mcp_copy(b["profile"], b["scope"], b["name"], b["to"]),
                "/api/profiles/update": lambda: op_update_profile(b["id"], b.get("label"), b.get("command")),
                "/api/profiles/delete": lambda: op_delete_profile(b["id"], b.get("merge_into") or None,
                                                                  bool(b.get("force"))),
                "/api/profiles/create": lambda: op_create_profile(
                    b["label"], b["id"], b.get("base") or None,
                    bool(b.get("include_projects")), b.get("share") or []),
            }
            if self.path not in routes:
                return self._json(404, {"error": "Not found"})
            with _lock:
                self._json(200, routes[self.path]())
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except KeyError as e:
            self._json(400, {"error": f"Missing parameter: {e}"})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": f"{type(e).__name__}: {e}"})


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------
def current_label():
    """Label of the profile Claude Code is using now (for status lines)."""
    d = os.path.realpath(expand(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude")).rstrip("/")
    cfg = read_json(CONFIG_FILE, {}) or {}
    for p in cfg.get("profiles", []):
        if os.path.realpath(expand(p["dir"])).rstrip("/") == d:
            return p["label"]
    base = os.path.basename(d)
    return base[len(".claude-"):] if base.startswith(".claude-") else "default"


def serve(port, open_browser):
    global PORT, ALLOWED_HOSTS
    PORT = port
    ALLOWED_HOSTS = {f"127.0.0.1:{port}", f"localhost:{port}"}
    load_config()
    try:
        srv = Server(("127.0.0.1", port), Handler)
    except OSError:
        print(f"Port {port} is busy: cc-profiles may already be running.")
        print(f"Open http://127.0.0.1:{port} or use --port {port + 1}.")
        sys.exit(1)
    url = f"http://127.0.0.1:{port}"
    print(f"cc-profiles {__version__} on {url}  (ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def is_running(port):
    """True if cc-profiles answers on the port (another program there does not count).
    http.client talks to 127.0.0.1 directly, without urllib's proxy handling."""
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=1)
    try:
        conn.request("GET", "/")
        return (conn.getresponse().getheader("Server") or "").startswith("cc-profiles/")
    except (OSError, http.client.HTTPException):
        return False
    finally:
        conn.close()


def open_app(port, open_browser):
    """Start the server in the background unless it is running, then open the browser.

    Returns at once, so it can run from a Claude Code slash command."""
    url = f"http://127.0.0.1:{port}"
    if is_running(port):
        print(f"cc-profiles is already running on {url}")
    else:
        os.makedirs(DATA_DIR, exist_ok=True)
        log = os.path.join(DATA_DIR, "server.log")
        with open(log, "wb") as out:
            proc = subprocess.Popen(
                [sys.executable, "-m", "cc_profiles", "--port", str(port), "--no-browser"],
                stdin=subprocess.DEVNULL, stdout=out, stderr=out, start_new_session=True)
        deadline = time.time() + 15
        while time.time() < deadline and proc.poll() is None and not is_running(port):
            time.sleep(0.1)
        if not is_running(port):
            print(f"cc-profiles did not start. See {pretty(log)}:")
            print(open(log, errors="replace").read().strip())
            sys.exit(1)
        print(f"cc-profiles started in the background on {url} (pid {proc.pid}). Stop it with: kill {proc.pid}")
    if open_browser:
        webbrowser.open(url)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="cc-profiles", description="A local web UI to manage Claude Code profiles.")
    ap.add_argument("--version", action="version", version=f"cc-profiles {__version__}")
    ap.add_argument("--port", type=int, default=PORT, help="port to listen on (default: 4777, or CC_PROFILES_PORT)")
    ap.add_argument("--no-browser", action="store_true", help="do not open the browser")
    sub = ap.add_subparsers(dest="cmd")
    sub.add_parser("label", help="print the label of the active profile (for status lines)")
    sub.add_parser("install-command", help="add the /cc-profiles command to Claude Code in every profile")
    op = sub.add_parser("open", help="start in the background if needed, open the browser and return")
    op.add_argument("--port", type=int, default=argparse.SUPPRESS, help="port to listen on")
    op.add_argument("--no-browser", action="store_true", default=argparse.SUPPRESS, help="do not open the browser")
    args = ap.parse_args(argv)
    if args.cmd == "label":
        print(current_label())
        return
    if os.name == "nt":
        print("cc-profiles supports macOS and Linux only for now.")
        sys.exit(1)
    if args.cmd == "install-command":
        lines, backup = install_command()
        print("\n".join(lines))
        if backup:
            print(f"Backup: {backup} (undo it from the Backups tab)")
        print("Restart Claude Code sessions that are already open to see /cc-profiles.")
        return
    if args.cmd == "open":
        open_app(args.port, not args.no_browser)
        return
    serve(args.port, not args.no_browser)


if __name__ == "__main__":
    main()
