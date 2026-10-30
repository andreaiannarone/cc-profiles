"""Profile by folder: cc-profiles which, shell-init and the line in the shell rc files.

Like every end-to-end test here, they run against a real server on a fake home and
usually end by restoring every backup and comparing the fake home with how it started.
"""
import json
import shutil
import subprocess
import sys
import threading
import urllib.parse

import pytest

from conftest import SRC, child_env
from helpers import basic_home, run_cli


# --- profile by folder (cc-profiles which, shell-init, the rc line) ------------


SHELL_LINE = 'command -v cc-profiles >/dev/null 2>&1 && eval "$(cc-profiles shell-init {})"  # cc-profiles: profile by folder'


def test_a_config_that_cannot_be_read_is_never_lost(home, app_factory):
    basic_home(home)
    app = app_factory()
    data, file = home.path(".cc-profiles"), home.path(".cc-profiles/config.json")
    cfg = json.loads(file.read_text())
    cfg["rules"] = [{"match": "code/mine", "profile": "work"}]
    file.write_text('{"profiles": [')  # an editor half way through saving: whole again a moment later
    later = threading.Timer(0.2, lambda: file.write_text(json.dumps(cfg)))
    later.start()
    assert app.get("/api/profiles")
    later.join()
    assert json.loads(file.read_text()) == cfg and not list(data.glob("config.broken-*"))
    file.write_text('{"rules": [{"match": "code/mine"')  # broken for good
    assert app.get("/api/profiles")  # the defaults replace it, and the file is kept next to it
    assert json.loads(file.read_text())["profiles"]
    kept = list(data.glob("config.broken-*.json"))
    assert kept and kept[0].read_text() == '{"rules": [{"match": "code/mine"'


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
                          capture_output=True, text=True, timeout=60)


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


# --- rules ------------------------------------------------------------------------
def test_rules_are_checked_and_stored_relative_to_home(home, app_factory):
    basic_home(home)
    app = app_factory()
    assert "Invalid profile" in app.post_error("/api/rules", {"match": "code", "profile": "nobody"})
    assert "Empty rule" in app.post_error("/api/rules", {"match": "  ", "profile": "work"})
    assert "“code/work” → Work" in app.post("/api/rules", {"match": str(home.path("code/work")), "profile": "work"})["message"]
    assert "“~” → " in app.post("/api/rules", {"match": str(home.root), "profile": "shared"})["message"]
    rows = {r["pretty"]: r for r in app.get("/api/projects")}
    assert rows["~/code/work/api"]["expected"] == "work"
