# CLAUDE.md

Notes for AI coding assistants (and humans) working on this repository.

## What this is

**cc-profiles** is a local web UI to manage multiple Claude Code profiles: folders like `~/.claude` and `~/.claude-<id>`, selected with `CLAUDE_CONFIG_DIR`. It moves projects between profiles, relinks projects whose folder moved, edits memories and settings, shares skills and plugins, creates and deletes profiles, and can undo every one of these operations.

The app **modifies Claude Code's own files, possibly while a session is using them**. Every change must therefore be reversible and safe for concurrent readers. That constraint drives everything else.

## Layout

| Path | Role |
|---|---|
| `src/cc_profiles/` | the server, one module per area (`core`, `projects`, `memories`, `extensions`, `backups`, …, `web` for HTTP, `cli`); see the table in `docs/architecture.md`. `server.py` only re-exports them; the version is in `__init__.py` |
| `src/cc_profiles/static/index.html` | the whole UI: one file, inline CSS and vanilla JS, no build step |
| `tests/conftest.py` | `FakeHome` (builds fake profiles) and `App` (a real server on it, plus an API client) |
| `tests/test_app.py` | end-to-end tests |
| `DESIGN.md` | the UI's visual system: read it before touching `index.html` |
| `.claude-plugin/marketplace.json` | makes the repo a Claude Code plugin marketplace |
| `plugin/` | the Claude Code plugin: `commands/open.md` runs `cc-profiles open`. Same text as `COMMAND_TEXT` in `command.py` without the mark (a test checks it). Check it with `claude plugin validate .` and `claude plugin validate plugin` |
| `.claude/` | Claude Code project setup: `settings.json` (permissions, hook), `hooks/sandbox_guard.py` (blocks cc-profiles on the real home), skills `sandbox` (fake home + app on port 4799) and `check-settings-schema` |
| `install.sh` | `curl … \| sh` installer: pipx or uv, then `cc-profiles install-command`. POSIX `sh`, no `sudo`. Test it with `HOME=<sandbox> CC_PROFILES_SOURCE=$PWD sh install.sh` |
| `docs/assets/` | the logo (`logo.svg`), the two mascots alone (`logo-mark.svg`, inlined next to the title in `index.html`) and one mascot (`favicon.svg`, inlined as the favicon) |

User data, **never in the repo**: `~/.cc-profiles/config.json` (profiles, rules, search roots) and `~/.cc-profiles/backups/`.

## Commands

```sh
.venv/bin/pip install -e ".[test]"     # once
.venv/bin/python -m pytest             # all tests (about 10 s)
.venv/bin/cc-profiles --port 4799      # run the app (use HOME=<sandbox> unless you mean it)
```

Only ever run write operations against a sandbox `HOME`, never against real profiles. The `sandbox_guard.py` hook blocks starting the app without one; the `/sandbox` skill builds one with sample data.

## Hard rules

- **Standard library only, Python 3.9 compatible**: no `match`, no `X | None` annotations, no new dependencies.
- **Atomic writes**: always `write_text()` / `write_json()` (temp file in the same folder, then `os.replace`). They follow symlinks with `os.path.realpath`. Without that, `os.replace` would replace a shared file's link with a regular file and silently break sharing.
- **Every write goes through `Backup`**, which journals its steps in `manifest.json`:
  - `bk.copy(path)` **before** modifying a file (it records `absent` if the file did not exist). Only the first copy of a path counts.
  - `bk.stash(path)` instead of deleting anything.
  - `bk.moved(src, dst)` after every `shutil.move`.
  - `bk.mkdir(path)` to create folders (it journals every missing parent); `bk.created(path)` for new links, launchers and profiles.
  - `bk.close()` at the end; return its value in the `backup` field of the response.

  Journal a new folder (`bk.created`) before filling it. If an operation raises, the POST handler closes its open backups as "failed" (`abort_open_backups`), so whatever was journaled can still be restored; `CC_PROFILES_FAULT=<name>` makes `fault_point(name)` raise in tests.

  A step that is not journaled makes the operation impossible to undo. The tests catch it: they restore everything and compare snapshots of the fake home.
- **One write at a time**: POST handlers run under `_lock`.
- **Never trust the client**: project, memory and backup names go through `project_dir()`, `memory_path()` and `backup_path()`, which reject `/`, `..` and empty names. The installer accepts only a method id from `INSTALL_METHODS`, never a command.
- **Local security**: listen on `127.0.0.1` only. `_guard()` checks the `Host` header (against DNS rebinding) and the `X-Token` header on every `/api/` call (against cross-site requests). Do not relax these checks and do not add CORS headers.
- **Never copy login credentials** between profiles (`.credentials.json`, `oauthAccount`). A copied token can be invalidated when the original profile refreshes it.

## Claude Code's on-disk formats (undocumented, may change)

- **Project folders**: `projects/<name>`, where `<name>` is the absolute path with every non-alphanumeric character replaced by `-` (`san()`). This is **not reversible**: `path_index()` recovers the real path from config files, prompt history and the `cwd` field of conversations, and `resolve_on_disk()` rebuilds it by walking the disk when nothing mentions it.
- **Conversations**: `projects/<name>/<sessionId>.jsonl`. File snapshots live in `file-history/<sessionId>/`, outside `projects/`, so they must move together with the conversation.
- **Prompt history** (arrow up in Claude Code): `history.jsonl`, one JSON line per prompt with `display`, `timestamp` and `project`.
- **Per-project settings**: the `projects` key of `.claude.json`. For the default profile this file is `~/.claude.json`, outside `~/.claude`; for other profiles it is `<dir>/.claude.json`.
- **Memories**: `projects/<name>/memory/*.md` with frontmatter (`name`, `description`, `metadata.type`), plus a `MEMORY.md` index with one `- [Title](file.md) — description` line per memory.
- **Settings precedence**: `settings.local.json` wins over `settings.json`. `effective()` finds where a value lives, and writes go to that file.
- **Settings schema**: dropdown options in `SETTING_FIELDS` come from the schema inside the Claude Code binary (`SCHEMA_VERSION`); the `/check-settings-schema` skill walks through the check. To check them after a Claude Code update, run `strings -n 6 "$(readlink -f "$(which claude)")"` and search for `<key>:()=>`. For example `effortLevel:()=>B(["low",…])` is an enum, while `o()` means any string, which gets a free text field. Lists referenced by name, like `B(vZe)`, are defined elsewhere as `vZe=[…]`. Always keep a current value that is not in the list as an option; never drop it.
- **Sharing**: relative symlinks (`../.claude/skills`) to the first profile in `config.json`, the source. Never chain links through secondary profiles.
- **Installer**: the commands in `INSTALL_METHODS` come from the official docs (code.claude.com/docs/en/setup). For tests, `CC_PROFILES_INSTALL_DRYRUN=1` (plus `CC_PROFILES_INSTALL_DRYRUN_CODE=7` to simulate a failure) runs `echo` instead of installing.
- **Self-update**: only on click. `UPDATE_COMMANDS` holds the fixed pipx and uv commands; `install_kind()` picks one from where the code runs (`/pipx/venvs/`, `/uv/tools/`, or `source`); after a successful update `restart_soon()` re-executes the server on the same port. For tests, `CC_PROFILES_PYPI_URL` points the check to a `file://` JSON and `CC_PROFILES_UPDATE_DRYRUN=1` skips the update.

## Known gotchas

- Backups must be listed and restored by their `created` timestamp, not by name: names only have seconds, and operations in the same second depend on each other.
- A `projects/` folder may hold only memories and no conversation: "no conversations" does not mean "empty".
- `settings.local.json` and `plugins/installed_plugins.json` contain absolute paths to the profile folder. When copying a profile, rewrite them unless that part is shared.
- External programs (`claude`, `brew`, `npm`, `node`) are looked up with `find_tool()`, which adds `~/.local/bin`, `/opt/homebrew/bin` and `/usr/local/bin` to `PATH`. The app may have been started from a terminal that does not have them yet.
- New profiles get a launcher in `~/.local/bin` marked with `LAUNCHER_MARK`. Only files with that mark may be rewritten or removed. The same goes for `commands/cc-profiles.md` and `COMMAND_MARK`. Aliases from older setups in `~/.zshrc`, `~/.bashrc` and `~/.bash_profile` are handled by `rewrite_alias()`, which touches only the alias line and the `# Claude Code:` comment above it.

- Listings reuse file contents through `cached_read()`, keyed on each file's stat (see `docs/architecture.md`, Caches). Before a write, read afresh (`history_lines()`, `memory_files(d, fresh=True)`, `read_json()`): never decide a write on a time-keyed cache.

## Style

- UI text, messages and comments in English. Sentence case, buttons named after their action, concrete numbers. See `DESIGN.md`.
- Error messages say what happened and what to do, e.g. `ApiError("Folder does not exist: …")`.
- Add code to the right module and follow the existing patterns. A module imports only from the modules above it in `docs/architecture.md`: if two areas need the same helper, move it down (usually into `core.py`) instead of creating a cycle. Read `core.PORT` and `core.ALLOWED_HOSTS` through `core`, never by name.
