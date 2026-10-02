# HTTP API

The UI talks to the server through a small JSON API. It is an internal API, made for `index.html`, and may change between versions. It is documented to make contributing easier.

## Conventions

- Base URL `http://127.0.0.1:<port>`.
- Every `/api/` request needs the header `X-Token: <token>`. The token is generated at each start and embedded in the page served at `/`.
- The `Host` header must be `127.0.0.1:<port>` or `localhost:<port>`.
- GET requests only read. POST requests take a JSON body and run one at a time.
- Errors return a non-2xx status and `{"error": "message"}`.
- Write operations return `{"message": "...", "backup": "~/.cc-profiles/backups/…"}`.
- `profile` is a profile `id`; `project` is a folder name under `projects/` (for example `-Users-me-code-api`).

## Read

| Endpoint | Parameters | Returns |
|---|---|---|
| `GET /api/profiles` | | profiles with label, command, folder, email, counts, `primary`, `active` |
| `GET /api/projects` | | every project: real path, `exists`, expected profile, per-profile counts, `issues` |
| `GET /api/candidates` | `name` | up to 10 folders with that name under the search roots |
| `GET /api/memory/projects` | `profile` | the profile's projects with memory and conversation counts |
| `GET /api/memory/list` | `profile`, `project` | memories with name, type, description, `indexed`; `missing` index entries |
| `GET /api/memory/file` | `profile`, `project`, `file` | `{content}` |
| `GET /api/sharing` | | for each secondary profile, the state of every shareable item |
| `GET /api/settings` | `profile` | settings fields (value, source, options, other profiles), permissions, `CLAUDE.md`, raw files, global info |
| `GET /api/backups` | | backups, newest first, with title, size, steps, `restorable` |
| `GET /api/health` | | checks and orphan projects for every profile (runs `claude auth status`) |
| `GET /api/about` | | Claude Code, per-profile account/usage/contents, app info |
| `GET /api/claude/status` | | whether Claude Code is installed, install methods, install job state |

Issue kinds in `/api/projects`: `orphan` (folder gone), `profile` (content in a profile it does not belong to; includes `from` and `to`), `unclassified` (no rule matches).

## Write

| Endpoint | Body |
|---|---|
| `POST /api/projects/move` | `project`, `from`, `to` |
| `POST /api/projects/relink` | `project`, `profile`, `path` |
| `POST /api/projects/delete` | `project`, `profile` |
| `POST /api/rules` | `match`, `profile` (an id or `shared`) |
| `POST /api/memory/save` | `profile`, `project`, `file`, `content` |
| `POST /api/memory/move` | `profile`, `project`, `file`, `to_profile`, `to_project` |
| `POST /api/memory/delete` | `profile`, `project`, `file` |
| `POST /api/sharing` | `profile`, `item`, `shared` (bool) |
| `POST /api/settings/field` | `profile`, `key`, `value` (`null` removes the setting) |
| `POST /api/settings/permissions` | `profile`, `rules: {allow, ask, deny}` (lists of strings) |
| `POST /api/settings/raw` | `profile`, `file` (`settings` or `local`), `content` (JSON text) |
| `POST /api/settings/claude-md` | `profile`, `content` |
| `POST /api/settings/global` | `profile`, `key` (`autoUpdates`), `value` (bool) |
| `POST /api/profiles/create` | `label`, `id`, `base` (profile id or empty), `include_projects`, `share` (list) |
| `POST /api/profiles/update` | `id`, `label`, `command` |
| `POST /api/profiles/delete` | `id`, `merge_into` (optional), `force` (skip the open-session check) |
| `POST /api/backups/restore` | `name` |
| `POST /api/backups/delete` | `name` |
| `POST /api/claude/install` | `method` (`native`, `brew`, `brew-latest`, `npm`) |

## Example

```sh
PORT=4777
TOKEN=$(curl -s http://127.0.0.1:$PORT/ | grep -o 'const TOKEN = "[a-f0-9]*"' | cut -d'"' -f2)
curl -s -H "X-Token: $TOKEN" http://127.0.0.1:$PORT/api/profiles
```
