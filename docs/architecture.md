# Architecture

cc-profiles is a small Python package (one module per area), one HTML file for the UI and a test suite, on purpose: no framework, no build step, no dependencies.

```
browser ──HTTP (token)──► cc_profiles ──reads/writes──► ~/.claude*, ~/.claude.json
   ▲                          │
   └──── index.html ◄─────────┘        ~/.cc-profiles/{config.json, backups/}
```

## The server: `src/cc_profiles/`

A `ThreadingHTTPServer` from the standard library, bound to `127.0.0.1`. `GET /` serves `static/index.html` with a fresh token inside. Everything else is a JSON API under `/api/` (see [API](api.md)).

The code is one module per area. Each module imports only from the ones above it in this table, so there are no import cycles:

| Module | Responsibility |
|---|---|
| `byfolder.py` | rule matching (`match_rule()`, `san()`), `cc-profiles which` and `shell-init`. Imports nothing from the package, so `which` starts fast on every `claude` launch |
| `core.py` | paths and constants, `san()`, atomic `write_text()`, `cached_read()`, config loading and first-run detection, `Backup` and failed-operation handling, tool lookup, settings files, running sessions |
| `paths.py` | rules, `path_index()` (folder name → real path), `resolve_on_disk()` |
| `projects.py` | list, move (with preview), relink, delete, rules |
| `memories.py` | list, read, save, move, delete |
| `sharing.py` | symlinks to the source profile, with a preview |
| `settings.py` | schema-checked fields (`SETTING_FIELDS`, `SCHEMA_VERSION`), permissions, raw JSON, `CLAUDE.md`; a value or a rule applied to every profile |
| `health.py` | profile summaries, candidate folders, health checks |
| `backups.py` | list, restore (journal replayed backwards), delete, prune, automatic cleanup (`backup_keep_days`) |
| `info.py` | the About panel |
| `extensions.py` | skills and MCP servers, copied to one profile or to all |
| `conversations.py` | list, view, move one, delete |
| `usage.py` | tokens and estimated cost per day, project, model and profile, from the usage of every reply (read-only); the list-price table |
| `search.py` | global search and profile comparison (read-only) |
| `command.py` | the `/cc-profiles` command file |
| `launchers.py` | `~/.local/bin` scripts, legacy shell aliases, and the profile by folder line in the shell rc files |
| `newprofile.py` | copy or create, never copying credentials |
| `transfer.py` | export and import of a profile as a `.zip` |
| `templates.py` | profile templates: an export without projects in `~/.cc-profiles/templates/`, used to create new profiles |
| `plugins.py` | installed plugins, enable and disable |
| `editprofile.py` | rename, change command, delete with optional merge, with a preview |
| `installer.py` | official Claude Code install methods, background job with live log |
| `updater.py` | check for updates on PyPI, update and restart |
| `web.py` | routing, error handling, the security guard, the Content-Security-Policy |
| `cli.py` | `serve` (with the automatic backup cleanup at start and daily), `open`, `stop`, `restart`, `install-command`, `label`, argument parsing |
| `entry.py` | the console script: `which` and `shell-init` go to `byfolder.py` without loading the server, everything else to `cli.main` |

`server.py` re-exports every public name, so `from cc_profiles import server` keeps working; the `cc-profiles` console script is `entry.main`. The version lives in `__init__.py`. `PORT` and `ALLOWED_HOSTS` are set when the server starts: other modules read them as `core.PORT` and `core.ALLOWED_HOSTS`, never as names imported at load time.

### Request flow

1. `_guard()` checks the `Host` header and, for `/api/`, the `X-Token` header.
2. A routing table maps the path to a function. GET handlers only read.
3. POST handlers run under a global lock, so writes never interleave.
4. Errors raised as `ApiError` become `{"error": "..."}` with their status code; anything unexpected becomes a 500 with the exception text, which the UI shows in a toast.

### The backup journal

The `Backup` class is the heart of the safety model. An operation opens a backup, records each step **as it does it**, and closes it:

```python
bk = Backup("move-a-b", "Move ~/code/api: A → B")
bk.copy(history_file)          # before modifying it
write_text(history_file, ...)
shutil.move(src, dst)
bk.moved(src, dst)             # right after moving
return {"message": "...", "backup": bk.close()}
```

`op_restore()` replays the journal backwards. Two details matter:

- `bk.copy()` keeps only the *first* copy of a path, the true original. A later copy would capture an intermediate state.
- `bk.copy()` and `write_text()` resolve symlinks, so shared files are written and restored in place without replacing the link.

### Atomic writes

`write_text()` writes a temporary file in the same folder and renames it over the target with `os.replace`. On the same file system the rename is atomic: Claude Code, which reads `.claude.json` and `history.jsonl` all the time, sees either the old file or the new one.

### Path resolution

Claude Code names project folders with `san(path)`, which loses information (`/`, ` `, `.` and `+` all become `-`). `path_index()` builds the reverse map from the paths the profiles mention: first the `projects` key of each `.claude.json` and the `project` field of history lines; then, only for folders still without an existing path, the `cwd` of the first lines of their conversations. For names nothing mentions, `resolve_on_disk()` walks from `/` and, at each level, tries entries whose sanitized name is a prefix of what is left, longest first.

### Caches

A large home has tens of thousands of conversation files, so listings keep what they read. Every cache is read-only and lives in the server process; none is written to disk.

| Cache | Where | Keyed on |
|---|---|---|
| `cached_read(kind, path, compute)`: the parsed content of a file or the listing of a folder | `core._file_cache` | the file's or folder's `(mtime_ns, size, inode)`, checked with a fresh `stat()` on every use |
| `load_config()` | `core._file_cache` | `config.json`'s stat; callers get a deep copy |
| Conversation and memory file names of each project folder (`project_folders()`, `memory_files()`) | `core._file_cache` | the folder's stat (adding, removing or renaming an entry changes its mtime) |
| Token usage of a conversation file (one record per reply), for the Usage tab | `core._file_cache` | the file's stat |
| `cwd`s of a conversation, projects of `.claude.json`, history summary (prompts, broken lines, projects), `MEMORY.md`, memory and skill text for search, backup manifests | `core._file_cache` | the file's stat |
| Size of a closed backup | `core._file_cache` | the backup folder's stat (only its manifest is ever rewritten, by `os.replace`) |
| Size of a profile folder (About) | `backups._size_cache` | time: 60 s |
| Folders under the search roots, by name (Health, relink candidates) | `health._cand_cache` | time: 60 s, and the search roots |
| Running `claude` processes | `core._running` | time: 3 s |

Rules that keep this safe:

- A cache keyed on a stat is as current as a new read: a changed file is read again in the same request. Time-keyed caches only serve numbers and suggestions on screen.
- Before a write, code reads afresh: `history_lines()` (never cached) for history rewrites, `memory_files(d, fresh=True)` before deleting a folder, `read_json()` for manifests being restored.
- At startup, `cli.warm_caches()` fills the caches in a background thread (projects, backups, profile sizes, search texts, token usage), so the first tabs open fast. It only reads.

`tests/bench_home.py` times every tab on a large fake home (see CONTRIBUTING).

## The UI: `src/cc_profiles/static/index.html`

One file: CSS custom properties for both themes, semantic HTML, and vanilla JavaScript.

- A single state object `S` holds the current tab, data and filters.
- Each tab has a `load…()` function, which fetches, and a `render…()` function, which writes `#main.innerHTML` from `S`.
- All user data goes through `esc()` before entering HTML.
- One delegated `click` listener on `document` dispatches on `data-*` attributes.
- `modal()` returns a promise with the chosen action, which keeps confirmation flows linear with `await`.
- `api()` adds the token and turns errors into exceptions; `run()` shows the resulting toast.

The visual rules are in [DESIGN.md](https://github.com/andreaiannarone/cc-profiles/blob/main/DESIGN.md).

## Security model

The threat is another program or website reaching the local server, not the user. Hence:

- binding to `127.0.0.1` only;
- an exact `Host` check, because DNS rebinding can make a remote name resolve to `127.0.0.1`;
- a per-run token that only the served page knows. No CORS headers are sent, so another origin cannot read the page to steal it;
- strict validation of every name coming from the client, and installer methods chosen from a fixed list.

## Tests

`tests/conftest.py` builds a fake `HOME` with fake profiles (`FakeHome`) and starts the real server on it as a subprocess (`App`), with a `PATH` that contains no `claude`, `brew` or `npm`. Tests call the API exactly like the UI, then usually restore every backup and compare a snapshot of the fake home (every file's hash, every link's target, every folder) with the one taken before.
