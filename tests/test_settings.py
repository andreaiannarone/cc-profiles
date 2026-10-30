"""Sharing and settings: fields, permissions, raw files, CLAUDE.md, the status line.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json
import os
import shutil
import subprocess
import sys
import time

import pytest

from conftest import SRC
from helpers import basic_home, restore_newest

sys.path.insert(0, str(SRC))
from cc_profiles import settings as S  # noqa: E402
from cc_profiles import statusline as SL  # noqa: E402
from cc_profiles.core import ApiError  # noqa: E402


# --- sharing and settings -----------------------------------------------------


def test_sharing_and_writing_through_links(home, app_factory):
    basic_home(home)
    home.write(".claude/skills/hello/SKILL.md", "hello")
    home.write(".claude-work/skills/only-work/SKILL.md", "x")
    before = home.snapshot()
    app = app_factory()

    state = {i["item"]: i for i in app.get("/api/sharing")[0]["items"]}
    assert state["skills"]["only_own"] == ["only-work"]
    app.post("/api/sharing", {"profile": "work", "item": "skills", "shared": True})
    assert os.readlink(home.path(".claude-work/skills")) == "../.claude/skills"

    app.post("/api/sharing", {"profile": "work", "item": "CLAUDE.md", "shared": True})
    app.post("/api/settings/claude-md", {"profile": "work", "content": "# written from work"})
    assert home.path(".claude-work/CLAUDE.md").is_symlink(), "writing must not replace the link"
    assert home.path(".claude/CLAUDE.md").read_text() == "# written from work\n"

    app.restore_all()
    assert home.snapshot() == before


def test_settings_write_where_the_value_lives(home, app_factory):
    basic_home(home)
    home.json(".claude/settings.json", {"model": "opus", "permissions": {"defaultMode": "default"}})
    home.json(".claude/settings.local.json", {"outputStyle": "Explanatory"})
    home.json(".claude-work/settings.local.json", {"theme": "light"})
    home.write(".claude/output-styles/terse.md", "---\nname: Terse\n---\nBe brief.\n")
    before = home.snapshot()
    app = app_factory()
    P = "/api/settings/field"

    app.post(P, {"profile": "default", "key": "outputStyle", "value": "Terse"})
    assert json.loads(home.path(".claude/settings.local.json").read_text()) == {"outputStyle": "Terse"}
    assert "pick one of the options" in app.post_error(P, {"profile": "work", "key": "outputStyle", "value": "Terse"})
    assert "pick one of the options" in app.post_error(P, {"profile": "default", "key": "timeFormat", "value": "max"})
    assert "true or false" in app.post_error(P, {"profile": "default", "key": "verbose", "value": "yes"})
    assert "advanced editor" in app.post_error(P, {"profile": "default", "key": "hooks", "value": {}})
    app.post(P, {"profile": "default", "key": "timeFormat", "value": "24-hour"})
    # the keys /config keeps in .claude.json are written there, and only those
    app.post(P, {"profile": "default", "key": "autoCompactEnabled", "value": False})
    app.post(P, {"profile": "work", "key": "permissions.defaultMode", "value": "plan"})
    assert json.loads(home.path(".claude.json").read_text())["autoCompactEnabled"] is False
    assert json.loads(home.path(".claude-work/settings.json").read_text()) == {"permissions": {"defaultMode": "plan"}}
    # thinking on is the key's absence, as /config writes it
    app.post(P, {"profile": "default", "key": "alwaysThinkingEnabled", "value": False})
    assert json.loads(home.path(".claude/settings.json").read_text())["alwaysThinkingEnabled"] is False
    app.post(P, {"profile": "default", "key": "alwaysThinkingEnabled", "value": True})
    assert "alwaysThinkingEnabled" not in json.loads(home.path(".claude/settings.json").read_text())
    # theme lives where a file has it: settings.local.json here, .claude.json otherwise
    app.post(P, {"profile": "work", "key": "theme", "value": "dark"})
    assert json.loads(home.path(".claude-work/settings.local.json").read_text()) == {"theme": "dark"}
    app.post(P, {"profile": "default", "key": "theme", "value": "light"})
    assert json.loads(home.path(".claude.json").read_text())["theme"] == "light"

    app.post("/api/settings/permissions", {"profile": "default", "rules": {"deny": ["mcp__gmail", "  "]}})
    perms = json.loads(home.path(".claude/settings.json").read_text())["permissions"]
    assert perms == {"defaultMode": "default", "deny": ["mcp__gmail"]}

    assert "Invalid JSON" in app.post_error("/api/settings/raw", {"profile": "work", "file": "settings", "content": "{ x"})
    assert "JSON object" in app.post_error("/api/settings/raw", {"profile": "work", "file": "settings", "content": "[]"})
    assert "cannot be changed" in app.post_error("/api/settings/global", {"profile": "default", "key": "userID", "value": True})

    app.restore_all()
    assert home.snapshot() == before


def test_several_settings_saved_at_once_in_one_backup(home, app_factory):
    basic_home(home)
    home.json(".claude/settings.json", {"model": "opus"})
    before = home.snapshot()
    app = app_factory()
    n = len(app.get("/api/backups"))
    P = "/api/settings/fields"
    # one bad value: nothing is written
    assert "pick one of the options" in app.post_error(P, {"profile": "default", "values": {"language": "Italiano", "timeFormat": "x"}})
    assert home.snapshot() == before
    r = app.post(P, {"profile": "default", "values": {"language": "Italiano", "verbose": True, "attribution.commit": False}})
    assert r["message"].startswith("Saved 3 settings")
    assert len(app.get("/api/backups")) == n + 1
    assert json.loads(home.path(".claude/settings.json").read_text()) == {"model": "opus", "language": "Italiano", "attribution": {"commit": ""}}
    assert json.loads(home.path(".claude.json").read_text())["verbose"] is True
    assert "Nothing to save" in app.post_error(P, {"profile": "default", "values": {}})
    restore_newest(app)
    assert home.snapshot() == before


def test_attribution_keys_live_inside_their_object(home, app_factory):
    """attribution is an object: commit and pr are switches, off is an empty text (no
    attribution), on is the key's absence; a custom text counts as on and is kept. The
    deprecated includeCoAuthoredBy shows only where a profile still has it."""
    basic_home(home)
    home.json(".claude/settings.json", {"includeCoAuthoredBy": False, "attribution": {"pr": "via Claude"}})
    before = home.snapshot()
    app = app_factory()
    P = "/api/settings/field"
    keys = lambda pid: [f["key"] for f in app.get(f"/api/settings?profile={pid}")["fields"]]
    assert "includeCoAuthoredBy" in keys("work")  # Default still has it
    fields = {f["key"]: f for f in app.get("/api/settings?profile=default")["fields"]}
    assert fields["attribution.pr"]["value"] == "via Claude" and fields["attribution.commit"]["source"] is None

    assert "true or false" in app.post_error(P, {"profile": "default", "key": "attribution.commit", "value": 5})
    app.post(P, {"profile": "default", "key": "attribution.commit", "value": False})
    app.post(P, {"profile": "default", "key": "includeCoAuthoredBy", "value": None})
    data = json.loads(home.path(".claude/settings.json").read_text())
    assert data == {"attribution": {"pr": "via Claude", "commit": ""}}
    assert "includeCoAuthoredBy" not in keys("work")
    plan = app.get("/api/settings/field/all/preview?profile=default&key=attribution.commit")
    assert plan["shown"] == "off" and [a["id"] for a in plan["apply"]] == ["work"]
    for k in ("attribution.pr", "attribution.commit"):
        app.post(P, {"profile": "default", "key": k, "value": True})
    assert json.loads(home.path(".claude/settings.json").read_text()) == {}  # the empty object goes too

    home.json(".claude-work/settings.json", {"attribution": "text"})
    assert "not an object" in app.post_error(P, {"profile": "work", "key": "attribution.pr", "value": False})
    app.restore_all()
    home.json(".claude-work/settings.json", {})
    assert home.snapshot() == before


def test_status_line_built_in_custom_off_and_to_all(home, app_factory):
    basic_home(home)
    home.json(".claude/settings.json", {"model": "opus"})
    home.write(".claude-work/statusline.sh", "#!/bin/sh\necho mine\n")  # not ours: never overwritten
    before = home.snapshot()
    app = app_factory()
    S = "/api/statusline"
    assert app.get(S + "?profile=default")["mode"] == "off"

    preview = app.get(S + "/preview?profile=default&parts=cost,profile,model&separator=dot&colors=0")["text"]
    colored = app.get(S + "/preview?profile=default&parts=model:none,context:none&separator=bar")
    square = app.get(S + "/preview?profile=default&parts=model:square,cost:square&colors=0")["text"]
    assert "Unknown brackets" in app.request(S + "/preview?profile=default&parts=model:x")[1]["error"]
    if shutil.which("jq"):
        assert square == "[Opus] [$1.27]"
        assert preview == "$1.27 · (Default) · [Opus]"  # in the order picked, each with its own brackets
        assert colored["text"] == "\x1b[35mOpus\x1b[0m\x1b[2m | \x1b[0m\x1b[34mctx:42%\x1b[0m"
    else:
        assert "install jq" in preview
    assert "# style: separator=bar colors=1" in colored["script"]
    assert "Unknown separator" in app.request(S + "/preview?profile=default&parts=model&separator=x")[1]["error"]
    app.post(S, {"profile": "default", "mode": "builtin", "parts": ["model:none", "profile", "nope"], "refreshInterval": 5,
                 "separator": "bar", "colors": False})
    script = home.path(".claude/statusline.sh").read_text()
    assert "# managed by cc-profiles: status line" in script and "# parts: model:none profile:round" in script
    line = json.loads(home.path(".claude/settings.json").read_text())["statusLine"]
    assert line["type"] == "command" and line["command"].endswith("/.claude/statusline.sh") and line["refreshInterval"] == 5
    got = app.get(S + "?profile=default")
    assert got["mode"] == "builtin" and got["parts"] == ["model:none", "profile:round"]
    assert got["separator"] == "bar" and not got["colors"]
    if shutil.which("jq"):  # the real script, as Claude Code runs it
        r = subprocess.run(["sh", "-c", line["command"]], input='{"model": {"display_name": "Opus"}}', capture_output=True,
                           text=True, env=dict(os.environ, HOME=str(home.root), CLAUDE_CONFIG_DIR=str(home.path(".claude"))))
        assert r.stdout == "Opus | (Default)"

    assert "not made by cc-profiles" in app.post_error(S, {"profile": "work", "mode": "builtin", "parts": ["model"]})
    assert app.get(S + "/all/preview?profile=default")["skip"][0]["reason"].endswith("was not made by cc-profiles")
    assert "Pick at least one" in app.post_error(S, {"profile": "default", "mode": "builtin", "parts": []})
    assert "whole number" in app.post_error(S, {"profile": "default", "mode": "custom", "command": "x", "padding": -1})

    app.post(S, {"profile": "default", "mode": "custom", "command": "echo hi"})
    assert not home.path(".claude/statusline.sh").exists()  # the unused script goes to the backup
    assert app.get(S + "?profile=default")["mode"] == "custom"
    app.post(S, {"profile": "default", "mode": "off"})
    assert "statusLine" not in json.loads(home.path(".claude/settings.json").read_text())

    app.restore_all()
    assert home.snapshot() == before


def run_status_script(home, path, data):
    r = subprocess.run(["/bin/sh", str(path)], input=json.dumps(data), capture_output=True, text=True,
                       env=dict(os.environ, HOME=str(home.root), CLAUDE_CONFIG_DIR=str(home.path(".claude"))))
    return r.stdout


@pytest.mark.skipif(not shutil.which("jq"), reason="the status line script needs jq")
def test_status_line_tokens_and_limits_left(home, app_factory, tmp_path):
    basic_home(home)
    before = home.snapshot()
    app = app_factory()
    S = "/api/statusline"
    assert "used or left" in app.request(S + "/preview?profile=default&parts=limit&limits=x")[1]["error"]
    # the preview reads a sample conversation of its own and counts down from now
    used = app.get(S + "/preview?profile=default&parts=tokens,limit,week&colors=0")
    left = app.get(S + "/preview?profile=default&parts=tokens,limit,week&colors=0&limits=left")
    assert used["text"] == "question:12k session:340k 5h:78% 7d:41%"
    assert left["text"] == "question:12k session:340k 5h:22%→1h20m 7d:59%"
    assert "# style: separator=space colors=0 limits=left" in left["script"]

    app.post(S, {"profile": "default", "mode": "builtin", "parts": ["tokens", "limit", "week"], "colors": False, "limits": "left"})
    script = home.path(".claude/statusline.sh")
    got = app.get(S + "?profile=default")
    assert got["limits"] == "left"
    assert {p["id"]: p.get("sample_left") for p in got["parts_available"]}["limit"] == "5h:22%→1h20m"

    lines = [{"type": "user", "message": {"content": "first"}},
             {"type": "assistant", "message": {"usage": {"input_tokens": 1000000, "cache_read_input_tokens": 200000,
                                                         "output_tokens": 5000}}},
             {"type": "user", "message": {"content": "second"}},
             {"type": "assistant", "message": {"usage": {"input_tokens": 500, "cache_creation_input_tokens": 1500}}},
             {"type": "user", "message": {"content": [{"type": "tool_result", "content": "done"}]}},  # not a prompt
             {"type": "assistant", "message": {"usage": {"output_tokens": 600}}}]
    (tmp_path / "t.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines) + '{"type": "assist')  # a line being written
    now = int(time.time())
    data = {"transcript_path": str(tmp_path / "t.jsonl"),
            "rate_limits": {"five_hour": {"used_percentage": 92.4, "resets_at": now + 2 * 3600 + 13 * 60 + 30},
                            "seven_day": {"used_percentage": 41, "resets_at": now + 4 * 86400}}}
    assert run_status_script(home, script, data) == "question:2k session:1.2M 5h:8%→2h13m 7d:59%"
    data["rate_limits"]["seven_day"] = {"used_percentage": 60, "resets_at": now + 3 * 86400 + 11 * 3600 + 60}
    data["rate_limits"]["five_hour"]["resets_at"] = now + 45 * 60 + 30
    assert run_status_script(home, script, data) == "question:2k session:1.2M 5h:8%→45m 7d:40%→3d11h"
    data["rate_limits"]["five_hour"]["resets_at"] = now + 90  # margin: a busy machine runs the script later
    assert run_status_script(home, script, data) == "question:2k session:1.2M 5h:8%→1m 7d:40%→3d11h"
    data["rate_limits"]["five_hour"]["resets_at"] = now + 40  # under a minute: not "0m"
    assert run_status_script(home, script, data) == "question:2k session:1.2M 5h:8%→<1m 7d:40%→3d11h"
    data["transcript_path"] = str(tmp_path / "missing.jsonl")  # no conversation file: no tokens, nothing else breaks
    del data["rate_limits"]["five_hour"]["resets_at"]
    assert run_status_script(home, script, data) == "5h:8% 7d:40%→3d11h"

    # used, as before: the same data shows the share used, without countdown
    app.post(S, {"profile": "default", "mode": "builtin", "parts": ["limit", "week"], "colors": False, "limits": "used"})
    assert run_status_script(home, script, data) == "5h:92% 7d:60%"
    # a script from before limits=: still recognized, and shows the limits used
    text = script.read_text()
    script.write_text(text.replace(" limits=used", ""))
    assert app.get(S + "?profile=default")["limits"] == "used"
    script.write_text(text.replace(" limits=used", " limits=sideways"))
    assert app.get(S + "?profile=default")["limits"] == "used"
    script.write_text(text)

    app.restore_all()
    assert home.snapshot() == before


def test_status_line_presets_use_existing_pieces(home, app_factory):
    basic_home(home)
    app = app_factory()
    got = app.get("/api/statusline?profile=default")
    presets = got["presets"]
    assert [p["label"] for p in presets] == ["Essential", "Developer", "Usage", "Like a hand-made one"]
    pieces = {p["id"]: p["brackets"] for p in got["parts_available"]}
    brackets = {b["id"] for b in got["brackets"]}
    for p in presets:
        assert p["description"] and p["parts"], p["id"]
        ids = [x.split(":")[0] for x in p["parts"]]
        assert len(set(ids)) == len(ids) and set(ids) <= set(pieces), p["id"]
        assert all(x.split(":")[1] in brackets for x in p["parts"]), p["id"]
        assert p["brackets"] is None or p["brackets"] in brackets
        if p["brackets"] is None:  # each piece its own brackets
            assert all(x.split(":")[1] == pieces[x.split(":")[0]] for x in p["parts"]), p["id"]
        assert p["separator"] in {s["id"] for s in got["separators"]} and p["limits"] in ("used", "left")
        assert isinstance(p["colors"], bool)
        # the server takes it as it is
        prev = app.get(f"/api/statusline/preview?profile=default&parts={','.join(p['parts'])}&separator={p['separator']}"
                       f"&colors={int(p['colors'])}&limits={p['limits']}")
        assert f"# parts: {' '.join(p['parts'])}" in prev["script"]
    byid = {p["id"]: p for p in presets}
    assert byid["essential"]["parts"] == ["profile:none", "model:none", "context:none"] and byid["essential"]["separator"] == "dot"
    assert byid["usage"]["limits"] == "left" and byid["usage"]["separator"] == "bar"
    assert len(byid["handmade"]["parts"]) == 11 and byid["handmade"]["limits"] == "left"


def test_status_line_to_every_profile_is_undone_by_one_restore(home, app_factory):
    basic_home(home)
    home.profile("solo")
    home.json(".claude-solo/settings.json", {"statusLine": {"type": "command", "command": "echo solo"}})
    before = home.snapshot()
    app = app_factory()
    app.post("/api/statusline", {"profile": "default", "mode": "builtin", "parts": ["profile", "branch"], "padding": 1})
    plan = app.get("/api/statusline/all/preview?profile=default")
    assert sorted(a["id"] for a in plan["apply"]) == ["solo", "work"]
    app.post("/api/statusline/all", {"profile": "default"})
    for d in (".claude-work", ".claude-solo"):  # each profile gets its own script, same parts and options
        line = json.loads(home.path(f"{d}/settings.json").read_text())["statusLine"]
        assert line["command"].endswith(f"{d}/statusline.sh") and line["padding"] == 1
        assert "# parts: profile:round branch:round" in home.path(f"{d}/statusline.sh").read_text()
    assert app.get("/api/statusline/all/preview?profile=default")["apply"] == []
    for b in app.get("/api/backups")[:2]:  # to every profile, then the one it copied
        app.post("/api/backups/restore", {"name": b["name"]})
    assert home.snapshot() == before


# --- settings and status line helpers, their error paths --------------------------
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
    assert SL.status_parts(["model", "nope", "model:round", "context:square", ""]) == [("model", "square"), ("context", "square")]
    with pytest.raises(ApiError, match="Unknown brackets"):
        SL.status_parts(["model:zigzag"])
    assert SL.status_style("bar", 1) == ("bar", True, "used")
    with pytest.raises(ApiError, match="Unknown separator"):
        SL.status_style("tab", True)
    with pytest.raises(ApiError, match="used or left"):
        SL.status_style("dot", True, "both")


@pytest.mark.parametrize("text,expected", [
    (None, None),  # no file
    ("#!/bin/sh\n", None),  # too short
    ("#!/bin/sh\n# some other script\n# parts: model\n", None),
    ("#!/bin/sh\n" + SL.STATUS_MARK + "\necho hi\n", None),  # no parts line
    ("#!/bin/sh\n" + SL.STATUS_MARK + "\n# parts: model:zigzag\n", None),  # brackets it does not know
    # before per-piece brackets: bare ids, no brackets; before the style line: dot, no colors
    ("#!/bin/sh\n" + SL.STATUS_MARK + "\n# parts: model context\n",
     {"parts": [("model", "none"), ("context", "none")], "separator": "dot", "colors": False, "limits": "used"}),
    ("#!/bin/sh\n" + SL.STATUS_MARK + "\n# parts: model:round\n# style: separator=bar colors=1 limits=left\n",
     {"parts": [("model", "round")], "separator": "bar", "colors": True, "limits": "left"}),
    # values it does not know fall back, stray words are ignored
    ("#!/bin/sh\n" + SL.STATUS_MARK + "\n# parts: model:round\n# style: separator=tab junk colors=yes limits=both\n",
     {"parts": [("model", "round")], "separator": "dot", "colors": False, "limits": "used"}),
])
def test_status_script_info_reads_only_its_own_headers(tmp_path, text, expected):
    path = tmp_path / "statusline.sh"
    if text is not None:
        path.write_text(text)
    assert SL.status_script_info(str(path)) == expected


def test_status_script_info_reads_back_what_it_writes(tmp_path):
    path = tmp_path / "statusline.sh"
    parts = SL.status_parts(["path", "branch:square", "week"])
    path.write_text(SL.status_script(parts, "arrow", False, "left"))
    assert SL.status_script_info(str(path)) == {"parts": parts, "separator": "arrow", "colors": False, "limits": "left"}


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
