"""Hooks, custom slash commands and keyboard shortcuts of a profile.

Like every end-to-end test here, they run against a real server on a fake home and
end by restoring every backup and comparing the fake home with how it started.
"""
import json

from helpers import basic_home


# --- hooks ----------------------------------------------------------------------


def hooks_home(home):
    basic_home(home)
    home.json(".claude/settings.json", {"model": "opus", "hooks": {
        "PostToolUse": [{"matcher": "Edit|Write", "hooks": [
            {"type": "command", "command": "npx prettier --write", "timeout": 30, "shell": "bash"}]}],
        "Stop": [{"hooks": [{"type": "prompt", "prompt": "Check the tests ran"}]}]}})
    home.json(".claude/settings.local.json", {"hooks": {"SessionStart": [{"matcher": "startup", "hooks": [
        {"type": "command", "command": "echo hi"}]}]}})
    home.write(".claude/plugins/installed_plugins.json", json.dumps({"plugins": {"kit@market": [
        {"installPath": str(home.path("plugin-kit"))}]}}))
    home.json("plugin-kit/hooks/hooks.json", {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/guard.sh"}]}]}})


def at(row):
    return {k: row[k] for k in ("file", "event", "group", "index", "fp")}


def test_hooks_are_listed_edited_moved_and_undoable(home, app_factory):
    hooks_home(home)
    before = home.snapshot()
    app = app_factory()

    d = app.get("/api/hooks?profile=default")
    assert [(h["file"], h["event"], h["matcher"], h["type"], h["text"]) for h in d["hooks"]] == [
        ("settings", "PostToolUse", "Edit|Write", "command", "npx prettier --write"),
        ("settings", "Stop", "", "prompt", "Check the tests ran"),
        ("local", "SessionStart", "startup", "command", "echo hi")]
    assert d["hooks"][0]["other"] == ["shell"] and d["hooks"][0]["timeout"] == 30
    assert [(h["plugin"], h["event"], h["text"]) for h in d["plugins"]] == [
        ("kit@market", "PreToolUse", "${CLAUDE_PLUGIN_ROOT}/guard.sh")]
    assert "Bash" in next(e for e in d["events"] if e["name"] == "PreToolUse")["matchers"]
    assert d["disabled"] is False

    # a new hook joins the group with the same matcher
    app.post("/api/hooks/save", {"profile": "default", "hook": {"event": "PostToolUse", "matcher": "Edit|Write",
                                                                "command": "ruff format", "async": True}})
    data = json.loads(home.path(".claude/settings.json").read_text())
    assert data["hooks"]["PostToolUse"][0]["hooks"][1] == {"type": "command", "command": "ruff format", "async": True}
    assert data["model"] == "opus"

    # editing keeps the keys the form does not show; a new matcher moves it into a new group
    first = app.get("/api/hooks?profile=default")["hooks"][0]
    app.post("/api/hooks/save", {"profile": "default", "at": at(first),
                                 "hook": {"event": "PostToolUse", "matcher": "Edit", "command": "npx prettier --write .",
                                          "timeout": "60", "statusMessage": "Formatting"}})
    groups = json.loads(home.path(".claude/settings.json").read_text())["hooks"]["PostToolUse"]
    assert groups == [{"matcher": "Edit|Write", "hooks": [{"type": "command", "command": "ruff format", "async": True}]},
                      {"matcher": "Edit", "hooks": [{"type": "command", "command": "npx prettier --write .", "shell": "bash",
                                                     "timeout": 60, "statusMessage": "Formatting"}]}]

    # the page's copy is stale now: the old position is refused, not edited in the wrong place
    assert "reload" in app.post_error("/api/hooks/delete", {"profile": "default", "at": at(first)})
    # moved to settings.local.json, the empty event and file keys go away
    local = next(h for h in app.get("/api/hooks?profile=default")["hooks"] if h["file"] == "local")
    app.post("/api/hooks/save", {"profile": "default", "at": at(local),
                                 "hook": {"file": "settings", "event": "SessionStart", "matcher": "startup", "command": "echo hi"}})
    assert json.loads(home.path(".claude/settings.local.json").read_text()) == {}
    # a prompt hook is edited in the advanced editor, but it can be deleted
    stop = next(h for h in app.get("/api/hooks?profile=default")["hooks"] if h["event"] == "Stop")
    assert "advanced editor" in app.post_error("/api/hooks/save", {"profile": "default", "at": at(stop),
                                                                   "hook": {"event": "Stop", "command": "x"}})
    app.post("/api/hooks/delete", {"profile": "default", "at": at(stop)})
    assert "Stop" not in json.loads(home.path(".claude/settings.json").read_text())["hooks"]
    assert "command" in app.post_error("/api/hooks/save", {"profile": "default", "hook": {"event": "Stop", "command": " "}})
    assert "event" in app.post_error("/api/hooks/save", {"profile": "default", "hook": {"event": "Nope", "command": "x"}})

    # copy to another profile, then to all: a profile that has it is skipped
    hook = next(h for h in app.get("/api/hooks?profile=default")["hooks"] if h["event"] == "SessionStart")
    app.post("/api/hooks/copy", {"profile": "default", "at": at(hook), "to": "work"})
    assert json.loads(home.path(".claude-work/settings.json").read_text())["hooks"] == {
        "SessionStart": [{"matcher": "startup", "hooks": [{"type": "command", "command": "echo hi"}]}]}
    assert "already has" in app.post_error("/api/hooks/copy", {"profile": "default", "at": at(hook), "to": "work"})
    plan = app.get("/api/hooks/copy-all/preview?profile=default&" + "&".join(f"{k}={v}" for k, v in at(hook).items()))
    assert plan["apply"] == [] and plan["skip"][0]["reason"] == "already has this hook"

    app.restore_all()
    assert home.snapshot() == before


def test_turning_off_all_hooks_is_a_setting(home, app_factory):
    hooks_home(home)
    app = app_factory()
    app.post("/api/settings/field", {"profile": "default", "key": "disableAllHooks", "value": True})
    d = app.get("/api/hooks?profile=default")
    assert d["disabled"] is True and d["disabled_in"] == "settings.json"
    app.post("/api/settings/field", {"profile": "default", "key": "disableAllHooks", "value": False})
    assert "disableAllHooks" not in json.loads(home.path(".claude/settings.json").read_text())


# --- custom slash commands ------------------------------------------------------


def test_commands_are_managed_and_undoable(home, app_factory):
    basic_home(home)
    home.write(".claude/commands/review.md", "---\ndescription: Review the diff\nargument-hint: [file]\n---\nReview $ARGUMENTS\n")
    home.write(".claude/commands/frontend/test.md", "# Run the frontend tests\n\nnpm test\n")
    home.write(".claude/commands/cc-profiles.md", "---\ndescription: Open cc-profiles\n---\n# managed by cc-profiles\n")
    home.write(".claude/plugins/installed_plugins.json", json.dumps({"plugins": {"kit@market": [
        {"installPath": str(home.path("plugin-kit"))}]}}))
    home.write("plugin-kit/commands/ship.md", "---\ndescription: Ship it\n---\nShip.\n")
    home.write("plugin-kit/skills/deploy/SKILL.md", "---\nname: deploy\ndescription: Deploy the app\nargument-hint: [env]\n---\nGo.\n")
    home.write(".claude/skills/notes/SKILL.md", "---\nname: notes\ndescription: Take notes\n---\nWrite.\n")
    home.write(".claude/skills/background/SKILL.md", "---\nname: background\ndescription: Only for Claude\nuser-invocable: false\n---\nx\n")
    before = home.snapshot()
    app = app_factory()

    d = app.get("/api/commands?profile=default")
    assert [(c["slash"], c["description"], c["fallback"], c["hint"], c["managed"]) for c in d["commands"]] == [
        ("/cc-profiles", "Open cc-profiles", "", "", True),
        ("/frontend:test", "", "Run the frontend tests", "", False),
        ("/review", "Review the diff", "", "[file]", False)]
    assert [(c["slash"], c["plugin"]) for c in d["plugins"]] == [("/kit:ship", "kit@market")]
    builtin = {c["slash"]: c for c in d["builtin"]}
    assert builtin["/usage"]["aliases"] == ["/cost", "/stats"] and builtin["/compact"]["group"] == "Conversation"
    assert d["builtin_version"] and len(builtin) == len(d["builtin"]) > 50
    # skills typed as commands: the profile's (not those marked user-invocable: false), the plugins', Claude Code's
    skills = {c["slash"]: c for c in d["skills"]}
    assert skills["/notes"]["source"] == "profile" and "/background" not in skills
    assert (skills["/kit:deploy"]["source"], skills["/kit:deploy"]["hint"]) == ("kit@market", "[env]")
    assert skills["/simplify"]["source"] == "builtin"
    assert app.get("/api/commands/file?profile=default&name=review")["content"].startswith("---\ndescription: Review")

    app.post("/api/commands/save", {"profile": "default", "name": "git/commit", "new": True,
                                    "content": "---\ndescription: Commit\n---\nCommit the staged changes"})
    assert home.path(".claude/commands/git/commit.md").read_text() == "---\ndescription: Commit\n---\nCommit the staged changes\n"
    assert "already has" in app.post_error("/api/commands/save", {"profile": "default", "name": "git/commit",
                                                                   "new": True, "content": "x"})
    app.post("/api/commands/save", {"profile": "default", "name": "review", "content": "Review it all\n"})
    assert home.path(".claude/commands/review.md").read_text() == "Review it all\n"
    for bad in ("../x", "a/../../b", "", ".hidden", "x.md"):
        assert "Invalid name" in app.post_error("/api/commands/save", {"profile": "default", "name": bad, "new": True, "content": "x"})
    assert "not closed" in app.post_error("/api/commands/save", {"profile": "default", "name": "review", "content": "---\nx: 1\n"})
    # cc-profiles' own command stays as it is
    assert "own command" in app.post_error("/api/commands/save", {"profile": "default", "name": "cc-profiles", "content": "x"})
    assert "own command" in app.post_error("/api/commands/delete", {"profile": "default", "name": "cc-profiles"})

    app.post("/api/commands/copy", {"profile": "default", "name": "git/commit", "to": "work"})
    assert home.path(".claude-work/commands/git/commit.md").exists()
    plan = app.get("/api/commands/copy-all/preview?profile=default&name=review")
    assert [a["label"] for a in plan["apply"]] == ["Work"]
    app.post("/api/commands/copy-all", {"profile": "default", "name": "review"})
    assert home.path(".claude-work/commands/review.md").read_text() == "Review it all\n"
    app.post("/api/commands/delete", {"profile": "default", "name": "frontend/test"})
    assert not home.path(".claude/commands/frontend/test.md").exists()

    app.restore_all()
    assert home.snapshot() == before


# --- keyboard shortcuts ---------------------------------------------------------


def test_keybindings_are_checked_copied_and_undoable(home, app_factory):
    basic_home(home)
    home.json(".claude/keybindings.json", {"bindings": [{"context": "Chat", "bindings": {
        "ctrl+e": "chat:externalEditor", "ctrl+u": None}}]})
    before = home.snapshot()
    app = app_factory()

    d = app.get("/api/keybindings?profile=default")
    assert d["exists"] and d["error"] is None
    assert d["rows"] == [{"context": "Chat", "key": "ctrl+e", "action": "chat:externalEditor"},
                         {"context": "Chat", "key": "ctrl+u", "action": None}]
    assert d["others"] == [{"id": "work", "label": "Work", "count": 0, "same": False}]
    assert app.get("/api/keybindings?profile=work")["exists"] is False

    assert "bindings" in app.post_error("/api/keybindings/save", {"profile": "default", "content": "[]"})
    assert "Invalid JSON" in app.post_error("/api/keybindings/save", {"profile": "default", "content": "{"})
    assert "action" in app.post_error("/api/keybindings/save", {"profile": "default", "content": json.dumps(
        {"bindings": [{"context": "Chat", "bindings": {"ctrl+e": 3}}]})})
    app.post("/api/keybindings/save", {"profile": "default", "content": json.dumps(
        {"bindings": [{"context": "Nowhere", "bindings": {"ctrl+g": "command:review"}}]})})
    d = app.get("/api/keybindings?profile=default")
    assert d["warnings"] == ['Unknown context "Nowhere" in block 1',
                             '"ctrl+g" runs command:review: command bindings work only in the Chat context']

    plan = app.get("/api/keybindings/copy-all/preview?profile=default")
    assert [(a["label"], a["detail"]) for a in plan["apply"]] == [("Work", "keybindings.json created")]
    app.post("/api/keybindings/copy", {"profile": "default", "to": "work"})
    assert json.loads(home.path(".claude-work/keybindings.json").read_text())["bindings"][0]["context"] == "Nowhere"
    assert "same shortcuts" in app.post_error("/api/keybindings/copy-all", {"profile": "default"})
    app.post("/api/keybindings/delete", {"profile": "work"})
    assert not home.path(".claude-work/keybindings.json").exists()

    app.restore_all()
    assert home.snapshot() == before
