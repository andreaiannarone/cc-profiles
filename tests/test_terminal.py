"""Open in Terminal (macOS), with a dry run.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json
import os
import shutil

from helpers import basic_home


# --- open in terminal ---------------------------------------------------------


def test_open_in_terminal_writes_a_script_for_the_profile(home, app_factory):
    """Open in Terminal: a .command script that goes into the folder and starts Claude Code in the
    profile (CLAUDE_CONFIG_DIR unset for ~/.claude); the terminal chosen is saved with a backup."""
    basic_home(home)
    home.path("Applications/iTerm.app").mkdir(parents=True)
    home.path("Applications/Ghostty.app").mkdir()
    app = app_factory(CC_PROFILES_TERMINAL_DRYRUN="1")
    before = home.snapshot()

    st = app.get("/api/terminal")
    assert st["supported"] and {"iTerm", "Ghostty"} <= set(st["choices"]) and st["terminal"] in st["choices"]
    assert "not installed" in app.post_error("/api/terminal", {"terminal": "Hyper"})
    assert app.post("/api/terminal", {"terminal": "iTerm"})["backup"]
    assert app.get("/api/terminal")["terminal"] == "iTerm"
    assert json.loads(home.path(".cc-profiles/config.json").read_text())["terminal"] == "iTerm"

    api = str(home.path("code/work/api"))
    name = next(p["name"] for p in app.get("/api/projects") if p.get("path") == api)
    r = app.post("/api/terminal/open", {"project": name, "profile": "work"})
    assert r["command"][:3] == ["/usr/bin/open", "-a", str(home.path("Applications/iTerm.app"))]
    script = r["command"][-1]
    assert script.endswith(".command") and os.access(script, os.X_OK)
    text = open(script).read()
    assert f"cd {api} " in text and "rm -f \"$0\"" in text and "command claude" in text
    assert f"export CLAUDE_CONFIG_DIR={home.path('.claude-work')}" in text

    app.post("/api/terminal", {"terminal": "Ghostty"})
    r = app.post("/api/terminal/open", {"project": name, "profile": "default"})
    assert r["command"][:5] == ["/usr/bin/open", "-na", str(home.path("Applications/Ghostty.app")), "--args", "-e"]
    assert "unset CLAUDE_CONFIG_DIR" in open(r["command"][-1]).read()

    moved = next(p["name"] for p in app.get("/api/projects") if p.get("path") == str(home.path("code/old-name")))
    assert "Relink the project first" in app.post_error("/api/terminal/open", {"project": moved, "profile": "default"})
    assert "not found" in app.post_error("/api/terminal/open", {"project": "-nope", "profile": "default"})

    shutil.rmtree(home.path(".cc-profiles/terminal"))  # scripts a terminal would run and delete
    app.restore_all()
    assert home.snapshot() == before


def test_open_any_folder_in_a_terminal(home, app_factory):
    """From the Finder (the Mac app's Quick Actions): any folder, in the profile picked, else the
    one the rules give it, else the one its project is in, else the first profile."""
    basic_home(home)
    home.path("code/notes").mkdir()
    home.path("Applications/iTerm.app").mkdir(parents=True)  # Linux has no Terminal.app
    app = app_factory(CC_PROFILES_TERMINAL_DRYRUN="1")
    app.post("/api/rules", {"match": "code/work", "profile": "work"})

    def opened(path, profile=None):
        r = app.post("/api/terminal/open", {"path": path, "profile": profile})
        return r["profile"], open(r["command"][-1]).read()

    pid, script = opened(str(home.path("code/work/api")))
    assert pid == "work" and f"cd {home.path('code/work/api')} " in script
    assert opened("~/code/personal/blog")[0] == "default"  # no rule: its project's profile
    assert opened(str(home.path("code/notes")))[0] == "default"  # not a project: the first profile
    assert opened(str(home.path("code/notes")), "work")[0] == "work"
    assert "Folder does not exist" in app.post_error("/api/terminal/open", {"path": str(home.path("code/gone"))})
    assert "Unknown profile" in app.post_error("/api/terminal/open", {"path": str(home.path("code/notes")),
                                                                      "profile": "nope"})
