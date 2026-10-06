"""Tests for scripts/release.py: its pure parts and the dry run (never a real release)."""
import importlib.util
import io
import subprocess
import sys

import pytest

from conftest import ROOT

SCRIPT = ROOT / "scripts" / "release.py"
spec = importlib.util.spec_from_file_location("release", SCRIPT)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)

URL = "https://github.com/andreaiannarone/cc-profiles"
CHANGELOG = f"""# Changelog

Intro text.

## [Unreleased]

### Added
- A new thing.

### Fixed
- A bug.

## [0.4.3] - 2026-10-06

### Changed
- Something older. See [Unreleased] notes in 0.4.2.

## [0.4.2] - 2026-10-05

- Even older.

[Unreleased]: {URL}/compare/v0.4.3...HEAD
[0.4.3]: {URL}/compare/v0.4.2...v0.4.3
[0.4.2]: {URL}/compare/v0.4.1...v0.4.2
"""


def test_version_compare():
    assert release.is_newer("0.4.10", "0.4.9")
    assert release.is_newer("1.0.0", "0.99.99")
    assert not release.is_newer("0.4.3", "0.4.3")
    assert not release.is_newer("0.4.2", "0.4.3")
    for bad in ("0.5", "v0.5.0", "0.5.0rc1", "", "0.5.0 "):
        with pytest.raises(release.ReleaseError):
            release.version_key(bad)


def test_changelog_rewrite():
    out = release.rewrite_changelog(CHANGELOG, "0.5.0", "0.4.3", "2026-10-07")
    assert out == CHANGELOG.replace(
        "## [Unreleased]\n\n### Added", "## [Unreleased]\n\n## [0.5.0] - 2026-10-07\n\n### Added").replace(
        f"[Unreleased]: {URL}/compare/v0.4.3...HEAD\n",
        f"[Unreleased]: {URL}/compare/v0.5.0...HEAD\n[0.5.0]: {URL}/compare/v0.4.3...v0.5.0\n")
    assert release.unreleased_notes(out) == ""  # Unreleased stays, empty
    assert release.unreleased_notes(CHANGELOG).startswith("### Added")


def test_changelog_rewrite_refuses():
    empty = CHANGELOG.replace("### Added\n- A new thing.\n\n### Fixed\n- A bug.\n\n", "")
    with pytest.raises(release.ReleaseError, match="Nothing under"):
        release.rewrite_changelog(empty, "0.5.0", "0.4.3", "2026-10-07")
    with pytest.raises(release.ReleaseError, match="already has a section"):
        release.rewrite_changelog(CHANGELOG, "0.4.2", "0.4.3", "2026-10-07")
    with pytest.raises(release.ReleaseError, match="compares from v0.4.3"):
        release.rewrite_changelog(CHANGELOG, "0.5.0", "0.4.2", "2026-10-07")
    with pytest.raises(release.ReleaseError, match="no ## \\[Unreleased\\]"):
        release.unreleased_notes("# Changelog\n\n## [0.1.0]\n")


def test_version_bumps():
    init = '"""Doc."""\n\n__version__ = "0.4.3"\n'
    assert release.read_version(init) == "0.4.3"
    assert release.bump_init(init, "0.5.0") == init.replace("0.4.3", "0.5.0")
    plugin = '{\n  "name": "cc-profiles",\n  "version": "0.4.3",\n  "license": "x"\n}\n'
    assert release.bump_plugin(plugin, "0.5.0") == plugin.replace("0.4.3", "0.5.0")
    assert release.pr_number("https://github.com/a/b/pull/16\n") == 16
    assert release.wheel_listed('<a href="https://x/cc_profiles-0.5.0-py3-none-any.whl#sha256=1">', "0.5.0")
    assert not release.wheel_listed('<a href="https://x/cc_profiles-0.5.0.tar.gz#sha256=1">', "0.5.0")
    assert not release.wheel_listed('<a href="https://x/cc_profiles-0.5.01-py3-none-any.whl">', "0.5.0")


def release_files(tmp_path, changelog=CHANGELOG):
    (tmp_path / "src" / "cc_profiles").mkdir(parents=True)
    (tmp_path / "src" / "cc_profiles" / "__init__.py").write_text('__version__ = "0.4.3"\n')
    (tmp_path / "plugin" / ".claude-plugin").mkdir(parents=True)
    (tmp_path / "plugin" / ".claude-plugin" / "plugin.json").write_text('{\n  "version": "0.4.3"\n}\n')
    (tmp_path / "CHANGELOG.md").write_text(changelog)
    return tmp_path


def test_dry_run_prints_every_step_and_changes_nothing(tmp_path):
    root = release_files(tmp_path)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    out = io.StringIO()
    code = release.main(["0.5.0", "--dry-run", "--root", str(root), "--date", "2026-10-07"], out=out)
    text = out.getvalue()
    assert code == 0, text
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before
    expected = [
        "$ git rev-parse --abbrev-ref HEAD",
        "$ git status --porcelain",
        "$ git fetch origin main",
        "$ git rev-parse origin/main",
        "would edit src/cc_profiles/__init__.py",
        '+__version__ = "0.5.0"',
        "would edit plugin/.claude-plugin/plugin.json",
        "+## [0.5.0] - 2026-10-07",
        f"+[0.5.0]: {URL}/compare/v0.4.3...v0.5.0",
        "$ git switch -c release-0.5.0",
        "$ git commit -m 'Release 0.5.0'",
        "$ git push -u origin release-0.5.0",
        "$ gh pr create --base main --head release-0.5.0 --title 'Release 0.5.0' "
        "--body 'Bump the version to 0.5.0 and date the CHANGELOG section.'",
        "$ gh pr checks '<n>' --json name",
        "$ git commit --allow-empty -m 'Trigger CI'",
        "$ gh pr checks '<n>' --watch --interval 10",
        "$ gh pr merge '<n>' --squash --subject 'Release 0.5.0 (#<n>)' --body ''",
        "$ git pull --ff-only origin main",
        "$ git tag v0.5.0",
        "$ git push origin v0.5.0",
        "$ gh run list --workflow release.yml --branch v0.5.0",
        "$ gh run watch '<run id>' --exit-status",
        "GET https://pypi.org/simple/cc-profiles/ (Cache-Control: no-cache)",
        "$ git branch -D release-0.5.0",
        "$ git push origin --delete release-0.5.0",
        "pipx upgrade cc-profiles",
    ]
    pos = 0
    for line in expected:  # all there, in this order
        found = text.find(line, pos)
        assert found >= 0, f"{line!r} missing (or out of order) in:\n{text}"
        pos = found
    # never any attribution
    assert "Co-Authored-By" not in text and "Generated with" not in text


@pytest.mark.parametrize("args,changelog,message", [
    (["0.4.3"], CHANGELOG, "not greater than the current version 0.4.3"),
    (["0.5"], CHANGELOG, "Not a version"),
    (["0.5.0"], CHANGELOG.replace("### Added\n- A new thing.\n\n### Fixed\n- A bug.\n\n", ""), "Nothing under"),
])
def test_dry_run_stops_on_bad_input(tmp_path, args, changelog, message):
    root = release_files(tmp_path, changelog)
    r = subprocess.run([sys.executable, str(SCRIPT), *args, "--dry-run", "--root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 1 and message in r.stderr
