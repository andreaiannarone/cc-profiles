"""End-to-end tests: every operation runs against a real server on a fake home.

The key property of cc-profiles is that everything can be undone, so most tests
end the same way: restore every backup, newest first, and check the fake home is
byte-for-byte identical to how it started.
"""
import io
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

import pytest

from conftest import SRC, free_port, san


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
    home.write(".claude/output-styles/terse.md", "---\nname: Terse\n---\nBe brief.\n")
    before = home.snapshot()
    app = app_factory()
    P = "/api/settings/field"

    app.post(P, {"profile": "default", "key": "outputStyle", "value": "Terse"})
    assert json.loads(home.path(".claude/settings.local.json").read_text()) == {"outputStyle": "Terse"}
    assert "pick one of the options" in app.post_error(P, {"profile": "work", "key": "outputStyle", "value": "Terse"})
    assert "pick one of the options" in app.post_error(P, {"profile": "default", "key": "effortLevel", "value": "max"})
    assert "greater than zero" in app.post_error(P, {"profile": "default", "key": "cleanupPeriodDays", "value": 0})
    assert "advanced editor" in app.post_error(P, {"profile": "default", "key": "hooks", "value": {}})
    app.post(P, {"profile": "default", "key": "effortLevel", "value": "xhigh"})

    app.post("/api/settings/permissions", {"profile": "default", "rules": {"deny": ["mcp__gmail", "  "]}})
    perms = json.loads(home.path(".claude/settings.json").read_text())["permissions"]
    assert perms == {"defaultMode": "default", "deny": ["mcp__gmail"]}

    assert "Invalid JSON" in app.post_error("/api/settings/raw", {"profile": "work", "file": "settings", "content": "{ x"})
    assert "JSON object" in app.post_error("/api/settings/raw", {"profile": "work", "file": "settings", "content": "[]"})
    assert "cannot be changed" in app.post_error("/api/settings/global", {"profile": "default", "key": "userID", "value": True})

    app.restore_all()
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
    home.json(".claude/settings.json", {"model": "opus", "permissions": {"allow": ["Bash(ls)", "Read"]}})
    home.json(".claude-work/settings.local.json", {"model": "sonnet"})
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
    model = next(s for s in c["settings"] if s["key"] == "model")
    assert (model["a"], model["a_source"], model["b"], model["b_source"], model["same"]) == \
        ("opus", "settings", "sonnet", "local", False)
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


# --- profiles -----------------------------------------------------------------
def test_new_profiles_get_the_cc_profiles_command(home, app_factory):
    basic_home(home)
    home.write(".claude-work/commands/cc-profiles.md", "my own command\n")
    before = home.snapshot()
    app = app_factory()

    app.post("/api/profiles/create", {"label": "Empty", "id": "empty", "base": "", "share": []})
    text = home.path(".claude-empty/commands/cc-profiles.md").read_text()
    assert "# managed by cc-profiles" in text and "!`cc-profiles open`" in text

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
    e = {"HOME": str(home.root), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC), **env}
    return subprocess.run([sys.executable, "-m", "cc_profiles", *args], env=e,
                          capture_output=True, text=True, timeout=20)


def test_label_command(home, app_factory):
    basic_home(home)
    app_factory()  # first run writes the config
    assert run_cli(home, "label").stdout.strip() == "Default"
    assert run_cli(home, "label", CLAUDE_CONFIG_DIR=str(home.path(".claude-work"))).stdout.strip() == "Work"


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
    assert "# managed by cc-profiles" in text and "!`cc-profiles open`" in text
    assert home.path(".claude-client/commands/cc-profiles.md").read_text() == "my own command\n"
    assert home.path(".claude-shared/commands/cc-profiles.md").read_text() == text  # through the link

    again = run_cli(home, "install-command").stdout
    assert "Backup:" not in again and again.count("already up to date") == 2

    newest = app.get("/api/backups")[0]
    assert newest["title"] == "Add the /cc-profiles command"
    app.post("/api/backups/restore", {"name": newest["name"]})
    assert home.snapshot() == before


def test_plugin_command_matches_installed_command():
    sys.path.insert(0, str(SRC))
    from cc_profiles import server
    plugin = (SRC.parent / "plugin" / "commands" / "open.md").read_text()
    assert plugin == server.COMMAND_TEXT.replace(server.COMMAND_MARK + "\n", "", 1)


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
