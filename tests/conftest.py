"""Test fixtures: a fake home with fake Claude Code profiles, and a real server on it.

Every test gets its own temporary HOME, so the tests never touch your real
~/.claude. The server runs as a subprocess, exactly as a user would start it.
"""
import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Some tests call cc_profiles code in this process, where its paths point to the real home:
# nothing they start may write there on its own (the /cc-profiles command, the update check).
os.environ["CC_PROFILES_AUTO_COMMAND"] = "0"
os.environ["CC_PROFILES_UPDATE_CHECK"] = "0"
REAL_HOME = Path(os.path.expanduser("~"))


def real_home_state():
    """What the tests must never change in the real home: cc-profiles' data and each profile's command."""
    out = {}
    for p in [REAL_HOME / ".cc-profiles" / "config.json", *REAL_HOME.glob(".claude*/commands/cc-profiles.md")]:
        try:
            out[str(p)] = p.stat().st_mtime_ns
        except OSError:
            out[str(p)] = None
    return out


@pytest.fixture(scope="session", autouse=True)
def real_home_untouched():
    """A safety net: fail the run if anything wrote into the real home's cc-profiles data or commands."""
    before = real_home_state()
    yield
    after = real_home_state()
    changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k))
    assert not changed, f"the tests changed the real home: {changed}"
OLD = time.time() - 3600  # files older than the "session open" window


def child_env(env):
    """Environment for a cc-profiles process started by a test. Under coverage
    (COVERAGE_PROCESS_START is set) the process is measured too."""
    env = dict(env)
    if os.environ.get("COVERAGE_PROCESS_START"):
        env["COVERAGE_PROCESS_START"] = os.environ["COVERAGE_PROCESS_START"]
        # data next to the config, never in the process's working folder (often a fake home):
        # newer coverage starts measuring before tests/coverage_startup can set this itself
        env["COVERAGE_FILE"] = os.path.join(os.path.dirname(os.path.abspath(os.environ["COVERAGE_PROCESS_START"])), ".coverage")
        env["PYTHONPATH"] = os.pathsep.join([str(ROOT / "tests" / "coverage_startup"), env.get("PYTHONPATH", "")])
    return env


def san(path):
    return re.sub(r"[^A-Za-z0-9]", "-", str(path))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class FakeHome:
    """Builds a home directory with Claude Code profiles in it."""

    def __init__(self, root: Path):
        self.root = root

    def path(self, rel):
        return self.root / rel

    def write(self, rel, text):
        p = self.root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        return p

    def json(self, rel, data):
        return self.write(rel, json.dumps(data))

    def profile(self, name):
        """name='' is ~/.claude, otherwise ~/.claude-<name>."""
        d = self.root / (".claude" if not name else f".claude-{name}")
        d.mkdir(parents=True, exist_ok=True)
        (d / "settings.json").exists() or (d / "settings.json").write_text("{}")
        return d

    def conversation(self, profile, project, session, memories=None):
        """A conversation for project (a path relative to home) in a profile."""
        proj = self.root / project
        proj.mkdir(parents=True, exist_ok=True)
        d = self.profile(profile) / "projects" / san(proj)
        d.mkdir(parents=True, exist_ok=True)
        f = d / f"{session}.jsonl"
        f.write_text(json.dumps({"type": "user", "cwd": str(proj)}) + "\n")
        os.utime(f, (OLD, OLD))
        fh = self.profile(profile) / "file-history" / session
        fh.mkdir(parents=True, exist_ok=True)
        (fh / "snapshot").write_text(session)
        for fname, body in (memories or {}).items():
            md = d / "memory"
            md.mkdir(exist_ok=True)
            (md / fname).write_text(f"---\nname: {fname[:-3]}\ndescription: about {fname}\n---\n{body}\n")
            with open(md / "MEMORY.md", "a") as idx:
                idx.write(f"- [{fname[:-3]}]({fname}) — about {fname}\n")
        return d

    def history(self, profile, entries):
        """entries: (project relative to home, prompt, timestamp)."""
        lines = [json.dumps({"display": t, "timestamp": ts, "project": str(self.root / p)}) for p, t, ts in entries]
        (self.profile(profile) / "history.jsonl").write_text("\n".join(lines) + "\n")

    def snapshot(self):
        """Every file (with its hash), link (with its target) and folder, except app data."""
        out = []
        for p in sorted(self.root.rglob("*")):
            rel = p.relative_to(self.root)
            if rel.parts[0] in (".cc-profiles", "Library") or "__pycache__" in rel.parts:
                continue
            if p.is_symlink():
                out.append(f"L {rel} -> {os.readlink(p)}")
            elif p.is_file():
                out.append(f"F {rel} {hashlib.md5(p.read_bytes()).hexdigest()}")
            elif p.is_dir():
                out.append(f"D {rel}")
        return out


class App:
    """A running cc-profiles server on a fake home, with a tiny API client."""

    def __init__(self, home: FakeHome, extra_env=None):
        self.home = home
        self.port = free_port()
        env = {
            "HOME": str(home.root),
            "PATH": "/usr/bin:/bin",  # no claude, brew or npm: tests never run them for real
            "PYTHONPATH": str(SRC),
            "PYTHONDONTWRITEBYTECODE": "1",
            "CC_PROFILES_QUIET": "1",
            "CC_PROFILES_INSTALL_DRYRUN": "1",
            "CC_PROFILES_AUTO_COMMAND": "0",  # tests compare the fake home: no /cc-profiles written at start
        }
        env.update(extra_env or {})
        env = child_env(env)
        self.env = env
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "cc_profiles", "--no-browser", "--port", str(self.port)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        self.base = f"http://127.0.0.1:{self.port}"
        for _ in range(100):
            try:
                html = urllib.request.urlopen(self.base + "/", timeout=1).read().decode()
                self.token = re.search(r'const TOKEN = "([a-f0-9]+)"', html).group(1)
                break
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.05)
        else:
            self.stop()
            raise RuntimeError("server did not start: " + self.proc.stdout.read().decode())

    def request(self, path, body=None, token=True, host=None):
        headers = {"Content-Type": "application/json"}
        if token:
            headers["X-Token"] = self.token
        if host:
            headers["Host"] = host
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())

    def get(self, path):
        status, data = self.request(path)
        assert status == 200, data
        return data

    def post(self, path, body):
        status, data = self.request(path, body)
        assert status == 200, data
        return data

    def post_error(self, path, body):
        status, data = self.request(path, body)
        assert status != 200, f"expected an error, got {data}"
        return data["error"]

    def restore_all(self):
        for b in self.get("/api/backups"):  # newest first
            if b["restorable"]:
                self.post("/api/backups/restore", {"name": b["name"]})

    def stop(self):
        self.proc.terminate()
        self.proc.wait(timeout=5)


@pytest.fixture
def home(tmp_path):
    h = FakeHome(tmp_path / "home")
    h.root.mkdir()
    return h


@pytest.fixture
def app_factory(home):
    apps = []

    def make(**env):
        a = App(home, env)
        apps.append(a)
        return a

    yield make
    for a in apps:
        a.stop()
