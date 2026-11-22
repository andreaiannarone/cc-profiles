"""The Linux app: a desktop entry in the applications menu, kept up to date by the server,
shown from the About panel, opened in a window of its own, removed by uninstall.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json
import os
import subprocess
import sys

from conftest import SRC, child_env, free_port
from helpers import basic_home, fake_pipx, run_cli

LINUX = {"CC_PROFILES_LINUX_APP": "1", "CC_PROFILES_APP_BROWSER": ""}
ENTRY = ".local/share/applications/cc-profiles.desktop"
ICON = ".local/share/icons/hicolor/256x256/apps/cc-profiles.png"


def entry(home):
    return dict(l.split("=", 1) for l in home.path(ENTRY).read_text().splitlines() if "=" in l)


def test_install_app_adds_cc_profiles_to_the_applications_menu(home, app_factory):
    """install-app on Linux: a marked desktop entry running `cc-profiles open` on its port, and the
    icon; undone from its backup; an entry someone else wrote is left alone."""
    basic_home(home)
    app = app_factory()
    before = home.snapshot()

    r = run_cli(home, "install-app", "--port", "4790", **LINUX)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Added cc-profiles in your applications menu" in r.stdout and "No Chrome" in r.stdout
    e = entry(home)
    assert e["X-CC-Profiles-Managed"] == "true" and e["X-CC-Profiles-Port"] == "4790" and e["Type"] == "Application"
    assert e["Exec"].endswith(" open --port 4790") and e["Icon"] == str(home.path(ICON))
    assert home.path(ICON).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
    assert "already in your applications menu" in run_cli(home, "install-app", "--port", "4790", **LINUX).stdout
    assert "Updated" in run_cli(home, "install-app", "--port", "4791", **LINUX).stdout
    assert entry(home)["X-CC-Profiles-Port"] == "4791"

    for b in app.get("/api/backups")[:2]:  # newest first
        app.post("/api/backups/restore", {"name": b["name"]})
    assert home.snapshot() == before

    home.write(ENTRY, "[Desktop Entry]\nName=Someone else's\n")
    r = run_cli(home, "install-app", **LINUX)
    assert r.returncode == 1 and "was not created by cc-profiles" in r.stdout
    assert "Someone else's" in home.path(ENTRY).read_text()


def test_the_server_adds_the_entry_once_and_keeps_it_current(home, app_factory):
    """The first start adds the entry; an outdated one is rewritten keeping its port; a removed one
    stays removed; the About panel adds or updates it; uninstall removes it with its icon."""
    basic_home(home)
    app = app_factory(CC_PROFILES_AUTO_APP="1", **LINUX)
    assert entry(home)["X-CC-Profiles-Port"] == str(app.port)
    assert json.loads(home.path(".cc-profiles/config.json").read_text())["linux_app"] is True
    s = app.get("/api/macapp")
    assert (s["kind"], s["state"], s["window"]) == ("linux", "current", False)
    app.stop()

    text = home.path(ENTRY).read_text()
    home.path(ENTRY).write_text(text.replace("X-CC-Profiles-Version=", "X-CC-Profiles-Version=0.0.1-was-"))
    app = app_factory(CC_PROFILES_AUTO_APP="1", **LINUX)
    assert entry(home)["X-CC-Profiles-Version"] != "0.0.1-was-" and "0.0.1" not in home.path(ENTRY).read_text()
    assert app.get("/api/backups")[0]["title"] == "Update the Linux app"
    app.stop()

    home.path(ENTRY).unlink()  # removed by the user
    app = app_factory(CC_PROFILES_AUTO_APP="1", **LINUX)
    assert not home.path(ENTRY).exists() and app.get("/api/macapp")["state"] == "missing"
    r = app.post("/api/macapp", {})  # the About panel's button
    assert r["state"] == "current" and r["port"] == app.port and r["backup"]
    app.stop()

    fake_pipx(home)
    r = run_cli(home, "uninstall", "--yes", "--port", str(free_port()), CC_PROFILES_INSTALL_KIND="pipx", **LINUX)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "removes cc-profiles from the applications menu" in r.stdout
    assert not home.path(ENTRY).exists() and not home.path(ICON).exists()


def test_open_shows_the_page_in_a_window_of_its_own(home):
    """With the entry on this port and a Chromium-based browser, `open` runs it in app mode."""
    calls = home.path("browser-calls")
    browser = home.write("bin/chromium", f"#!/bin/sh\necho \"$@\" >> {calls}\n")
    browser.chmod(0o755)
    assert run_cli(home, "install-app", "--port", "4790", **LINUX).returncode == 0

    def window_for(port, browser_path):
        code = f"from cc_profiles import linuxapp; print(linuxapp.window_for({port}))"
        env = child_env({"HOME": str(home.root), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC),
                         "CC_PROFILES_LINUX_APP": "1", "CC_PROFILES_APP_BROWSER": browser_path})
        return subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True).stdout.strip()

    assert window_for(4790, str(browser)) == f"['{browser}', '--app=http://127.0.0.1:4790', '--class=cc-profiles']"
    assert window_for(4791, str(browser)) == "None"  # another port: the browser as usual
    assert window_for(4790, "") == "None"  # no app-mode browser
    home.path(ENTRY).write_text("[Desktop Entry]\nX-CC-Profiles-Port=4790\n")  # not ours
    assert window_for(4790, str(browser)) == "None"
    assert not os.path.exists(calls)
