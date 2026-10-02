"""End-to-end tests: every operation runs against a real server on a fake home.

The key property of cc-profiles is that everything can be undone, so most tests
end the same way: restore every backup, newest first, and check the fake home is
byte-for-byte identical to how it started.
"""
import json
import os
import subprocess
import sys
import time

from conftest import SRC, san


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


# --- profiles -----------------------------------------------------------------
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


def test_version_command(home):
    out = run_cli(home, "--version").stdout
    assert out.startswith("cc-profiles ")
