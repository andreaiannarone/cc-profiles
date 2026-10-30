"""Helpers shared by the end-to-end tests: fake homes, the command line, fake tools."""
import json
import os
import re
import subprocess
import sys

from conftest import SRC, child_env


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


def pypi(tmp_path, version):
    f = tmp_path / f"pypi-{version}.json"
    f.write_text(json.dumps({"info": {"version": version}}))
    return f.as_uri()


def fake_tool(tmp_path, name, output, code):
    """A fake `pipx` or `uv` on PATH, first, so a real one is never run."""
    bin_dir = tmp_path / f"bin-{code}-{abs(hash(output))}"
    bin_dir.mkdir()
    tool = bin_dir / name
    tool.write_text(f"#!/bin/sh\ncat <<'EOF'\n{output}\nEOF\nexit {code}\n")
    tool.chmod(0o755)
    return f"{bin_dir}:/usr/bin:/bin"


def run_cli(home, *args, **env):
    e = child_env({"HOME": str(home.root), "PATH": "/usr/bin:/bin", "PYTHONPATH": str(SRC), **env})
    return subprocess.run([sys.executable, "-m", "cc_profiles", *args], env=e,
                          capture_output=True, text=True, timeout=60)


def is_current_command(text):
    """The /cc-profiles text this version writes, with the cc-profiles it found (an absolute path)."""
    sys.path.insert(0, str(SRC))
    from cc_profiles import server
    exe = re.search(r"^!`(.*) open \$ARGUMENTS`$", text, re.M).group(1)
    return os.path.isabs(exe.split()[0]) and text == server.command_text(exe)


def fake_pipx(home):
    """A pipx in the fake ~/.local/bin that only records its arguments."""
    pipx = home.write(".local/bin/pipx", '#!/bin/sh\necho "$@" >> "$HOME/pipx-calls"\necho "pipx $1 done"\n')
    pipx.chmod(0o755)
    return home.path("pipx-calls")


def restore_newest(app):
    newest = app.get("/api/backups")[0]
    app.post("/api/backups/restore", {"name": newest["name"]})
