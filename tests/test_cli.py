"""The command line: open, stop, restart, label, install-command, uninstall and reinstall.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json
import os
import re
import signal
import socket
import struct
import subprocess
import sys
import urllib.request

import pytest

from conftest import SRC, child_env, free_port
from helpers import basic_home, fake_pipx, is_current_command, run_cli


# --- command line ---------------------------------------------------------------


def test_label_command(home, app_factory):
    basic_home(home)
    app_factory()  # first run writes the config
    assert run_cli(home, "label").stdout.strip() == "Default"
    assert run_cli(home, "label", CLAUDE_CONFIG_DIR=str(home.path(".claude-work"))).stdout.strip() == "Work"


def test_favicons_for_safari(home, app_factory):
    """Safari ignores the inline SVG favicon: the server also sends a PNG and an .ico."""
    app = app_factory()
    html = urllib.request.urlopen(app.base + "/").read().decode()
    assert 'href="/favicon.png"' in html and 'href="/apple-touch-icon.png"' in html
    for path, ctype, side in (("/favicon.png", "image/png", 96), ("/apple-touch-icon.png", "image/png", 180)):
        r = urllib.request.urlopen(app.base + path)
        data = r.read()
        assert r.headers["Content-Type"] == ctype and data.startswith(b"\x89PNG\r\n\x1a\n")
        assert struct.unpack(">II", data[16:24]) == (side, side)
    ico = urllib.request.urlopen(app.base + "/favicon.ico").read()
    assert ico[:6] == b"\0\0\1\0\1\0" and ico[6] == 48 and ico[22:26] == b"\x89PNG"


def test_open_command(home):
    port = free_port()
    first = run_cli(home, "open", "--no-browser", "--port", str(port))
    assert first.returncode == 0, first.stdout + first.stderr
    pid = int(re.search(r"pid (\d+)", first.stdout).group(1))
    try:
        assert "started in the background" in first.stdout
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).status == 200
        again = run_cli(home, "open", "--no-browser", "--port", str(port))
        assert again.returncode == 0 and "already running" in again.stdout
    finally:
        os.kill(pid, signal.SIGTERM)


def test_stop_and_restart_commands(home):
    port = free_port()
    first = run_cli(home, "open", "--no-browser", "--port", str(port))
    pid = int(re.search(r"pid (\d+)", first.stdout).group(1))
    assert f"Stop it with: cc-profiles stop --port {port}" in first.stdout
    pids = [pid]
    try:
        r = run_cli(home, "restart", "--port", str(port))
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"Stopped cc-profiles on http://127.0.0.1:{port} (pid {pid})" in r.stdout
        new = int(re.search(r"started in the background .* \(pid (\d+)\)", r.stdout).group(1))
        pids.append(new)
        assert new != pid and "Reload the page" in r.stdout
        assert urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5).headers["X-CC-Profiles-Pid"] == str(new)
        r = run_cli(home, "stop", "--port", str(port))
        assert r.returncode == 0 and f"(pid {new})" in r.stdout
        with pytest.raises(OSError):
            urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2)
        assert "is not running" in run_cli(home, "stop", "--port", str(port)).stdout
    finally:
        for p in pids:
            try:
                os.kill(p, signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_open_with_an_action_restarts_or_stops(home):
    """/cc-profiles restart and /cc-profiles stop: Claude Code puts the arguments in
    place of $ARGUMENTS in the command's ! line, which then runs cc-profiles open <action>."""
    basic_home(home)
    run_cli(home, "install-command")
    text = home.path(".claude/commands/cc-profiles.md").read_text()
    line = re.search(r"^!`(.*)`$", text, re.M).group(1)
    exe = line[:-len(" open $ARGUMENTS")]
    assert line.endswith(" open $ARGUMENTS") and f"allowed-tools: Bash({exe} open:*)" in text
    assert os.path.isabs(exe.split()[0]), "an absolute path: Claude Code's PATH may not have cc-profiles"

    def slash(arguments):  # what Claude Code does: the ! line, in a shell whose PATH has no cc-profiles
        cmd = line.replace("$ARGUMENTS", arguments) + f" --no-browser --port {port}"
        e = child_env({"HOME": str(home.root), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC)})
        return subprocess.run(cmd, shell=True, env=e, capture_output=True, text=True, timeout=60)

    port = free_port()
    first = slash("")
    assert first.returncode == 0, first.stdout + first.stderr
    pids = [int(re.search(r"pid (\d+)", first.stdout).group(1))]
    try:
        r = slash("restart")
        assert r.returncode == 0, r.stdout + r.stderr
        assert f"(pid {pids[0]})" in r.stdout and "Reload the page" in r.stdout
        pids.append(int(re.search(r"started in the background .* \(pid (\d+)\)", r.stdout).group(1)))
        r = slash("stop")
        assert r.returncode == 0 and f"Stopped cc-profiles on http://127.0.0.1:{port} (pid {pids[1]})" in r.stdout
        r = slash("bogus")
        assert r.returncode == 2 and "unknown action: bogus" in r.stderr
        assert "is not running" in slash("stop").stdout
    finally:
        for p in pids:
            try:
                os.kill(p, signal.SIGTERM)
            except ProcessLookupError:
                pass


def test_stop_leaves_other_programs_alone(home):
    with socket.socket() as other:  # not cc-profiles: nothing to stop
        other.bind(("127.0.0.1", 0))
        other.listen()
        r = run_cli(home, "stop", "--port", str(other.getsockname()[1]))
    assert r.returncode == 0 and "is not running" in r.stdout


def test_open_command_port_taken(home):
    with socket.socket() as other:  # another program on the port
        other.bind(("127.0.0.1", 0))
        other.listen()
        r = run_cli(home, "open", "--no-browser", "--port", str(other.getsockname()[1]))
    assert r.returncode == 1
    assert "did not start" in r.stdout and "is busy" in r.stdout


def test_install_command(home, app_factory):
    basic_home(home)
    home.profile("client")
    home.write(".claude-client/commands/cc-profiles.md", "my own command\n")  # not ours: left alone
    home.profile("shared")
    app = app_factory()
    app.post("/api/sharing", {"profile": "shared", "item": "commands", "shared": True})
    before = home.snapshot()

    out = run_cli(home, "install-command").stdout
    assert "Default: added ~/.claude/commands/cc-profiles.md" in out
    assert "Work: added ~/.claude-work/commands/cc-profiles.md" in out
    assert "Client: skipped" in out and "Shared: shares commands with Default" in out
    text = home.path(".claude/commands/cc-profiles.md").read_text()
    assert is_current_command(text) and "argument-hint:" in text
    assert home.path(".claude-client/commands/cc-profiles.md").read_text() == "my own command\n"
    assert home.path(".claude-shared/commands/cc-profiles.md").read_text() == text  # through the link

    again = run_cli(home, "install-command").stdout
    assert "Backup:" not in again and again.count("already up to date") == 2

    newest = app.get("/api/backups")[0]
    assert newest["title"] == "Add the /cc-profiles command"
    app.post("/api/backups/restore", {"name": newest["name"]})
    assert home.snapshot() == before


def test_install_command_updates_an_older_command(home):
    """A command written by an older version (before /cc-profiles restart|stop) is rewritten."""
    sys.path.insert(0, str(SRC))
    from cc_profiles import server
    basic_home(home)
    old = server.command_text("cc-profiles").replace("!`cc-profiles open $ARGUMENTS`", "!`cc-profiles open`")
    old = old.replace('argument-hint: "[restart|stop]"\n', "")
    home.write(".claude/commands/cc-profiles.md", old)
    out = run_cli(home, "install-command").stdout
    assert "Default: updated ~/.claude/commands/cc-profiles.md" in out
    assert is_current_command(home.path(".claude/commands/cc-profiles.md").read_text())


def test_server_adds_the_command_the_first_time_then_only_updates_it(home, app_factory):
    """No need for `cc-profiles install-command`: the first start adds /cc-profiles everywhere,
    later starts rewrite only the copies an older version wrote, and a deleted one stays deleted."""
    basic_home(home)
    app = app_factory(CC_PROFILES_AUTO_COMMAND="")
    for d in (".claude", ".claude-work"):
        assert is_current_command(home.path(f"{d}/commands/cc-profiles.md").read_text())
    assert json.loads(home.path(".cc-profiles/config.json").read_text())["slash_command"] is True
    assert app.get("/api/backups")[0]["title"] == "Add the /cc-profiles command"
    app.stop()

    home.path(".claude-work/commands/cc-profiles.md").unlink()  # the user does not want it there
    current = home.path(".claude/commands/cc-profiles.md").read_text()
    home.write(".claude/commands/cc-profiles.md", current.replace("one short line", "a line"))  # an older version
    app = app_factory(CC_PROFILES_AUTO_COMMAND="")
    assert home.path(".claude/commands/cc-profiles.md").read_text() == current
    assert not home.path(".claude-work/commands/cc-profiles.md").exists()
    assert app.get("/api/backups")[0]["title"] == "Update the /cc-profiles command"
    n = len(app.get("/api/backups"))
    app.stop()
    app = app_factory(CC_PROFILES_AUTO_COMMAND="")  # nothing to do: no new backup
    assert len(app.get("/api/backups")) == n


def test_install_command_off(home, app_factory):
    """install-command --off (install.sh --no-command runs it): the app never adds the command,
    not at start and not in new profiles; install-command turns it back on."""
    basic_home(home)
    r = run_cli(home, "install-command", "--off")
    assert r.returncode == 0 and "no longer add" in r.stdout
    assert json.loads(home.path(".cc-profiles/config.json").read_text())["slash_command"] is False
    app = app_factory(CC_PROFILES_AUTO_COMMAND="")
    assert not home.path(".claude/commands/cc-profiles.md").exists()
    app.post("/api/profiles/create", {"label": "Side", "id": "side", "base": "", "share": []})
    assert not home.path(".claude-side/commands/cc-profiles.md").exists()
    out = run_cli(home, "install-command").stdout
    assert "Default: added" in out
    assert json.loads(home.path(".cc-profiles/config.json").read_text())["slash_command"] is True


def test_uninstall_removes_what_cc_profiles_added(home, app_factory):
    basic_home(home)
    app = app_factory(CC_PROFILES_AUTO_COMMAND="")  # writes /cc-profiles in both profiles
    app.post("/api/shell", {"install": True})
    app.stop()
    rcs = lambda: "".join(home.path(f).read_text() for f in (".zshrc", ".bashrc", ".bash_profile") if home.path(f).exists())
    assert "cc-profiles: profile by folder" in rcs()  # .zshrc or .bashrc, after the shell
    home.write(".claude-other/commands/cc-profiles.md", "my own command\n")
    calls = fake_pipx(home)
    port = str(free_port())

    # asked without a terminal: nothing happens
    r = run_cli(home, "uninstall", "--port", port, CC_PROFILES_INSTALL_KIND="pipx")
    assert r.returncode == 1 and "Nothing was changed" in r.stdout and not calls.exists()
    assert "pipx uninstall cc-profiles" in r.stdout and "are not touched" in r.stdout

    r = run_cli(home, "uninstall", "--yes", "--port", port, CC_PROFILES_INSTALL_KIND="pipx")
    assert r.returncode == 0, r.stdout + r.stderr
    assert calls.read_text() == "uninstall cc-profiles\n"
    assert not home.path(".claude/commands/cc-profiles.md").exists()
    assert not home.path(".claude-work/commands/cc-profiles.md").exists()
    assert home.path(".claude-other/commands/cc-profiles.md").read_text() == "my own command\n"
    assert "cc-profiles: profile by folder" not in rcs()
    assert json.loads(home.path(".cc-profiles/config.json").read_text())["slash_command"] is False
    assert "Backup:" in r.stdout and home.path(".cc-profiles/backups").is_dir()
    assert home.path(".claude/projects").is_dir()  # the profiles stay

    # --purge deletes the app's data too
    r = run_cli(home, "uninstall", "--yes", "--purge", "--port", port, CC_PROFILES_INSTALL_KIND="pipx")
    assert r.returncode == 0 and not home.path(".cc-profiles").exists()


def test_reinstall(home, app_factory):
    basic_home(home)
    app_factory().stop()
    calls = fake_pipx(home)
    port = str(free_port())
    r = run_cli(home, "reinstall", "--yes", "--port", port, CC_PROFILES_INSTALL_KIND="pipx")
    assert r.returncode == 0, r.stdout + r.stderr
    assert calls.read_text() == "install --force cc-profiles\n" and "reinstalled" in r.stdout
    assert home.path(".cc-profiles/config.json").exists()  # settings and backups are kept
    r = run_cli(home, "reinstall", "--yes", "--port", port, CC_PROFILES_INSTALL_KIND="source")
    assert r.returncode == 1 and "source checkout" in r.stdout
    r = run_cli(home, "uninstall", "--yes", "--port", port, CC_PROFILES_INSTALL_KIND="uv")
    assert r.returncode == 1 and "uv is not installed" in r.stdout


def test_plugin_command_matches_installed_command():
    sys.path.insert(0, str(SRC))
    from cc_profiles import server
    plugin = (SRC.parent / "plugin" / "commands" / "open.md").read_text()
    assert plugin == server.command_text("cc-profiles", mark=False)


def test_install_script_options():
    script = str(SRC.parent / "install.sh")
    assert subprocess.run(["sh", "-n", script]).returncode == 0
    with open(script) as f:  # piped, as with curl | sh
        r = subprocess.run(["sh", "-s", "--", "--help"], stdin=f, capture_output=True, text=True)
    assert r.returncode == 0 and "--no-command" in r.stdout and "--no-app" in r.stdout
    assert subprocess.run(["sh", script, "--nope"], capture_output=True).returncode == 2


def test_version_command(home):
    out = run_cli(home, "--version").stdout
    assert out.startswith("cc-profiles ")
