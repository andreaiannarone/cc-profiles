"""Backups: apply to all profiles in one backup, automatic cleanup, what a backup changed.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json
import os
import time
import urllib.parse

from conftest import san
from helpers import basic_home, restore_newest


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
