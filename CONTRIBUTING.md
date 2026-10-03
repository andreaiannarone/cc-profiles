# Contributing to cc-profiles

Thanks for wanting to help! This guide covers how to run the project, how it is organized, and what a good pull request looks like.

## Ground rules

- **Never test on your real profiles.** The test suite builds a fake home for every test. When you try the app by hand, use a sandbox (see below).
- **Every write must be undoable.** If you add an operation that changes files, it must go through the `Backup` journal. The tests check this property for every operation.
- **No dependencies.** cc-profiles uses only the Python standard library, so it installs anywhere in seconds. Please keep it that way.
- **Python 3.9 compatible.** That is the version that ships with macOS. No `match` statements and no `X | None` annotations.

## Setup

```sh
git clone https://github.com/andreaiannarone/cc-profiles.git
cd cc-profiles
python3 -m venv .venv
.venv/bin/pip install -e ".[test]"
```

## Run the tests

```sh
.venv/bin/python -m pytest
```

Each test starts a real server on a temporary fake home with fake profiles, calls the API like the browser does, and in most cases ends by restoring every backup and checking that the fake home is byte-for-byte identical to how it started.

## Run the app on a sandbox

```sh
SANDBOX=$(mktemp -d)
mkdir -p "$SANDBOX/.claude" "$SANDBOX/.claude-work"
HOME="$SANDBOX" .venv/bin/cc-profiles --port 4799
```

For a sandbox with sample profiles, projects, memories and a moved folder, so every tab has something to show:

```sh
SANDBOX=$(.venv/bin/python .claude/skills/sandbox/make_home.py)
HOME="$SANDBOX" .venv/bin/cc-profiles open --port 4799
```

To try the Claude Code installer flow without installing anything:

```sh
HOME="$SANDBOX" PATH=/usr/bin:/bin CC_PROFILES_INSTALL_DRYRUN=1 .venv/bin/cc-profiles --port 4799
# CC_PROFILES_INSTALL_DRYRUN_CODE=7 simulates a failed install
```

## Project layout

```
src/cc_profiles/server.py        HTTP server and all the logic, organized in sections
src/cc_profiles/static/index.html the whole UI: one file, inline CSS and vanilla JS
tests/                           end-to-end tests on a fake home, plus documentation link checks
docs/                            user guide and developer reference (start at docs/README.md)
DESIGN.md                        the UI's visual system: read it before touching index.html
CLAUDE.md                        notes for AI coding assistants (also useful for humans)
.claude/                         Claude Code project setup: permissions, a hook, two skills (see below)
plugin/, .claude-plugin/         the Claude Code plugin and its marketplace
install.sh                       the curl | sh installer
```

### Working with Claude Code

The repository ships a `.claude/` folder for contributors who use Claude Code:

- `settings.json` pre-approves the test suite, `claude plugin validate` and read-only git commands.
- `hooks/sandbox_guard.py` blocks any command that would start cc-profiles on your real home folder: only `label`, `--version` and `--help` may run there. Use a sandbox `HOME` instead.
- `/sandbox` builds a fake home with sample data and starts the app on it.
- `/check-settings-schema` compares the Settings dropdowns with the schema in your installed Claude Code and updates them after a release.

Claude Code runs the hook only after you trust the folder. It is about 80 lines of standard-library Python: read it first if you like.

## Pull requests

1. Open an issue first for anything bigger than a small fix, so we can agree on the approach.
2. Keep each PR focused on one change.
3. Add or update tests. A new operation needs a test that runs it and then restores it.
4. Update `CHANGELOG.md` under **Unreleased**, and the relevant page in `docs/` if behavior changes.
5. Make sure `python -m pytest` passes.

## Commit messages

Use short, imperative subject lines, for example "Add Windows path handling" or "Fix restore of nested folders". Explain the *why* in the body when it is not obvious.

## Releasing (maintainers)

1. Update `__version__` in `src/cc_profiles/server.py` and move the **Unreleased** entries in `CHANGELOG.md` under the new version.
2. Commit, then tag: `git tag v0.2.0 && git push --tags`.
3. Create a GitHub release from the tag, with the changelog entries as notes.
4. Build and upload: `python -m build && python -m twine upload dist/*`.
