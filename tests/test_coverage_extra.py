"""Tests for the paths the main suite leaves out: updating cc-profiles, settings and the
status line (helpers and their error paths), the Claude Code installer, memories,
sharing and the command line.

Pure helpers are tested directly; everything that writes goes through a real server on
a fake home and ends, like test_app.py, by restoring every backup and comparing the
home with how it started.
"""
import json
import os
import socket
import subprocess
import sys

import pytest

from conftest import SRC, child_env, san
from test_app import basic_home, fake_tool, pypi, run_cli

sys.path.insert(0, str(SRC))
from cc_profiles import settings as S  # noqa: E402
from cc_profiles import updater as U  # noqa: E402
from cc_profiles.core import ApiError  # noqa: E402


def fake_bin(tmp_path, tools):
    """A folder of fake programs ({name: sh body}) first on PATH."""
    d = tmp_path / "fakebin"
    d.mkdir(exist_ok=True)
    for name, body in tools.items():
        f = d / name
        f.write_text("#!/bin/sh\n" + body + "\n")
        f.chmod(0o755)
    return f"{d}:/usr/bin:/bin"


def fake_prof(tmp_path, settings=None, local=None, glob=None):
    """A profile dict as core.profiles() returns it, on files in tmp_path."""
    d = tmp_path / "prof"
    d.mkdir(parents=True, exist_ok=True)
    for name, data in (("settings.json", settings), ("settings.local.json", local)):
        if data is not None:
            (d / name).write_text(json.dumps(data))
    if glob is not None:
        (d / ".claude.json").write_text(json.dumps(glob))
    return {"id": "p", "label": "P", "dir_abs": str(d), "config_abs": str(d / ".claude.json")}


# --- settings helpers ---------------------------------------------------------------
def test_get_set_pop_key():
    data = {"a": {"b": 1}, "s": "text"}
    assert S.get_key(data, "a.b") == (True, 1)
    assert S.get_key(data, "a.c") == (False, None)
    assert S.get_key(data, "s.x") == (False, None)  # a string is not an object
    assert S.get_key(data, "a") == (True, {"b": 1})

    S.set_key(data, "x.y.z", 2)
    assert data["x"] == {"y": {"z": 2}}
    with pytest.raises(ApiError, match="“s” is not an object"):
        S.set_key(data, "s.inner", 1)

    S.pop_key(data, "x.y.z")  # the objects it leaves empty go too
    assert "x" not in data
    S.pop_key(data, "a.missing")  # nothing to remove: unchanged
    assert data["a"] == {"b": 1}
    S.pop_key(data, "s.inner")  # not an object: unchanged
    S.pop_key(data, "nope")
    S.pop_key(data, "a.b")
    assert data == {"s": "text"}


def test_effective_precedence_local_then_settings_then_global(tmp_path):
    prof = fake_prof(tmp_path, settings={"model": "opus", "theme": "light", "verbose": True},
                     local={"model": "sonnet"}, glob={"theme": "dark", "verbose": False, "editorMode": "vim"})
    assert S.effective(prof, "model") == ("sonnet", "local")
    # theme is a global key that settings files may also hold: a settings file wins
    assert S.effective(prof, "theme") == ("light", "settings")
    assert S.effective(prof, "editorMode") == ("vim", "global")
    # verbose lives in .claude.json only: settings.json is not read for it
    assert S.effective(prof, "verbose") == (False, "global")
    assert S.effective(prof, "language") == (None, None)
    assert S.effective(prof, "autoCompactEnabled") == (None, None)
    (tmp_path / "prof" / ".claude.json").write_text("[]")  # not an object: as if empty
    assert S.effective(prof, "editorMode") == (None, None)
    assert S.file_error(prof, "global") == "invalid JSON"
    assert S.file_error(fake_prof(tmp_path / "x"), "global") is None


def test_field_options(tmp_path):
    prof = fake_prof(tmp_path)
    styles = tmp_path / "prof" / "output-styles"
    styles.mkdir()
    (styles / "terse.md").write_text("---\nname: Terse\ndescription: Short\n---\nBe brief.\n")
    (styles / "plain.md").write_text("no frontmatter\n")
    fd = S.FIELD_BY_KEY["outputStyle"]

    opts = S.field_options(fd, prof, None)
    values = [o["value"] for o in opts]
    assert values[:4] == ["Proactive", "Concise", "Explanatory", "Learning"] and "default" not in values
    custom = {o["value"]: o for o in opts if o["group"] == "Custom"}
    assert custom["Terse"]["desc"] == "Short · output-styles/terse.md"
    assert custom["plain"]["desc"] == "No description · output-styles/plain.md"
    # "default" is listed only when a profile has it set explicitly
    assert S.field_options(fd, prof, "default")[0]["value"] == "default"
    # a value not in the list is kept as an option, never dropped
    kept = S.field_options(fd, prof, "Gone")[-1]
    assert kept == {"value": "Gone", "label": "Gone (current value)", "desc": "Not a known style: kept so it is not lost",
                    "group": None}
    # plain (value, label) options get no description and no group
    tf = S.field_options(S.FIELD_BY_KEY["timeFormat"], prof, "auto")
    assert tf[0] == {"value": "auto", "label": "Auto", "desc": None, "group": None} and len(tf) == 4
    assert S.field_options(S.FIELD_BY_KEY["language"], prof, "x") is None  # a text field has no options


def test_check_setting_value_for_every_field_type(tmp_path):
    prof = fake_prof(tmp_path, settings={"timeFormat": "auto"})
    check = lambda key, v: S.check_setting_value(S.FIELD_BY_KEY[key], prof, v)  # noqa: E731
    assert check("language", None) is None  # None removes, whatever the type

    # a switch stored as text: off is the empty text, on the key's absence, a custom text kept
    assert check("attribution.commit", False) == ""
    assert check("attribution.commit", True) is None
    assert check("attribution.commit", "  by me  ") == "by me"
    assert check("attribution.commit", "   ") == ""
    with pytest.raises(ApiError, match="true or false"):
        check("attribution.commit", 1)

    assert check("verbose", True) is True
    with pytest.raises(ApiError, match="true or false"):
        check("verbose", "yes")
    # drop_default: thinking on is the key's absence
    assert check("alwaysThinkingEnabled", True) is None and check("alwaysThinkingEnabled", False) is False

    assert check("language", "  Italiano ") == "Italiano"
    assert check("language", "   ") is None
    assert check("language", 5) == "5"

    assert check("timeFormat", "24-hour") == "24-hour"
    with pytest.raises(ApiError, match="time format: pick one of the options"):
        check("timeFormat", "max")

    number = {"key": "n", "type": "number", "label": "N"}  # no field uses it today: the rule still holds
    assert S.check_setting_value(number, prof, 3) == 3
    for bad in (0, -1, True, 1.5, "2"):
        with pytest.raises(ApiError, match="whole number"):
            S.check_setting_value(number, prof, bad)


def test_show_value(tmp_path):
    prof = fake_prof(tmp_path)
    show = lambda key, v: S.show_value(S.FIELD_BY_KEY[key], prof, v)  # noqa: E731
    assert show("language", None) == "the default"
    assert show("attribution.pr", "") == "off" and show("attribution.pr", "via me") == "custom text"
    assert show("language", "") == "none"
    assert show("verbose", True) == "on" and show("verbose", False) == "off"
    assert show("timeFormat", "24-hour-utc") == "24-hour, UTC"
    assert show("language", "Italiano") == '"Italiano"'
    assert show("outputStyle", "Mine") == "Mine (current value)"


def test_status_parts_and_style():
    assert S.status_parts(["model", "nope", "model:round", "context:square", ""]) == [("model", "square"), ("context", "square")]
    with pytest.raises(ApiError, match="Unknown brackets"):
        S.status_parts(["model:zigzag"])
    assert S.status_style("bar", 1) == ("bar", True, "used")
    with pytest.raises(ApiError, match="Unknown separator"):
        S.status_style("tab", True)
    with pytest.raises(ApiError, match="used or left"):
        S.status_style("dot", True, "both")


@pytest.mark.parametrize("text,expected", [
    (None, None),  # no file
    ("#!/bin/sh\n", None),  # too short
    ("#!/bin/sh\n# some other script\n# parts: model\n", None),
    ("#!/bin/sh\n" + S.STATUS_MARK + "\necho hi\n", None),  # no parts line
    ("#!/bin/sh\n" + S.STATUS_MARK + "\n# parts: model:zigzag\n", None),  # brackets it does not know
    # before per-piece brackets: bare ids, no brackets; before the style line: dot, no colors
    ("#!/bin/sh\n" + S.STATUS_MARK + "\n# parts: model context\n",
     {"parts": [("model", "none"), ("context", "none")], "separator": "dot", "colors": False, "limits": "used"}),
    ("#!/bin/sh\n" + S.STATUS_MARK + "\n# parts: model:round\n# style: separator=bar colors=1 limits=left\n",
     {"parts": [("model", "round")], "separator": "bar", "colors": True, "limits": "left"}),
    # values it does not know fall back, stray words are ignored
    ("#!/bin/sh\n" + S.STATUS_MARK + "\n# parts: model:round\n# style: separator=tab junk colors=yes limits=both\n",
     {"parts": [("model", "round")], "separator": "dot", "colors": False, "limits": "used"}),
])
def test_status_script_info_reads_only_its_own_headers(tmp_path, text, expected):
    path = tmp_path / "statusline.sh"
    if text is not None:
        path.write_text(text)
    assert S.status_script_info(str(path)) == expected


def test_status_script_info_reads_back_what_it_writes(tmp_path):
    path = tmp_path / "statusline.sh"
    parts = S.status_parts(["path", "branch:square", "week"])
    path.write_text(S.status_script(parts, "arrow", False, "left"))
    assert S.status_script_info(str(path)) == {"parts": parts, "separator": "arrow", "colors": False, "limits": "left"}


# --- updater helpers ----------------------------------------------------------------
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


def test_wsl_and_system_name(monkeypatch, tmp_path):
    import cc_profiles.core as C
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(C.platform, "system", lambda: "Linux")
    version = tmp_path / "version"
    real_open = open
    for text, wsl in (("Linux version 5.15.153.1-microsoft-standard-WSL2", True), ("Linux version 6.8.0-45-generic", False)):
        version.write_text(text)
        monkeypatch.setattr("builtins.open", lambda f, *a, **k: real_open(version if f == "/proc/version" else f, *a, **k))
        assert C.is_wsl() is wsl
        assert C.system_name().endswith(" · WSL") is wsl and C.system_name().startswith("Linux ")
    monkeypatch.setattr(sys, "platform", "darwin")
    assert not C.is_wsl() and C.system_name().startswith("macOS ")


def test_open_url_uses_windows_under_wsl(monkeypatch):
    import cc_profiles.cli as CLI
    calls = []
    monkeypatch.setattr(CLI.core, "is_wsl", lambda: True)
    monkeypatch.setattr(CLI, "find_tool", lambda name: None if name == "wslview" else "/mnt/c/Windows/System32/cmd.exe")
    monkeypatch.setattr(CLI.subprocess, "Popen", lambda args, **k: calls.append(args))
    monkeypatch.setattr(CLI.webbrowser, "open", lambda url: calls.append(["webbrowser", url]))
    CLI.open_url("http://127.0.0.1:4777")
    assert calls == [["/mnt/c/Windows/System32/cmd.exe", "/c", "start", "", "http://127.0.0.1:4777"]]
    monkeypatch.setattr(CLI.core, "is_wsl", lambda: False)
    CLI.open_url("http://127.0.0.1:4777")
    assert calls[-1] == ["webbrowser", "http://127.0.0.1:4777"]


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
    U.restart_soon()
    assert calls == [("sleep", 0.7), ("execv", sys.executable,
                                      [sys.executable, "-m", "cc_profiles", "--port", "4791", "--no-browser"])]


# --- updating, through the server -----------------------------------------------------
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


# --- settings, through the server ------------------------------------------------------
def test_settings_page_and_its_error_paths(home, app_factory):
    basic_home(home)
    home.json(".claude/settings.json", {"permissions": {"allow": ["Bash(ls)"], "defaultMode": "plan"}})
    home.write(".claude/settings.local.json", "{ broken")
    home.write(".claude/CLAUDE.md", "# rules\n")
    home.write(".claude/output-styles/terse.md", "---\nname: Terse\ndescription: Short\n---\n")
    before = home.snapshot()
    app = app_factory()

    got = app.get("/api/settings?profile=default")
    assert got["files"]["local"]["error"].startswith("invalid JSON") and got["files"]["local"]["raw"] == "{ broken"
    assert got["permissions"] == {"allow": ["Bash(ls)"], "ask": [], "deny": []}
    assert got["claude_md"]["content"] == "# rules\n" and got["global"]["info"]["Account"] == "me@example.com"
    style = next(f for f in got["fields"] if f["key"] == "outputStyle")
    assert "Terse" in [o["value"] for o in style["options"]]
    assert [o["id"] for o in style["others"]] == ["work"]

    P = "/api/settings/field"
    assert "not managed here" in app.post_error(P, {"profile": "default", "key": "env", "value": 1})
    # a value goes where it lives, and an unreadable file is never overwritten
    home.json(".claude/settings.local.json", {"language": "English"})
    home.write(".claude/settings.json", "[1]")
    app.post(P, {"profile": "default", "key": "language", "value": "Italiano"})  # settings.local.json has it
    assert json.loads(home.path(".claude/settings.local.json").read_text()) == {"language": "Italiano"}
    err = app.post_error(P, {"profile": "default", "key": "spinnerTipsEnabled", "value": False})
    assert err.startswith("settings.json has an error (the file does not contain a JSON object)")
    home.write(".claude.json", "{ not json")
    assert "not valid JSON" in app.post_error(P, {"profile": "default", "key": "verbose", "value": True})
    assert "cannot be read" in app.post_error("/api/settings/global", {"profile": "default", "key": "autoUpdates", "value": True})
    home.json(".claude/settings.json", {"permissions": {"allow": ["Bash(ls)"], "defaultMode": "plan"}})
    home.json(".claude.json", {"oauthAccount": {"emailAddress": "me@example.com"},
                               "projects": {str(home.path("code/work/api")): {"allowedTools": ["Bash"]}}})

    # the advanced editor, CLAUDE.md and the global switches
    R = "/api/settings/raw"
    assert "Invalid file" in app.post_error(R, {"profile": "work", "file": "claude.json", "content": "{}"})
    r = app.post(R, {"profile": "work", "file": "local", "content": '{"model": "opus"}'})
    assert r["message"] == "settings.local.json saved."
    assert json.loads(home.path(".claude-work/settings.local.json").read_text()) == {"model": "opus"}
    app.post("/api/settings/claude-md", {"profile": "work", "content": "# no newline"})
    assert home.path(".claude-work/CLAUDE.md").read_text() == "# no newline\n"
    assert app.post("/api/settings/global", {"profile": "work", "key": "autoUpdates", "value": False})["message"] == "autoUpdates: off."
    assert json.loads(home.path(".claude-work/.claude.json").read_text())["autoUpdates"] is False
    assert "cannot be changed" in app.post_error("/api/settings/global", {"profile": "work", "key": "autoUpdates", "value": "no"})

    # permissions: a bad list is refused, empty lists remove the key
    assert "Invalid permissions format" in app.post_error("/api/settings/permissions", {"profile": "work", "rules": {"allow": "Bash"}})
    assert "Invalid permissions format" in app.post_error("/api/settings/permissions", {"profile": "work", "rules": {"deny": [1]}})
    app.post("/api/settings/permissions", {"profile": "default", "rules": {"allow": [" "]}})
    assert json.loads(home.path(".claude/settings.json").read_text())["permissions"] == {"defaultMode": "plan"}
    home.json(".claude-work/settings.json", {"permissions": {"deny": ["x"]}})
    app.post("/api/settings/permissions", {"profile": "work", "rules": {}})
    assert json.loads(home.path(".claude-work/settings.json").read_text()) == {}

    app.restore_all()
    # written by hand above, outside any backup
    home.json(".claude-work/settings.json", {})
    home.write(".claude/settings.local.json", "{ broken")
    assert home.snapshot() == before


def test_apply_to_all_profiles_skips_with_reasons(home, app_factory):
    basic_home(home)
    home.profile("solo")
    home.json(".claude/settings.json", {"outputStyle": "Terse", "spinnerTipsEnabled": "yes"})
    home.write(".claude/output-styles/terse.md", "---\nname: Terse\n---\n")
    home.write(".claude-solo/settings.json", "{ broken")
    home.json(".claude-work/.claude.json", {"projects": {}, "editorMode": "vim"})
    before = home.snapshot()
    app = app_factory()
    PV = "/api/settings/field/all/preview?profile=default&key="

    plan = app.get(PV + "outputStyle")
    reasons = {s["id"]: s["reason"] for s in plan["skip"]}
    assert reasons == {"work": "Terse is not available in this profile",
                       "solo": "settings.json has an error: fix it in the advanced editor"}
    assert "Work: Terse is not available in this profile" in app.post_error(
        "/api/settings/field/all", {"profile": "default", "key": "outputStyle"})
    assert "not valid: fix it there first" in app.request(PV + "spinnerTipsEnabled")[1]["error"]

    # back to the default: every file of the other profile that has the key is written
    plan = app.get(PV + "editorMode")
    assert plan["value"] is None and [a["id"] for a in plan["apply"]] == ["work"]
    assert plan["apply"][0]["detail"] == "Vim → the default in .claude.json"
    app.post("/api/settings/field/all", {"profile": "default", "key": "editorMode"})
    assert "editorMode" not in json.loads(home.path(".claude-work/.claude.json").read_text())

    # permissions to every profile: checked, and a broken settings.json is skipped
    PP = "/api/settings/permissions/all/preview?list="
    assert "Pick allow, ask or deny" in app.request(PP + "maybe&rule=x")[1]["error"]
    assert "Write one rule" in app.request(PP + "allow&rule=%20")[1]["error"]
    plan = app.get(PP + "deny&rule=Bash(rm)")
    assert {s["id"]: s["reason"] for s in plan["skip"]} == {
        "solo": "settings.json has an error: fix it in the advanced editor"}

    app.restore_all()
    assert home.snapshot() == before


def test_status_line_requests_and_to_all(home, app_factory):
    basic_home(home)
    home.profile("solo")
    home.write(".claude-solo/settings.json", "{ broken")
    home.path(".claude-twin").mkdir()  # a profile whose settings.json is Work's
    os.symlink("../.claude-work/settings.json", home.path(".claude-twin/settings.json"))
    before = home.snapshot()
    app = app_factory()
    S_ = "/api/statusline"

    assert app.get(S_ + "/preview?profile=default&parts=")["text"] == ""  # nothing to show: nothing run
    assert "Unknown status line mode" in app.post_error(S_, {"profile": "default", "mode": "fancy"})
    assert "Write the command" in app.post_error(S_, {"profile": "default", "mode": "custom", "command": "  "})
    assert "refresh interval" in app.post_error(S_, {"profile": "default", "mode": "custom", "command": "x", "refreshInterval": 0})
    assert "padding" in app.post_error(S_, {"profile": "default", "mode": "custom", "command": "x", "padding": True})

    app.post(S_, {"profile": "default", "mode": "custom", "command": "echo hi", "padding": "", "hideVimModeIndicator": True})
    line = json.loads(home.path(".claude/settings.json").read_text())["statusLine"]
    assert line == {"type": "command", "command": "echo hi", "hideVimModeIndicator": True}

    # a custom command to every profile: the broken one and the one sharing a file are skipped
    plan = app.get(S_ + "/all/preview?profile=default")
    assert [a["id"] for a in plan["apply"]] == ["twin"]
    assert {s["id"]: s["reason"] for s in plan["skip"]} == {
        "solo": "settings.json has an error: fix it in the advanced editor", "work": "shares settings.json with Twin"}
    app.post(S_ + "/all", {"profile": "default"})
    assert json.loads(home.path(".claude-work/settings.json").read_text())["statusLine"]["command"] == "echo hi"
    assert "No profile to change" in app.post_error(S_ + "/all", {"profile": "default"})

    # off to every profile
    app.post(S_, {"profile": "default", "mode": "off"})
    app.post(S_ + "/all", {"profile": "default"})
    assert "statusLine" not in json.loads(home.path(".claude-work/settings.json").read_text())

    app.restore_all()
    assert home.snapshot() == before


# --- installing Claude Code, about ------------------------------------------------------
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


def test_about_lists_profile_contents(home, app_factory):
    basic_home(home)
    home.write(".claude/skills/hello/SKILL.md", "x")
    home.write(".claude/skills/loose-file", "x")  # not a skill folder
    home.write(".claude/agents/reviewer.md", "x")
    home.write(".claude/agents/.hidden.md", "x")
    home.write(".claude/agents/notes.txt", "x")
    contents = app_factory().get("/api/about")["profiles"][0]["contents"]
    assert contents["Skills"] == ["hello"] and contents["Subagents"] == ["reviewer"]
    assert contents["Slash commands"] == []


# --- memories, sharing ---------------------------------------------------------------
def test_memory_read_move_and_delete(home, app_factory):
    basic_home(home)
    home.conversation("work", "code/personal/blog", "s-blog-work", {"api-notes.md": "same name"})
    before = home.snapshot()
    app = app_factory()
    api, blog = san(home.path("code/work/api")), san(home.path("code/personal/blog"))
    F = "/api/memory/file?profile=default&project=" + api + "&file="

    assert "the api uses postgres" in app.get(F + "api-notes.md")["content"]
    status, body = app.request(F + "nope.md")
    assert status == 404 and body["error"] == "Memory not found"
    assert "Memory not found" in app.post_error("/api/memory/move", {"profile": "default", "project": api, "file": "nope.md",
                                                                     "to_profile": "work", "to_project": blog})
    assert "already has a memory" in app.post_error("/api/memory/move", {"profile": "default", "project": api,
                                                                         "file": "api-notes.md", "to_profile": "work",
                                                                         "to_project": blog})
    r = app.post("/api/memory/delete", {"profile": "default", "project": api, "file": "api-notes.md"})
    assert r["message"].startswith("Memory deleted")
    assert not home.path(f".claude/projects/{api}/memory/api-notes.md").exists()
    assert "api-notes" not in home.path(f".claude/projects/{api}/memory/MEMORY.md").read_text()

    app.restore_all()
    assert home.snapshot() == before


def test_sharing_a_file_and_separating_it_again(home, app_factory):
    basic_home(home)
    home.write(".claude-work/CLAUDE.md", "# work rules\n")
    before = home.snapshot()
    app = app_factory()
    P = "/api/sharing"

    assert "cannot be shared" in app.post_error(P, {"profile": "work", "item": "projects", "shared": True})
    assert "Not shared" in app.post_error(P, {"profile": "work", "item": "CLAUDE.md", "shared": False})
    # the source has no CLAUDE.md yet: an empty one is created, the own copy goes to the backup
    plan = app.get(P + "/preview?profile=work&item=CLAUDE.md&shared=1")
    assert [i["action"] for i in plan["items"]] == ["create", "stash", "link"]
    app.post(P, {"profile": "work", "item": "CLAUDE.md", "shared": True})
    assert home.path(".claude/CLAUDE.md").read_text() == ""
    assert os.readlink(home.path(".claude-work/CLAUDE.md")) == "../.claude/CLAUDE.md"
    assert "Already shared" in app.request(P + "/preview?profile=work&item=CLAUDE.md&shared=1")[1]["error"]
    assert "Already shared" in app.post_error(P, {"profile": "work", "item": "CLAUDE.md", "shared": True})
    app.post("/api/settings/claude-md", {"profile": "default", "content": "# shared\n"})

    plan = app.get(P + "/preview?profile=work&item=CLAUDE.md&shared=0")
    assert [(i["action"], i.get("files")) for i in plan["items"]] == [("stash", None), ("copy", 1)]
    r = app.post(P, {"profile": "work", "item": "CLAUDE.md", "shared": False})
    assert r["message"] == "CLAUDE.md: Work now has its own independent copy."
    assert not home.path(".claude-work/CLAUDE.md").is_symlink()
    assert home.path(".claude-work/CLAUDE.md").read_text() == "# shared\n"

    # a folder: shared, then separated again with its files
    app.post(P, {"profile": "work", "item": "agents", "shared": True})
    home.write(".claude/agents/a.md", "x")  # written through the source, outside any operation
    app.post(P, {"profile": "work", "item": "agents", "shared": False})
    assert home.path(".claude-work/agents/a.md").read_text() == "x"
    home.path(".claude/agents/a.md").unlink()

    app.restore_all()
    assert home.snapshot() == before


# --- projects: merging into a folder that already has things ---------------------------
def test_relink_into_an_existing_project_merges_and_keeps_conflicts(home, app_factory):
    basic_home(home)
    old_path, new_path = home.path("code/old-name"), home.path("code/new-name")
    old_rel = f".claude/projects/{san(old_path)}"
    home.conversation("", "code/new-name", "s-new", {"dup.md": "the target's"})
    home.write(f"{old_rel}/s-new.jsonl", "{}\n")  # the same conversation in both
    home.write(f"{old_rel}/memory/dup.md", "---\nname: dup\n---\nthe source's\n")
    home.write(f"{old_rel}/memory/solo.md", "---\nname: solo\n---\nonly here\n")
    home.write(f"{old_rel}/memory/MEMORY.md", "# index\n- [dup](dup.md) — about dup.md\n- [solo](solo.md) — only here\n")
    with open(home.path(".claude/history.jsonl"), "a") as f:
        f.write("not json\n")
    cfg = json.loads(home.path(".claude.json").read_text())
    cfg["projects"][str(old_path)] = {"allowedTools": ["Read"]}
    home.json(".claude.json", cfg)
    before = home.snapshot()
    app = app_factory()
    old_name, new_name = san(old_path), san(new_path)
    R = "/api/projects/relink"

    assert "Folder does not exist: ~/code/nowhere" in app.post_error(
        R, {"project": old_name, "profile": "default", "path": "~/code/nowhere"})
    assert "already linked" in app.post_error(R, {"project": new_name, "profile": "default", "path": str(new_path) + "/"})
    r = app.post(R, {"project": old_name, "profile": "default", "path": "~/code/new-name"})
    assert r["message"] == "Linked to ~/code/new-name: 1 conversations, 1 prompts, settings moved."
    new_d = home.path(f".claude/projects/{new_name}")
    assert not home.path(old_rel).exists()
    assert (new_d / "s-old.jsonl").exists() and (new_d / "memory/solo.md").exists()
    assert "the target's" in (new_d / "memory/dup.md").read_text()  # the source's copy is in the backup
    index = (new_d / "memory/MEMORY.md").read_text()
    assert index.count("(dup.md)") == 1 and index.count("(solo.md)") == 1
    assert "not json" in home.path(".claude/history.jsonl").read_text()
    projects = json.loads(home.path(".claude.json").read_text())["projects"]
    assert str(old_path) not in projects and str(new_path) in projects

    app.restore_all()
    assert home.snapshot() == before


def test_move_merges_history_without_duplicates(home, app_factory):
    basic_home(home)
    api = home.path("code/work/api")
    lines = [json.dumps({"display": "work prompt", "timestamp": 4, "project": str(api)}),  # Default has it too
             json.dumps({"display": "another", "timestamp": 5, "project": str(api)}), "garbage"]
    home.write(".claude-work/history.jsonl", "\n".join(lines) + "\n")
    with open(home.path(".claude/history.jsonl"), "a") as f:
        f.write(lines[0] + "\nbroken\n")
    before = home.snapshot()
    app = app_factory()

    assert "same profile" in app.post_error("/api/projects/move", {"project": san(api), "from": "work", "to": "work"})
    r = app.post("/api/projects/move", {"project": san(api), "from": "work", "to": "default"})
    assert "2 prompts" in r["message"]
    hist = home.path(".claude/history.jsonl").read_text().splitlines()
    assert hist.count(lines[0]) == 1 and lines[1] in hist and "broken" in hist
    assert home.path(".claude-work/history.jsonl").read_text() == "garbage\n"

    app.restore_all()
    assert home.snapshot() == before


def test_rules_are_checked_and_stored_relative_to_home(home, app_factory):
    basic_home(home)
    app = app_factory()
    assert "Invalid profile" in app.post_error("/api/rules", {"match": "code", "profile": "nobody"})
    assert "Empty rule" in app.post_error("/api/rules", {"match": "  ", "profile": "work"})
    assert "“code/work” → Work" in app.post("/api/rules", {"match": str(home.path("code/work")), "profile": "work"})["message"]
    assert "“~” → " in app.post("/api/rules", {"match": str(home.root), "profile": "shared"})["message"]
    rows = {r["pretty"]: r for r in app.get("/api/projects")}
    assert rows["~/code/work/api"]["expected"] == "work"


# --- command line ----------------------------------------------------------------------
def test_label_without_a_matching_profile_in_the_config(home):
    home.profile("")
    assert run_cli(home, "label", CLAUDE_CONFIG_DIR=str(home.path(".claude-later"))).stdout.strip() == "later"
    assert run_cli(home, "label", CLAUDE_CONFIG_DIR=str(home.path("elsewhere"))).stdout.strip() == "default"


def test_server_on_a_busy_port_says_so(home):
    home.profile("")
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        env = child_env({"HOME": str(home.root), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC), "CC_PROFILES_QUIET": "1"})
        r = subprocess.run([sys.executable, "-m", "cc_profiles", "--no-browser", "--port", str(port)], env=env,
                           capture_output=True, text=True, timeout=20)
    assert r.returncode == 1 and f"Port {port} is busy with another program" in r.stdout and f"--port {port + 1}" in r.stdout


def test_starting_it_again_opens_the_running_one(home, app_factory, monkeypatch):
    """`cc-profiles` while it already runs (e.g. started by /cc-profiles): the browser opens on
    it, instead of an error about the port."""
    import cc_profiles.cli as CLI
    app = app_factory()
    env = child_env({"HOME": str(home.root), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC), "CC_PROFILES_QUIET": "1"})
    r = subprocess.run([sys.executable, "-m", "cc_profiles", "--no-browser", "--port", str(app.port)], env=env,
                       capture_output=True, text=True, timeout=20)
    assert r.returncode == 0 and f"cc-profiles is already running on http://127.0.0.1:{app.port}" in r.stdout
    opened = []
    monkeypatch.setattr(CLI, "open_url", opened.append)
    monkeypatch.setattr(CLI, "load_config", lambda: {})
    monkeypatch.setattr(CLI, "cleanup_backups", lambda: None)
    monkeypatch.setattr(CLI.threading, "Thread", lambda *a, **k: type("T", (), {"start": lambda self: None})())
    monkeypatch.setattr(CLI.signal, "signal", lambda *a: None)
    with pytest.raises(SystemExit) as e:
        CLI.serve(app.port, True)
    assert e.value.code == 0 and opened == [f"http://127.0.0.1:{app.port}"]
