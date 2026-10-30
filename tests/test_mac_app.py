"""The Mac app: install-app, kept up to date by the server, the About panel, uninstall.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import time
import urllib.request

import pytest

from conftest import SRC, child_env, free_port
from helpers import basic_home, fake_pipx, run_cli


def fake_app_binary(home):
    """Stands in for the compiled Mac app (src/cc_profiles/app/cc-profiles-app): only copied."""
    return str(home.write("build/cc-profiles-app", "#!/bin/sh\n"))


def read_plist(path):
    return plistlib.loads(path.read_bytes())


def test_install_app_puts_together_the_mac_app(home, app_factory):
    """install-app: ~/Applications/cc-profiles.app with the program, its Info.plist (marked), the
    icon and launch.json (the command and port); undone from its backup; a foreign app is left alone."""
    basic_home(home)
    sys.path.insert(0, str(SRC))
    from cc_profiles import __version__
    app = app_factory()
    binary = fake_app_binary(home)
    before = home.snapshot()

    r = run_cli(home, "install-app", "--port", "4790", CC_PROFILES_APP_BINARY=binary)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Created ~/Applications/cc-profiles.app" in r.stdout and "Backup:" in r.stdout
    contents = home.path("Applications/cc-profiles.app/Contents")
    exe = contents / "MacOS" / "cc-profiles"
    assert exe.read_text() == "#!/bin/sh\n" and os.access(exe, os.X_OK)
    info = read_plist(contents / "Info.plist")
    assert info["CCProfilesManaged"] is True and info["CFBundleExecutable"] == "cc-profiles"
    assert info["CFBundleShortVersionString"] == __version__
    assert [x["NSMessage"] for x in info["NSServices"]] == ["openInClaude", "openInClaudeWithProfile"]
    launch = json.loads((contents / "Resources" / "launch.json").read_text())
    assert launch == {"command": [sys.executable, "-m", "cc_profiles"], "port": 4790}
    icns = (contents / "Resources" / "AppIcon.icns").read_bytes()
    assert icns[:4] == b"icns" and struct.unpack(">I", icns[4:8])[0] == len(icns) and b"ic10" in icns

    again = run_cli(home, "install-app", "--port", "4790", CC_PROFILES_APP_BINARY=binary)
    assert "already up to date" in again.stdout and "Backup:" not in again.stdout
    moved = run_cli(home, "install-app", "--port", "4791", CC_PROFILES_APP_BINARY=binary)
    assert "Updated ~/Applications/cc-profiles.app" in moved.stdout
    assert json.loads((contents / "Resources" / "launch.json").read_text())["port"] == 4791

    for b in app.get("/api/backups")[:2]:  # newest first: the update, then the first install
        app.post("/api/backups/restore", {"name": b["name"]})
    assert home.snapshot() == before

    home.write("Applications/cc-profiles.app/Contents/Info.plist", "not ours\n")
    r = run_cli(home, "install-app", CC_PROFILES_APP_BINARY=binary)
    assert r.returncode == 1 and "was not created by cc-profiles" in r.stdout
    assert home.path("Applications/cc-profiles.app/Contents/Info.plist").read_text() == "not ours\n"


def test_the_server_keeps_the_mac_app_up_to_date_and_uninstall_removes_it(home, app_factory):
    """An app from an older version is rewritten when the server starts, keeping its port;
    cc-profiles uninstall removes it with the /cc-profiles command."""
    basic_home(home)
    binary = fake_app_binary(home)
    assert run_cli(home, "install-app", "--port", "4790", CC_PROFILES_APP_BINARY=binary).returncode == 0
    plist = home.path("Applications/cc-profiles.app/Contents/Info.plist")
    current = read_plist(plist)["CFBundleShortVersionString"]
    plist.write_bytes(plistlib.dumps(dict(read_plist(plist), CFBundleShortVersionString="0.0.1")))

    app = app_factory(CC_PROFILES_APP_BINARY=binary)
    assert read_plist(plist)["CFBundleShortVersionString"] == current
    launch = json.loads(home.path("Applications/cc-profiles.app/Contents/Resources/launch.json").read_text())
    assert launch["port"] == 4790
    assert app.get("/api/backups")[0]["title"] == "Update the Mac app"
    app.stop()

    fake_pipx(home)
    r = run_cli(home, "uninstall", "--yes", "--port", str(free_port()), CC_PROFILES_INSTALL_KIND="pipx",
                CC_PROFILES_APP_BINARY=binary)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "removes the Mac app" in r.stdout and not home.path("Applications/cc-profiles.app").exists()


@pytest.mark.skipif(not os.environ.get("CC_PROFILES_APP_SMOKE"), reason="opens a window: CI's Mac app job only")
def test_the_mac_app_starts_the_server(home):
    """The compiled app (scripts/build_app.py), opened on a fake home, starts the server on its port."""
    basic_home(home)
    port = free_port()
    assert run_cli(home, "install-app", "--port", str(port)).returncode == 0
    exe = home.path("Applications/cc-profiles.app/Contents/MacOS/cc-profiles")
    env = child_env({"HOME": str(home.root), "CFFIXED_USER_HOME": str(home.root),  # its settings, WebKit data
                     "PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC),
                     "CC_PROFILES_AUTO_COMMAND": "0", "CC_PROFILES_AUTO_GITHUB": "0"})
    proc = subprocess.Popen([str(exe)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    server = None
    try:
        deadline = time.time() + 60
        while time.time() < deadline and not server:
            try:
                server = urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=1).headers["Server"]
            except OSError:
                time.sleep(0.5)
        assert server and server.startswith("cc-profiles/"), "the app did not start the server"
        assert proc.poll() is None, "the app quit"
    finally:
        proc.terminate()
        run_cli(home, "stop", "--port", str(port))


def test_the_about_panel_adds_and_updates_the_mac_app(home, app_factory):
    """GET /api/macapp says whether the app is there; POST adds it or brings it up to date,
    on the server's port, with a backup."""
    basic_home(home)
    binary = fake_app_binary(home)
    app = app_factory(CC_PROFILES_APP_BINARY=binary)
    before = home.snapshot()
    assert app.get("/api/macapp") == {"supported": True, "state": "missing", "path": "~/Applications/cc-profiles.app",
                                      "port": None}
    r = app.post("/api/macapp", {})
    assert r["state"] == "current" and r["port"] == app.port and r["backup"]
    assert r["message"].startswith("Created ~/Applications/cc-profiles.app")
    assert run_cli(home, "install-app", "--port", "4790", CC_PROFILES_APP_BINARY=binary).returncode == 0
    assert app.get("/api/macapp")["state"] == "outdated"  # another port than this server's
    assert app.post("/api/macapp", {})["port"] == app.port
    for b in app.get("/api/backups")[:3]:
        app.post("/api/backups/restore", {"name": b["name"]})
    assert home.snapshot() == before
    if sys.platform != "darwin":
        assert app_factory().get("/api/macapp") == {"supported": False}


def test_the_server_adds_the_mac_app_once(home, app_factory):
    """The first start on macOS adds the app, as /cc-profiles is added; a deleted app stays
    deleted, and install-app --off (install.sh --no-app) keeps it from being added at all."""
    basic_home(home)
    binary = fake_app_binary(home)
    before = home.snapshot()
    app = app_factory(CC_PROFILES_APP_BINARY=binary, CC_PROFILES_AUTO_APP="1")
    contents = home.path("Applications/cc-profiles.app/Contents")
    assert read_plist(contents / "Info.plist")["CCProfilesManaged"] is True
    assert json.loads((contents / "Resources" / "launch.json").read_text())["port"] == app.port
    assert json.loads(home.path(".cc-profiles/config.json").read_text())["mac_app"] is True
    app.stop()

    shutil.rmtree(home.path("Applications/cc-profiles.app"))  # moved to the Trash
    app = app_factory(CC_PROFILES_APP_BINARY=binary, CC_PROFILES_AUTO_APP="1")
    assert not home.path("Applications/cc-profiles.app").exists()
    app.stop()

    shutil.rmtree(home.path(".cc-profiles"))  # from the start, with --no-app
    shutil.rmtree(home.path("Applications"))
    r = run_cli(home, "install-app", "--off", CC_PROFILES_APP_BINARY=binary)
    assert "will not add the Mac app" in r.stdout and "Backup:" in r.stdout
    app = app_factory(CC_PROFILES_APP_BINARY=binary, CC_PROFILES_AUTO_APP="1")
    assert not home.path("Applications/cc-profiles.app").exists()
    assert json.loads(home.path(".cc-profiles/config.json").read_text())["mac_app"] is False
    r = run_cli(home, "install-app", "--port", str(app.port), CC_PROFILES_APP_BINARY=binary)  # changed their mind
    assert "Created" in r.stdout and json.loads(home.path(".cc-profiles/config.json").read_text())["mac_app"] is True
    app.restore_all()
    shutil.rmtree(home.path(".cc-profiles"))
    assert home.snapshot() == before


def test_install_app_is_for_macos(home):
    if sys.platform == "darwin":
        pytest.skip("macOS builds the app")
    r = run_cli(home, "install-app")
    assert r.returncode == 1 and "macOS only" in r.stdout


def test_the_cli_shows_the_mac_app_when_it_is_installed(home):
    """app_for(): `cc-profiles open` shows the Mac app only when it is ours and on the same port."""
    res = home.path("Applications/cc-profiles.app/Contents/Resources")
    res.mkdir(parents=True)
    (res / "launch.json").write_text(json.dumps({"command": ["x"], "port": 4777}))

    def app_for(port):
        code = f"import sys; sys.platform = 'darwin'; from cc_profiles import macapp; print(macapp.app_for({port}))"
        env = child_env({"HOME": str(home.root), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC)})
        return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout.strip()

    (res.parent / "Info.plist").write_bytes(plistlib.dumps({"CCProfilesManaged": True}))
    assert app_for(4777) == str(res.parent.parent) and app_for(4778) == "None"
    (res.parent / "Info.plist").write_bytes(plistlib.dumps({}))  # another app with the same name
    assert app_for(4777) == "None"
