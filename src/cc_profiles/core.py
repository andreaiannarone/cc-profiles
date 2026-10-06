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

import copy
import glob
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time

from . import __version__
from . import byfolder

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


san = byfolder.san  # one definition, shared with `cc-profiles which`


def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


# Read-only caches. Every entry is keyed on a file's (mtime, size, inode) and checked
# against a fresh stat() on every use, so a changed file is always read again: the
# caches only save re-reading and re-parsing files that did not change.
_file_cache = {}


def file_sig(path):
    try:
        st = os.stat(path)
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size, st.st_ino)


def cached_read(kind, path, compute):
    """compute(path), reused while the file's stat() is unchanged."""
    sig = file_sig(path)  # before reading: a write during the read changes it again
    if sig is None:
        return compute(path)
    hit = _file_cache.get((kind, path))
    if hit is not None and hit[0] == sig:
        return hit[1]
    value = compute(path)
    if len(_file_cache) > 200000:  # files come and go: start over rather than grow forever
        _file_cache.clear()
    _file_cache[(kind, path)] = (sig, value)
    return value


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
    cfg = cached_read("config", CONFIG_FILE, read_json)
    if cfg is None:
        cfg = {"profiles": detect_profiles(), "rules": json.loads(json.dumps(DEFAULT_RULES)),
               "search_roots": list(DEFAULT_SEARCH_ROOTS)}
        write_json(CONFIG_FILE, cfg)
    return copy.deepcopy(cfg)  # callers change it before writing it back


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


_tls = threading.local()


def _open_backups():
    """Backups opened by the operation running in this thread and not closed yet."""
    if not hasattr(_tls, "backups"):
        _tls.backups = []
    return _tls.backups


def abort_open_backups(error):
    """An operation failed: close its open backups with what was journaled so far.
    A backup with no steps has nothing to undo and is removed. Returns whether any
    step was kept (so the error can say that Restore undoes it)."""
    kept = False
    for bk in list(_open_backups()):
        if bk.journal:
            bk.close(failed=error)
            kept = True
        else:
            _open_backups().remove(bk)
            shutil.rmtree(bk.dir, ignore_errors=True)
    return kept


def fault_point(name):
    """Tests only: fail on purpose at a named point, to check what a failure leaves behind."""
    if os.environ.get("CC_PROFILES_FAULT") == name:
        raise RuntimeError(f"fault injected at {name}")


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
        _open_backups().append(self)
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

    def close(self, failed=None):
        """Write the journal. failed: the error that stopped the operation halfway; the
        steps done until then are journaled anyway, so Restore can undo them."""
        if self in _open_backups():
            _open_backups().remove(self)
        man = {"title": self.title, "created": time.time(), "log": self.log,
               "journal": self.journal, "version": __version__}
        if failed:
            man["failed"] = failed
        write_json(os.path.join(self.dir, "manifest.json"), man)
        write_text(os.path.join(self.dir, "operation.txt"), "\n".join([self.title] + self.log) + "\n")
        return pretty(self.dir)


def pid_label(pid):
    if pid == "shared":
        return "all profiles"
    try:
        return profile(pid)["label"]
    except ApiError:
        return pid


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
