"""Profiles: create, edit, delete, templates; export, import and plugins.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import io
import json
import os
import time
import urllib.error
import urllib.request
import zipfile

import pytest

from conftest import san
from helpers import basic_home, is_current_command


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


MOD_SOURCE = """import type { Register } from 'claude-code'
import { pretty } from './format'

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    await $.command.register({ name: 'glance', description: 'Open the glance pane' })
    return next(e)
  })
  on('tool.call', { tool: 'Bash' }, async ($, e, next) => {
    $.ui.status(pretty(e.command))
    return next(e)
  })
}
"""


def mod_home(home):
    """basic_home, with a mod (glance) and a plugin of command hooks (fmt) installed in Default."""
    basic_home(home)
    d = home.path(".claude/plugins")
    glance = "cache/team/glance/0.1.0"
    home.json(f".claude/plugins/{glance}/.claude-plugin/plugin.json", {"name": "glance", "version": "0.1.0"})
    home.json(f".claude/plugins/{glance}/hooks/hooks.json", {"modules": ["./register.tsx"]})
    home.write(f".claude/plugins/{glance}/hooks/register.tsx", MOD_SOURCE)
    home.write(f".claude/plugins/{glance}/hooks/format.ts",
               "export const pretty = (s: string) => s.slice(0, 40)\n"
               "export const send = ($: any, s: string) => $.http.fetch({ url: 'https://example.com', body: s })\n")
    home.json(".claude/plugins/cache/team/fmt/1.0.0/hooks/hooks.json", {"hooks": {"PostToolUse": []}})
    home.json(".claude/plugins/marketplaces/team/.claude-plugin/marketplace.json", {"name": "team", "plugins": []})
    home.json(".claude/plugins/installed_plugins.json", {"version": 2, "plugins": {
        "glance@team": [{"scope": "user", "installPath": f"{d}/{glance}", "version": "0.1.0",
                         "installedAt": "2026-10-20T10:00:00.000Z"}],
        "fmt@team": [{"scope": "user", "installPath": f"{d}/cache/team/fmt/1.0.0", "version": "1.0.0"}]}})
    home.json(".claude/plugins/known_marketplaces.json", {"team": {
        "source": {"source": "github", "repo": "me/team"}, "installLocation": f"{d}/marketplaces/team"}})
    home.json(".claude/settings.json", {"enabledPlugins": {"glance@team": True, "fmt@team": True}})


def test_mods_are_recognised_copied_and_compared(home, app_factory):
    mod_home(home)
    home.json(".claude-work/settings.json", {"model": "opus"})
    before = home.snapshot()
    app = app_factory()

    by = {p["name"]: p for p in app.get("/api/plugins?profile=default")["plugins"]}
    assert by["fmt@team"]["mod"] is None  # hooks.json without modules: a plugin of command hooks
    assert by["glance@team"]["mod"] == {  # read from the source, imported files included
        "features": ["Status line"], "commands": ["glance"], "reach": ["Network"],
        "events": [{"name": "session.start", "label": "Session start"},
                   {"name": "tool.call", "label": "Tool calls (can block or change them)"}]}
    mods = app.get("/api/compare?a=default&b=work")["mods"]
    assert (mods["only_a"], mods["only_b"], mods["both"], mods["shared"]) == (["glance@team"], [], [], False)

    r = app.post("/api/plugins/copy", {"profile": "default", "plugin": "glance@team", "to": "work"})
    assert r["message"].startswith("glance@team copied to Work and enabled in settings.json")
    w = home.path(".claude-work/plugins")
    assert (w / "cache/team/glance/0.1.0/hooks/register.tsx").read_text() == MOD_SOURCE
    entry = json.loads((w / "installed_plugins.json").read_text())["plugins"]["glance@team"][0]
    assert entry["installPath"] == str(w / "cache/team/glance/0.1.0") and entry["version"] == "0.1.0"
    market = json.loads((w / "known_marketplaces.json").read_text())["team"]
    assert market["installLocation"] == str(w / "marketplaces/team") and (w / "marketplaces/team/.claude-plugin").is_dir()
    assert json.loads(home.path(".claude-work/settings.json").read_text()) == {
        "model": "opus", "enabledPlugins": {"glance@team": True}}
    assert app.get("/api/plugins?profile=work")["plugins"][0]["mod"]["commands"] == ["glance"]
    assert any("marketplace team added to Work" in l for l in app.get("/api/backups")[0]["log"])
    both = app.get("/api/compare?a=default&b=work")["mods"]
    assert both["only_a"] == [] and both["both"] == [{"name": "glance@team", "a": True, "b": True}]

    # the second time the target has it; the marketplace is not added twice
    assert "Work already has glance@team" in app.post_error(
        "/api/plugins/copy", {"profile": "default", "plugin": "glance@team", "to": "work"})
    app.post("/api/plugins/copy", {"profile": "default", "plugin": "fmt@team", "to": "work"})
    last = max(app.get("/api/backups"), key=lambda b: b["created"])
    assert last["title"] == "Copy plugin fmt@team: Default → Work" and not any("marketplace" in l for l in last["log"])
    assert app.request("/api/plugins/copy", {"profile": "default", "plugin": "nope@x", "to": "work"})[0] == 404
    assert "Pick another profile" in app.post_error(
        "/api/plugins/copy", {"profile": "default", "plugin": "fmt@team", "to": "default"})

    app.restore_all()
    assert home.snapshot() == before


def test_a_plugin_is_not_copied_where_plugins_are_shared(home, app_factory):
    mod_home(home)
    os.symlink("../.claude/plugins", home.path(".claude-work/plugins"))
    app = app_factory()
    assert "share their plugins" in app.post_error(
        "/api/plugins/copy", {"profile": "default", "plugin": "glance@team", "to": "work"})
    assert app.get("/api/compare?a=default&b=work")["mods"]["shared"] is True


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


# --- about ------------------------------------------------------------------------
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
