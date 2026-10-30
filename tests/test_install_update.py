"""Installing Claude Code (dry run) and updating cc-profiles (PyPI replaced by a local file).

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import sys
import time

import pytest

from conftest import SRC
from helpers import basic_home, fake_tool, pypi


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
