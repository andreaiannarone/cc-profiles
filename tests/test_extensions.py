"""Skills, MCP servers, claude.ai connectors, agents, the GitHub account per profile.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json
import shutil

from conftest import san
from helpers import basic_home


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


def test_every_profile_has_its_own_github_folder(home, app_factory):
    basic_home(home)
    home.write(".config/gh/hosts.yml", "github.com:\n    git_protocol: https\n    users:\n        me:\n"
                                       "        me-at-work:\n    user: me\n")
    home.write(".config/gh/config.yml", "editor: vim\n")
    home.write(".config/gh-old/hosts.yml", "github.com:\n    users:\n        stray:\n            oauth_token: gho_x\n"
                                           "    user: stray\n")
    home.json(".claude-work/settings.local.json", {"env": {"GIT_AUTHOR_EMAIL": "old@example.com", "FOO": "1"}})
    before = home.snapshot()
    app = app_factory(CC_PROFILES_AUTO_GITHUB="1")  # at start, Work gets ~/.config/gh-work

    # with the account it used alone: a session of Work sees no other account to switch to
    assert home.path(".config/gh-work/hosts.yml").read_text() == \
        "github.com:\n    git_protocol: https\n    users:\n        me:\n    user: me\n"
    assert home.path(".config/gh-work/config.yml").read_text() == "editor: vim\n"
    assert json.loads(home.path(".claude-work/settings.json").read_text())["env"] == {
        "GH_CONFIG_DIR": str(home.path(".config/gh-work"))}
    g = app.get("/api/github")
    assert "gho_" not in json.dumps(g)
    assert g["accounts"] == ["me", "me-at-work"]  # a user with its token in hosts.yml is not offered
    assert [(p["id"], p["dir"], p["user"], p["set_up"]) for p in g["profiles"]] == [
        ("default", "~/.config/gh", "me", True), ("work", "~/.config/gh-work", "me", True)]
    assert "already has" in app.post("/api/github/setup", {"profile": "work"})["message"]

    # picking an account makes it the active user of the profile's own folder only
    app.post("/api/github/account", {"profile": "work", "user": "me-at-work"})
    assert home.path(".config/gh-work/hosts.yml").read_text() == \
        "github.com:\n    git_protocol: https\n    users:\n        me-at-work:\n    user: me-at-work\n"  # me left it
    assert "user: me\n" in home.path(".config/gh/hosts.yml").read_text()
    assert {p["id"]: p["github"] for p in app.get("/api/profiles")} == {"default": "me", "work": "me-at-work"}
    assert "already uses" in app.post("/api/github/account", {"profile": "work", "user": "me-at-work"})["message"]
    assert "terminal" in app.post("/api/github/account", {"profile": "default", "user": "me-at-work"})["message"]
    assert "not signed in" in app.post_error("/api/github/account", {"profile": "work", "user": "stray"})

    # commit identity: a key already in settings.local.json is changed there
    app.post("/api/github/identity", {"profile": "work", "name": "Me At Work", "email": "me@work.example"})
    assert json.loads(home.path(".claude-work/settings.local.json").read_text())["env"] == {
        "GIT_AUTHOR_EMAIL": "me@work.example", "FOO": "1"}
    assert json.loads(home.path(".claude-work/settings.json").read_text())["env"] == {
        "GH_CONFIG_DIR": str(home.path(".config/gh-work")), "GIT_AUTHOR_NAME": "Me At Work",
        "GIT_COMMITTER_NAME": "Me At Work", "GIT_COMMITTER_EMAIL": "me@work.example"}
    app.post("/api/github/identity", {"profile": "work", "name": "", "email": ""})
    assert json.loads(home.path(".claude-work/settings.local.json").read_text())["env"] == {"FOO": "1"}
    assert "both the name and the email" in app.post_error("/api/github/identity", {"profile": "work", "name": "Me"})
    assert "not an email" in app.post_error("/api/github/identity", {"profile": "work", "name": "Me", "email": "me"})

    app.restore_all()
    assert home.snapshot() == before


def test_a_profile_folder_lists_only_its_account(home, app_factory):
    basic_home(home)
    home.profile("lab")
    default = "github.com:\n    users:\n        me:\n        other:\n    user: me\n"
    written = "github.com:\n    users:\n        a:\n            oauth_token: gho_x\n        b:\n    user: a\n"
    home.write(".config/gh/hosts.yml", default)
    home.write(".config/gh-work/hosts.yml", "github.com:\n    git_protocol: ssh\n    users:\n        me:\n"
                                            "        me-at-work:\n        side:\n    user: me-at-work\n")
    home.write(".config/gh-lab/hosts.yml", written)
    for pid in ("work", "lab"):
        home.json(f".claude-{pid}/settings.json", {"env": {"GH_CONFIG_DIR": str(home.path(f".config/gh-{pid}"))}})
    before = home.snapshot()
    app = app_factory(CC_PROFILES_AUTO_GITHUB="1")  # at start, the folders that list more are put right

    work = home.path(".config/gh-work/hosts.yml")
    assert work.read_text() == "github.com:\n    git_protocol: ssh\n    users:\n        me-at-work:\n    user: me-at-work\n"
    assert home.path(".config/gh/hosts.yml").read_text() == default  # Default is the terminal's: as it was
    assert home.path(".config/gh-lab/hosts.yml").read_text() == written  # a token is written there: never touched
    # side was listed nowhere else: it stays one you can pick, from the accounts folder
    accounts = home.path(".config/gh-accounts/hosts.yml")
    assert accounts.read_text() == "github.com:\n    git_protocol: https\n    users:\n        side:\n    user: side\n"
    assert oct(accounts.stat().st_mode & 0o777) == "0o600"
    assert sorted(app.get("/api/github")["accounts"]) == ["me", "me-at-work", "other", "side"]

    # picking another account: the one it used leaves the folder, and is still on the list
    app.post("/api/github/account", {"profile": "work", "user": "side"})
    assert work.read_text() == "github.com:\n    git_protocol: ssh\n    users:\n        side:\n    user: side\n"
    assert "        me-at-work:\n" in accounts.read_text() and "    user: side\n" in accounts.read_text()
    assert "me-at-work" in app.get("/api/github")["accounts"]
    app.post("/api/github/account", {"profile": "default", "user": "other"})  # Default keeps them all
    assert home.path(".config/gh/hosts.yml").read_text() == default.replace("user: me", "user: other")

    app.restore_all()
    assert home.snapshot() == before


def test_github_accounts_are_listed_and_removed(home, app_factory):
    basic_home(home)
    home.write(".config/gh/hosts.yml", "github.com:\n    users:\n        me:\n        old:\n    user: me\n")
    home.write(".config/gh-work/hosts.yml", "github.com:\n    users:\n        old:\n        me:\n    user: me\n")
    home.write(".config/gh-accounts/hosts.yml", "github.com:\n    users:\n        side:\n            oauth_token: gho_x\n"
                                                "    user: side\n")
    home.json(".claude-work/settings.json", {"env": {"GH_CONFIG_DIR": str(home.path(".config/gh-work"))}})
    before = home.snapshot()
    app = app_factory()

    g = app.get("/api/github")
    assert g["accounts_dir"] == "~/.config/gh-accounts" and "gho_" not in json.dumps(g)
    assert g["account_list"] == [
        {"user": "me", "folders": ["~/.config/gh", "~/.config/gh-work"], "used_by": ["Default", "Work"], "insecure": False},
        {"user": "old", "folders": ["~/.config/gh", "~/.config/gh-work"], "used_by": [], "insecure": False},
        {"user": "side", "folders": ["~/.config/gh-accounts"], "used_by": [], "insecure": True}]
    assert g["accounts"] == ["me", "old"]  # side's token is not in the keychain

    assert "connect another account there first" in app.post_error("/api/github/remove", {"user": "me"})
    assert "gh auth logout" in app.post_error("/api/github/remove", {"user": "side"})
    r = app.post("/api/github/remove", {"user": "old"})
    assert "2 GitHub CLI folders" in r["message"] and "gh auth logout --hostname github.com --user old" in r["message"]
    assert home.path(".config/gh-work/hosts.yml").read_text() == "github.com:\n    users:\n        me:\n    user: me\n"
    assert [a["user"] for a in app.get("/api/github")["account_list"]] == ["me", "side"]
    assert "Unknown GitHub account" in app.post_error("/api/github/remove", {"user": "old"})

    app.restore_all()
    assert home.snapshot() == before


def test_github_table_is_saved_in_one_backup(home, app_factory):
    basic_home(home)
    home.write(".config/gh/hosts.yml", "github.com:\n    users:\n        me:\n        me-at-work:\n    user: me\n")
    home.write(".config/gh-work/hosts.yml", "github.com:\n    users:\n        me:\n    user: me\n")
    home.json(".claude-work/settings.json", {"env": {"GH_CONFIG_DIR": str(home.path(".config/gh-work"))}})
    before = home.snapshot()
    app = app_factory()

    # every change is checked before anything is written
    assert "both the name and the email" in app.post_error("/api/github/save", {"changes": [
        {"profile": "work", "user": "me-at-work"}, {"profile": "default", "name": "Me", "email": ""}]})
    assert "user: me\n" in home.path(".config/gh-work/hosts.yml").read_text()
    r = app.post("/api/github/save", {"changes": [
        {"profile": "work", "user": "me-at-work", "name": "Me At Work", "email": "me@work.example"},
        {"profile": "default", "name": "Me", "email": "me@example.com"}]})
    assert r["message"].startswith("Work uses GitHub as me-at-work; commits in Work are by Me At Work")
    assert "user: me-at-work" in home.path(".config/gh-work/hosts.yml").read_text()
    assert json.loads(home.path(".claude/settings.json").read_text())["env"]["GIT_AUTHOR_NAME"] == "Me"
    assert len(app.get("/api/backups")) == 1
    assert app.post("/api/github/save", {"changes": [{"profile": "work", "user": "me-at-work"}]})["message"] == "Nothing changed."

    app.restore_all()
    assert home.snapshot() == before


def test_with_active_user_keeps_the_rest_of_hosts_yml():
    from cc_profiles.github import parse_users, with_active_user
    lines = ["github.example.com:", "    user: corp", "github.com:", "    git_protocol: ssh", "    users:",
             "        me:", "    user: me"]
    out = with_active_user(lines, "other")
    assert out == ["github.example.com:", "    user: corp", "github.com:", "    git_protocol: ssh", "    users:",
                   "        other:", "        me:", "    user: other"]
    assert parse_users(out)[:2] == ("other", ["other", "me"])
    assert parse_users(with_active_user([], "me"))[:2] == ("me", ["me"])
    from cc_profiles.github import without_user
    assert without_user(out, "other") == ["github.example.com:", "    user: corp", "github.com:", "    git_protocol: ssh",
                                          "    users:", "        me:", "    user: me"]
    assert without_user(["github.com:", "    users:", "        me:", "    user: me"], "me") == ["github.com:", "    users:"]
    from cc_profiles.github import only_user, with_user
    assert with_user(out, "third")[-4:] == ["        third:", "        other:", "        me:", "    user: other"]
    assert only_user(out, "me") == without_user(out, "other") and parse_users(only_user([], "me"))[:2] == ("me", ["me"])


def test_new_profiles_get_their_own_github_folder(home, app_factory):
    basic_home(home)
    home.write(".config/gh/hosts.yml", "github.com:\n    users:\n        me:\n    git_protocol: https\n    user: me\n")
    home.write(".config/gh/config.yml", "editor: vim\n")
    before = home.snapshot()
    app = app_factory()

    r = app.post("/api/profiles/create", {"label": "Noa", "id": "noa", "share": []})
    assert "GitHub as me, from ~/.config/gh-noa" in r["message"]
    assert home.path(".config/gh-noa/hosts.yml").read_text() == home.path(".config/gh/hosts.yml").read_text()
    assert home.path(".config/gh-noa/config.yml").read_text() == "editor: vim\n"
    assert oct(home.path(".config/gh-noa/hosts.yml").stat().st_mode & 0o777) == "0o600"
    assert json.loads(home.path(".claude-noa/settings.json").read_text())["env"] == {
        "GH_CONFIG_DIR": str(home.path(".config/gh-noa"))}

    # a token written in hosts.yml (gh's insecure storage) is never copied: that folder needs a sign-in
    home.write(".config/gh/hosts.yml", "github.com:\n    users:\n        me:\n            oauth_token: gho_secret\n"
                                       "    oauth_token: gho_secret\n    user: me\n")
    r = app.post("/api/profiles/create", {"label": "Lab", "id": "lab", "share": []})
    assert "GH_CONFIG_DIR=~/.config/gh-lab gh auth login" in r["message"]
    assert "gho_" not in home.path(".config/gh-lab/hosts.yml").read_text()
    # a shared settings.json shares the account too
    r = app.post("/api/profiles/create", {"label": "Same", "id": "same", "share": ["settings.json"]})
    assert "Its settings.json is shared" in r["message"] and not home.path(".config/gh-same").exists()

    app.restore_all()
    home.write(".config/gh/hosts.yml", "github.com:\n    users:\n        me:\n    git_protocol: https\n    user: me\n")
    assert home.snapshot() == before


def test_agents_are_managed_and_undoable(home, app_factory):
    basic_home(home)
    home.write(".claude/agents/reviewer.md", "---\nname: reviewer\ndescription: Reviews diffs. Use after coding.\n"
                                             "tools:\n  - Read\n  - Grep\nmodel: sonnet\nhooks:\n  Stop:\n    - command: echo done\n"
                                             "memory: project\n---\nYou review code.\n")
    home.write(".claude/agents/broken.md", "no frontmatter here\n")
    home.write(".claude/plugins/installed_plugins.json", json.dumps({"plugins": {"kit@market": [
        {"installPath": str(home.path("plugin-kit")), "version": "1.0"}]}}))
    home.write("plugin-kit/agents/helper.md", "---\nname: helper\ndescription: From a plugin\n---\nHelp.\n")
    before = home.snapshot()
    app = app_factory()

    listed = app.get("/api/agents?profile=default")
    assert [(a["name"], a["model"], a["tools"], a["valid"]) for a in listed["agents"]] == [
        ("broken", "", [], False), ("reviewer", "sonnet", ["Read", "Grep"], True)]
    assert [(a["name"], a["plugin"]) for a in listed["plugins"]] == [("helper", "kit@market")]
    assert ("inherit", "Same as the conversation") in [tuple(o) for o in listed["options"]["model"]]
    r = app.get("/api/agents/file?profile=default&name=reviewer")
    assert r["fields"]["tools"] == ["Read", "Grep"] and r["prompt"] == "You review code." and r["other"] == ["hooks", "memory"]

    # the form: fields rewritten, keys it does not show kept, the file renamed with the name
    app.post("/api/agents/save", {"profile": "default", "old_name": "reviewer", "prompt": "You review code carefully.",
                                  "fields": {"name": "code-reviewer", "description": "Reviews: diffs, before commits",
                                             "tools": "Read, Grep, Bash", "model": "opus", "effort": "high", "maxTurns": "12",
                                             "color": "blue", "permissionMode": "", "disallowedTools": ""}})
    assert not home.path(".claude/agents/reviewer.md").exists()
    assert home.path(".claude/agents/code-reviewer.md").read_text() == (
        "---\nname: code-reviewer\ndescription: \"Reviews: diffs, before commits\"\ntools: Read, Grep, Bash\nmodel: opus\n"
        "effort: high\nmaxTurns: 12\ncolor: blue\nhooks:\n  Stop:\n    - command: echo done\nmemory: project\n---\n"
        "You review code carefully.\n")
    assert app.get("/api/agents/file?profile=default&name=code-reviewer")["fields"]["description"] == "Reviews: diffs, before commits"

    # a new one, then the errors
    app.post("/api/agents/save", {"profile": "work", "prompt": "Write docs.",
                                  "fields": {"name": "docs", "description": "Writes docs", "model": "inherit"}})
    assert home.path(".claude-work/agents/docs.md").read_text() == "---\nname: docs\ndescription: Writes docs\nmodel: inherit\n---\nWrite docs.\n"
    assert "already has an agent" in app.post_error("/api/agents/save", {"profile": "work", "fields": {"name": "docs", "description": "x"}})
    assert "Invalid name" in app.post_error("/api/agents/save", {"profile": "work", "fields": {"name": "Docs!", "description": "x"}})
    assert "Write a description" in app.post_error("/api/agents/save", {"profile": "work", "fields": {"name": "x"}})
    assert "Max turns" in app.post_error("/api/agents/save", {"profile": "work", "fields": {"name": "x", "description": "d", "maxTurns": "-1"}})
    assert "Effort" in app.post_error("/api/agents/save", {"profile": "work", "fields": {"name": "x", "description": "d", "effort": "huge"}})
    assert "Invalid agent name" in app.post_error("/api/agents/save-raw", {"profile": "work", "name": "../x", "content": ""})

    # the file editor: anything, as long as the name stays and there is a description
    raw = "---\nname: docs\ndescription: Writes docs\nskills: [changelog]\n---\nWrite docs well."
    app.post("/api/agents/save-raw", {"profile": "work", "name": "docs", "content": raw})
    assert home.path(".claude-work/agents/docs.md").read_text() == raw + "\n"
    assert "name must stay docs" in app.post_error("/api/agents/save-raw", {"profile": "work", "name": "docs",
                                                                              "content": "---\nname: other\ndescription: d\n---\n"})
    assert "frontmatter" in app.post_error("/api/agents/save-raw", {"profile": "work", "name": "docs", "content": "hello"})

    # copy, copy to all, compare, delete
    app.post("/api/agents/copy", {"profile": "work", "name": "docs", "to": "default"})
    assert "already has an agent" in app.post_error("/api/agents/copy", {"profile": "work", "name": "docs", "to": "default"})
    plan = app.get("/api/agents/copy-all/preview?profile=default&name=code-reviewer")
    assert [t["id"] for t in plan["apply"]] == ["work"]
    app.post("/api/agents/copy-all", {"profile": "default", "name": "code-reviewer"})
    cmp = app.get("/api/compare?a=default&b=work")["agents"]
    assert cmp["only_a"] == ["broken"] and cmp["only_b"] == [] and {x["name"]: x["same"] for x in cmp["both"]} == {
        "code-reviewer": True, "docs": True}
    app.post("/api/agents/delete", {"profile": "default", "name": "broken"})
    assert not home.path(".claude/agents/broken.md").exists()

    app.restore_all()
    assert home.snapshot() == before


def test_choose_a_folder(home, app_factory):
    basic_home(home)
    home.path("code/work/.hidden").mkdir(parents=True)
    app = app_factory()
    d = app.get("/api/folders?path=~/code")
    assert d["path"] == "~/code" and d["parent"] == "~" and d["home"] == "~"
    assert d["folders"] == ["new-name", "personal", "work"] and d["crumbs"][-1] == {"name": "code", "path": "~/code"}
    assert app.get("/api/folders?path=~/code/work")["folders"] == ["api"]
    assert app.get("/api/folders?path=~/code/work&hidden=1")["folders"] == [".hidden", "api"]
    assert app.get("/api/folders?path=~/code/nope/deeper")["path"] == "~/code"  # the closest folder that exists
    assert app.get("/api/folders?path=relative")["path"] == "~"
    # no dialog here: the page browses instead
    assert app.get("/api/folders/pick?start=~/code") == {"native": False, "start": "~/code"}
    app.stop()

    # the system's dialog (a fake zenity): its answer, or a cancel
    zenity = home.write(".local/bin/zenity", '#!/bin/sh\necho "$@" > "$HOME/zenity-args"\n'
                                              '[ -f "$HOME/cancel" ] && exit 1\necho "$HOME/code/work/api"\n')
    zenity.chmod(0o755)
    app = app_factory(CC_PROFILES_PICKER="zenity")
    r = app.get("/api/folders/pick?start=~/code/work&prompt=New%20folder")
    assert r == {"native": True, "cancelled": False, "path": "~/code/work/api", "exists": True}
    assert home.path("zenity-args").read_text().split() == [
        "--file-selection", "--directory", "--title=New", "folder", f"--filename={home.path('code/work')}/"]
    home.write("cancel", "")
    assert app.get("/api/folders/pick") == {"native": True, "cancelled": True}


def test_merge_an_orphan_into_another_project(home, app_factory):
    basic_home(home)
    old, blog = san(home.path("code/old-name")), san(home.path("code/personal/blog"))
    home.write(f".claude/projects/{old}/memory/old-notes.md", "---\nname: old-notes\ndescription: d\n---\nold\n")
    home.write(f".claude/projects/{old}/memory/MEMORY.md", "- [old-notes](old-notes.md) — d\n")
    home.write(f".claude/projects/{old}/s-blog.jsonl", "{}\n")  # the same conversation file in both
    before = home.snapshot()
    app = app_factory()

    pl = app.get(f"/api/projects/merge/preview?project={old}&profile=default&into={blog}")
    assert pl == {"from": "~/code/old-name", "into": "~/code/personal/blog", "conversations": 2, "memories": 1,
                  "prompts": 1, "conflicts": ["s-blog.jsonl"]}
    r = app.post("/api/projects/merge", {"project": old, "profile": "default", "into": blog})
    assert r["message"].startswith("Merged into ~/code/personal/blog")
    assert not home.path(f".claude/projects/{old}").exists()
    target = home.path(f".claude/projects/{blog}")
    assert (target / "s-old.jsonl").exists() and (target / "memory/old-notes.md").exists()
    assert "old-notes" in (target / "memory/MEMORY.md").read_text()
    hist = [json.loads(l)["project"] for l in home.path(".claude/history.jsonl").read_text().splitlines()]
    assert hist.count(str(home.path("code/personal/blog"))) == 2
    assert app.get("/api/backups")[0]["title"] == "Merge ~/code/old-name into ~/code/personal/blog (Default)"

    assert "Pick another project" in app.post_error("/api/projects/merge", {"project": blog, "profile": "default", "into": blog})
    api = san(home.path("code/work/api"))
    shutil.rmtree(home.path("code/work/api"))
    assert "not on disk" in app.post_error("/api/projects/merge", {"project": blog, "profile": "default", "into": api})
    home.path("code/work/api").mkdir()

    app.restore_all()
    assert home.snapshot() == before
