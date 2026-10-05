"""End-to-end tests: every operation runs against a real server on a fake home.

The key property of cc-profiles is that everything can be undone, so most tests
end the same way: restore every backup, newest first, and check the fake home is
byte-for-byte identical to how it started.
"""
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.request

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
