# Architecture

cc-profiles is two files and a test suite, on purpose: no framework, no build step, no dependencies.

```
browser ──HTTP (token)──► server.py ──reads/writes──► ~/.claude*, ~/.claude.json
   ▲                          │
   └──── index.html ◄─────────┘        ~/.cc-profiles/{config.json, backups/}
```

## The server: `src/cc_profiles/server.py`

A `ThreadingHTTPServer` from the standard library, bound to `127.0.0.1`. `GET /` serves `static/index.html` with a fresh token inside. Everything else is a JSON API under `/api/` (see [API](api.md)).

The file is organized in sections, top to bottom:

| Section | Responsibility |
|---|---|
| Basics | paths, `san()`, atomic `write_text()`, config loading and first-run detection, `Backup` |
| Classification and path resolution | rules, `path_index()` (folder name → real path), `resolve_on_disk()` |
| Projects | list, move, relink, delete, rules |
| Memories | list, read, save, move, delete |
| Profiles and health | profile summaries, candidate folders, health checks |
| Backups and restore | list, restore (journal replayed backwards), delete |
| Sharing | symlinks to the source profile |
| Launchers | `~/.local/bin` scripts and legacy shell aliases |
| New profile | copy or create, never copying credentials |
| Claude Code settings | schema-checked fields, permissions, raw JSON, `CLAUDE.md` |
| Edit and delete profiles | rename, change command, delete with optional merge |
| Claude Code information | the About panel |
| Installing Claude Code | official install methods, background job with live log |
| HTTP | routing, error handling, the security guard |
| Command line | `serve`, `label`, argument parsing |

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
