#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""Release cc-profiles: from a clean main to the new version on PyPI.

    python scripts/release.py 0.4.4 --dry-run   # print every step, change nothing
    python scripts/release.py 0.4.4

Checks that main is clean and up to date and that CHANGELOG.md has something under
## [Unreleased]; bumps the version in src/cc_profiles/__init__.py and
plugin/.claude-plugin/plugin.json and dates the CHANGELOG section; opens the
"Release <v>" pull request, waits for its checks and squash-merges it; tags v<v>,
waits for the Release workflow and for the wheel on PyPI; deletes the release branch.
Needs git and an authenticated gh. Standard library only.
"""

import argparse
import datetime
import difflib
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INIT = os.path.join("src", "cc_profiles", "__init__.py")
PLUGIN = os.path.join("plugin", ".claude-plugin", "plugin.json")
CHANGELOG = "CHANGELOG.md"
PYPI_SIMPLE = "https://pypi.org/simple/cc-profiles/"
PR_BODY = "Bump the version to {v} and date the CHANGELOG section."
CHECKS_APPEAR_TIMEOUT = 60      # seconds before pushing an empty "Trigger CI" commit
RUN_APPEAR_TIMEOUT = 180        # seconds for the Release workflow run to show up
PYPI_TIMEOUT = 15 * 60
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ReleaseError(Exception):
    pass


# --- pure helpers (tested in tests/test_release.py) ---------------------------
def version_key(v):
    """(major, minor, patch) of an x.y.z version; anything else is an error."""
    if not VERSION_RE.match(v or ""):
        raise ReleaseError(f"Not a version: {v!r}. Use x.y.z, e.g. 0.4.4.")
    return tuple(int(x) for x in v.split("."))


def is_newer(new, old):
    return version_key(new) > version_key(old)


def next_version(v):
    """The version after v in this project's numbering: only the last number moves, up to
    9, then the one before it (0.4.8 -> 0.4.9 -> 0.5.0; 0.9.9 -> 1.0.0)."""
    major, minor, patch = version_key(v)
    if patch < 9:
        return f"{major}.{minor}.{patch + 1}"
    if minor < 9:
        return f"{major}.{minor + 1}.0"
    return f"{major + 1}.0.0"


def read_version(init_text):
    m = re.search(r'^__version__ = "([^"]+)"', init_text, re.M)
    if not m:
        raise ReleaseError(f"No __version__ in {INIT}.")
    return m.group(1)


def bump_init(init_text, new):
    return re.sub(r'^__version__ = "[^"]+"', f'__version__ = "{new}"', init_text, count=1, flags=re.M)


def bump_plugin(plugin_text, new):
    """Change only the version value, keeping the file's formatting."""
    if "version" not in json.loads(plugin_text):
        raise ReleaseError(f"No version in {PLUGIN}.")
    return re.sub(r'("version"\s*:\s*")[^"]*(")', lambda m: m.group(1) + new + m.group(2), plugin_text, count=1)


def plugin_version(plugin_text):
    return json.loads(plugin_text).get("version")


def unreleased_notes(changelog):
    """The text under ## [Unreleased], up to the next ## section (stripped)."""
    m = re.search(r"^## \[Unreleased\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)", changelog, re.M | re.S)
    if not m:
        raise ReleaseError(f"{CHANGELOG} has no ## [Unreleased] section.")
    return m.group(1).strip()


def rewrite_changelog(changelog, new, prev, date):
    """Date the Unreleased entries as ## [new] - date (Unreleased stays, empty) and update
    the compare links at the bottom. Older entries are left as they are."""
    if not unreleased_notes(changelog):
        raise ReleaseError(f"Nothing under ## [Unreleased] in {CHANGELOG}: add the changes first.")
    if re.search(r"^## \[" + re.escape(new) + r"\]", changelog, re.M):
        raise ReleaseError(f"{CHANGELOG} already has a section for {new}.")
    text = re.sub(r"^## \[Unreleased\][^\n]*\n+", f"## [Unreleased]\n\n## [{new}] - {date}\n\n", changelog,
                  count=1, flags=re.M)
    link = re.search(r"^\[Unreleased\]: (\S+)/compare/v([^.\s][^\s]*?)\.\.\.HEAD$", text, re.M)
    if not link:
        raise ReleaseError(f"No [Unreleased]: …/compare/v<version>...HEAD link at the bottom of {CHANGELOG}.")
    base, linked = link.group(1), link.group(2)
    if linked != prev:
        raise ReleaseError(f"The [Unreleased] link compares from v{linked}, but the current version is {prev}.")
    new_links = f"[Unreleased]: {base}/compare/v{new}...HEAD\n[{new}]: {base}/compare/v{prev}...v{new}"
    return text[:link.start()] + new_links + text[link.end():]


def pr_number(url):
    m = re.search(r"/pull/(\d+)", url or "")
    if not m:
        raise ReleaseError(f"Could not read the pull request number from: {url!r}")
    return int(m.group(1))


def wheel_listed(html, version):
    return re.search(r"cc_profiles-" + re.escape(version) + r"-[^\"'#<>\s]*\.whl", html) is not None


# --- running commands ---------------------------------------------------------
class Releaser:
    def __init__(self, root, dry_run, out=sys.stdout):
        self.root, self.dry, self.out = root, dry_run, out
        self.force_version = False
        self.step_no = 0

    def say(self, text=""):
        print(text, file=self.out, flush=True)

    def step(self, title):
        self.step_no += 1
        self.say(f"\n== {self.step_no}. {title}")

    def run(self, cmd, capture=False, readonly=False, check=True):
        """Run a command in the repository. In a dry run only read-only commands run."""
        self.say("$ " + " ".join(shlex.quote(c) for c in cmd))
        if self.dry and not readonly:
            return ""
        try:
            r = subprocess.run(cmd, cwd=self.root, text=True, capture_output=capture)
        except OSError as e:
            if self.dry:
                self.say(f"  (could not run: {e})")
                return None
            raise ReleaseError(f"Could not run {cmd[0]}: {e}")
        if r.returncode != 0 and check:
            detail = (r.stderr or r.stdout or "").strip() if capture else ""
            if self.dry:
                self.say(f"  (exit {r.returncode}{': ' + detail.splitlines()[-1] if detail else ''})")
                return None
            raise ReleaseError(f"{' '.join(cmd)} ended with code {r.returncode}" + (f": {detail}" if detail else ""))
        return (r.stdout or "").strip() if capture else ""

    def check(self, ok, message):
        """A failed check stops a real run; a dry run reports it and goes on."""
        if ok:
            return
        if self.dry:
            self.say(f"  ! {message} (a real run would stop here)")
            return
        raise ReleaseError(message)

    def read(self, rel):
        with open(os.path.join(self.root, rel)) as f:
            return f.read()

    def write(self, rel, old, new):
        if self.dry:
            self.say(f"would edit {rel}:")
            for line in difflib.unified_diff(old.splitlines(), new.splitlines(), f"a/{rel}", f"b/{rel}", lineterm="", n=1):
                self.say("  " + line)
            return
        self.say(f"edit {rel}")
        with open(os.path.join(self.root, rel), "w") as f:
            f.write(new)

    def wait(self, seconds):
        if not self.dry:
            time.sleep(seconds)

    # --- the release ------------------------------------------------------------
    def release(self, new, date):
        branch, tag = f"release-{new}", f"v{new}"
        init, plugin, changelog = self.read(INIT), self.read(PLUGIN), self.read(CHANGELOG)
        prev = read_version(init)

        self.step("Check the repository")
        if not is_newer(new, prev):
            raise ReleaseError(f"{new} is not greater than the current version {prev}.")
        if new != next_version(prev) and not self.force_version:
            raise ReleaseError(f"The version after {prev} is {next_version(prev)}, not {new}: versions move one step "
                               "at a time (see CONTRIBUTING). Pass --force-version to release it anyway.")
        self.say(f"version: {prev} -> {new}")
        if plugin_version(plugin) != prev:
            raise ReleaseError(f"{PLUGIN} has version {plugin_version(plugin)}, {INIT} has {prev}: fix them first.")
        if not unreleased_notes(changelog):
            raise ReleaseError(f"Nothing under ## [Unreleased] in {CHANGELOG}: add the changes first.")
        new_changelog = rewrite_changelog(changelog, new, prev, date)
        current = self.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], capture=True, readonly=True)
        self.check(current == "main", f"Not on main (on {current or 'unknown'}): git switch main")
        status = self.run(["git", "status", "--porcelain"], capture=True, readonly=True)
        self.check(status == "", "The working tree has changes: commit or stash them first")
        self.run(["git", "fetch", "origin", "main"])
        head = self.run(["git", "rev-parse", "HEAD"], capture=True, readonly=True)
        remote = self.run(["git", "rev-parse", "origin/main"], capture=True, readonly=True)
        self.check(head is not None and head == remote, "main is not the same as origin/main: git pull (or push) first")
        self.run(["gh", "auth", "status"], capture=True, readonly=True)

        self.step(f"Bump the version to {new} and date the CHANGELOG section")
        self.write(INIT, init, bump_init(init, new))
        self.write(PLUGIN, plugin, bump_plugin(plugin, new))
        self.write(CHANGELOG, changelog, new_changelog)

        self.step("Open the release pull request")
        self.run(["git", "switch", "-c", branch])
        self.run(["git", "add", INIT, PLUGIN, CHANGELOG])
        self.run(["git", "commit", "-m", f"Release {new}"])
        self.run(["git", "push", "-u", "origin", branch])
        url = self.run(["gh", "pr", "create", "--base", "main", "--head", branch, "--title", f"Release {new}",
                        "--body", PR_BODY.format(v=new)], capture=True)
        number = pr_number(url) if not self.dry else "<n>"
        self.say(f"pull request: {url or '#' + str(number)}")

        self.step("Wait for the checks")
        if self.dry:  # show the fallback too
            self.checks_appear(number)
            self.say(f"  if none is listed after {CHECKS_APPEAR_TIMEOUT} s (it happens), an empty commit starts them:")
            self.run(["git", "commit", "--allow-empty", "-m", "Trigger CI"])
            self.run(["git", "push"])
        elif not self.checks_appear(number):
            self.say(f"No checks after {CHECKS_APPEAR_TIMEOUT} s: pushing an empty commit to start them")
            self.run(["git", "commit", "--allow-empty", "-m", "Trigger CI"])
            self.run(["git", "push"])
            if not self.checks_appear(number) and not self.dry:
                raise ReleaseError(f"Still no checks on pull request #{number}: look at it on GitHub.")
        self.run(["gh", "pr", "checks", str(number), "--watch", "--interval", "10"])

        self.step("Merge the pull request")
        self.run(["gh", "pr", "merge", str(number), "--squash", "--subject", f"Release {new} (#{number})", "--body", ""])
        self.run(["git", "switch", "main"])
        self.run(["git", "pull", "--ff-only", "origin", "main"])

        self.step(f"Tag {tag} and publish")
        self.run(["git", "tag", tag])
        self.run(["git", "push", "origin", tag])
        run_id = self.release_run(tag)
        self.run(["gh", "run", "watch", str(run_id), "--exit-status", "--interval", "15"])

        self.step(f"Wait for cc-profiles {new} on PyPI")
        self.wait_for_pypi(new)

        self.step("Delete the release branch")
        self.run(["git", "branch", "-D", branch])
        self.run(["git", "push", "origin", "--delete", branch], check=False)

        self.say(f"\ncc-profiles {new} is on PyPI. To upgrade:")
        self.say("  pipx upgrade cc-profiles      # or: uv tool upgrade cc-profiles")
        self.say("  cc-profiles restart           # or /cc-profiles restart in Claude Code")
        self.say("or click Check for updates in the app's About panel.")

    def checks_appear(self, number):
        """Whether GitHub reports any check on the pull request within the timeout."""
        cmd = ["gh", "pr", "checks", str(number), "--json", "name"]
        if self.dry:
            self.run(cmd, readonly=False)
            self.say(f"  (repeated every 5 s for up to {CHECKS_APPEAR_TIMEOUT} s, until a check is listed)")
            return True
        deadline = time.time() + CHECKS_APPEAR_TIMEOUT
        while time.time() < deadline:
            out = self.run(cmd, capture=True, check=False)
            try:
                if json.loads(out or "[]"):
                    return True
            except ValueError:
                pass
            time.sleep(5)
        return False

    def release_run(self, tag):
        """The id of the Release workflow run started by the tag."""
        cmd = ["gh", "run", "list", "--workflow", "release.yml", "--branch", tag, "--json", "databaseId", "--limit", "1"]
        if self.dry:
            self.run(cmd)
            self.say(f"  (repeated every 5 s for up to {RUN_APPEAR_TIMEOUT} s, until the run for {tag} is listed)")
            return "<run id>"
        deadline = time.time() + RUN_APPEAR_TIMEOUT
        while time.time() < deadline:
            out = self.run(cmd, capture=True, check=False)
            try:
                runs = json.loads(out or "[]")
            except ValueError:
                runs = []
            if runs:
                return runs[0]["databaseId"]
            time.sleep(5)
        raise ReleaseError(f"No Release workflow run for {tag} after {RUN_APPEAR_TIMEOUT} s: look at GitHub Actions.")

    def wait_for_pypi(self, new):
        self.say(f"GET {PYPI_SIMPLE} (Cache-Control: no-cache) until cc_profiles-{new}-*.whl is listed, "
                 f"every 20 s for up to {PYPI_TIMEOUT // 60} min")
        if self.dry:
            return
        deadline = time.time() + PYPI_TIMEOUT
        while True:
            try:
                req = urllib.request.Request(PYPI_SIMPLE, headers={"Cache-Control": "no-cache",
                                                                   "Accept": "text/html"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    if wheel_listed(r.read().decode("utf-8", "replace"), new):
                        self.say(f"cc-profiles {new} is on PyPI")
                        return
            except OSError as e:
                self.say(f"  ({e})")
            if time.time() > deadline:
                raise ReleaseError(f"The wheel for {new} is not on {PYPI_SIMPLE} after {PYPI_TIMEOUT // 60} min.")
            time.sleep(20)


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description="Release a new version of cc-profiles.")
    ap.add_argument("version", help='the new version, x.y.z, or "next" for the one after the current version')
    ap.add_argument("--force-version", action="store_true", help="allow a version that is not the next one")
    ap.add_argument("--dry-run", action="store_true", help="print every step and command, change nothing")
    ap.add_argument("--root", default=ROOT, help=argparse.SUPPRESS)  # tests: a copy of the release files
    ap.add_argument("--date", default=None, help=argparse.SUPPRESS)  # tests: a fixed date
    args = ap.parse_args(argv)
    date = args.date or datetime.date.today().isoformat()
    rel = Releaser(args.root, args.dry_run, out)
    if args.dry_run:
        rel.say("Dry run: nothing is changed, only read-only commands run.")
    rel.force_version = args.force_version
    try:
        version = args.version
        if version == "next":
            version = next_version(read_version(rel.read(INIT)))
            rel.say(f"next version: {version}")
        version_key(version)
        rel.release(version, date)
    except ReleaseError as e:
        print(f"\nRelease stopped: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
