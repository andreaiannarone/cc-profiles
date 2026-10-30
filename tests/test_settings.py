"""Sharing and settings: fields, permissions, raw files, CLAUDE.md, the status line.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json
import os
import shutil
import subprocess
import time

import pytest

from helpers import basic_home, restore_newest


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
    data["rate_limits"]["five_hour"]["resets_at"] = now + 61
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
