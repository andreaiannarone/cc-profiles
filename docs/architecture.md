# Architecture

cc-profiles is two files and a test suite, on purpose: no framework, no build step, no dependencies.

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
| `core.py` | paths and constants, `san()`, atomic `write_text()`, config loading and first-run detection, `Backup` and failed-operation handling, tool lookup, settings files, running sessions |
| `paths.py` | rules, `path_index()` (folder name → real path), `resolve_on_disk()` |
| `projects.py` | list, move (with preview), relink, delete, rules |
| `memories.py` | list, read, save, move, delete |
| `sharing.py` | symlinks to the source profile |
| `settings.py` | schema-checked fields (`SETTING_FIELDS`, `SCHEMA_VERSION`), permissions, raw JSON, `CLAUDE.md` |
| `health.py` | profile summaries, candidate folders, health checks |
| `backups.py` | list, restore (journal replayed backwards), delete, prune |
| `info.py` | the About panel |
| `extensions.py` | skills and MCP servers |
| `conversations.py` | list, view, move one, delete |
| `search.py` | global search and profile comparison (read-only) |
| `command.py` | the `/cc-profiles` command file |
| `launchers.py` | `~/.local/bin` scripts and legacy shell aliases |
| `newprofile.py` | copy or create, never copying credentials |
| `transfer.py` | export and import of a profile as a `.zip` |
| `plugins.py` | installed plugins, enable and disable |
| `editprofile.py` | rename, change command, delete with optional merge |
| `installer.py` | official Claude Code install methods, background job with live log |
| `updater.py` | check for updates on PyPI, update and restart |
| `web.py` | routing, error handling, the security guard, the Content-Security-Policy |
| `cli.py` | `serve`, `open`, `install-command`, `label`, argument parsing |

`server.py` re-exports every public name, so `from cc_profiles import server` and the `cc-profiles` console script keep working. The version lives in `__init__.py`. `PORT` and `ALLOWED_HOSTS` are set when the server starts: other modules read them as `core.PORT` and `core.ALLOWED_HOSTS`, never as names imported at load time.

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

Claude Code names project folders with `san(path)`, which loses information (`/`, ` `, `.` and `+` all become `-`). `path_index()` builds the reverse map from every path mentioned anywhere: the `projects` key of each `.claude.json`, the `project` field of history lines, and the `cwd` of the first lines of each conversation. For names nothing mentions, `resolve_on_disk()` walks from `/` and, at each level, tries entries whose sanitized name is a prefix of what is left, longest first.

## The UI: `src/cc_profiles/static/index.html`

One file: CSS custom properties for both themes, semantic HTML, and vanilla JavaScript.

- A single state object `S` holds the current tab, data and filters.
- Each tab has a `load…()` function, which fetches, and a `render…()` function, which writes `#main.innerHTML` from `S`.
- All user data goes through `esc()` before entering HTML.
- One delegated `click` listener on `document` dispatches on `data-*` attributes.
- `modal()` returns a promise with the chosen action, which keeps confirmation flows linear with `await`.
- `api()` adds the token and turns errors into exceptions; `run()` shows the resulting toast.

The visual rules are in [DESIGN.md](../DESIGN.md).

## Security model

The threat is another program or website reaching the local server, not the user. Hence:

- binding to `127.0.0.1` only;
- an exact `Host` check, because DNS rebinding can make a remote name resolve to `127.0.0.1`;
- a per-run token that only the served page knows. No CORS headers are sent, so another origin cannot read the page to steal it;
- strict validation of every name coming from the client, and installer methods chosen from a fixed list.

## Tests

`tests/conftest.py` builds a fake `HOME` with fake profiles (`FakeHome`) and starts the real server on it as a subprocess (`App`), with a `PATH` that contains no `claude`, `brew` or `npm`. Tests call the API exactly like the UI, then usually restore every backup and compare a snapshot of the fake home (every file's hash, every link's target, every folder) with the one taken before.
