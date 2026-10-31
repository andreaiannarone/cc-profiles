"""Projects, memories and restoring them; the security guard, the first run, previews and the listings' caches.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request

from conftest import SRC, san
from helpers import basic_home


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
    # scripts: only the page's own files and the inline ones with this response's nonce
    nonce = re.search(r"script-src 'self' 'nonce-([\w-]+)';", csp).group(1)
    assert "unsafe-inline" not in csp.split("script-src")[1].split(";")[0]
    html = urllib.request.urlopen(app.base + "/", timeout=5).read().decode()
    assert nonce not in html  # a fresh nonce for every response
    inline = re.findall(r"<script( nonce=\"[\w-]+\")?>", html, re.IGNORECASE)
    assert len(inline) == 2 and all(inline)


def test_static_files_are_only_the_pages_css_and_scripts(home, app_factory):
    app = app_factory()
    html = urllib.request.urlopen(app.base + "/", timeout=5).read().decode()
    files = re.findall(r'(?:src|href)="/static/([^"]+)"', html)
    assert "app.css" in files and "core.js" in files and files[-1] == "main.js"
    for name in files:
        with urllib.request.urlopen(f"{app.base}/static/{name}", timeout=5) as r:
            assert r.headers["Content-Type"].startswith("text/css" if name.endswith(".css") else "text/javascript")
            assert r.headers["X-Content-Type-Options"] == "nosniff" and r.read()
    for bad in ("whatsnew.json", "index.html", "..%2Fcore.py", "missing.js", "a/core.js"):
        assert app.request(f"/static/{bad}", token=False)[0] == 404


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


def test_a_folder_moved_just_now_is_suggested_when_asked(home, app_factory):
    basic_home(home)
    app = app_factory()
    assert app.get("/api/candidates?name=old-name") == []  # the walk is kept for a minute
    home.path("elsewhere/old-name").mkdir(parents=True)
    assert app.get("/api/candidates?name=old-name") == []
    assert app.get("/api/candidates?name=old-name&fresh=1") == ["~/elsewhere/old-name"]  # Relink… asks afresh
    home.path("other/old-name").mkdir(parents=True)
    orphans = {p["id"]: p for p in app.get("/api/health?fresh=1")}["default"]["orphans"]  # Run the checks again
    assert sorted(orphans[0]["candidates"]) == ["~/elsewhere/old-name", "~/other/old-name"]


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
    home.write(".config/gh/hosts.yml", "github.com:\n    user: me\n")
    home.json(".claude-work/settings.json", {"env": {"GH_CONFIG_DIR": str(home.path(".config/gh-work"))}})
    about = app_factory().get("/api/about")
    github = {p["id"]: p["account"]["GitHub"] for p in about["profiles"]}
    assert github == {"default": "me · ~/.config/gh", "work": "not signed in · ~/.config/gh-work"}
    usage = {p["id"]: p["usage"] for p in about["profiles"]}
    assert usage["default"]["Saved conversations"] == 3 and usage["default"]["Prompts in history"] == 3
    assert usage["work"]["Prompts in history"] == 1 and usage["default"]["Disk usage"] > 0
    assert about["app"]["Backups"].startswith("0 ·")


# --- memories, relink and move: merging -------------------------------------------
def test_memory_read_move_and_delete(home, app_factory):
    basic_home(home)
    home.conversation("work", "code/personal/blog", "s-blog-work", {"api-notes.md": "same name"})
    before = home.snapshot()
    app = app_factory()
    api, blog = san(home.path("code/work/api")), san(home.path("code/personal/blog"))
    F = "/api/memory/file?profile=default&project=" + api + "&file="

    assert "the api uses postgres" in app.get(F + "api-notes.md")["content"]
    status, body = app.request(F + "nope.md")
    assert status == 404 and body["error"] == "Memory not found"
    assert "Memory not found" in app.post_error("/api/memory/move", {"profile": "default", "project": api, "file": "nope.md",
                                                                     "to_profile": "work", "to_project": blog})
    assert "already has a memory" in app.post_error("/api/memory/move", {"profile": "default", "project": api,
                                                                         "file": "api-notes.md", "to_profile": "work",
                                                                         "to_project": blog})
    r = app.post("/api/memory/delete", {"profile": "default", "project": api, "file": "api-notes.md"})
    assert r["message"].startswith("Memory deleted")
    assert not home.path(f".claude/projects/{api}/memory/api-notes.md").exists()
    assert "api-notes" not in home.path(f".claude/projects/{api}/memory/MEMORY.md").read_text()

    app.restore_all()
    assert home.snapshot() == before


def test_relink_into_an_existing_project_merges_and_keeps_conflicts(home, app_factory):
    basic_home(home)
    old_path, new_path = home.path("code/old-name"), home.path("code/new-name")
    old_rel = f".claude/projects/{san(old_path)}"
    home.conversation("", "code/new-name", "s-new", {"dup.md": "the target's"})
    home.write(f"{old_rel}/s-new.jsonl", "{}\n")  # the same conversation in both
    home.write(f"{old_rel}/memory/dup.md", "---\nname: dup\n---\nthe source's\n")
    home.write(f"{old_rel}/memory/solo.md", "---\nname: solo\n---\nonly here\n")
    home.write(f"{old_rel}/memory/MEMORY.md", "# index\n- [dup](dup.md) — about dup.md\n- [solo](solo.md) — only here\n")
    with open(home.path(".claude/history.jsonl"), "a") as f:
        f.write("not json\n")
    cfg = json.loads(home.path(".claude.json").read_text())
    cfg["projects"][str(old_path)] = {"allowedTools": ["Read"]}
    home.json(".claude.json", cfg)
    before = home.snapshot()
    app = app_factory()
    old_name, new_name = san(old_path), san(new_path)
    R = "/api/projects/relink"

    assert "Folder does not exist: ~/code/nowhere" in app.post_error(
        R, {"project": old_name, "profile": "default", "path": "~/code/nowhere"})
    assert "already linked" in app.post_error(R, {"project": new_name, "profile": "default", "path": str(new_path) + "/"})
    r = app.post(R, {"project": old_name, "profile": "default", "path": "~/code/new-name"})
    assert r["message"] == "Linked to ~/code/new-name: 1 conversations, 1 prompts, settings moved."
    new_d = home.path(f".claude/projects/{new_name}")
    assert not home.path(old_rel).exists()
    assert (new_d / "s-old.jsonl").exists() and (new_d / "memory/solo.md").exists()
    assert "the target's" in (new_d / "memory/dup.md").read_text()  # the source's copy is in the backup
    index = (new_d / "memory/MEMORY.md").read_text()
    assert index.count("(dup.md)") == 1 and index.count("(solo.md)") == 1
    assert "not json" in home.path(".claude/history.jsonl").read_text()
    projects = json.loads(home.path(".claude.json").read_text())["projects"]
    assert str(old_path) not in projects and str(new_path) in projects

    app.restore_all()
    assert home.snapshot() == before


def test_move_merges_history_without_duplicates(home, app_factory):
    basic_home(home)
    api = home.path("code/work/api")
    lines = [json.dumps({"display": "work prompt", "timestamp": 4, "project": str(api)}),  # Default has it too
             json.dumps({"display": "another", "timestamp": 5, "project": str(api)}), "garbage"]
    home.write(".claude-work/history.jsonl", "\n".join(lines) + "\n")
    with open(home.path(".claude/history.jsonl"), "a") as f:
        f.write(lines[0] + "\nbroken\n")
    before = home.snapshot()
    app = app_factory()

    assert "same profile" in app.post_error("/api/projects/move", {"project": san(api), "from": "work", "to": "work"})
    r = app.post("/api/projects/move", {"project": san(api), "from": "work", "to": "default"})
    assert "2 prompts" in r["message"]
    hist = home.path(".claude/history.jsonl").read_text().splitlines()
    assert hist.count(lines[0]) == 1 and lines[1] in hist and "broken" in hist
    assert home.path(".claude-work/history.jsonl").read_text() == "garbage\n"

    app.restore_all()
    assert home.snapshot() == before


# --- shared memory ------------------------------------------------------------------------
def test_shared_memory_between_profiles(home, app_factory):
    """Work and Personal use Default's memory of a project through a link: Work's own memories join it
    (a clash goes to the backup), edits reach every profile, the project cannot be moved or deleted
    from under them, and separating gives a profile its own copy again. All of it can be undone."""
    basic_home(home)
    home.conversation("work", "code/work/api", "s-api-work2", {"deploy.md": "deploy on fridays",
                                                               "api-notes.md": "work's notes"})
    home.profile("personal")
    before = home.snapshot()
    app = app_factory()
    api = san(home.path("code/work/api"))
    q = f"project={api}"

    sh = app.get(f"/api/memory/list?profile=default&{q}")["sharing"]
    assert sh["from"] is None and sh["with"] == [] and {o["id"]: o["own"] for o in sh["others"]} == {"work": 2, "personal": 0}
    plan = app.get(f"/api/memory/share-plan?profile=work&{q}&from=default")
    assert plan["join"] == ["deploy.md"] and plan["conflicts"] == ["api-notes.md"]
    msg = app.post("/api/memory/share", {"profile": "work", "project": api, "from": "default", "shared": True})["message"]
    assert "1 of its memories joined it" in msg and "1 with a name already there is kept in the backup" in msg
    work_md = home.path(f".claude-work/projects/{api}/memory")
    default_md = home.path(f".claude/projects/{api}/memory")
    assert work_md.is_symlink() and os.readlink(work_md) == f"../../../.claude/projects/{api}/memory"
    assert sorted(os.listdir(default_md)) == ["MEMORY.md", "api-notes.md", "deploy.md"]
    assert "the api uses postgres" in (default_md / "api-notes.md").read_text()  # the shared one wins a clash
    assert "(deploy.md)" in (default_md / "MEMORY.md").read_text()

    # a profile that never opened the project gets the folder and the link
    app.post("/api/memory/share", {"profile": "personal", "project": api, "from": "default", "shared": True})
    assert home.path(f".claude-personal/projects/{api}/memory").is_symlink()
    assert "already uses this memory" in app.post_error(
        "/api/memory/share", {"profile": "work", "project": api, "from": "default", "shared": True})
    assert "share it from there" in app.post_error(
        "/api/memory/share", {"profile": "personal", "project": api, "from": "work", "shared": True})

    # edited from Work: written in the shared folder, the link stays
    app.post("/api/memory/save", {"profile": "work", "project": api, "file": "deploy.md", "content": "deploy on mondays"})
    assert work_md.is_symlink() and "mondays" in (default_md / "deploy.md").read_text()
    found = app.get("/api/search?q=mondays")["results"]["memories"]  # one result, every profile that sees it
    assert len(found) == 1 and sorted(found[0]["profiles"]) == ["default", "personal", "work"]
    assert app.get(f"/api/memory/list?profile=personal&{q}")["sharing"]["from"] == "default"
    assert sorted(app.get(f"/api/memory/list?profile=default&{q}")["sharing"]["with"]) == ["personal", "work"]
    assert next(p for p in app.get("/api/memory/projects?profile=work") if p["name"] == api)["shared"]
    row = next(r for r in app.get("/api/projects") if r["name"] == api)
    assert row["in"]["work"]["mem_from"] == "default" and "mem_from" not in row["in"]["default"]

    # the holder's project stays put while others use its memory
    err = app.post_error("/api/projects/move", {"project": api, "from": "default", "to": "work"})
    assert "Personal and Work use its memory" in err and "Separate the memory" in err
    assert "Cannot delete this project" in app.post_error("/api/projects/delete", {"project": api, "profile": "default"})

    # separating: Personal gets its own copy, Work still shares
    app.post("/api/memory/share", {"profile": "personal", "project": api, "shared": False})
    personal_md = home.path(f".claude-personal/projects/{api}/memory")
    assert not personal_md.is_symlink() and sorted(os.listdir(personal_md)) == sorted(os.listdir(default_md))
    assert app.get(f"/api/memory/list?profile=default&{q}")["sharing"]["with"] == ["work"]
    assert "is not shared" in app.post_error("/api/memory/share", {"profile": "personal", "project": api, "shared": False})

    app.restore_all()
    assert home.snapshot() == before


def test_a_shared_memory_follows_its_project(home, app_factory):
    """Moving a project whose memory is shared keeps the link (same project, another profile);
    relinking it to another folder gives it a copy of its own; a profile holding shared memory
    cannot be deleted."""
    basic_home(home)
    home.profile("personal")
    shutil.rmtree(home.path(f".claude-work/projects/{san(home.path('code/work/api'))}"))
    home.conversation("work", "code/work/cli", "s-cli", {"cli.md": "the cli is in go"})
    before = home.snapshot()
    app = app_factory()
    api = san(home.path("code/work/api"))
    app.post("/api/memory/share", {"profile": "work", "project": api, "from": "default", "shared": True})
    plan = app.get(f"/api/projects/move/preview?project={api}&from=work&to=personal")
    assert [i["action"] for i in plan["items"]] == ["link"]
    app.post("/api/projects/move", {"project": api, "from": "work", "to": "personal"})
    moved = home.path(f".claude-personal/projects/{api}/memory")
    assert moved.is_symlink() and os.path.realpath(moved) == os.path.realpath(home.path(f".claude/projects/{api}/memory"))
    assert not home.path(f".claude-work/projects/{api}").exists()

    home.path("code/work/api2").mkdir()
    app.post("/api/projects/relink", {"project": api, "profile": "personal", "path": str(home.path("code/work/api2"))})
    copy = home.path(f".claude-personal/projects/{san(home.path('code/work/api2'))}/memory")
    assert not copy.is_symlink() and (copy / "api-notes.md").read_text().endswith("the api uses postgres\n")
    home.path("code/work/api2").rmdir()

    cli = san(home.path("code/work/cli"))
    app.post("/api/memory/share", {"profile": "personal", "project": cli, "from": "work", "shared": True})
    assert "Personal uses the memory of projects in Work" in app.post_error("/api/profiles/delete", {"id": "work"})
    app.restore_all()
    assert home.snapshot() == before
