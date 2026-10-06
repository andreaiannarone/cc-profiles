"""Tests for the repository's tooling: the Claude Code hook and skills in .claude/,
and the plugin marketplace."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import App, FakeHome, ROOT

GUARD = ROOT / ".claude" / "hooks" / "sandbox_guard.py"


def guard(command, tool="Bash"):
    data = json.dumps({"tool_name": tool, "tool_input": {"command": command}})
    return subprocess.run([sys.executable, str(GUARD)], input=data, capture_output=True, text=True).returncode


@pytest.mark.parametrize("command", [
    "cc-profiles",
    ".venv/bin/cc-profiles --port 4799",
    "python3 -m cc_profiles --no-browser",
    ".venv/bin/python -m cc_profiles open",
    "cd ~/code/cc-profiles && cc-profiles open",
    "cc-profiles install-command",
    "HOME=$HOME cc-profiles",
    "HOME=~ .venv/bin/cc-profiles",
    "HOME=/tmp/sandbox true; cc-profiles",  # HOME=… before a command holds for that command only
    "CC_PROFILES_HOME=/tmp/data cc-profiles open",  # the profiles are still the real ones
    "git status\ncc-profiles open",  # a new line outside quotes separates commands
    "(cc-profiles open)",
    "echo $(cc-profiles open)",
    "cat <<'EOF'\ntext\nEOF\ncc-profiles open",  # once the here-document ends, commands count again
])
def test_guard_blocks_the_app_on_the_real_home(command):
    assert guard(command) == 2


@pytest.mark.parametrize("command", [
    "cc-profiles label",
    "cc-profiles --version",
    ".venv/bin/cc-profiles open --help",
    'HOME="/tmp/sandbox" .venv/bin/cc-profiles --port 4799',
    "export HOME=/tmp/sandbox; cc-profiles open",
    "env -i HOME=/tmp/sandbox PATH=/usr/bin .venv/bin/cc-profiles open",
    ".venv/bin/python -m pytest -q",
    "cd ~/code/cc-profiles && git status",
    "cat ~/.claude/commands/cc-profiles.md",
    "pipx install cc-profiles",
    "git commit -m 'run cc-profiles open'",
    'git commit -m "Fix startup\n\ncc-profiles open gave up waiting."',  # a new line inside quotes
    "echo \"cc-profiles; cc-profiles open\"",
    "git commit -F - <<'EOF'\nFix it\n\ncc-profiles did not write this file\nEOF\ngit push",  # a here-document is text
    "cat > notes.md <<EOF\ncc-profiles open\nEOF",
    "",
])
def test_guard_allows_everything_else(command):
    assert guard(command) == 0


def test_sandbox_home_loads_in_the_app(tmp_path):
    root = tmp_path / "sandbox"
    r = subprocess.run([sys.executable, str(ROOT / ".claude" / "skills" / "sandbox" / "make_home.py"), str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert Path(r.stdout.strip()) == root
    app = App(FakeHome(root))
    try:
        assert [p["id"] for p in app.get("/api/profiles")] == ["default", "client", "work"]
        assert len(app.get("/api/projects")) >= 5
    finally:
        app.stop()


def test_plugin_marketplace_manifests():
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    (entry,) = market["plugins"]
    plugin_dir = ROOT / entry["source"]
    manifest = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text())
    assert manifest["name"] == entry["name"] == "cc-profiles"
    command = (plugin_dir / "commands" / "open.md").read_text()
    # /cc-profiles:open restart|stop: the arguments reach cc-profiles open, which the rule allows
    assert "!`cc-profiles open $ARGUMENTS`" in command
    assert 'argument-hint: "[restart|stop]"' in command and "allowed-tools: Bash(cc-profiles open:*)" in command


def test_docs_build_on_github_pages():
    """GitHub Pages renders docs/ with Jekyll: Liquid tags in a page break the build,
    and every page in the sidebar must exist."""
    for md in (ROOT / "docs").rglob("*.md"):
        text = md.read_text()
        assert "{{" not in text and "{%" not in text, f"{md.relative_to(ROOT)}: Liquid syntax breaks the docs site"
    nav = (ROOT / "docs" / "_data" / "nav.yml").read_text()
    for url in __import__("re").findall(r"url: ([\w/.-]+\.md)", nav):
        assert (ROOT / "docs" / url).is_file(), f"docs/_data/nav.yml links {url}, which does not exist"
    assert (ROOT / "docs" / "CNAME").read_text().strip() == "cc-profiles.andreaia.com"
