"""Installing Claude Code (dry run) and updating cc-profiles (PyPI replaced by a local file).

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest

from conftest import SRC
from helpers import basic_home, fake_tool, pypi

sys.path.insert(0, str(SRC))
from cc_profiles import updater as U  # noqa: E402
from cc_profiles.core import ApiError  # noqa: E402


# --- installing Claude Code (dry run: nothing is installed) --------------------


def wait_job(app):
    for _ in range(100):
        st = app.get("/api/claude/status")
        if not st["job"]["running"]:
            return st
        time.sleep(0.1)
    raise AssertionError("install job did not finish")


def test_install_dry_run(home, app_factory):
    basic_home(home)
    app = app_factory()
    st = app.get("/api/claude/status")
    assert st["installed"] is False
    assert "Unknown install method" in app.post_error("/api/claude/install", {"method": "rm -rf /"})
    app.post("/api/claude/install", {"method": "native"})
    assert "already running" in app.post_error("/api/claude/install", {"method": "native"})
    st = wait_job(app)
    assert st["job"]["code"] == 0 and "dry run ok" in st["job"]["lines"]


def test_install_failure_is_reported(home, app_factory):
    basic_home(home)
    app = app_factory(CC_PROFILES_INSTALL_DRYRUN_CODE="7")
    app.post("/api/claude/install", {"method": "native"})
    assert wait_job(app)["job"]["code"] == 7


# --- updating cc-profiles (PyPI replaced by a local file) ------------------------


def test_update_check_compares_with_pypi(home, app_factory, tmp_path):
    sys.path.insert(0, str(SRC))
    from cc_profiles import server
    current = server.__version__
    newer = app_factory(CC_PROFILES_PYPI_URL=pypi(tmp_path, "99.0.0")).get("/api/update")
    assert newer["current"] == current and newer["latest"] == "99.0.0" and newer["newer"] is True
    # the tests run from the source folder: no self-update, but the way to do it by hand
    assert newer["kind"] == "source" and newer["can_update"] is False and "git pull" in newer["manual"]
    same = app_factory(CC_PROFILES_PYPI_URL=pypi(tmp_path, current))
    assert same.get("/api/update")["newer"] is False
    assert "already the latest" in same.post("/api/update", {})["message"]
    src = app_factory(CC_PROFILES_PYPI_URL=pypi(tmp_path, "99.0.0"))
    assert "cannot update itself" in src.post_error("/api/update", {})
    offline = app_factory(CC_PROFILES_PYPI_URL=(tmp_path / "missing.json").as_uri())
    status, body = offline.request("/api/update")
    assert status == 502 and "Could not reach PyPI" in body["error"]


@pytest.mark.parametrize("kind,output,code", [
    ("pipx", "cc-profiles is already at latest version 0.0.1 (location: /x)", 0),  # pipx, right after a release
    ("pipx", "ERROR: Could not find a version that satisfies the requirement cc-profiles==99.0.0\n"
             "ERROR: No matching distribution found for cc-profiles==99.0.0", 1),
    ("uv", "Nothing to upgrade", 0),
    ("uv", "Updated cc-profiles", 0),  # it ran, but the installed version did not change
])
def test_update_right_after_a_release_says_to_try_again(home, app_factory, tmp_path, kind, output, code):
    app = app_factory(CC_PROFILES_PYPI_URL=pypi(tmp_path, "99.0.0"), CC_PROFILES_INSTALL_KIND=kind,
                      PATH=fake_tool(tmp_path, kind, output, code))
    info = app.get("/api/update")
    assert info["can_update"] is True and info["kind"] == kind
    r = app.post("/api/update", {})
    assert r["retry"] is True and r["restarting"] is False
    assert "99.0.0 was published only minutes ago" in r["message"] and "try again in a few minutes" in r["message"]
    assert "ERROR" not in r["message"] and output.splitlines()[-1] in r["details"]
    assert r["details"].startswith("$ " + " ".join(server_update_command(kind)))


def server_update_command(kind):
    sys.path.insert(0, str(SRC))
    from cc_profiles import server
    return server.UPDATE_COMMANDS[kind]


def test_update_that_fails_for_another_reason(home, app_factory, tmp_path):
    app = app_factory(CC_PROFILES_PYPI_URL=pypi(tmp_path, "99.0.0"), CC_PROFILES_INSTALL_KIND="pipx",
                      PATH=fake_tool(tmp_path, "pipx", "Fatal: disk full", 3))
    error = app.post_error("/api/update", {})
    assert "The update failed (pipx upgrade cc-profiles ended with code 3)" in error and "disk full" in error


def test_version_order():
    sys.path.insert(0, str(SRC))
    from cc_profiles.server import version_key
    assert version_key("0.10.1") > version_key("0.9") > version_key("0.2.1") > version_key("0.2.0")
    assert version_key("1.0.0rc1") == version_key("1.0.0")  # pre-releases are not offered as newer


# --- updater helpers and error paths, the Claude Code status ----------------------
def fake_bin(tmp_path, tools):
    """A folder of fake programs ({name: sh body}) first on PATH."""
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    for name, body in tools.items():
        f = d / name
        f.write_text("#!/bin/sh\n" + body + "\n")
        f.chmod(0o755)
    return f"{d}:/usr/bin:/bin"


def test_install_kind(monkeypatch):
    monkeypatch.setenv("CC_PROFILES_INSTALL_KIND", "uv")
    assert U.install_kind() == "uv"
    monkeypatch.delenv("CC_PROFILES_INSTALL_KIND")
    monkeypatch.setattr(U, "APP_DIR", "/home/me/src/cc-profiles/src/cc_profiles")
    assert U.install_kind() == "source"
    monkeypatch.setattr(U, "APP_DIR", "/x/lib/python3.12/site-packages/cc_profiles")
    for prefix, kind in (("/home/me/.local/pipx/venvs/cc-profiles", "pipx"),
                         ("/home/me/.local/share/uv/tools/cc-profiles", "uv"),
                         ("/opt/homebrew/Cellar/cc-profiles/0.5.1/libexec", "brew"),
                         ("/usr/local", "pip")):
        monkeypatch.setattr(sys, "prefix", prefix)
        assert U.install_kind() == kind


def test_the_check_asks_pypi_past_its_cache(monkeypatch, tmp_path):
    """Right after a release PyPI's CDN can answer the previous version: the check asks it not to."""
    asked = []

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"info": {"version": "9.9.9"}}'
    monkeypatch.setattr(U.urllib.request, "urlopen", lambda req, timeout: asked.append(req) or Answer())
    monkeypatch.setattr(U, "UPDATE_STATE", str(tmp_path / "update-check.json"))
    assert U.check_update()["latest"] == "9.9.9"
    assert asked[0].get_header("Cache-control") == "no-cache" and asked[0].full_url == U.PYPI_URL


def test_version_key_of_odd_versions():
    assert U.version_key("") == () and U.version_key(None) == () and U.version_key("dev") == ()
    assert U.version_key("2") == (2,) and U.version_key("1.2.3.post1") == (1, 2, 3)


def test_update_error_classification(monkeypatch):
    monkeypatch.setattr(U, "installed_version", lambda: "1.0.0")
    for sign in U.INDEX_LAG_SIGNS:  # whatever the exit code and case
        assert U.index_lag(1, "ERROR: " + sign.upper(), "2.0.0")
    assert U.index_lag(0, "upgraded", "2.0.0")  # it ran, but the version did not change
    assert not U.index_lag(0, "upgraded", "1.0.0")
    assert not U.index_lag(3, "Fatal: disk full", "2.0.0")  # another failure: reported as one
    monkeypatch.setattr(U, "installed_version", lambda: None)
    assert not U.index_lag(0, "upgraded", "2.0.0")  # unknown: assume it worked


def test_installed_version_when_it_cannot_be_read(monkeypatch):
    assert U.installed_version() not in ("",)  # the real one: a version, or None outside an install

    def boom(*a, **k):
        raise OSError("no python")
    monkeypatch.setattr(U.subprocess, "run", boom)
    assert U.installed_version() is None
    monkeypatch.setattr(U.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "no module"))
    assert U.installed_version() is None
    monkeypatch.setattr(U.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "\n", ""))
    assert U.installed_version() is None
    monkeypatch.setattr(U.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 0, "9.9.9\n", ""))
    assert U.installed_version() == "9.9.9"


def test_successful_update_restarts(monkeypatch):
    """The one path the servers cannot take in a test: the update works, then the server
    re-executes itself on the same port."""
    monkeypatch.delenv("CC_PROFILES_UPDATE_DRYRUN", raising=False)
    monkeypatch.setattr(U, "check_update", lambda: {"newer": True, "can_update": True, "kind": "uv", "latest": "9.0.0",
                                                    "manual": None})
    monkeypatch.setattr(U, "find_tool", lambda name: "/fake/" + name)
    ran = []
    monkeypatch.setattr(U.subprocess, "run", lambda cmd, **k: ran.append(cmd) or subprocess.CompletedProcess(cmd, 0, "Updated", ""))
    monkeypatch.setattr(U, "index_lag", lambda *a: False)
    restarts = []
    monkeypatch.setattr(U, "restart_soon", lambda: restarts.append(1))
    r = U.op_update()
    assert r == {"message": "Updated to cc-profiles 9.0.0. Restarting…", "restarting": True}
    assert ran == [["/fake/uv", "tool", "upgrade", "cc-profiles"]] and restarts == [1]

    monkeypatch.setattr(U, "check_update", lambda: {"newer": True, "can_update": False, "kind": "pip", "latest": "9.0.0",
                                                    "manual": "python3 -m pip install --upgrade cc-profiles"})
    with pytest.raises(ApiError, match="cannot update itself \\(pip\\): run python3 -m pip install"):
        U.op_update()


def test_restart_soon_reexecutes_on_the_same_port(monkeypatch):
    calls = []

    class NowThread:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()
    monkeypatch.setattr(U.threading, "Thread", NowThread)
    monkeypatch.setattr(U.time, "sleep", lambda s: calls.append(("sleep", s)))
    monkeypatch.setattr(U.os, "execv", lambda exe, args: calls.append(("execv", exe, args)))
    monkeypatch.setattr(U.core, "PORT", 4791)
    assert U.restart_soon()
    assert calls == [("sleep", 0.7), ("execv", sys.executable,
                                      [sys.executable, "-m", "cc_profiles", "--port", "4791", "--no-browser"])]


def test_restart_after_a_python_update_uses_the_environments_python(monkeypatch, tmp_path):
    """Homebrew deleted the Python this process runs on: start again with the venv's bin/python3
    (a link that follows the update); with none left, say how to start it by hand."""
    (tmp_path / "bin").mkdir()
    venv_python = tmp_path / "bin" / "python3"
    venv_python.write_text("#!/bin/sh\n")
    venv_python.chmod(0o755)
    monkeypatch.setattr(U.sys, "executable", str(tmp_path / "Cellar" / "3.15.0" / "python3.15"))  # deleted by Homebrew
    monkeypatch.setattr(U.sys, "prefix", str(tmp_path))
    assert U.interpreter() == str(venv_python)

    monkeypatch.setattr(U, "STDLIB_DIR", str(tmp_path / "lib"))  # gone
    monkeypatch.setattr(U, "restart_soon", lambda: False)
    assert U.unexpected_error(LookupError("unknown encoding: idna")) == {
        "error": "Python was updated after cc-profiles started (LookupError: unknown encoding: idna). "
                 "Start it again with cc-profiles restart"}
    monkeypatch.setattr(U, "STDLIB_DIR", str(tmp_path))  # still there: an ordinary error
    assert U.unexpected_error(LookupError("x")) == {"error": "LookupError: x"}
    monkeypatch.undo()
    monkeypatch.setattr(U.sys, "executable", "")
    monkeypatch.setattr(U.sys, "prefix", str(tmp_path / "nowhere"))
    assert U.interpreter() is None and U.restart_soon() is False


def test_the_server_restarts_itself_when_python_was_updated_under_it(home, app_factory, tmp_path):
    """An error after Homebrew replaced Python: the answer says so and asks the page to wait,
    and the server starts again (a new token proves it) instead of failing on every request."""
    basic_home(home)
    stdlib = tmp_path / "stdlib"
    stdlib.mkdir()
    app = app_factory(CC_PROFILES_STDLIB_DIR=str(stdlib), CC_PROFILES_FAULT="create-profile-after-copy")
    status, body = app.request("/api/profiles/create", {"label": "Half", "id": "half", "base": "default", "share": []})
    assert status == 500 and body["error"].startswith("RuntimeError: fault injected") and "restarting" not in body
    stdlib.rmdir()
    old = app.token
    status, body = app.request("/api/profiles/create", {"label": "Half", "id": "half2", "base": "default", "share": []})
    assert status == 500 and body["restarting"] is True
    assert body["error"].startswith("Python was updated after cc-profiles started")
    for _ in range(300):
        try:
            html = urllib.request.urlopen(app.base + "/", timeout=1).read().decode()
            app.token = re.search(r'const TOKEN = "([a-f0-9]+)"', html).group(1)
            if app.token != old:
                break
        except (urllib.error.URLError, ConnectionError):
            pass
        time.sleep(0.1)
    assert app.token != old, "the server did not start again"
    assert app.get("/api/profiles")


@pytest.mark.parametrize("kind", ["pipx", "uv", "brew"])
def test_update_dry_run_names_the_command(home, app_factory, tmp_path, kind):
    app = app_factory(CC_PROFILES_PYPI_URL=pypi(tmp_path, "99.0.0"), CC_PROFILES_INSTALL_KIND=kind,
                      CC_PROFILES_UPDATE_DRYRUN="1", PATH=fake_tool(tmp_path, kind, "never run", 9))
    info = app.get("/api/update")
    assert info["command"] == " ".join(U.UPDATE_COMMANDS[kind]) and info["manual"] is None
    r = app.post("/api/update", {})
    assert r == {"message": f"Dry run: would run {info['command']}.", "restarting": False}


def test_update_check_with_a_bad_answer_from_pypi(home, app_factory, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"releases": {}}))  # no info.version
    app = app_factory(CC_PROFILES_PYPI_URL=bad.as_uri(), CC_PROFILES_INSTALL_KIND="pip")
    status, body = app.request("/api/update")
    assert status == 502 and "Could not reach PyPI" in body["error"]
    bad.write_text("not json")
    assert app.request("/api/update")[0] == 502


def test_claude_status_with_fake_tools(home, app_factory, tmp_path):
    basic_home(home)
    path = fake_bin(tmp_path, {"claude": 'echo "2.1.300 (Claude Code)"', "node": "echo v20.1.0", "npm": "true"})
    app = app_factory(PATH=path)
    st = app.get("/api/claude/status")
    assert st["installed"] and st["version"] == "2.1.300" and st["path"].endswith("fakebin/claude")
    npm = next(m for m in st["methods"] if m["id"] == "npm")
    assert npm == dict(npm, available=False, why="needs Node.js 22 or later (you have 20)")
    assert "npm is not available: needs Node.js 22" in app.post_error("/api/claude/install", {"method": "npm"})
    about = app.get("/api/about")
    assert about["claude"]["Version"] == "2.1.300"


def test_claude_status_when_node_says_nothing_useful(home, app_factory, tmp_path):
    basic_home(home)
    path = fake_bin(tmp_path, {"claude": "exit 1", "node": "echo garbage", "npm": "true"})
    st = app_factory(PATH=path).get("/api/claude/status")
    npm = next(m for m in st["methods"] if m["id"] == "npm")
    assert npm["available"] and npm["why"] == ""  # an unknown Node.js version is not held against it
    assert st["installed"] and st["version"] is None


def test_auto_check_asks_pypi_at_most_once_a_day(tmp_path, monkeypatch):
    monkeypatch.setattr(U, "UPDATE_STATE", str(tmp_path / "update-check.json"))
    monkeypatch.setattr(U, "load_config", lambda: {})
    monkeypatch.delenv("CC_PROFILES_UPDATE_CHECK", raising=False)
    calls = []
    monkeypatch.setattr(U, "check_update", lambda: calls.append(1) or U.write_json(U.UPDATE_STATE, {"checked": U.time.time(), "latest": "99.0.0"}))
    U.auto_check()
    U.auto_check()  # the answer is fresh: PyPI is not asked again
    assert calls == [1]
    U.write_json(U.UPDATE_STATE, {"checked": U.time.time() - U.CHECK_EVERY - 1, "latest": "99.0.0"})
    U.auto_check()
    assert calls == [1, 1]
    monkeypatch.setattr(U, "load_config", lambda: {"update_check": False})  # turned off
    U.write_json(U.UPDATE_STATE, {"checked": 0})
    U.auto_check()
    assert calls == [1, 1]
    monkeypatch.setattr(U, "load_config", lambda: {})
    monkeypatch.setenv("CC_PROFILES_UPDATE_CHECK", "0")  # the tests' own servers
    U.auto_check()
    assert calls == [1, 1]


def test_update_status_and_the_switch(home, app_factory, tmp_path):
    """The page reads the last answer (no request to PyPI); a manual check refreshes it; the switch
    in About writes "update_check" in config.json, with a backup."""
    basic_home(home)
    app = app_factory(CC_PROFILES_PYPI_URL=pypi(tmp_path, "99.0.0"))
    st = app.get("/api/update/auto")
    assert st["latest"] is None and st["newer"] is False and st["enabled"] is False  # off in tests (CC_PROFILES_UPDATE_CHECK=0)
    app.get("/api/update")  # Check for updates
    st = app.get("/api/update/auto")
    assert st["latest"] == "99.0.0" and st["newer"] is True and st["checked"] and "can_update" in st
    assert json.loads(home.path(".cc-profiles/update-check.json").read_text())["latest"] == "99.0.0"

    app2 = app_factory(CC_PROFILES_UPDATE_CHECK="")
    assert app2.get("/api/update/auto")["enabled"] is True
    before = home.snapshot()
    r = app2.post("/api/update/auto", {"enabled": False})
    assert "only when you click" in r["message"]
    assert json.loads(home.path(".cc-profiles/config.json").read_text())["update_check"] is False
    assert app2.get("/api/update/auto")["enabled"] is False
    assert "Nothing to change" in app2.post_error("/api/update/auto", {"enabled": False})
    app2.post("/api/backups/restore", {"name": app2.get("/api/backups")[0]["name"]})
    assert home.snapshot() == before
