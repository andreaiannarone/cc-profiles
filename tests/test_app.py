"""End-to-end tests: every operation runs against a real server on a fake home.

The key property of cc-profiles is that everything can be undone, so most tests
end the same way: restore every backup, newest first, and check the fake home is
byte-for-byte identical to how it started.
"""
import csv
import io
import json
import os
import re
import shutil
import signal
import socket
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import pytest

from conftest import SRC, child_env, free_port, san


def basic_home(home):
    """Two profiles: 'default' (~/.claude) and 'work' (~/.claude-work)."""
    home.profile("")
    home.profile("work")
    home.json(".claude.json", {"oauthAccount": {"emailAddress": "me@example.com"},
                               "projects": {str(home.path("code/work/api")): {"allowedTools": ["Bash"]}}})
    home.json(".claude-work/.claude.json", {"projects": {}})
    home.conversation("", "code/work/api", "s-api", {"api-notes.md": "the api uses postgres"})
    home.conversation("work", "code/work/api", "s-api-work")
    home.conversation("", "code/personal/blog", "s-blog")
    home.conversation("", "code/old-name", "s-old")
    home.history("", [("code/work/api", "fix the api", 2), ("code/personal/blog", "new post", 1),
                      ("code/old-name", "old prompt", 3)])
    home.history("work", [("code/work/api", "work prompt", 4)])
    os.rename(home.path("code/old-name"), home.path("code/new-name"))  # the user moved a folder


# --- security ---------------------------------------------------------------
def test_api_requires_token_and_local_host(home, app_factory):
    basic_home(home)
    app = app_factory()
    assert app.request("/api/projects", token=False)[0] == 403
    assert app.request("/api/projects", host=f"evil.example:{app.port}")[0] == 403
    assert app.request("/api/projects")[0] == 200


def test_page_sends_a_strict_content_security_policy(home, app_factory):
    basic_home(home)
    app = app_factory()
    with urllib.request.urlopen(app.base + "/", timeout=5) as r:
        csp = r.headers["Content-Security-Policy"]
        assert r.headers["X-Frame-Options"] == "DENY"
    assert "default-src 'none'" in csp and "connect-src 'self'" in csp and "frame-ancestors 'none'" in csp


def test_path_traversal_is_rejected(home, app_factory):
    basic_home(home)
    app = app_factory()
    assert "Invalid project name" in app.request("/api/memory/list?profile=default&project=..")[1]["error"]
    proj = san(home.path("code/work/api"))
    assert "Invalid file name" in app.request(
        f"/api/memory/file?profile=default&project={proj}&file=../../x.md")[1]["error"]
    assert "Invalid backup name" in app.post_error("/api/backups/restore", {"name": "../x"})


# --- first run ----------------------------------------------------------------
def test_first_run_detects_profiles(home, app_factory):
    basic_home(home)
    (home.root / ".claude-notaprofile").mkdir()          # empty folder: ignored
    os.symlink(home.path(".claude-work"), home.path(".claude-alias"))  # symlink: ignored
    app = app_factory()
    profiles = app.get("/api/profiles")
    assert [(p["id"], p["command"]) for p in profiles] == [("default", "claude"), ("work", "claude-work")]
    assert profiles[0]["primary"] and profiles[0]["email"] == "me@example.com"


def test_projects_report_issues(home, app_factory):
    basic_home(home)
    app = app_factory()
    rows = {r["pretty"]: r for r in app.get("/api/projects")}
    assert rows["~/code/old-name"]["issues"][0]["kind"] == "orphan"
    app.post("/api/rules", {"match": "code/work", "profile": "work"})
    rows = {r["pretty"]: r for r in app.get("/api/projects")}
    kinds = [i["kind"] for i in rows["~/code/work/api"]["issues"]]
    assert kinds == ["profile"] and rows["~/code/work/api"]["expected"] == "work"


# --- projects, memories, restore ----------------------------------------------
def test_operations_are_fully_undoable(home, app_factory):
    basic_home(home)
    before = home.snapshot()
    app = app_factory()
    api, blog, old = (san(home.path(p)) for p in ("code/work/api", "code/personal/blog", "code/old-name"))

    r = app.post("/api/projects/move", {"project": api, "from": "default", "to": "work"})
    assert "1 conversations" in r["message"] and "1 prompts" in r["message"]
    assert not home.path(f".claude/projects/{api}").exists()
    assert (home.path(f".claude-work/projects/{api}/memory/api-notes.md")).exists()
    assert home.path(".claude-work/file-history/s-api").is_dir()
    assert str(home.path("code/work/api")) in json.loads(home.path(".claude-work/.claude.json").read_text())["projects"]

    app.post("/api/projects/relink", {"project": old, "profile": "default", "path": "~/code/new-name"})
    assert home.path(f".claude/projects/{san(home.path('code/new-name'))}/s-old.jsonl").exists()
    hist = [json.loads(l) for l in home.path(".claude/history.jsonl").read_text().splitlines()]
    assert {h["project"] for h in hist} == {str(home.path("code/personal/blog")), str(home.path("code/new-name"))}

    app.post("/api/memory/move", {"profile": "work", "project": api, "file": "api-notes.md",
                                  "to_profile": "default", "to_project": blog})
    app.post("/api/memory/save", {"profile": "default", "project": blog, "file": "api-notes.md", "content": "edited"})
    app.post("/api/projects/delete", {"project": blog, "profile": "default"})
    app.post("/api/rules", {"match": "code/personal", "profile": "default"})
    assert home.snapshot() != before

    app.restore_all()
    assert home.snapshot() == before


def test_restore_twice_is_refused(home, app_factory):
    basic_home(home)
    app = app_factory()
    app.post("/api/rules", {"match": "code/work", "profile": "work"})
    name = app.get("/api/backups")[0]["name"]
    app.post("/api/backups/restore", {"name": name})
    assert "already restored" in app.post_error("/api/backups/restore", {"name": name})


# --- conversations ------------------------------------------------------------
def write_session(home, profile, project, session, n_prompts=2):
    """A conversation shaped like Claude Code's: prompts, replies, a tool call and its result,
    a slash command, a meta line, the AI title and a file snapshot folder."""
    proj = home.conversation(profile, project, session)  # creates the folder and file-history/<session>
    lines = [
        {"type": "user", "isMeta": True, "message": {"role": "user", "content": "<local-command-caveat>x</local-command-caveat>"}},
        {"type": "user", "message": {"role": "user", "content": "<command-name>/clear</command-name>"},
         "timestamp": "2026-10-01T09:00:00Z"},
    ]
    for i in range(n_prompts):
        lines += [
            {"type": "user", "message": {"role": "user", "content": f"Fix the login bug number {i}"},
             "timestamp": f"2026-10-01T10:0{i}:00Z"},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "thinking", "thinking": "hm"}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "tool_use", "name": "Bash", "input": {}}]}},
            {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "x" * 5000}]}},
            {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": f"Fixed bug {i}."}]},
             "timestamp": f"2026-10-01T10:0{i}:30Z"},
        ]
    lines.append({"type": "ai-title", "aiTitle": "Login bug fixes", "sessionId": session})
    (proj / f"{session}.jsonl").write_text("\n".join(json.dumps(l, separators=(",", ":")) for l in lines) + "\n")
    return proj


def test_conversations_are_listed_and_viewed(home, app_factory):
    basic_home(home)
    write_session(home, "", "code/work/api", "s-api", n_prompts=2)
    app = app_factory()
    api = san(home.path("code/work/api"))
    projects = {p["name"]: p["count"] for p in app.get("/api/conversations/projects?profile=default")}
    assert projects[api] == 1
    (c,) = app.get(f"/api/conversations?profile=default&project={api}")["conversations"]
    assert c["session"] == "s-api" and c["title"] == "Login bug fixes"  # the AI title wins
    assert (c["prompts"], c["replies"]) == (2, 2) and c["snapshots"] is True
    assert c["first"] == "2026-10-01T09:00:00Z" and c["last"] == "2026-10-01T10:01:30Z"
    view = app.get(f"/api/conversations/view?profile=default&project={api}&session=s-api")
    assert [m["role"] for m in view["messages"]] == ["user", "tool", "assistant", "user", "tool", "assistant"]
    assert view["truncated"] is False and view["messages"][1]["text"] == "Tool: Bash"
    assert "x" * 100 not in json.dumps(view)  # tool results are left out

    blog = san(home.path("code/personal/blog"))
    write_session(home, "", "code/personal/blog", "s-long", n_prompts=0)
    with open(home.path(f".claude/projects/{blog}/s-long.jsonl"), "a") as f:
        for i in range(320):
            f.write(json.dumps({"type": "user", "message": {"content": f"prompt {i} " + "y" * 5000}},
                               separators=(",", ":")) + "\n")
    view = app.get(f"/api/conversations/view?profile=default&project={blog}&session=s-long")
    assert view["truncated"] is True and view["total"] == 320 and len(view["messages"]) == 300
    assert view["messages"][-1]["text"].startswith("prompt 319") and view["messages"][-1]["text"].endswith("…")

    # JSON with spaces (not how Claude Code writes it today) is read just the same
    with open(home.path(f".claude/projects/{blog}/s-spaced.jsonl"), "w") as f:
        f.write(json.dumps({"type": "user", "message": {"role": "user", "content": "spaced prompt"}}) + "\n")
        f.write(json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}}) + "\n")
    spaced = next(c for c in app.get(f"/api/conversations?profile=default&project={blog}")["conversations"]
                  if c["session"] == "s-spaced")
    assert (spaced["title"], spaced["prompts"], spaced["replies"]) == ("spaced prompt", 1, 1)

    for bad in ("../x", "", "a/b", ".."):
        assert app.request(f"/api/conversations/view?profile=default&project={api}&session={bad}")[0] in (400, 404)
    assert app.request("/api/conversations?profile=default&project=..")[0] == 400


def test_one_conversation_moves_and_everything_is_undoable(home, app_factory):
    basic_home(home)
    write_session(home, "", "code/work/api", "s-two")  # a second conversation in the same project
    before = home.snapshot()
    app = app_factory()
    api = san(home.path("code/work/api"))
    hist = home.path(".claude/history.jsonl").read_text()

    r = app.post("/api/conversations/move", {"profile": "default", "project": api, "session": "s-two", "to": "work"})
    assert "with its file snapshots" in r["message"]
    assert home.path(f".claude-work/projects/{api}/s-two.jsonl").exists()
    assert home.path(".claude-work/file-history/s-two").is_dir() and not home.path(".claude/file-history/s-two").exists()
    assert home.path(f".claude/projects/{api}/s-api.jsonl").exists()  # the other conversation stays
    assert home.path(".claude/history.jsonl").read_text() == hist  # prompt history is not touched
    assert "Pick another" in app.post_error("/api/conversations/move",
                                            {"profile": "work", "project": api, "session": "s-two", "to": "work"})

    app.post("/api/conversations/delete", {"profile": "default", "project": api, "session": "s-api"})
    assert not home.path(f".claude/projects/{api}/s-api.jsonl").exists()
    assert not home.path(".claude/file-history/s-api").exists()

    app.restore_all()
    assert home.snapshot() == before


def test_moving_a_conversation_the_target_has_is_refused(home, app_factory):
    basic_home(home)
    app = app_factory()
    api = san(home.path("code/work/api"))
    write_session(home, "work", "code/work/api", "s-api")  # Work already has a conversation with this id
    assert "already has" in app.post_error("/api/conversations/move",
                                           {"profile": "default", "project": api, "session": "s-api", "to": "work"})


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


# --- sessions, move preview, old backups ---------------------------------------
def test_claude_processes_are_matched_to_profiles(tmp_path):
    sys.path.insert(0, str(SRC))
    from cc_profiles import server
    home = str(tmp_path)
    work = os.path.join(home, ".claude-work")
    found = server.parse_claude_processes([
        ("claude", [f"HOME={home}"]),                                          # default profile
        ("/Users/x/.local/share/claude/versions/2.1.289", [f"CLAUDE_CONFIG_DIR={work}", f"HOME={home}"]),
        ("node", ["/usr/lib/node_modules/@anthropic-ai/claude-code/cli.js", "CLAUDE_CONFIG_DIR=~/.claude-x", f"HOME={home}"]),
        ("/usr/bin/python3", ["CLAUDE_CONFIG_DIR=/nope", f"HOME={home}"]),     # not Claude Code
        ("vim", ["claude.md"]),
    ])
    assert found == {os.path.realpath(os.path.join(home, d)) for d in (".claude", ".claude-work", ".claude-x")}


def test_a_running_claude_process_marks_its_profile_active(home, app_factory, tmp_path):
    """A real process named claude, as `ps -E` (macOS) or /proc (Linux) shows it."""
    sys.path.insert(0, str(SRC))
    from cc_profiles import core
    home.profile("")
    work = home.profile("work")  # no conversations: only the process can make it active
    fake = tmp_path / "bin" / "claude"
    fake.parent.mkdir()
    shutil.copy("/bin/sleep", fake)
    if sys.platform == "darwin":
        # A copied system binary is killed at launch, and ps -E hides the environment of
        # system binaries (a link to /bin/sleep runs, but shows no CLAUDE_CONFIG_DIR):
        # an ad-hoc signature makes the copy an ordinary program, like the real claude.
        subprocess.run(["codesign", "-f", "-s", "-", str(fake)], check=True, capture_output=True)
    proc =subprocess.Popen([str(fake), "30"], env={"HOME": str(home.root), "CLAUDE_CONFIG_DIR": str(work)})
    try:
        core._running["at"] = 0  # the result is cached for 3 s
        assert os.path.realpath(work) in core.running_claude_dirs()
        active = {p["id"]: p["active"] for p in app_factory().get("/api/profiles")}
        assert active == {"default": False, "work": True}
    finally:
        proc.kill()
        proc.wait()
    core._running["at"] = 0
    assert os.path.realpath(work) not in (core.running_claude_dirs() or set())


def test_move_preview_lists_what_moves_and_changes_nothing(home, app_factory):
    basic_home(home)
    before = home.snapshot()
    app = app_factory()
    api = san(home.path("code/work/api"))
    plan = app.get(f"/api/projects/move/preview?project={api}&from=default&to=work")
    actions = {(i["action"], i["item"]) for i in plan["items"]}
    assert ("move", "s-api.jsonl") in actions and ("move", "memory/api-notes.md") in actions
    assert ("merge", "memory/MEMORY.md") in actions and ("move", "file-history/s-api") in actions  # snapshots too
    assert plan["prompts"] == 1 and plan["settings"] is True
    assert home.snapshot() == before
    assert "same profile" in app.request(f"/api/projects/move/preview?project={api}&from=work&to=work")[1]["error"]


def test_old_backups_are_pruned(home, app_factory):
    basic_home(home)
    app = app_factory()
    app.post("/api/rules", {"match": "code/personal", "profile": "default"})
    app.post("/api/rules", {"match": "code/work", "profile": "work"})
    names = [b["name"] for b in app.get("/api/backups")]
    man = home.path(f".cc-profiles/backups/{names[-1]}/manifest.json")  # the oldest
    data = json.loads(man.read_text())
    data["created"] -= 40 * 86400
    man.write_text(json.dumps(data))
    r = app.post("/api/backups/prune", {"days": 30})
    assert r["message"].startswith("Deleted 1 backup older than 30 days")
    assert [b["name"] for b in app.get("/api/backups")] == names[:-1]
    assert "No backups older" in app.post("/api/backups/prune", {"days": 30})["message"]
    assert app.request("/api/backups/prune", {"days": 0})[0] == 400


# --- search and compare (read-only) --------------------------------------------
def search_home(home):
    basic_home(home)
    home.write(".claude/skills/release-notes/SKILL.md",
               "---\nname: release-notes\ndescription: Write the changelog from merged pull requests\n---\nBody.\n")
    home.write(".claude/CLAUDE.md", "# Rules\n\nAlways answer in English.\nPrefer postgres for databases.\n")
    cfg = json.loads(home.path(".claude.json").read_text())
    cfg["mcpServers"] = {"files": {"type": "stdio", "command": "npx", "args": ["-y", "server-filesystem"],
                                   "env": {"API_KEY": "secret-zebra-123"}}}
    home.json(".claude.json", cfg)


def test_search_finds_everything_and_changes_nothing(home, app_factory):
    search_home(home)
    before = home.snapshot()
    app = app_factory()
    r = app.get("/api/search?q=POSTGRES")  # case-insensitive
    assert {m["open"]["file"] for m in r["results"]["memories"]} == {"api-notes.md"}  # a memory body
    hit = r["results"]["claude_md"][0]
    assert hit["profile"] == "default" and hit["open"]["line"] == 4
    assert hit["snippet"]["text"][hit["snippet"]["at"]:][:8].lower() == "postgres"
    assert [s["title"] for s in app.get("/api/search?q=changelog")["results"]["skills"]] == ["release-notes"]
    mcp = app.get("/api/search?q=filesystem")["results"]["mcp"]
    assert [(m["title"], m["open"]["scope"]) for m in mcp] == [("files", "user")]
    proj = app.get("/api/search?q=work/api")["results"]["projects"]
    assert len(proj) == 1 and sorted(proj[0]["profiles"]) == ["default", "work"]
    assert "secret-zebra" not in json.dumps(app.get("/api/search?q=files"))
    assert app.get("/api/search?q=secret-zebra")["counts"]["mcp"] == 0  # env values are not searched
    assert app.request("/api/search?q=a")[0] == 400
    assert home.snapshot() == before


def test_compare_two_profiles(home, app_factory):
    search_home(home)
    home.json(".claude/settings.json", {"language": "English", "permissions": {"allow": ["Bash(ls)", "Read"]}})
    home.json(".claude-work/settings.local.json", {"language": "Italiano"})
    home.json(".claude-work/settings.json", {"permissions": {"allow": ["Read"], "deny": ["Bash(rm:*)"]}})
    home.write(".claude-work/skills/release-notes/SKILL.md", "---\nname: release-notes\n---\nOther.\n")
    home.write(".claude-work/skills/oncall/SKILL.md", "---\nname: oncall\n---\n")
    cfg = json.loads(home.path(".claude-work/.claude.json").read_text())
    cfg["mcpServers"] = {"sentry": {"type": "http", "url": "https://mcp.sentry.dev/mcp",
                                    "headers": {"Authorization": "Bearer secret-zebra-456"}}}
    home.json(".claude-work/.claude.json", cfg)
    before = home.snapshot()
    app = app_factory()
    c = app.get("/api/compare?a=default&b=work")
    lang = next(s for s in c["settings"] if s["key"] == "language")
    assert (lang["a"], lang["a_source"], lang["b"], lang["b_source"], lang["same"]) == \
        ("English", "settings", "Italiano", "local", False)
    assert not any(s["key"] == "model" for s in c["settings"])  # the model is picked with /model, not here
    assert c["permissions"]["diff"]["allow"] == {"only_a": ["Bash(ls)"], "only_b": [], "both": ["Read"]}
    assert c["permissions"]["diff"]["deny"]["only_b"] == ["Bash(rm:*)"]
    assert c["permissions"]["b"]["deny"] == ["Bash(rm:*)"]  # full lists, to post a merged one back
    assert c["skills"]["only_b"] == ["oncall"] and c["skills"]["both"] == [{"name": "release-notes", "same": False}]
    assert [m["name"] for m in c["mcp"]["only_a"]] == ["files"] and c["mcp"]["only_b"][0]["type"] == "http"
    assert c["claude_md"]["a"]["exists"] and not c["claude_md"]["b"]["exists"] and not c["claude_md"]["same"]
    assert "secret-zebra" not in json.dumps(c)
    assert "two different profiles" in app.request("/api/compare?a=work&b=work")[1]["error"]
    assert home.snapshot() == before


# --- skills and MCP servers --------------------------------------------------
def test_skills_are_managed_and_undoable(home, app_factory):
    basic_home(home)
    home.write(".claude/skills/review/SKILL.md", "---\nname: review\ndescription: Review a diff\n---\nReview it.\n")
    home.write(".claude/skills/review/checklist.md", "- tests\n")
    before = home.snapshot()
    app = app_factory()

    listed = app.get("/api/skills?profile=default")
    assert [(s["name"], s["description"], s["files"]) for s in listed["skills"]] == [("review", "Review a diff", 1)]
    assert app.get("/api/skills/file?profile=default&name=review")["files"] == ["checklist.md"]

    app.post("/api/skills/create", {"profile": "default", "name": "deploy", "description": "Deploy the app"})
    text = home.path(".claude/skills/deploy/SKILL.md").read_text()
    assert "name: deploy" in text and 'description: "Deploy the app"' in text
    app.post("/api/skills/save", {"profile": "default", "name": "deploy", "content": "---\nname: deploy\n---\nedited"})
    app.post("/api/skills/copy", {"profile": "default", "name": "review", "to": "work"})
    assert home.path(".claude-work/skills/review/checklist.md").read_text() == "- tests\n"
    app.post("/api/skills/delete", {"profile": "default", "name": "review"})
    assert not home.path(".claude/skills/review").exists()
    assert "already has" in app.post_error("/api/skills/create", {"profile": "default", "name": "deploy",
                                                                  "description": "x"})
    for bad in ("../x", "Bad Name", ""):
        assert app.request("/api/skills/create", {"profile": "default", "name": bad, "description": "x"})[0] == 400
    assert app.request("/api/skills/file?profile=default&name=..")[0] == 400

    app.restore_all()
    assert home.snapshot() == before


def test_skill_copy_refused_when_skills_are_shared(home, app_factory):
    basic_home(home)
    home.write(".claude/skills/review/SKILL.md", "---\nname: review\n---\n")
    app = app_factory()
    app.post("/api/sharing", {"profile": "work", "item": "skills", "shared": True})
    assert "shared with Work" in app.get("/api/skills?profile=default")["shared"]
    assert "share their skills" in app.post_error("/api/skills/copy", {"profile": "default", "name": "review",
                                                                        "to": "work"})


def test_mcp_servers_are_managed_and_undoable(home, app_factory):
    basic_home(home)
    before = home.snapshot()
    app = app_factory()
    api_path = str(home.path("code/work/api"))
    stdio = {"type": "stdio", "command": "npx", "args": ["-y", "some-server"], "env": {"API_KEY": "secret-123"}}

    app.post("/api/mcp/save", {"profile": "default", "scope": "user", "name": "files", "config": stdio})
    app.post("/api/mcp/save", {"profile": "default", "scope": api_path, "name": "docs",
                               "config": {"type": "http", "url": "https://example.com/mcp"}})
    listed = app.get("/api/mcp?profile=default")
    assert [(s["name"], s["scope"], s["type"]) for s in listed["servers"]] == [
        ("files", "user", "stdio"), ("docs", api_path, "http")]
    assert listed["servers"][0]["env"] == ["API_KEY"] and "secret-123" not in json.dumps(listed)
    assert app.get("/api/mcp/server?profile=default&scope=user&name=files")["config"] == stdio

    app.post("/api/mcp/save", {"profile": "default", "scope": "user", "name": "files2", "old_name": "files",
                               "config": {**stdio, "args": ["-y", "other"]}})
    cfg = json.loads(home.path(".claude.json").read_text())
    assert list(cfg["mcpServers"]) == ["files2"] and cfg["oauthAccount"]  # the rest of the file is kept
    r = app.post("/api/mcp/copy", {"profile": "default", "scope": api_path, "name": "docs", "to": "work"})
    assert "authenticate" in r["message"]
    assert json.loads(home.path(".claude-work/.claude.json").read_text())["mcpServers"]["docs"]["url"]
    app.post("/api/mcp/delete", {"profile": "default", "scope": api_path, "name": "docs"})

    assert "needs a command" in app.post_error("/api/mcp/save", {"profile": "default", "scope": "user",
                                                                 "name": "x", "config": {"type": "stdio"}})
    assert "URL" in app.post_error("/api/mcp/save", {"profile": "default", "scope": "user", "name": "x",
                                                     "config": {"type": "http", "url": "ftp://x"}})
    assert "already a server" in app.post_error("/api/mcp/save", {"profile": "work", "scope": "user",
                                                                  "name": "docs", "config": stdio})
    assert "Invalid server name" in app.post_error("/api/mcp/save", {"profile": "default", "scope": "user",
                                                                     "name": "a b", "config": stdio})
    assert "Unknown project" in app.post_error("/api/mcp/save", {"profile": "default", "scope": "/nope",
                                                                 "name": "x", "config": stdio})

    app.restore_all()
    assert home.snapshot() == before



def test_claude_ai_connectors_can_be_kept_out_of_a_profile(home, app_factory):
    basic_home(home)
    home.json(".claude.json", {"oauthAccount": {"emailAddress": "me@example.com"},
                               "claudeAiMcpEverConnected": ["claude.ai Gmail", "claude.ai Google Drive",
                                                            "claude.ai vidIQ for Claude", "github"]})
    home.json(".claude/settings.local.json", {"permissions": {"deny": ["mcp__claude_ai_Gmail__*", "Bash(rm:*)"]}})
    home.json(".claude/settings.json", {"permissions": {"defaultMode": "plan",
                                                        "deny": ["mcp__claude_ai_Old_One", "mcp__claude_ai_Gmail__send"]}})
    before = home.snapshot()
    app = app_factory()

    listed = app.get("/api/connectors?profile=default")
    assert [(c["name"], c["rule"], c["blocked"], c["where"]) for c in listed["connectors"]] == [
        ("Gmail", "mcp__claude_ai_Gmail", True, ["local"]),
        ("Google Drive", "mcp__claude_ai_Google_Drive", False, []),
        ("Old One", "mcp__claude_ai_Old_One", True, ["settings"]),  # only a deny rule names it
        ("vidIQ for Claude", "mcp__claude_ai_vidIQ_for_Claude", False, [])]
    assert listed["all_off"] == [] and app.get("/api/connectors?profile=work")["connectors"] == []

    app.post("/api/connectors/set", {"profile": "default", "name": "Google Drive", "enabled": False})
    app.post("/api/connectors/set", {"profile": "default", "name": "Gmail", "enabled": True})
    settings = json.loads(home.path(".claude/settings.json").read_text())
    assert settings["permissions"] == {"defaultMode": "plan", "deny": [
        "mcp__claude_ai_Old_One", "mcp__claude_ai_Gmail__send", "mcp__claude_ai_Google_Drive"]}
    # one tool's rule stays; the rule for the whole connector is gone from settings.local.json
    assert json.loads(home.path(".claude/settings.local.json").read_text()) == {"permissions": {"deny": ["Bash(rm:*)"]}}
    assert "already off" in app.post("/api/connectors/set", {"profile": "default", "name": "Google Drive",
                                                             "enabled": False})["message"]
    app.post("/api/connectors/set", {"profile": "default", "name": "Old One", "enabled": True})
    assert "Old One" not in [c["name"] for c in app.get("/api/connectors?profile=default")["connectors"]]

    # Claude Code never shortens its list: a connector removed on claude.ai is forgotten here
    assert [c["seen"] for c in app.get("/api/connectors?profile=default")["connectors"]] == [True, True, True]
    assert "turn it on first" in app.post_error("/api/connectors/forget", {"profile": "default", "name": "Google Drive"})
    app.post("/api/connectors/forget", {"profile": "default", "name": "vidIQ for Claude"})
    assert json.loads(home.path(".claude.json").read_text())["claudeAiMcpEverConnected"] == [
        "claude.ai Gmail", "claude.ai Google Drive", "github"]
    assert "Unknown connector" in app.post_error("/api/connectors/forget", {"profile": "default",
                                                                            "name": "vidIQ for Claude"})

    app.post("/api/connectors/all", {"profile": "work", "enabled": False})
    assert json.loads(home.path(".claude-work/settings.json").read_text())["disableClaudeAiConnectors"] is True
    assert app.get("/api/connectors?profile=work")["all_off"] == ["settings"]
    app.post("/api/connectors/all", {"profile": "work", "enabled": True})
    assert "disableClaudeAiConnectors" not in json.loads(home.path(".claude-work/settings.json").read_text())

    assert "Unknown connector" in app.post_error("/api/connectors/set", {"profile": "default", "name": "Nope",
                                                                         "enabled": False})
    home.write(".claude/settings.local.json", "{ broken")
    assert "has an error" in app.post_error("/api/connectors/set", {"profile": "default", "name": "Google Drive",
                                                                    "enabled": True})
    home.json(".claude/settings.local.json", {"permissions": {"deny": ["Bash(rm:*)"]}})

    app.restore_all()
    assert home.snapshot() == before


def test_connectors_follow_the_account(home, app_factory):
    """`claude mcp list` tells which connectors the account has now: gone ones leave the list."""
    basic_home(home)
    home.json(".claude.json", {"oauthAccount": {"emailAddress": "me@example.com"},
                               "claudeAiMcpEverConnected": ["claude.ai Gmail", "claude.ai Old Remote",
                                                            "claude.ai Old Blocked", "claude.ai Google Drive"]})
    home.json(".claude/settings.json", {"permissions": {"deny": ["mcp__claude_ai_Old_Blocked"]}})
    claude = home.write(".local/bin/claude", """#!/bin/sh
echo "$CLAUDE_CONFIG_DIR|$@" >> "$HOME/claude-calls"
cat "$HOME/mcp-list.txt"
""")
    claude.chmod(0o755)
    listing = home.write("mcp-list.txt", "Checking MCP server health…\n\n"
               "claude.ai Gmail: https://gmailmcp.googleapis.com/mcp/v1 - ✔ Connected\n"
               "claude.ai Google Drive: https://drivemcp.googleapis.com/mcp/v1 - ! Needs authentication\n"
               "claude.ai Linear: https://mcp.linear.app/mcp - ✔ Connected\n"
               "filesystem: npx -y server-filesystem - ✔ Connected\n")
    before = home.snapshot()
    app = app_factory()

    r = app.get("/api/connectors/check?profile=default")
    assert r == {"skipped": None, "gone": ["Old Remote"], "error": None}  # the blocked one keeps its rule
    app.post("/api/connectors/sync", {"profile": "default"})
    assert json.loads(home.path(".claude.json").read_text())["claudeAiMcpEverConnected"] == [
        "claude.ai Gmail", "claude.ai Old Blocked", "claude.ai Google Drive"]
    listed = {c["name"]: c for c in app.get("/api/connectors?profile=default")["connectors"]}
    assert sorted(listed) == ["Gmail", "Google Drive", "Linear", "Old Blocked"]  # Linear: new, not seen yet
    assert listed["Linear"]["on_account"] and not listed["Linear"]["seen"]
    assert listed["Old Blocked"]["on_account"] is False and listed["Old Blocked"]["blocked"]
    # turned on, its rule goes; the next sync takes it off the list
    app.post("/api/connectors/set", {"profile": "default", "name": "Old Blocked", "enabled": True})
    assert app.get("/api/connectors/check?profile=default")["gone"] == ["Old Blocked"]
    app.post("/api/connectors/sync", {"profile": "default"})
    assert "up to date" in app.post("/api/connectors/sync", {"profile": "default"})["message"]

    # once an hour, unless asked again; the default profile runs without CLAUDE_CONFIG_DIR
    app.get("/api/connectors/check?profile=default")
    app.get("/api/connectors/check?profile=default&force=1")
    assert home.path("claude-calls").read_text().splitlines() == ["|mcp list"] * 2  # the first check and the forced one
    # no answer from claude.ai: nothing is taken off
    full = listing.read_text()
    listing.write_text("Checking MCP server health…\n")
    r = app.get("/api/connectors/check?profile=default&force=1")
    assert "listed no connectors" in r["error"] and r["gone"] == []
    # a profile without an account, or with connectors off, is not checked
    assert "not signed in" in app.get("/api/connectors/check?profile=work")["skipped"]

    app.restore_all()
    home.path("claude-calls").unlink()
    listing.write_text(full)
    assert home.snapshot() == before


def test_a_github_account_per_profile(home, app_factory):
    basic_home(home)
    home.write(".config/gh/hosts.yml", "github.com:\n    git_protocol: https\n    users:\n        me:\n"
                                       "            oauth_token: gho_not-a-real-token\n    user: me\n")
    home.write(".config/gh-work/hosts.yml", "github.com:\n    users:\n        me-at-work:\n    user: me-at-work\n")
    home.write(".config/gh-empty/config.yml", "")
    home.json(".claude-work/settings.local.json", {"env": {"GIT_AUTHOR_EMAIL": "old@example.com", "FOO": "1"}})
    before = home.snapshot()
    app = app_factory()

    g = app.get("/api/github")
    assert "gho_" not in json.dumps(g)  # only the user name is read
    assert [(a["dir"], a["user"], a["default"]) for a in g["accounts"]] == [
        ("~/.config/gh", "me", True), ("~/.config/gh-empty", None, False), ("~/.config/gh-work", "me-at-work", False)]
    assert [(p["id"], p["user"], p["own"]) for p in g["profiles"]] == [("default", "me", False), ("work", "me", False)]

    app.post("/api/github", {"profile": "work", "folder": "~/.config/gh-work", "name": "Me At Work",
                             "email": "me@work.example"})
    env = json.loads(home.path(".claude-work/settings.json").read_text())["env"]
    assert env == {"GH_CONFIG_DIR": str(home.path(".config/gh-work")), "GIT_AUTHOR_NAME": "Me At Work",
                   "GIT_COMMITTER_NAME": "Me At Work", "GIT_COMMITTER_EMAIL": "me@work.example"}
    # a key already in settings.local.json is changed there
    assert json.loads(home.path(".claude-work/settings.local.json").read_text())["env"] == {
        "GIT_AUTHOR_EMAIL": "me@work.example", "FOO": "1"}
    work = app.get("/api/github")["profiles"][1]
    assert (work["user"], work["own"], work["name"], work["email"]) == ("me-at-work", True, "Me At Work", "me@work.example")
    assert "already uses" in app.post("/api/github", {"profile": "work", "folder": "~/.config/gh-work",
                                                      "name": "Me At Work", "email": "me@work.example"})["message"]

    # back to the default account and the git config: the variables go, other env keys stay
    app.post("/api/github", {"profile": "work", "folder": "~/.config/gh", "name": "", "email": ""})
    assert "env" not in json.loads(home.path(".claude-work/settings.json").read_text())
    assert json.loads(home.path(".claude-work/settings.local.json").read_text())["env"] == {"FOO": "1"}

    assert "not signed in" in app.post_error("/api/github", {"profile": "work", "folder": "~/.config/gh-empty"})
    assert "Unknown GitHub CLI folder" in app.post_error("/api/github", {"profile": "work", "folder": "/etc"})
    assert "both the name and the email" in app.post_error("/api/github", {"profile": "work", "folder": "",
                                                                           "name": "Me", "email": ""})
    assert "Not an email" in app.post_error("/api/github", {"profile": "work", "folder": "", "name": "Me",
                                                            "email": "me"})

    app.restore_all()
    assert home.snapshot() == before


def test_new_profiles_get_their_own_github_folder(home, app_factory):
    basic_home(home)
    home.write(".config/gh/hosts.yml", "github.com:\n    users:\n        me:\n    git_protocol: https\n    user: me\n")
    home.write(".config/gh/config.yml", "editor: vim\n")
    before = home.snapshot()
    app = app_factory()

    r = app.post("/api/profiles/create", {"label": "Noa", "id": "noa", "share": [], "github": True})
    assert "GitHub as me from ~/.config/gh-noa" in r["message"]
    assert home.path(".config/gh-noa/hosts.yml").read_text() == home.path(".config/gh/hosts.yml").read_text()
    assert home.path(".config/gh-noa/config.yml").read_text() == "editor: vim\n"
    assert oct(home.path(".config/gh-noa/hosts.yml").stat().st_mode & 0o777) == "0o600"
    assert json.loads(home.path(".claude-noa/settings.json").read_text())["env"] == {
        "GH_CONFIG_DIR": str(home.path(".config/gh-noa"))}
    assert {p["id"]: p["github"] for p in app.get("/api/profiles")} == {"default": "me", "work": "me", "noa": "me"}

    # a token written in hosts.yml (gh's insecure storage) is never copied: that folder needs a sign-in
    home.write(".config/gh/hosts.yml", "github.com:\n    users:\n        me:\n            oauth_token: gho_secret\n"
                                       "    oauth_token: gho_secret\n    user: me\n")
    r = app.post("/api/profiles/create", {"label": "Lab", "id": "lab", "share": [], "github": True})
    assert "GH_CONFIG_DIR=~/.config/gh-lab gh auth login" in r["message"]
    assert "gho_" not in home.path(".config/gh-lab/hosts.yml").read_text()
    # a shared settings.json shares the account too
    r = app.post("/api/profiles/create", {"label": "Same", "id": "same", "share": ["settings.json"], "github": True})
    assert "Its settings.json is shared" in r["message"] and not home.path(".config/gh-same").exists()
    # without the option nothing is made
    app.post("/api/profiles/create", {"label": "Plain", "id": "plain", "share": []})
    assert not home.path(".config/gh-plain").exists()

    app.restore_all()
    home.write(".config/gh/hosts.yml", "github.com:\n    users:\n        me:\n    git_protocol: https\n    user: me\n")
    assert home.snapshot() == before

# --- profiles -----------------------------------------------------------------
def test_new_profiles_get_the_cc_profiles_command(home, app_factory):
    basic_home(home)
    home.write(".claude-work/commands/cc-profiles.md", "my own command\n")
    before = home.snapshot()
    app = app_factory()

    app.post("/api/profiles/create", {"label": "Empty", "id": "empty", "base": "", "share": []})
    text = home.path(".claude-empty/commands/cc-profiles.md").read_text()
    assert is_current_command(text) and "argument-hint:" in text

    # sharing commands with the source: the command goes into the source, through the link
    app.post("/api/profiles/create", {"label": "Shared", "id": "shared-cmd", "base": "", "share": ["commands"]})
    assert home.path(".claude-shared-cmd/commands").is_symlink()
    assert home.path(".claude/commands/cc-profiles.md").read_text() == text

    # a copy of a profile whose cc-profiles.md is someone else's keeps it as it is
    app.post("/api/profiles/create", {"label": "Copy", "id": "copy", "base": "work", "share": []})
    assert home.path(".claude-copy/commands/cc-profiles.md").read_text() == "my own command\n"

    # an empty profile that shares settings.json links it instead of writing its own
    app.post("/api/profiles/create", {"label": "Shared settings", "id": "shared-set", "base": "",
                                      "share": ["settings.json"]})
    assert home.path(".claude-shared-set/settings.json").is_symlink()

    app.restore_all()
    assert home.snapshot() == before


def test_a_failed_operation_can_still_be_undone(home, app_factory):
    basic_home(home)
    before = home.snapshot()
    app = app_factory(CC_PROFILES_FAULT="create-profile-after-copy")
    status, body = app.request("/api/profiles/create", {"label": "Half", "id": "half", "base": "default",
                                                        "include_projects": True, "share": []})
    assert status == 500 and "fault injected" in body["error"] and "restore the incomplete backup" in body["error"]
    assert home.path(".claude-half/projects").is_dir()  # the copy happened before the failure
    newest = app.get("/api/backups")[0]
    assert newest["failed"] and newest["restorable"]
    app.post("/api/backups/restore", {"name": newest["name"]})
    assert home.snapshot() == before


def test_a_failure_before_any_change_leaves_no_backup(home, app_factory):
    basic_home(home)
    app = app_factory()
    assert app.request("/api/projects/move", {"project": "nope", "from": "default", "to": "work"})[0] == 404
    assert app.get("/api/backups") == []


def test_create_edit_delete_profile(home, app_factory):
    basic_home(home)
    home.write(".claude/.credentials.json", "{\"secret\": 1}")
    home.write(".zshrc", "export X=1\n\n# Claude Code: work profile\nalias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work claude'\n")
    before = home.snapshot()
    app = app_factory()

    app.post("/api/profiles/create", {"label": "Client X", "id": "client-x", "base": "default",
                                      "include_projects": False, "share": ["skills"]})
    new = home.path(".claude-client-x")
    assert not (new / ".credentials.json").exists(), "login credentials must never be copied"
    assert "oauthAccount" not in json.loads((new / ".claude.json").read_text())
    launcher = home.path(".local/bin/claude-client-x")
    assert os.access(launcher, os.X_OK) and 'CLAUDE_CONFIG_DIR="$HOME/.claude-client-x"' in launcher.read_text()

    app.post("/api/profiles/update", {"id": "client-x", "label": "Client Y", "command": "cy"})
    assert not launcher.exists() and home.path(".local/bin/cy").exists()
    assert "already exists" in app.post_error("/api/profiles/create", {"label": "Client Y", "id": "client-y"})
    assert "cannot change" in app.post_error("/api/profiles/update", {"id": "default", "label": "Main", "command": "c"})

    assert "source profile" in app.post_error("/api/profiles/delete", {"id": "default"})
    app.post("/api/profiles/delete", {"id": "client-x"})
    assert not new.exists() and not home.path(".local/bin/cy").exists()
    app.post("/api/profiles/delete", {"id": "work", "merge_into": "default"})   # legacy alias in .zshrc
    assert home.path(".zshrc").read_text() == "export X=1\n"
    assert home.path(f".claude/projects/{san(home.path('code/work/api'))}/s-api-work.jsonl").exists()

    app.restore_all()
    assert home.snapshot() == before


def test_delete_refused_while_session_open(home, app_factory):
    basic_home(home)
    app = app_factory()
    f = next(home.path(".claude-work/projects").rglob("*.jsonl"))
    os.utime(f, (time.time(), time.time()))
    assert "session is open" in app.post_error("/api/profiles/delete", {"id": "work"})


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
def pypi(tmp_path, version):
    f = tmp_path / f"pypi-{version}.json"
    f.write_text(json.dumps({"info": {"version": version}}))
    return f.as_uri()


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


def fake_tool(tmp_path, name, output, code):
    """A fake `pipx` or `uv` on PATH, first, so a real one is never run."""
    bin_dir = tmp_path / f"bin-{code}-{abs(hash(output))}"
    bin_dir.mkdir()
    tool = bin_dir / name
    tool.write_text(f"#!/bin/sh\ncat <<'EOF'\n{output}\nEOF\nexit {code}\n")
    tool.chmod(0o755)
    return f"{bin_dir}:/usr/bin:/bin"


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


# --- export, import, plugins --------------------------------------------------
def raw(app, path, data=None):
    """A request whose answer (or body) is not JSON: (status, bytes)."""
    headers = {"X-Token": app.token}
    if data is not None:
        headers["Content-Type"] = "application/zip"
    req = urllib.request.Request(app.base + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def export_home(home):
    """A default profile with everything an export has to handle."""
    basic_home(home)
    d = home.path(".claude")
    home.write(".claude/.credentials.json", '{"secret": 1}')
    home.json(".claude/settings.local.json", {"hooks": {"Stop": [{"command": f"{d}/hooks/stop.sh"}]}})
    home.json(".claude/plugins/installed_plugins.json", {"version": 2, "plugins": {"demo@market": [
        {"scope": "user", "installPath": f"{d}/plugins/cache/market/demo/1.0.0", "version": "1.0.0",
         "installedAt": "2026-10-01T10:00:00.000Z"}]}})
    home.write(".claude/plugins/cache/market/demo/1.0.0/plugin.json", "{}")
    home.write(".claude/skills/review/SKILL.md", "---\nname: review\n---\n")
    home.write("elsewhere/linked/SKILL.md", "---\nname: linked\n---\n")  # a skill linked from elsewhere in home
    os.symlink(home.path("elsewhere/linked"), home.path(".claude/skills/linked"))
    os.symlink("/etc", home.path(".claude/skills/outside"))  # a link out of home: never exported
    home.write(".claude/shell-snapshots/snap.sh", "runtime data")
    home.conversation("", "", "s-home", {"general.md": "always answer briefly"})  # the general memory


def test_export_holds_the_profile_without_credentials(home, app_factory):
    export_home(home)
    app = app_factory()
    status, data = raw(app, "/api/profiles/export?id=default&projects=0")
    assert status == 200
    z = zipfile.ZipFile(io.BytesIO(data))
    names = set(z.namelist())
    assert {"cc-profiles-export.json", "claude.json", "profile/settings.json", "profile/skills/review/SKILL.md",
            "profile/plugins/cache/market/demo/1.0.0/plugin.json", "home-memory/general.md"} <= names
    assert not any(".credentials.json" in n or "shell-snapshots" in n for n in names)
    assert "profile/skills/linked/SKILL.md" in names  # links inside home: their real content
    assert not any(n.startswith("profile/skills/outside") for n in names)
    assert not any(n.startswith("profile/projects/") or n == "profile/history.jsonl" for n in names)
    assert "__CC_PROFILES_PROFILE_DIR__/hooks/stop.sh" in z.read("profile/settings.local.json").decode()
    assert str(home.path(".claude")) not in z.read("profile/plugins/installed_plugins.json").decode()
    cfg = json.loads(z.read("claude.json"))
    assert "oauthAccount" not in cfg and "projects" not in cfg
    man = json.loads(z.read("cc-profiles-export.json"))
    assert man["app"] == "cc-profiles" and man["id"] == "default" and man["projects"] is False

    with_projects = zipfile.ZipFile(io.BytesIO(raw(app, "/api/profiles/export?id=default&projects=1")[1]))
    assert any(n.startswith("profile/projects/") for n in with_projects.namelist())
    assert "profile/history.jsonl" in with_projects.namelist()
    assert "projects" in json.loads(with_projects.read("claude.json"))


def test_import_recreates_the_profile_and_restores(home, app_factory):
    export_home(home)
    app = app_factory()
    data = raw(app, "/api/profiles/export?id=default&projects=1")[1]
    before = home.snapshot()
    status, body = raw(app, "/api/profiles/import?label=Laptop&id=laptop", data)
    r = json.loads(body)
    assert status == 200 and "not logged in" in r["message"]
    new = home.path(".claude-laptop")
    assert (new / "skills/review/SKILL.md").exists()
    assert f"{new}/hooks/stop.sh" in (new / "settings.local.json").read_text()
    assert f"{new}/plugins/cache/market/demo/1.0.0" in (new / "plugins/installed_plugins.json").read_text()
    assert not (new / ".credentials.json").exists()
    assert "oauthAccount" not in json.loads((new / ".claude.json").read_text())
    assert (new / "commands/cc-profiles.md").exists()
    assert os.access(home.path(".local/bin/claude-laptop"), os.X_OK)
    assert "laptop" in [p["id"] for p in app.get("/api/profiles")]
    assert "already exists" in json.loads(raw(app, "/api/profiles/import?label=Laptop&id=laptop", data)[1])["error"]
    app.restore_all()
    assert home.snapshot() == before


@pytest.mark.parametrize("bad", ["../evil.txt", "/etc/evil", "profile/../../evil", "link"])
def test_import_rejects_unsafe_archives(home, app_factory, bad):
    basic_home(home)
    app = app_factory()
    before = home.snapshot()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("cc-profiles-export.json", json.dumps({"app": "cc-profiles", "format": 1, "label": "X", "id": "x"}))
        z.writestr("profile/settings.json", "{}")
        if bad == "link":  # a symbolic link entry
            info = zipfile.ZipInfo("profile/skills")
            info.external_attr = (0o120777 << 16)
            z.writestr(info, "/etc")
        else:
            z.writestr(bad, "evil")
    status, body = raw(app, "/api/profiles/import?label=X&id=x", buf.getvalue())
    assert status == 400 and "Nothing was imported" in json.loads(body)["error"]
    assert home.snapshot() == before and not home.path(".claude-x").exists()
    assert "not a zip" in json.loads(raw(app, "/api/profiles/import?label=X&id=x", b"plain text")[1])["error"]


def test_plugins_are_listed_and_switched(home, app_factory):
    basic_home(home)
    d = home.path(".claude")
    home.json(".claude/plugins/installed_plugins.json", {"version": 2, "plugins": {
        "warp@claude-code-warp": [{"scope": "user", "installPath": f"{d}/plugins/cache/x", "version": "2.1.0",
                                   "installedAt": "2026-06-28T20:57:07.083Z"}],
        "lint@team": [{"scope": "project", "projectPath": str(home.path("code/work/api")), "version": "0.3.0"}]}})
    home.json(".claude/plugins/known_marketplaces.json", {"claude-code-warp": {
        "source": {"source": "github", "repo": "warpdotdev/claude-code-warp"}, "lastUpdated": "2026-08-26T13:20:55Z"}})
    home.json(".claude/settings.json", {"enabledPlugins": {"warp@claude-code-warp": True}})
    home.json(".claude/settings.local.json", {"enabledPlugins": {"lint@team": False}})
    before = home.snapshot()
    app = app_factory()
    data = app.get("/api/plugins?profile=default")
    by = {p["name"]: p for p in data["plugins"]}
    assert by["warp@claude-code-warp"]["enabled"] is True and by["warp@claude-code-warp"]["source"] == "settings"
    assert by["warp@claude-code-warp"]["version"] == "2.1.0" and by["warp@claude-code-warp"]["plugin"] == "warp"
    assert by["lint@team"]["enabled"] is False and by["lint@team"]["source"] == "local"
    assert by["lint@team"]["scopes"] == ["project"] and by["lint@team"]["projects"] == ["~/code/work/api"]
    assert data["marketplaces"] == [{"name": "claude-code-warp", "source": "warpdotdev/claude-code-warp",
                                     "updated": "2026-08-26"}]

    app.post("/api/plugins/enable", {"profile": "default", "plugin": "warp@claude-code-warp", "enabled": False})
    assert json.loads(home.path(".claude/settings.json").read_text())["enabledPlugins"]["warp@claude-code-warp"] is False
    app.post("/api/plugins/enable", {"profile": "default", "plugin": "lint@team", "enabled": True})
    assert json.loads(home.path(".claude/settings.local.json").read_text())["enabledPlugins"]["lint@team"] is True
    assert "lint@team" not in home.path(".claude/settings.json").read_text()  # written where its value lives
    assert app.request("/api/plugins/enable", {"profile": "default", "plugin": "nope@x", "enabled": True})[0] == 404
    assert "true or false" in app.post_error("/api/plugins/enable", {"profile": "default", "plugin": "lint@team",
                                                                     "enabled": "yes"})
    app.restore_all()
    assert home.snapshot() == before


# --- command line ---------------------------------------------------------------
def run_cli(home, *args, **env):
    e = child_env({"HOME": str(home.root), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC), **env})
    return subprocess.run([sys.executable, "-m", "cc_profiles", *args], env=e,
                          capture_output=True, text=True, timeout=20)


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
    sys.path.insert(0, str(SRC))
    from cc_profiles import server
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
        return subprocess.run(cmd, shell=True, env=e, capture_output=True, text=True, timeout=20)

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


def is_current_command(text):
    """The /cc-profiles text this version writes, with the cc-profiles it found (an absolute path)."""
    sys.path.insert(0, str(SRC))
    from cc_profiles import server
    exe = re.search(r"^!`(.*) open \$ARGUMENTS`$", text, re.M).group(1)
    return os.path.isabs(exe.split()[0]) and text == server.command_text(exe)


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
    sys.path.insert(0, str(SRC))
    from cc_profiles import server
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
    assert r.returncode == 0 and "--no-command" in r.stdout
    assert subprocess.run(["sh", script, "--nope"], capture_output=True).returncode == 2


def test_version_command(home):
    out = run_cli(home, "--version").stdout
    assert out.startswith("cc-profiles ")


# --- previews of the big operations (read-only) ---------------------------------
def test_delete_preview_lists_what_goes_and_changes_nothing(home, app_factory):
    basic_home(home)
    home.write(".zshrc", "# Claude Code: work profile\nalias claude-work='CLAUDE_CONFIG_DIR=~/.claude-work claude'\n")
    before = home.snapshot()
    app = app_factory()

    plan = app.get("/api/profiles/delete/preview?id=work&merge_into=default")
    actions = {(i["action"], i["item"]) for i in plan["items"]}
    assert ("move", "api/s-api-work.jsonl") in actions and ("move", "api/file-history/s-api-work") in actions
    assert ("merge", "history.jsonl") in actions and ("edit", "shell alias") in actions
    assert ("edit", "config entry") in actions and ("stash", "profile folder") in actions
    assert (plan["projects"], plan["conversations"], plan["prompts"], plan["into"]) == (1, 1, 1, "Default")

    alone = app.get("/api/profiles/delete/preview?id=work")
    assert [i["action"] for i in alone["items"]] == ["edit", "edit", "stash"]  # alias, config, folder
    assert "source profile" in app.request("/api/profiles/delete/preview?id=default")[1]["error"]
    assert "into itself" in app.request("/api/profiles/delete/preview?id=work&merge_into=work")[1]["error"]
    assert home.snapshot() == before

    app.post("/api/profiles/delete", {"id": "work", "merge_into": "default"})  # does what the preview said
    assert home.path(f".claude/projects/{san(home.path('code/work/api'))}/s-api-work.jsonl").exists()
    app.restore_all()
    assert home.snapshot() == before


def test_share_preview_lists_what_the_link_replaces(home, app_factory):
    basic_home(home)
    home.write(".claude-work/skills/only-work/SKILL.md", "x")
    before = home.snapshot()
    app = app_factory()

    plan = app.get("/api/sharing/preview?profile=work&item=skills&shared=1")
    assert [(i["action"], i["item"]) for i in plan["items"]] == [
        ("create", "skills"), ("stash", "skills"), ("only-here", "skills/only-work"), ("link", "skills")]
    assert "Not shared" in app.request("/api/sharing/preview?profile=work&item=skills&shared=0")[1]["error"]
    assert "source profile" in app.request("/api/sharing/preview?profile=default&item=skills&shared=1")[1]["error"]
    assert home.snapshot() == before

    app.post("/api/sharing", {"profile": "work", "item": "skills", "shared": True})
    off = app.get("/api/sharing/preview?profile=work&item=skills&shared=0")
    assert [i["action"] for i in off["items"]] == ["stash", "copy"]
    app.restore_all()
    assert home.snapshot() == before


# --- apply to all profiles: one operation, one backup ------------------------------
def all_home(home):
    """default; lab shares settings.json and skills with default; solo and work have their own."""
    basic_home(home)
    home.json(".claude/settings.json", {"language": "English", "timeFormat": "24-hour"})
    home.write(".claude/skills/review/SKILL.md", "---\nname: review\n---\nReview it.\n")
    cfg = json.loads(home.path(".claude.json").read_text())
    cfg["mcpServers"] = {"files": {"type": "stdio", "command": "npx", "args": ["files"]}}
    home.json(".claude.json", cfg)
    home.path(".claude-lab").mkdir()
    os.symlink("../.claude/settings.json", home.path(".claude-lab/settings.json"))
    os.symlink("../.claude/skills", home.path(".claude-lab/skills"))
    home.json(".claude-solo/settings.json", {"language": "Français"})
    home.json(".claude-solo/.claude.json", {"mcpServers": {"files": {"type": "stdio", "command": "other"}}})
    home.write(".claude-solo/skills/review/SKILL.md", "my own review\n")
    home.json(".claude-work/settings.local.json", {"language": "Italiano"})


def restore_newest(app):
    newest = app.get("/api/backups")[0]
    app.post("/api/backups/restore", {"name": newest["name"]})


def test_apply_a_setting_to_all_profiles_is_undone_by_one_restore(home, app_factory):
    all_home(home)
    before = home.snapshot()
    app = app_factory()

    plan = app.get("/api/settings/field/all/preview?profile=work&key=language")
    assert [(a["id"], a["detail"]) for a in plan["apply"]] == [
        ("default", '"English" → "Italiano" in settings.json'), ("solo", '"Français" → "Italiano" in settings.json')]
    assert plan["skip"] == [{"id": "lab", "label": "Lab", "reason": "shares settings.json with Default"}]
    assert home.snapshot() == before
    n = len(app.get("/api/backups"))
    r = app.post("/api/settings/field/all", {"profile": "work", "key": "language"})
    assert r["message"] == 'Language set to "Italiano" in 2 profiles, 1 skipped.'
    assert len(app.get("/api/backups")) == n + 1
    assert json.loads(home.path(".claude/settings.json").read_text())["language"] == "Italiano"
    assert json.loads(home.path(".claude-solo/settings.json").read_text())["language"] == "Italiano"
    assert home.path(".claude-lab/settings.json").is_symlink()
    assert "No profile to change" in app.post_error("/api/settings/field/all", {"profile": "work", "key": "language"})
    restore_newest(app)
    assert home.snapshot() == before

    # the default value (work has no time format) removes it where it is set
    app.post("/api/settings/field/all", {"profile": "work", "key": "timeFormat"})
    assert "timeFormat" not in json.loads(home.path(".claude/settings.json").read_text())
    restore_newest(app)
    assert home.snapshot() == before

    # a key of .claude.json goes to each profile's own .claude.json, in the same backup
    app.post("/api/settings/field", {"profile": "work", "key": "verbose", "value": True})
    r = app.post("/api/settings/field/all", {"profile": "work", "key": "verbose"})
    assert json.loads(home.path(".claude.json").read_text())["verbose"] is True
    assert json.loads(home.path(".claude-solo/.claude.json").read_text())["verbose"] is True
    for b in app.get("/api/backups")[:2]:  # apply to all, then the single change before it
        app.post("/api/backups/restore", {"name": b["name"]})
    assert home.snapshot() == before


def test_add_a_permission_rule_to_all_profiles_is_undone_by_one_restore(home, app_factory):
    all_home(home)
    before = home.snapshot()
    app = app_factory()

    plan = app.get("/api/settings/permissions/all/preview?list=deny&rule=" + urllib.parse.quote("Bash(rm -rf:*)"))
    assert [a["id"] for a in plan["apply"]] == ["default", "solo", "work"]
    assert plan["skip"] == [{"id": "lab", "label": "Lab", "reason": "shares settings.json with Default"}]
    app.post("/api/settings/permissions/all", {"list": "deny", "rule": " Bash(rm -rf:*) "})
    for p in (".claude", ".claude-solo", ".claude-work"):
        assert json.loads(home.path(f"{p}/settings.json").read_text())["permissions"]["deny"] == ["Bash(rm -rf:*)"]
    assert json.loads(home.path(".claude/settings.json").read_text())["language"] == "English"  # the rest is kept
    assert "already in deny" in app.post_error("/api/settings/permissions/all", {"list": "deny", "rule": "Bash(rm -rf:*)"})
    assert "allow, ask or deny" in app.post_error("/api/settings/permissions/all", {"list": "nope", "rule": "x"})
    assert "one rule" in app.post_error("/api/settings/permissions/all", {"list": "deny", "rule": "a\nb"})
    restore_newest(app)
    assert home.snapshot() == before


def test_copy_a_skill_and_a_server_to_all_profiles_is_undone_by_one_restore(home, app_factory):
    all_home(home)
    before = home.snapshot()
    app = app_factory()

    plan = app.get("/api/skills/copy-all/preview?profile=default&name=review")
    assert [a["id"] for a in plan["apply"]] == ["work"]
    assert {s["id"]: s["reason"] for s in plan["skip"]} == {
        "lab": "shares its skills with Default", "solo": "already has a skill called review"}
    app.post("/api/skills/copy-all", {"profile": "default", "name": "review"})
    assert home.path(".claude-work/skills/review/SKILL.md").read_text() == "---\nname: review\n---\nReview it.\n"
    assert home.path(".claude-solo/skills/review/SKILL.md").read_text() == "my own review\n"
    restore_newest(app)
    assert home.snapshot() == before

    plan = app.get("/api/mcp/copy-all/preview?profile=default&scope=user&name=files")
    assert [a["id"] for a in plan["apply"]] == ["work"]
    assert {s["id"]: s["reason"].split(":")[0] for s in plan["skip"]} == {
        "lab": "~/.claude-lab/.claude.json cannot be read", "solo": "already has a server called files"}
    app.post("/api/mcp/copy-all", {"profile": "default", "scope": "user", "name": "files"})
    assert json.loads(home.path(".claude-work/.claude.json").read_text())["mcpServers"]["files"]["command"] == "npx"
    assert len(app.get("/api/backups")) == 3  # skill copy, its restore, server copy
    restore_newest(app)
    assert home.snapshot() == before


# --- automatic backup cleanup ---------------------------------------------------
def age_backup(home, name, days, **extra):
    man = home.path(f".cc-profiles/backups/{name}/manifest.json")
    data = json.loads(man.read_text())
    data["created"] -= days * 86400
    data.update(extra)
    man.write_text(json.dumps(data))


def test_automatic_cleanup_keeps_recent_and_incomplete_backups(home, app_factory):
    basic_home(home)
    app = app_factory()
    auto = app.get("/api/backups/auto")
    assert auto["days"] == 90 and auto["default"] == 90 and auto["choices"] == [15, 30, 60, 90]  # on by default
    for match in ("code/a", "code/b", "code/c", "code/d"):
        app.post("/api/rules", {"match": match, "profile": "default"})
    names = [b["name"] for b in app.get("/api/backups")]  # newest first: d, c, b, a
    age_backup(home, names[3], 100)                                # old: deleted
    age_backup(home, names[2], 100, failed="boom")                 # old and incomplete: kept
    age_backup(home, names[1], 100, failed="boom", restored=1.0)   # old, incomplete but restored: deleted
    age_backup(home, names[0], 20)                                 # younger than the limit: kept
    assert app.request("/api/backups/auto", {"days": 7})[0] == 400
    r = app.post("/api/backups/auto", {"days": 30})
    assert "Deleted 2 backups older than 30 days" in r["message"]
    left = [b["name"] for b in app.get("/api/backups")]
    assert names[2] in left and names[0] in left and names[3] not in left and names[1] not in left
    assert json.loads(home.path(".cc-profiles/config.json").read_text())["backup_keep_days"] == 30

    # the server prunes again when it starts; the backup of the last 24 hours stays
    app.stop()
    age_backup(home, names[0], 20)  # now 40 days old
    app = app_factory()
    left = [b["name"] for b in app.get("/api/backups")]
    assert names[0] not in left and names[2] in left and len(left) == 2  # the incomplete one and the setting's
    assert app.get("/api/backups/auto")["days"] == 30
    assert app.request("/api/backups/auto", {"days": None})[0] == 400  # it cannot be turned off

    # a value only older versions offered keeps working, and stays selectable; it cannot be picked anew
    assert app.request("/api/backups/auto", {"days": 365})[0] == 400
    cfg = json.loads(home.path(".cc-profiles/config.json").read_text())
    home.json(".cc-profiles/config.json", dict(cfg, backup_keep_days=365))
    auto = app.get("/api/backups/auto")
    assert auto["days"] == 365 and auto["choices"] == [15, 30, 60, 90, 365]


def test_kept_backups_survive_every_cleanup(home, app_factory):
    basic_home(home)
    app = app_factory()
    for match in ("code/a", "code/b", "code/c"):
        app.post("/api/rules", {"match": match, "profile": "default"})
    names = [b["name"] for b in app.get("/api/backups")]  # newest first: c, b, a
    for n in names:
        age_backup(home, n, 200)
    assert "Kept" in app.post("/api/backups/keep", {"name": names[0], "kept": True})["message"]
    assert app.request("/api/backups/keep", {"name": names[0], "kept": "yes"})[0] == 400
    assert app.request("/api/backups/keep", {"name": "../x", "kept": True})[0] == 400
    assert {b["name"]: b["kept"] for b in app.get("/api/backups")}[names[0]] is True
    assert "turn off Keep first" in app.post_error("/api/backups/delete", {"name": names[0]})

    # the default 90-day cleanup at start and the manual "delete old backups" both skip it
    app.stop()
    app = app_factory()
    assert [b["name"] for b in app.get("/api/backups")] == [names[0]]
    assert "No backups older" in app.post("/api/backups/prune", {"days": 1})["message"]
    app.post("/api/backups/keep", {"name": names[0], "kept": False})
    assert app.get("/api/backups")[0]["kept"] is False
    app.post("/api/backups/prune", {"days": 1})
    assert app.get("/api/backups") == []


# --- profile templates ------------------------------------------------------------
def test_templates_hold_no_credentials_and_create_profiles(home, app_factory):
    export_home(home)
    home.write(".claude/agents/reviewer.md", "an agent\n")
    home.write(".claude/output-styles/terse.md", "---\nname: Terse\n---\n")
    cfg = json.loads(home.path(".claude.json").read_text())
    cfg.update({"userID": "u-1", "mcpServers": {"files": {"type": "stdio", "command": "npx"}}})
    home.json(".claude.json", cfg)
    before = home.snapshot()
    app = app_factory()

    app.post("/api/templates/save", {"profile": "default", "name": "Base setup"})
    z = zipfile.ZipFile(home.path(".cc-profiles/templates/Base setup.zip"))
    names = z.namelist()
    assert {"profile/settings.json", "profile/skills/review/SKILL.md", "profile/agents/reviewer.md",
            "profile/output-styles/terse.md", "profile/settings.local.json"} <= set(names)
    assert not any(".credentials.json" in n for n in names), "templates never hold credentials"
    assert not any(n.startswith(("profile/projects/", "profile/plugins/", "profile/history", "home-memory/"))
                   for n in names), "templates hold no conversations, memories or plugins"
    assert json.loads(z.read("claude.json")) == {"mcpServers": {"files": {"type": "stdio", "command": "npx"}}}
    listed = app.get("/api/templates")["templates"]
    assert [(t["name"], t["from"], t["skills"], t["mcp"]) for t in listed] == [("Base setup", "Default", 2, 1)]
    assert "already a template" in app.post_error("/api/templates/save", {"profile": "default", "name": "Base setup"})
    for bad in ("../x", "a/b", "", ".hidden"):
        assert app.request("/api/templates/save", {"profile": "default", "name": bad})[0] == 400
    assert app.request("/api/templates/delete", {"name": "../config"})[0] == 400

    r = app.post("/api/templates/create", {"name": "Base setup", "label": "Client", "id": "client"})
    assert "from the template Base setup" in r["message"]
    new = home.path(".claude-client")
    assert (new / "skills/review/SKILL.md").exists() and (new / "agents/reviewer.md").exists()
    assert f"{new}/hooks/stop.sh" in (new / "settings.local.json").read_text()
    assert not (new / ".credentials.json").exists() and not (new / "projects").exists()
    assert json.loads((new / ".claude.json").read_text()) == {"mcpServers": {"files": {"type": "stdio", "command": "npx"}}}
    assert os.access(home.path(".local/bin/claude-client"), os.X_OK)

    app.post("/api/templates/delete", {"name": "Base setup"})
    assert app.get("/api/templates")["templates"] == []
    app.restore_all()
    assert home.snapshot() == before
    assert app.get("/api/templates")["templates"] == []  # restoring the save removes the template too


def test_template_items_can_be_shared_at_creation(home, app_factory):
    """A shared item is linked to the source profile instead of being filled from the template."""
    export_home(home)
    home.write(".claude/agents/reviewer.md", "an agent\n")
    home.write(".claude/CLAUDE.md", "base rules\n")
    before = home.snapshot()
    app = app_factory()
    app.post("/api/templates/save", {"profile": "default", "name": "Base"})
    [t] = app.get("/api/templates")["templates"]
    assert t["counts"] == {"skills": 2, "agents": 1, "CLAUDE.md": 1, "settings.json": 1}

    r = app.post("/api/templates/create", {"name": "Base", "label": "Client", "id": "client",
                                           "share": ["skills", "agents", "CLAUDE.md", "commands", "plugins",
                                                     "projects", "../x"]})
    msg = r["message"]
    assert "skills: shared with Default, the template's 2 skills are not copied" in msg
    assert "agents: shared with Default, the template's 1 agent is not copied" in msg
    assert "CLAUDE.md: shared with Default, the template's CLAUDE.md is not copied" in msg
    assert "commands: shared with Default;" in msg and "plugins: shared with Default" in msg
    new = home.path(".claude-client")
    for item in ("skills", "agents", "CLAUDE.md", "commands", "plugins"):
        assert os.readlink(new / item) == f"../.claude/{item}", item
    assert not (new / "projects").exists() and not os.path.lexists(home.path(".claude/projects/../x"))
    assert not os.path.islink(new / "settings.json") and (new / "settings.local.json").exists()
    assert (home.path(".claude/commands/cc-profiles.md")).exists(), "the command goes into the shared source folder"
    shared = {i["item"]: i["shared"] for p in app.get("/api/sharing") if p["id"] == "client" for i in p["items"]}
    assert shared == {"skills": True, "plugins": True, "agents": True, "commands": True, "CLAUDE.md": True,
                      "settings.json": False}

    app.restore_all()
    assert home.snapshot() == before


# --- listings and their caches ------------------------------------------------
def test_listings_follow_changes_on_disk(home, app_factory):
    """Listings reuse what they read while files and folders are unchanged: a change
    on disk must show up in the very next request."""
    basic_home(home)
    app = app_factory()
    api = san(home.path("code/work/api"))
    counts = lambda: {p["id"]: (p["conv"], p["memories"]) for p in app.get("/api/profiles")}
    mems = lambda: {r["name"]: r["count"] for r in app.get("/api/memory/projects?profile=default")}
    assert counts()["default"] == (3, 1) and mems()[api] == 1
    assert {r["name"] for r in app.get("/api/projects")} == {api, san(home.path("code/personal/blog")),
                                                            san(home.path("code/old-name"))}

    home.conversation("", "code/work/api", "s-api-2", {"todo.md": "next steps"})
    home.conversation("", "code/fresh", "s-fresh")  # a new project, known only from its conversation
    assert counts()["default"] == (5, 2) and mems()[api] == 2
    fresh = {r["name"]: r for r in app.get("/api/projects")}[san(home.path("code/fresh"))]
    assert fresh["path"] == str(home.path("code/fresh")) and fresh["exists"]
    conv = {r["name"]: r["count"] for r in app.get("/api/conversations/projects?profile=default")}
    assert conv[api] == 2

    home.json(".claude.json", {"projects": {}})  # what the config said is gone: the conversation still tells
    with open(home.path(".claude-work/history.jsonl"), "a") as f:
        f.write("3\n")  # valid JSON, but not a prompt
    assert {r["name"]: r for r in app.get("/api/projects")}[api]["path"] == str(home.path("code/work/api"))


def test_health_reports_problems_and_notices_fixes(home, app_factory):
    basic_home(home)
    home.path("elsewhere/old-name").mkdir(parents=True)  # a folder with the lost project's name
    md = home.path(f".claude/projects/{san(home.path('code/work/api'))}/memory")
    (md / "loose.md").write_text("---\nname: loose\n---\nnot in the index\n")
    with open(md / "MEMORY.md", "a") as f:
        f.write("- [gone](gone.md) — deleted by hand\n")
    with open(home.path(".claude/history.jsonl"), "a") as f:
        f.write("not json\n")
    app = app_factory()

    def report():
        r = {p["id"]: p for p in app.get("/api/health")}["default"]
        return [c["text"] for c in r["checks"]], r["orphans"]

    texts, orphans = report()
    assert "Prompt history: 4 prompts, 1 broken lines" in texts
    assert any(t.endswith("loose.md is not in MEMORY.md") for t in texts)
    assert any(t.endswith("gone.md is missing") for t in texts)
    (orphan,) = orphans
    assert orphan["name"] == san(home.path("code/old-name")) and orphan["candidates"] == ["~/elsewhere/old-name"]
    items = app.get(f"/api/memory/list?profile=default&project={md.parent.name}")["items"]
    assert {i["file"]: i["indexed"] for i in items} == {"api-notes.md": True, "loose.md": False}

    with open(md / "MEMORY.md", "a") as f:
        f.write("- [loose](loose.md) — now indexed\n")
    lines = home.path(".claude/history.jsonl").read_text().splitlines()
    home.write(".claude/history.jsonl", "\n".join(l for l in lines if l != "not json") + "\n")
    texts, _ = report()
    assert "Prompt history: 3 prompts" in texts
    assert not any("loose.md" in t for t in texts) and any(t.endswith("gone.md is missing") for t in texts)


def test_whats_new_lists_the_release_notes_shipped_with_the_app(home, app_factory):
    """/api/whatsnew needs nothing from the internet: the notes are in static/whatsnew.json."""
    d = app_factory().get("/api/whatsnew")
    from cc_profiles import __version__
    assert d["version"] == __version__
    assert d["releases"] and all({"version", "date", "sections"} <= set(r) for r in d["releases"])
    assert all(s["title"] and s["items"] for r in d["releases"] for s in r["sections"])


def test_about_counts_each_profile(home, app_factory):
    basic_home(home)
    about = app_factory().get("/api/about")
    usage = {p["id"]: p["usage"] for p in about["profiles"]}
    assert usage["default"]["Saved conversations"] == 3 and usage["default"]["Prompts in history"] == 3
    assert usage["work"]["Prompts in history"] == 1 and usage["default"]["Disk usage"] > 0
    assert about["app"]["Backups"].startswith("0 ·")


# --- usage ----------------------------------------------------------------------
def reply_line(mid, days_ago, model="claude-sonnet-5-5", inp=0, out=0, cw=0, cr=0, req="req-1", **extra):
    """An assistant line with the usage Claude Code records on every reply."""
    t = time.time() - days_ago * 86400
    usage = {"input_tokens": inp, "output_tokens": out, "cache_creation_input_tokens": cw,
             "cache_read_input_tokens": cr, **extra}
    return json.dumps({"type": "assistant", "requestId": req,
                       "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.123Z", time.gmtime(t)),
                       "message": {"id": mid, "model": model, "role": "assistant",
                                   "content": [{"type": "text", "text": "ok"}], "usage": usage}},
                      separators=(",", ":"))


def add_lines(home, profile, project, session, lines):
    d = home.conversation(profile, project, session) if not (home.profile(profile) / "projects" / san(home.path(project)) / f"{session}.jsonl").exists() \
        else home.profile(profile) / "projects" / san(home.path(project))
    with open(d / f"{session}.jsonl", "a") as f:
        f.write("\n".join(lines) + "\n")
    return d


M = 1_000_000


def test_usage_is_counted_once_per_reply_and_priced(home, app_factory):
    basic_home(home)
    big = reply_line("msg-a", 0.01, inp=M, out=M, cw=M, cr=M)  # sonnet 5.5: 2 + 10 + 2.50 + 0.20 = $14.70
    add_lines(home, "", "code/work/api", "s-use", [
        big, big,  # Claude Code writes one line per content block of the same reply
        reply_line("msg-a", 0.01, inp=M, out=10, cw=M, cr=M),  # a mid-stream line: the one with more output wins
        "{not json", '{"type":"assistant","message":"odd"}',  # broken lines are skipped
        reply_line("msg-b", 0.01, model="<synthetic>", inp=100, out=50),  # no list price: tokens, no cost
        reply_line("msg-c", 3, model="claude-haiku-4-5", out=M),  # $5
        reply_line("msg-d", 40, model="claude-opus-5-5", out=M),  # $20, outside 30 days
        reply_line("msg-e", 0.01, model="claude-sonnet-5-5", cw=M,  # written for 1 hour: 2 × input
                   cache_creation={"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": M}),
        reply_line("msg-f", 0.02, req="req-2", model="claude-opus-4-1", inp=M),  # $15; same id as below, other request
    ])
    add_lines(home, "", "code/personal/blog", "s-use2", [reply_line("msg-f", 0.02, req="req-3", model="claude-opus-4-1", inp=M)])
    # a resumed conversation copies earlier replies into its own file; a moved one can sit in two profiles
    add_lines(home, "work", "code/work/api", "s-use-work", [big, reply_line("msg-w", 1, model="claude-opus-4-8", out=M)])
    app = app_factory()
    before = home.snapshot()

    r = app.get("/api/usage?profile=all&days=30")
    t = r["totals"]
    assert t["replies"] == 7  # a, b, c, e, f twice (two requests), w
    assert (t["input"], t["output"], t["cache_write"], t["cache_read"]) == (3 * M + 100, 3 * M + 50, 2 * M, M)
    assert t["cost"] == pytest.approx(14.70 + 5 + 4 + 15 + 15 + 25)
    assert t["unpriced_tokens"] == 150 and t["cache_read_share"] == pytest.approx(M / (6 * M + 100), abs=1e-4)
    assert len(r["daily"]) == 30 and r["daily"][-1]["date"] == time.strftime("%Y-%m-%d")
    assert r["start"] == r["daily"][0]["date"] and r["end"] == r["daily"][-1]["date"]
    assert sum(d["replies"] for d in r["daily"]) == 7 and sum(1 for d in r["daily"] if d["tokens"]) <= 4
    assert all(d["tokens"] == 0 and d["cost"] == 0 for d in r["daily"][:-5])  # every day is there, zeros included
    models = {m["model"]: m for m in r["models"]}
    assert models["<synthetic>"]["family"] is None and models["<synthetic>"]["unpriced_tokens"] == 150
    assert models["claude-haiku-4-5"]["cost"] == 5 and models["claude-opus-4-8"]["family"] == "Opus 4.5–5"
    assert {p["id"]: p["replies"] for p in r["profiles"]} == {"default": 6, "work": 1}
    projects = {(p["profile"], p["pretty"]): p["replies"] for p in r["projects"]}
    assert projects == {("default", "~/code/work/api"): 5, ("default", "~/code/personal/blog"): 1, ("work", "~/code/work/api"): 1}
    assert r["projects_count"] == 3 and r["prices_checked"] and r["currency"] == "USD"

    work = app.get("/api/usage?profile=work&days=7")  # alone, work counts its copy of msg-a
    assert work["totals"]["replies"] == 2 and "profiles" not in work and len(work["daily"]) == 7
    assert work["totals"]["cost"] == pytest.approx(14.70 + 25)
    assert app.get("/api/usage?profile=default&days=90")["totals"]["replies"] == 7  # msg-d is 40 days old
    assert app.get("/api/usage")["days"] == 30  # all profiles, 30 days by default
    assert home.snapshot() == before  # read-only
    assert not home.path(".cc-profiles/backups").exists() or not any(home.path(".cc-profiles/backups").iterdir())

    # a new reply is read on the next request: the cache follows the file
    add_lines(home, "work", "code/work/api", "s-use-work", [reply_line("msg-new", 0, model="claude-haiku-4-5", inp=10)])
    assert app.get("/api/usage?profile=work&days=7")["totals"]["replies"] == 3


def test_usage_counts_subagent_conversations(home, app_factory):
    basic_home(home)
    d = add_lines(home, "", "code/work/api", "s-main", [reply_line("m-main", 0.01, out=10)])
    sub = d / "s-main" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text(reply_line("m-sub", 0.01, out=20) + "\n")
    app = app_factory()
    assert app.get("/api/usage?profile=default&days=7")["totals"]["output"] == 30


def test_usage_rejects_bad_parameters(home, app_factory):
    basic_home(home)
    app = app_factory()
    for q in ("days=10", "days=abc", "days=030", "days=-7", "days=7.0"):
        status, data = app.request("/api/usage?profile=all&" + q)
        assert status == 400 and "Pick 7, 14, 30 or 90 days" in data["error"], q
    status, data = app.request("/api/usage?profile=nope&days=7")
    assert status == 400 and "Unknown profile" in data["error"]
    r = app.get("/api/usage?profile=default&days=90")
    assert r["totals"]["replies"] == 0 and len(r["daily"]) == 90 and r["models"] == [] and r["projects"] == []


def test_usage_csv_has_one_row_per_day_and_model(home, app_factory):
    basic_home(home)
    add_lines(home, "", "code/work/api", "s-csv", [
        reply_line("c-1", 0.01, inp=M, out=M),                      # sonnet 5.5: $12
        reply_line("c-2", 0.01, req="r2", inp=10, out=20, cw=30, cr=40),
        reply_line("c-3", 0.01, model="claude-haiku-4-5", out=M),   # $5
        reply_line("c-4", 2, out=M),                                # $10, two days ago
        reply_line("c-5", 0.01, model="=cmd|' /C calc'!A0", inp=7),  # no list price, not a formula
        reply_line("c-6", 40, out=M),                               # outside 30 days
    ])
    app = app_factory()
    before = home.snapshot()
    req = urllib.request.Request(app.base + "/api/usage.csv?profile=default&days=30", headers={"X-Token": app.token})
    with urllib.request.urlopen(req, timeout=30) as r:
        assert r.headers["Content-Type"] == "text/csv; charset=utf-8"
        assert r.headers["Content-Disposition"] == 'attachment; filename="cc-profiles-usage-default-30d.csv"'
        rows = list(csv.reader(io.StringIO(r.read().decode("utf-8"))))
    assert rows[0] == ["date", "model", "input_tokens", "output_tokens", "cache_write_tokens", "cache_read_tokens",
                       "replies", "estimated_cost_usd"]
    # the days of the replies themselves (0.01 and 2 days ago): right after midnight "0.01 days ago" is yesterday
    today, two_ago = (time.strftime("%Y-%m-%d", time.localtime(time.time() - d * 86400)) for d in (0.01, 2))
    body = {(x[0], x[1]): x[2:] for x in rows[1:]}
    assert len(rows) == 5 and [x[0] for x in rows[1:]] == sorted(x[0] for x in rows[1:])  # oldest first
    assert body[(two_ago, "claude-sonnet-5-5")] == ["0", str(M), "0", "0", "1", "10.0000"]
    sonnet = body[(today, "claude-sonnet-5-5")]
    assert sonnet[:5] == [str(M + 10), str(M + 20), "30", "40", "2"] and float(sonnet[5]) == pytest.approx(12, abs=0.001)
    assert body[(today, "claude-haiku-4-5")] == ["0", str(M), "0", "0", "1", "5.0000"]
    assert body[(today, "'=cmd|' /C calc'!A0")] == ["7", "0", "0", "0", "1", ""]  # no price: no cost
    # the same validation as /api/usage, and the token guard
    assert app.request("/api/usage.csv?profile=default&days=10")[0] == 400
    assert app.request("/api/usage.csv?profile=nope&days=7")[0] == 400
    assert app.request("/api/usage.csv?profile=all&days=7", token=False)[0] == 403
    req = urllib.request.Request(app.base + "/api/usage.csv?days=7", headers={"X-Token": app.token})
    with urllib.request.urlopen(req, timeout=30) as r:
        assert 'filename="cc-profiles-usage-all-7d.csv"' in r.headers["Content-Disposition"]
    assert home.snapshot() == before


def test_usage_lists_the_most_expensive_sessions(home, app_factory):
    basic_home(home)
    p = home.profile("") / "projects" / san(home.path("code/work/api"))
    add_lines(home, "", "code/work/api", "s-cheap", [reply_line("e-1", 0.01, model="claude-haiku-4-5", out=1000)])
    (p / "s-cheap.jsonl").write_text(json.dumps({"type": "user", "message": {"content": "a cheap question"},
                                                 "timestamp": "2026-01-01T00:00:00Z"}) + "\n"
                                     + (p / "s-cheap.jsonl").read_text())
    add_lines(home, "", "code/work/api", "s-dear", [reply_line("e-2", 1, model="claude-opus-4-1", out=M)])  # $75
    sub = p / "s-dear" / "subagents"
    sub.mkdir(parents=True)
    (sub / "agent-1.jsonl").write_text(reply_line("e-3", 1, model="claude-opus-4-1", inp=M) + "\n")  # +$15, same session
    add_lines(home, "work", "code/work/api", "s-mid", [reply_line("e-4", 0.5, out=M)])  # sonnet 5.5: $10
    add_lines(home, "", "code/personal/blog", "s-free", [reply_line("e-5", 0.01, model="<synthetic>", out=M)])
    add_lines(home, "", "code/personal/blog", "s-old", [reply_line("e-6", 50, model="claude-opus-4-1", out=M)])
    for i in range(12):  # more than 10 sessions: only the top 10 are listed
        add_lines(home, "", "code/personal/blog", f"s-many-{i}",
                  [reply_line(f"m-{i}", 0.01, model="claude-haiku-4-5", out=10 + i)])
    app = app_factory()
    r = app.get("/api/usage?profile=all&days=30")
    s = r["sessions"]
    assert len(s) == 10
    assert [x["session"] for x in s[:3]] == ["s-dear", "s-mid", "s-cheap"]
    dear = s[0]
    assert dear["cost"] == pytest.approx(90) and dear["replies"] == 2 and dear["tokens"] == 2 * M
    assert dear["profile"] == "default" and dear["project"] == san(home.path("code/work/api"))
    assert dear["pretty"] == "~/code/work/api" and dear["exists"] is True
    assert dear["date"] == time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))
    assert s[2]["title"] == "a cheap question"  # the first prompt, like the Conversations tab
    assert s[1]["profile"] == "work"
    assert "s-old" not in [x["session"] for x in s]  # outside the period
    # a cheap session costs more than none: s-free (no list price, many tokens) comes after the priced ones
    assert [x["session"] for x in s[3:]] == [f"s-many-{i}" for i in range(11, 4, -1)]
    assert [x["session"] for x in app.get("/api/usage?profile=work&days=7")["sessions"]] == ["s-mid"]


# --- what a backup changed ----------------------------------------------------
def test_backup_changes_explain_every_step(home, app_factory):
    basic_home(home)
    home.json(".claude/settings.json", {"model": "opus", "permissions": {"defaultMode": "default"}})
    app = app_factory()
    api, blog = san(home.path("code/work/api")), san(home.path("code/personal/blog"))

    app.post("/api/projects/move", {"project": api, "from": "default", "to": "work"})
    app.post("/api/settings/field", {"profile": "default", "key": "permissions.defaultMode", "value": "plan"})
    app.post("/api/memory/save", {"profile": "work", "project": api, "file": "new-note.md", "content": "hello"})
    app.post("/api/memory/move", {"profile": "work", "project": api, "file": "new-note.md",
                                  "to_profile": "default", "to_project": blog})
    app.post("/api/projects/delete", {"project": blog, "profile": "default"})
    app.post("/api/mcp/save", {"profile": "default", "scope": "user", "name": "files", "config": {
        "type": "stdio", "command": "npx", "args": ["sk-ant-abc123"], "env": {"API_KEY": "secret-123"},
        "headers": {"X-Custom": "plain-value"}}})
    app.post("/api/mcp/save", {"profile": "default", "scope": "user", "name": "files", "old_name": "files", "config": {
        "type": "stdio", "command": "npx", "env": {"API_KEY": "secret-456"}}})
    listed = app.get("/api/backups")
    snap = home.snapshot()
    backups_before = sorted((str(p), p.stat().st_mtime_ns) for p in home.path(".cc-profiles/backups").rglob("*"))

    def changes(title_start, op=""):
        name = next(b["name"] for b in listed if b["title"].startswith(title_start) and b["name"].endswith(op))
        return app.get("/api/backups/changes?name=" + urllib.parse.quote(name))

    # a setting: the file copied before the change, with a diff of the JSON
    c = changes("", "_setting")
    step = next(s for s in c["steps"] if s["op"] == "copy")
    assert step["text"] == "Copied before a change" and step["path"] == "~/.claude/settings.json"
    d = step["diff"]
    assert d["status"] == "changed" and (d["added"], d["removed"]) == (1, 1)
    assert '-    "defaultMode": "default"' in d["lines"] and '+    "defaultMode": "plan"' in d["lines"]
    assert d["lines"][0].startswith("--- in the backup") and c["files_changed"] >= 1

    # a move: from → to, with the folder it moved
    c = changes("Move ~/code/work/api")
    moves = [s for s in c["steps"] if s["op"] == "move"]
    assert {"op": "move", "text": "Moved", "path": "~/.claude/file-history/s-api",
            "to": "~/.claude-work/file-history/s-api", "now": "folder"} in moves
    assert any(s["path"] == f"~/.claude/projects/{api}/s-api.jsonl" and s["now"] == "file" for s in moves)
    hist = next(s for s in c["steps"] if s["op"] == "copy" and s["path"] == "~/.claude/history.jsonl")
    assert hist["diff"]["status"] == "changed" and hist["diff"]["removed"] == 1

    # a new file (moved away since), then the move of it
    c = changes("Edit memory new-note.md")
    assert [(s["op"], s["text"], s["now"]) for s in c["steps"]] == [
        ("absent", "Did not exist before: the operation created it", None)]
    c = changes("Move memory new-note.md")
    assert any(s["op"] == "move" and s["to"].endswith("/memory/new-note.md") for s in c["steps"])
    assert ("mkdir", "Folder created") in [(s["op"], s["text"]) for s in c["steps"]]

    # a delete is a stash
    c = changes("Delete")
    stash = [s for s in c["steps"] if s["op"] == "stash"]
    assert {"op": "stash", "path": f"~/.claude/projects/{blog}", "now": None,
            "text": "Folder moved to the backup instead of being deleted"} in stash
    assert any(s["path"] == "~/.claude/file-history/s-blog" for s in stash)

    # secrets: env and header values and token-like strings are masked on both sides
    c = changes("Edit MCP server files")
    d = next(s for s in c["steps"] if s["op"] == "copy")["diff"]
    text = "\n".join(d["lines"])
    assert "secret-123" not in text and "secret-456" not in text and "sk-ant-abc123" not in text
    assert '"API_KEY": "•••• hidden"' in text and "X-Custom" in text and "plain-value" not in text
    assert d["status"] == "changed" and '-      "args": [' in d["lines"]
    assert "me@example.com" in json.dumps(changes("Add MCP server files"))  # not a secret: the rest stays readable

    # read-only: nothing on disk changed, not even the backups
    assert home.snapshot() == snap
    assert sorted((str(p), p.stat().st_mtime_ns) for p in home.path(".cc-profiles/backups").rglob("*")) == backups_before


def test_backup_changes_notes_and_guards(home, app_factory):
    basic_home(home)
    home.json(".claude/.credentials.json", {"claudeAiOauth": {"accessToken": "tok-1"}})
    home.write(".claude/big.txt", "x\n" * 300_000)
    home.write(".claude/data.bin", "a\0b")
    home.write(".claude/notes.txt", "\n".join(f"line {i}" for i in range(3000)) + "\n")
    bk = home.path(".cc-profiles/backups/2026-01-01_00-00-00_manual")
    (bk / "file").mkdir(parents=True)
    (bk / "file/001-cred").write_text(json.dumps({"claudeAiOauth": {"accessToken": "tok-0"}}))
    (bk / "file/002-big").write_text("y\n")
    (bk / "file/003-bin").write_text("a\0c")
    (bk / "file/004-notes").write_text("\n".join(f"old {i}" for i in range(3000)) + "\n")
    (bk / "file/005-gone").write_text("was here\n")
    journal = [{"op": "copy", "path": str(home.path(".claude/.credentials.json")), "file": "file/001-cred"},
               {"op": "copy", "path": str(home.path(".claude/big.txt")), "file": "file/002-big"},
               {"op": "copy", "path": str(home.path(".claude/data.bin")), "file": "file/003-bin"},
               {"op": "copy", "path": str(home.path(".claude/notes.txt")), "file": "file/004-notes"},
               {"op": "copy", "path": str(home.path(".claude/gone.txt")), "file": "file/005-gone"},
               {"op": "copy", "path": str(home.path(".claude/settings.json")), "file": "../../../.claude/settings.json"},
               {"op": "mkdir", "path": str(home.path(".claude/new-folder"))},
               {"op": "created", "path": str(home.path(".claude/projects"))}]
    (bk / "manifest.json").write_text(json.dumps({"title": "Manual", "created": time.time() - 3600, "journal": journal}))
    app = app_factory()
    st = {s["path"].split("/")[-1]: s for s in app.get("/api/backups/changes?name=2026-01-01_00-00-00_manual")["steps"]}
    assert st[".credentials.json"]["diff"]["status"] == "secret" and st[".credentials.json"]["diff"]["lines"] == []
    assert st["big.txt"]["diff"]["status"] == "too-big" and "512 KB" in st["big.txt"]["diff"]["notes"][0]
    assert st["data.bin"]["diff"]["status"] == "binary"
    notes = st["notes.txt"]["diff"]
    assert notes["truncated"] and len(notes["lines"]) == 2000 and any("first 2,000 lines" in n for n in notes["notes"])
    assert any("Changed again after this operation" in n for n in notes["notes"])
    gone = st["gone.txt"]["diff"]
    assert gone["status"] == "changed" and gone["lines"][-1] == "-was here" and "no longer exists" in gone["notes"][0]
    assert st["settings.json"]["diff"]["status"] == "unavailable"  # a manifest cannot point outside the backup
    assert st["new-folder"]["text"] == "Folder created" and st["projects"]["text"] == "Folder created"
    assert "tok-0" not in json.dumps(st) and "tok-1" not in json.dumps(st)
    for bad in ("..", "../x", ".hidden", "", "a/b"):
        status, data = app.request("/api/backups/changes?name=" + urllib.parse.quote(bad))
        assert status in (400, 404) and "error" in data, bad
    assert app.request("/api/backups/changes?name=nope")[0] == 404
    assert app.request("/api/backups/changes?name=2026-01-01_00-00-00_manual", token=False)[0] == 403


# --- profile by folder (cc-profiles which, shell-init, the rc line) ------------
SHELL_LINE = 'command -v cc-profiles >/dev/null 2>&1 && eval "$(cc-profiles shell-init {})"  # cc-profiles: profile by folder'


def folder_home(home, app_factory, **env):
    """basic_home plus a 'client' profile and rules: nested, shared, a deleted profile."""
    basic_home(home)
    home.profile("client")
    home.path("code/work/client/app").mkdir(parents=True)
    app = app_factory(**env)  # first run writes the config
    cfg = json.loads(home.path(".cc-profiles/config.json").read_text())
    cfg["rules"] = [{"exact": "~", "profile": "shared"},
                    {"match": "code/work/client", "profile": "client"},
                    {"match": "code/work", "profile": "work"},
                    {"match": "code/personal", "profile": "default"},
                    {"match": "scratch", "profile": "shared"},
                    {"match": "gone", "profile": "deleted"}]
    home.json(".cc-profiles/config.json", cfg)
    return app


def run_which(home, *args, cwd=None):
    e = child_env({"HOME": str(home.root), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC)})
    return subprocess.run([sys.executable, "-m", "cc_profiles", "which", *args], env=e, cwd=cwd,
                          capture_output=True, text=True, timeout=20)


def test_which_follows_the_rules(home, app_factory):
    app = folder_home(home, app_factory)
    before = home.snapshot()

    r = run_which(home, "~/code/work/api")
    assert (r.returncode, r.stdout) == (0, "Work\n")
    assert run_which(home, "--dir", "~/code/work/api").stdout == str(home.path(".claude-work")) + "\n"
    assert run_which(home, "--dir", str(home.path("code/work/client/app"))).stdout == str(home.path(".claude-client")) + "\n"
    assert run_which(home, cwd=home.path("code/work/client/app")).stdout == "Client\n"  # default: the current folder
    assert run_which(home, "~/code/personal/blog").stdout == "Default\n"
    assert run_which(home, "--dir", "~/code/personal/blog").stdout == str(home.path(".claude")) + "\n"
    for path, why in (("~", "every profile"), ("~/scratch/x", "every profile"),
                      ("~/elsewhere", "no rule matches"), ("~/gone/x", "no rule matches")):
        r = run_which(home, path)
        assert (r.returncode, r.stdout) == (1, "") and why in r.stderr, path
        r = run_which(home, "--dir", path)
        assert (r.returncode, r.stdout, r.stderr) == (1, "", ""), path

    # the same answers through the API, which only reads
    w = app.get("/api/shell/which?path=" + urllib.parse.quote("~/code/work/client/app"))
    assert (w["profile"], w["label"], w["dir"], w["default"]) == ("client", "Client", "~/.claude-client", False)
    w = app.get("/api/shell/which?path=" + urllib.parse.quote("~/code/personal/x"))
    assert (w["profile"], w["default"], w["exists"]) == ("default", True, False)
    w = app.get("/api/shell/which?path=" + urllib.parse.quote("~"))
    assert (w["rule"], w["profile"]) == ("shared", None)
    assert "absolute" in app.request("/api/shell/which?path=code/work")[1]["error"]
    state = app.get("/api/shell")
    expected = {r["pretty"]: r["expected"] for r in app.get("/api/projects")}
    assert state["projects"] and all(expected[p["path"]] == p["rule"] for p in state["projects"])  # as the Projects tab
    assert {p["path"]: p["label"] for p in state["projects"]}["~/code/work/api"] == "Work"
    assert {"text": "code/work", "exact": False, "profile": "work", "label": "Work"} in state["rules"]
    assert state["installed"] == []
    assert home.snapshot() == before


def test_which_never_writes_and_skips_the_server(home):
    r = run_which(home, "--dir")
    assert (r.returncode, r.stdout) == (1, "")
    assert not home.path(".cc-profiles").exists()  # no config yet: none is created
    code = ("import sys; sys.argv = ['cc-profiles', 'which', '/']\nfrom cc_profiles import entry\n"
            "try:\n    entry.main()\nexcept SystemExit:\n    pass\n"
            "print(sorted(m for m in sys.modules if m.startswith('cc_profiles')))")
    e = child_env({"HOME": str(home.root), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC)})
    r = subprocess.run([sys.executable, "-c", code], env=e, capture_output=True, text=True)
    assert r.stdout.strip() == "['cc_profiles', 'cc_profiles.byfolder', 'cc_profiles.entry']", r.stderr


def fake_tools(folder, with_cc_profiles=True):
    """A bin folder with a fake claude that prints its CLAUDE_CONFIG_DIR, and cc-profiles."""
    folder.mkdir(parents=True)
    (folder / "claude").write_text('#!/bin/sh\necho "dir=${CLAUDE_CONFIG_DIR-unset} args=$*"\n')
    (folder / "claude").chmod(0o755)
    if with_cc_profiles:
        (folder / "cc-profiles").write_text(f'#!/bin/sh\nexec "{sys.executable}" -m cc_profiles "$@"\n')
        (folder / "cc-profiles").chmod(0o755)
    return folder


@pytest.mark.parametrize("shell", ["bash", "zsh"])
def test_shell_function_picks_the_profile(home, app_factory, tmp_path, shell):
    exe = shutil.which(shell)
    if not exe:
        pytest.skip(f"{shell} is not installed")
    folder_home(home, app_factory)
    init = run_cli(home, "shell-init", shell).stdout
    assert init.startswith("# cc-profiles: profile by folder") and "function claude {" in init
    (tmp_path / "init.sh").write_text(init)
    tools, no_cc = fake_tools(tmp_path / "bin"), fake_tools(tmp_path / "bin-no-cc", with_cc_profiles=False)

    def claude(folder, path=tools, **env):
        e = child_env({"HOME": str(home.root), "PATH": f"{path}:/usr/bin:/bin", "PYTHONPATH": str(SRC), **env})
        flags = ["-f"] if shell == "zsh" else ["--norc", "--noprofile"]
        script = f'. "{tmp_path / "init.sh"}"; cd "{home.path(folder)}" && claude --resume "a b"'
        r = subprocess.run([exe, *flags, "-c", script], env=e, capture_output=True, text=True, timeout=30)
        assert r.returncode == 0 and r.stderr == "", r.stderr
        return r.stdout.strip()

    assert claude("code/work/api") == f"dir={home.path('.claude-work')} args=--resume a b"
    assert claude("code/work/client/app") == f"dir={home.path('.claude-client')} args=--resume a b"
    assert claude("code/personal/blog") == "dir=unset args=--resume a b"  # default profile: left unset
    assert claude("") == "dir=unset args=--resume a b"  # ~ is shared
    assert claude("code/work/api", CLAUDE_CONFIG_DIR="/mine") == "dir=/mine args=--resume a b"  # yours wins
    assert claude("code/work/api", path=no_cc) == "dir=unset args=--resume a b"  # without cc-profiles


def test_shell_line_on_off_is_idempotent_and_undoable(home, app_factory):
    app = folder_home(home, app_factory, SHELL="/bin/zsh")
    home.write(".zshrc", "export A=1\nalias claude-old='claude'\n")
    home.write(".bashrc", "export B=2\n")  # the shell is zsh: bash files are left alone
    before = home.snapshot()

    st = app.get("/api/shell")
    assert st["shell"] == "zsh" and st["installed"] == []
    line = SHELL_LINE.format("zsh")
    assert st["targets"] == [{"file": "~/.zshrc", "shell": "zsh", "line": line}]

    r = app.post("/api/shell", {"install": True})
    assert "~/.zshrc" in r["message"] and r["backup"]
    assert home.path(".zshrc").read_text() == "export A=1\nalias claude-old='claude'\n" + line + "\n"
    assert home.path(".bashrc").read_text() == "export B=2\n"
    assert app.get("/api/shell")["installed"] == ["~/.zshrc"]
    n = len(app.get("/api/backups"))
    assert "Already on" in app.post("/api/shell", {"install": True})["message"]
    assert len(app.get("/api/backups")) == n and home.path(".zshrc").read_text().count(line) == 1

    r = app.post("/api/shell", {"install": False})
    assert "~/.zshrc" in r["message"]
    assert home.snapshot() == before  # only its line was touched
    assert "Already off" in app.post("/api/shell", {"install": False})["message"]
    app.post("/api/shell", {"install": True})
    app.restore_all()
    assert home.snapshot() == before


def test_shell_line_for_bash_goes_to_the_files_bash_reads(home, app_factory):
    app = folder_home(home, app_factory, SHELL="/bin/bash")
    home.write(".bashrc", "export B=2")  # no final newline
    home.write(".bash_profile", "source ~/.bashrc\n")
    before = home.snapshot()
    line = SHELL_LINE.format("bash")
    assert [t["file"] for t in app.get("/api/shell")["targets"]] == ["~/.bashrc", "~/.bash_profile"]
    app.post("/api/shell", {"install": True})
    assert home.path(".bashrc").read_text() == "export B=2\n" + line + "\n"
    assert home.path(".bash_profile").read_text() == "source ~/.bashrc\n" + line + "\n"
    assert not home.path(".zshrc").exists()
    app.post("/api/shell", {"install": False})
    assert home.path(".bash_profile").read_text() == "source ~/.bashrc\n"
    app.restore_all()
    assert home.snapshot() == before


def test_shell_line_creates_a_missing_zshrc_and_refuses_other_shells(home, app_factory):
    app = folder_home(home, app_factory, SHELL="/bin/zsh")
    before = home.snapshot()
    app.post("/api/shell", {"install": True})
    assert home.path(".zshrc").read_text() == SHELL_LINE.format("zsh") + "\n"
    app.restore_all()
    assert home.snapshot() == before  # Restore removes the file it created
    assert "not zsh or bash" in app_factory(SHELL="/usr/bin/fish").post_error("/api/shell", {"install": True})
