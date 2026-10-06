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

### Coverage

Most of the code runs inside the servers the tests start, so coverage has to follow them into those processes. `COVERAGE_PROCESS_START` does that: with it set, the tests put `tests/coverage_startup/` on the servers' `PYTHONPATH`, and its `sitecustomize.py` starts coverage in each one. The settings are in `pyproject.toml` (`[tool.coverage.*]`).

```sh
COVERAGE_PROCESS_START=pyproject.toml .venv/bin/python -m coverage run -m pytest
.venv/bin/python -m coverage combine      # one data file per process -> .coverage
.venv/bin/python -m coverage report --sort=cover
.venv/bin/python -m coverage html         # optional: htmlcov/index.html, line by line
```

The server stops on SIGTERM with `os._exit()`, which skips coverage's own save: `sitecustomize.py` saves the data just before it, so keep that hook if you change how the server exits.

CI does the same on Python 3.12, shows the table in the run's summary and **fails when the total is below 92%** (`coverage report --fail-under=92` in `.github/workflows/ci.yml`; the suite reached 93.7% without the browser smoke test, which that job does not run). New code comes with tests that keep the total above it. When the total rises well above the threshold, raise the threshold to a point or two below the new total. Do not lower it to make a change pass. `tests/test_coverage_extra.py` covers helpers and error paths that the end-to-end tests in `test_app.py` do not reach.

### How fast it is on a big home

`tests/bench_home.py` is not part of the suite. It builds a large fake home once (4 profiles, 2,000 projects, 20,000 conversations, 5,000 memories, 2,000 backups, about 550 MB), starts the app on it and times every request a tab makes when it opens:

```sh
.venv/bin/python tests/bench_home.py /tmp/cc-profiles-bench      # right after start
.venv/bin/python tests/bench_home.py /tmp/cc-profiles-bench 40   # after the startup warm-up
```

Run it before and after a change that reads many files.

### The UI's JavaScript

`python3 scripts/check_js.py` type-checks the inline scripts of `index.html` with TypeScript's `--checkJs` (it needs Node.js; `npx` fetches TypeScript the first time). It catches misspelled names and wrong calls, and runs in CI. `scripts/check_js.d.ts` tells it what `querySelector` returns; where the code needs a precise type, a JSDoc cast like `/** @type {HTMLElement} */ (e.target)` does it.

### The browser smoke test

`tests/test_ui.py` opens every tab of the real page in Chromium and fails on JavaScript errors, Content-Security-Policy violations or a tab stuck loading. It is skipped unless Playwright is installed:

```sh
.venv/bin/pip install -e ".[ui]"
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest tests/test_ui.py
```

CI always runs it (the *UI smoke test* job).

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
src/cc_profiles/                 the server: one module per area (see docs/architecture.md)
src/cc_profiles/static/index.html the whole UI: one file, inline CSS and vanilla JS
tests/                           end-to-end tests on a fake home, plus documentation link checks
docs/                            user guide and developer reference, published at cc-profiles.andreaia.com
scripts/                         release, README images, JavaScript and settings-schema checks, Homebrew formula
.github/workflows/               CI, release to PyPI, CodeQL, the weekly Claude Code schema check
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
- `/check-settings-schema` compares the Settings dropdowns with the schema in your installed Claude Code and updates them after a release. It starts from `scripts/check_settings_schema.py`, which the *Claude Code settings schema* workflow (`.github/workflows/claude-code-schema.yml`) also runs every week against the latest Claude Code, opening an issue when something differs.

Claude Code runs the hook only after you trust the folder. It is about 120 lines of standard-library Python: read it first if you like.

### README images

The screenshots, the demo GIF and the social preview in `docs/assets/` are made from the real app on the sandbox home, never by hand. After a change to the UI, regenerate them all (about 30 seconds; the GIF needs `ffmpeg`):

```sh
.venv/bin/pip install -e ".[ui]" && .venv/bin/python -m playwright install chromium
.venv/bin/python scripts/make_screenshots.py            # add --no-gif to skip the GIF
```

The social preview, `docs/assets/social-preview.png`, is rendered from `docs/assets/social-preview.html`. Upload it again under *Settings → General → Social preview* after regenerating it.

## Pull requests

1. Open an issue first for anything bigger than a small fix, so we can agree on the approach.
2. Keep each PR focused on one change.
3. Add or update tests. A new operation needs a test that runs it and then restores it.
4. Update `CHANGELOG.md` under **Unreleased**, and the relevant page in `docs/` if behavior changes.
5. Make sure `python -m pytest` passes.

## Commit messages

Use short, imperative subject lines, for example "Add Windows path handling" or "Fix restore of nested folders". Explain the *why* in the body when it is not obvious.

## Releasing (maintainers)

With the changes listed under **Unreleased** in `CHANGELOG.md`, on an up-to-date `main`:

```sh
.venv/bin/python scripts/release.py next --dry-run   # prints every step and command, changes nothing
.venv/bin/python scripts/release.py next             # or the version itself, e.g. 0.4.4
```

**Version numbers move one step at a time**: only the last number goes up, to 9, then the one before it (0.4.8 → 0.4.9 → 0.5.0; 0.9.9 → 1.0.0). `next` picks that version; any other number is refused unless you add `--force-version`.

It needs `git`, and `gh` logged in to GitHub, and takes 5 to 15 minutes. Step by step:

1. **Checks**: on `main`, a clean tree, the same commit as `origin/main`, the next version after `__version__`, something under `## [Unreleased]`.
2. **Bump**: `__version__` in `src/cc_profiles/__init__.py` and `version` in `plugin/.claude-plugin/plugin.json`; in `CHANGELOG.md` a `## [x.y.z] - date` heading goes under `## [Unreleased]` (which stays, empty), and the compare links at the bottom are updated. Older entries are not touched.
3. **Pull request**: branch `release-x.y.z`, commit `Release x.y.z`, `gh pr create`. If GitHub reports no checks after a minute (it happens), it pushes an empty `Trigger CI` commit. It waits for every check and stops if one fails.
4. **Merge and tag**: squash merge as `Release x.y.z (#n)`, pull `main`, tag `vx.y.z` and push the tag.
5. **Publish**: it waits for the **Release** workflow (`.github/workflows/release.yml`), which checks that the tag matches `__version__`, runs the tests, builds the package, publishes it on PyPI and creates the GitHub release with the changelog section as notes. Then it waits, up to 15 minutes, until the wheel is in PyPI's download index (`/simple/`), which lags a few minutes behind the JSON API the app's update check reads.
6. **Clean up**: deletes the release branch, locally and on GitHub, and prints how to upgrade.

If it stops halfway, it says why: carry on by hand from that step. Nothing it writes carries an attribution line.

PyPI accepts the upload through *trusted publishing*: no token is stored in the repository. It was set up once on pypi.org for the project `cc-profiles`, owner `andreaiannarone`, repository `cc-profiles`, workflow `release.yml`, environment `pypi`.

### Homebrew and the documentation site

- **Homebrew** (not published yet): `python3 scripts/homebrew_formula.py <version>` prints a formula for a release on PyPI, ready for a tap repository once there is one.
- **Documentation site**: GitHub Pages publishes `docs/` from `main` with Jekyll (`docs/_config.yml`): `README.md` is the home page and links between `.md` files become pages. Link files outside `docs/` with their full GitHub URL, or they break on the site.
