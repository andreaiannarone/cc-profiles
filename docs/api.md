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
| `GET /api/profiles` | | profiles with label, command, folder, email, `github` (the active GitHub account), counts, `primary`, `active` |
| `GET /api/projects` | | every project: real path, `exists`, expected profile, per-profile counts, `issues` |
| `GET /api/candidates` | `name` | up to 10 folders with that name under the search roots |
| `GET /api/memory/projects` | `profile` | the profile's projects with memory and conversation counts |
| `GET /api/memory/list` | `profile`, `project` | memories with name, type, description, `indexed`; `missing` index entries |
| `GET /api/memory/file` | `profile`, `project`, `file` | `{content}` |
| `GET /api/conversations/projects` | `profile` | the profile's projects that have conversations, with `count` |
| `GET /api/conversations` | `profile`, `project` | `{conversations: [{session, title, prompts, replies, first, last, mtime, size, snapshots}], path}`, newest first |
| `GET /api/conversations/view` | `profile`, `project`, `session` | `{messages: [{role, time, text}], truncated, total}`: prompts, replies and one line per tool call; the last 300 |
| `GET /api/usage` | `profile` (`all` or an id, default `all`), `days` (`7`, `14`, `30` or `90`, default `30`) | `{profile, days, start, end, currency, prices_checked, prices, totals, daily, projects, projects_count, models, profiles}`. Every total has `input`, `output`, `cache_write`, `cache_read`, `tokens`, `replies`, `cost` (estimated USD at list price) and `unpriced_tokens` (tokens of models without a price); `totals` adds `cache_read_share`. `daily` has one entry per day of the period, zeros included, with `date` (local); `projects` the top 10 with `profile`, `name`, `pretty`; `models` has `model` and `family` (`null` without a price); `profiles` only with `all`; `sessions` the 10 conversations with the highest cost, then the most tokens, with `profile`, `project`, `pretty`, `session`, `title`, `exists` (the main conversation file is there), `date` and `last` of the last reply. A reply counts once per message and request id. Read-only |
| `GET /api/usage.csv` | the same as `/api/usage` | a `text/csv; charset=utf-8` download, `cc-profiles-usage-<profile>-<days>d.csv`: one row per day and model with `date`, `model`, `input_tokens`, `output_tokens`, `cache_write_tokens`, `cache_read_tokens`, `replies`, `estimated_cost_usd` (empty without a list price). Needs the `X-Token` header like every API call. Read-only |
| `GET /api/skills` | `profile` | `{skills: [{name, title, description, files, linked}], dir, shared}` |
| `GET /api/skills/file` | `profile`, `name` | `{content}` of `SKILL.md` and the other `files` in the folder |
| `GET /api/mcp` | `profile` | `{servers: [{name, scope, type, target, env, headers}], config, projects}`; `env` and `headers` list names only |
| `GET /api/connectors` | `profile` | `{connectors: [{name, rule, blocked, where, seen, on_account}], all_off, url, check, errors}`: the claude.ai connectors of the profile. `rule` is the deny rule for the whole connector, `where` the settings files that have it, `seen` whether it is in `claudeAiMcpEverConnected`, `on_account` what the last check found (`null` before one); `all_off` lists the files with `disableClaudeAiConnectors: true` |
| `GET /api/connectors/check` | `profile`, `force` (`1` to ask again within the hour) | `{skipped, gone, error}`: runs `claude mcp list` in the profile (at most once an hour) to learn the account's connectors; `gone` are the ones in the profile's list that the account no longer has. Skipped without Claude Code, without a sign-in, or with every connector off. Changes nothing |
| `GET /api/github` | | `{gh, git_uses_gh, accounts, profiles: [{id, label, dir, user, users, set_up, shared, default, name, email}], account_list: [{user, folders, used_by, insecure}], accounts_dir}`: each profile's GitHub CLI folder and active account, its commit identity, and every account signed in on the computer. Only user names are read from `hosts.yml`, never a token |
| `GET /api/mcp/server` | `profile`, `scope` (`user` or a project path), `name` | `{config}`: the full server entry, values included |
| `GET /api/sharing` | | for each secondary profile, the state of every shareable item |
| `GET /api/plugins` | `profile` | `{plugins: [{name, plugin, marketplace, version, installed, path, is_installed, scopes, projects, enabled, source}], marketplaces, dir, shared}` |
| `GET /api/profiles/export` | `id`, `projects` (`1` to include conversations) | a `.zip` download (not JSON): `profile/…`, `claude.json`, `home-memory/…`, `cc-profiles-export.json`; never login credentials |
| `GET /api/settings` | `profile` | settings fields (value, source, options, other profiles), permissions, `CLAUDE.md`, raw files, global info |
| `GET /api/projects/move/preview` | `project`, `from`, `to` | `{items: [{action, item, from, to}], prompts, settings, history, config}`: what a move would do; `action` is `move`, `merge` or `conflict`. Changes nothing |
| `GET /api/profiles/delete/preview` | `id`, `merge_into` (optional) | `{items: [{action, item, from, to}], projects, conversations, memories, prompts, settings, active, folder, config, into}`: what deleting would do; `action` is `move`, `merge`, `conflict`, `stash` (goes to the backup) or `edit` (a line or entry removed from a file). Changes nothing |
| `GET /api/sharing/preview` | `profile`, `item`, `shared` (`1` to share, `0` to separate) | `{items: [{action, item, from, to}], source, profile, only_own}`; `action` is `create` (made empty in the source), `stash`, `only-here` (only the own copy has it), `link` or `copy`. Changes nothing |
| `GET /api/settings/field/all/preview` | `profile`, `key` | `{key, label, value, shown, from, apply: [{id, label, detail}], skip: [{id, label, reason}]}`: which profiles applying the value would change |
| `GET /api/statusline` | `profile` | `{value, source, mode: off\|builtin\|custom, parts, separator, colors, limits, script, script_is_other, jq, separators, brackets, parts_available}`; `limits` is `used` or `left`, and the limit pieces of `parts_available` also have a `sample_left` |
| `GET /api/statusline/preview` | `profile`, `parts` (comma-separated `id:brackets`), `separator`, `colors` (`1` or `0`), `limits` (`used` or `left`) | `{text, script}`: what the built-in script prints on sample data (its own sample conversation, never a file of yours), and the script |
| `GET /api/statusline/all/preview` | `profile` | `{from, mode, apply, skip}` |
| `GET /api/settings/permissions/all/preview` | `list` (`allow`, `ask`, `deny`), `rule` | `{list, rule, apply, skip}` |
| `GET /api/skills/copy-all/preview` | `profile`, `name` | `{name, from, apply, skip}` |
| `GET /api/mcp/copy-all/preview` | `profile`, `scope`, `name` | `{name, from, apply, skip}` |
| `GET /api/templates` | | `{templates: [{name, from, created, items, skills, mcp, counts, size}], dir}`; `counts`: entries per shareable item the template holds, e.g. `{skills: 3, "CLAUDE.md": 1}` |
| `GET /api/backups` | | backups, newest first, with title, size, steps, `restorable` |
| `GET /api/backups/changes` | `name` | `{name, title, created, log, failed, restored, steps, files_changed, max_lines, max_bytes}`: each journal step with `op`, `text` (in plain words), `path`, `to` (moves), `now` (`file`, `folder`, `link` or `null`); `copy` steps add `diff` with `status` (`changed`, `same`, `hidden-only`, `secret`, `too-big`, `binary`, `dir`, `unavailable`), `lines` (unified diff, the backup copy against the file now, at most 2,000 lines), `added`, `removed`, `truncated`, `notes`. JSON is compared with sorted keys and secrets masked; `.credentials.json` is never read. Read-only |
| `GET /api/backups/auto` | | `{days, default, choices, last, message, config}`: the automatic cleanup setting (90 days when unset; it cannot be off) and its last run |
| `GET /api/search` | `q` (2 characters or more) | `{q, results: {projects, memories, skills, mcp, claude_md}, counts, truncated}`; each result has `kind`, `profile`, `title`, `snippet {text, at, len}` and `open` (what to open). Never includes MCP env or header values |
| `GET /api/compare` | `a`, `b` (profile ids) | `{a, b, settings, permissions: {a, b, diff}, skills, mcp, claude_md, plugins}`: differences between two profiles, read-only |
| `GET /api/health` | | checks and orphan projects for every profile (runs `claude auth status`) |
| `GET /api/about` | | Claude Code, per-profile account/usage/contents, app info |
| `GET /api/update` | | `{current, latest, newer, kind, command, can_update, manual}`: asks PyPI, only when called (Check for updates), and keeps the answer |
| `GET /api/update/auto` | | the same fields from the last answer, without asking PyPI, plus `enabled` (the automatic daily check) and `checked` (when PyPI was last asked) |
| `POST /api/update/auto` | `{enabled}` | turn the automatic daily check on or off (`update_check` in `config.json`), with a backup |
| `GET /api/claude/status` | | whether Claude Code is installed, install methods, install job state |
| `GET /api/shell` | | profile by folder: `{installed, targets: [{file, shell, line}], shell, lines, on_path, rules: [{text, exact, profile, label}], projects: [{path, rule, profile, label}]}`: the rc files that have the line, the ones turning it on would write, the rules, and what `cc-profiles which` gives each known project |
| `GET /api/shell/which` | `path` (absolute or starting with `~`) | `{path, exists, rule, profile, label, dir, default}`: the profile `claude` would start in there. `rule` is what the rules say (`shared` included), `profile` is `null` when claude keeps the default profile; `default` is true for `~/.claude`, where `CLAUDE_CONFIG_DIR` stays unset |

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
| `POST /api/conversations/move` | `profile`, `project`, `session`, `to`: one conversation and its file snapshots |
| `POST /api/conversations/delete` | `profile`, `project`, `session` |
| `POST /api/skills/create` | `profile`, `name`, `description` |
| `POST /api/skills/save` | `profile`, `name`, `content` (the whole `SKILL.md`) |
| `POST /api/skills/copy` | `profile`, `name`, `to` |
| `POST /api/skills/copy-all` | `profile`, `name`: to every profile that lacks it, one backup |
| `POST /api/skills/delete` | `profile`, `name` |
| `POST /api/mcp/save` | `profile`, `scope`, `name`, `config` (object), `old_name` (to rename or edit) |
| `POST /api/mcp/copy` | `profile`, `scope`, `name`, `to` (added to the target's user scope) |
| `POST /api/mcp/copy-all` | `profile`, `scope`, `name`: to every profile that lacks it, one backup |
| `POST /api/mcp/delete` | `profile`, `scope`, `name` |
| `POST /api/connectors/set` | `profile`, `name`, `enabled`: removes or adds the deny rule for the whole connector |
| `POST /api/connectors/all` | `profile`, `enabled`: removes or sets `disableClaudeAiConnectors` |
| `POST /api/connectors/forget` | `profile`, `name`: takes it off `claudeAiMcpEverConnected` (only when no deny rule blocks it) |
| `POST /api/connectors/sync` | `profile`: takes off the list the connectors the last check found gone from the account |
| `POST /api/github/save` | `changes: [{profile, user?, name?, email?}]`: the GitHub table, every change checked first, one backup |
| `POST /api/github/account` | `profile`, `user`: makes a signed-in account the active one in the profile's folder |
| `POST /api/github/identity` | `profile`, `name`, `email` (both or neither): `GIT_AUTHOR_*` and `GIT_COMMITTER_*` in the profile's `env` |
| `POST /api/github/setup` | `profile`: gives it its own GitHub CLI folder now (the server does it at start) |
| `POST /api/github/remove` | `user`: takes an account no profile uses off every folder; its keychain token stays |
| `POST /api/sharing` | `profile`, `item`, `shared` (bool) |
| `POST /api/plugins/enable` | `profile`, `plugin` (`name@marketplace`), `enabled` (bool): writes `enabledPlugins` where the value lives |
| `POST /api/profiles/import?label=…&id=…` | the request body is the exported `.zip` itself (`Content-Type: application/zip`, up to 500 MB), not JSON |
| `POST /api/settings/field` | `profile`, `key`, `value` (`null` removes the setting) |
| `POST /api/settings/permissions` | `profile`, `rules: {allow, ask, deny}` (lists of strings) |
| `POST /api/settings/field/all` | `profile`, `key`: the profile's value goes to every other profile, one backup |
| `POST /api/settings/fields` | `profile`, `values` (`{key: value}`): several fields at once, all checked first, one backup |
| `POST /api/statusline` | `profile`, `mode` (`off`, `builtin`, `custom`), `parts`, `separator`, `colors`, `limits` (`used`, the default, or `left`), `command`, `padding`, `refreshInterval`, `hideVimModeIndicator` |
| `POST /api/statusline/all` | `profile`: its status line goes to every other profile, one backup |
| `POST /api/settings/permissions/all` | `list`, `rule`: added to `settings.json` of every profile, one backup |
| `POST /api/settings/raw` | `profile`, `file` (`settings` or `local`), `content` (JSON text) |
| `POST /api/settings/claude-md` | `profile`, `content` |
| `POST /api/settings/global` | `profile`, `key` (`autoUpdates`), `value` (bool) |
| `POST /api/profiles/create` | `label`, `id`, `base` (profile id or empty), `include_projects`, `share` (list) |
| `POST /api/templates/save` | `profile`, `name` (letters, digits, spaces, `.`, `-`, `_`, up to 48) |
| `POST /api/templates/delete` | `name`: the file goes to the backup |
| `POST /api/templates/create` | `name`, `label`, `id`, `share` (as in `/api/profiles/create`: those items are linked to the source profile instead of being filled from the template): a new profile from the template, through the import code |
| `POST /api/profiles/update` | `id`, `label`, `command` |
| `POST /api/profiles/delete` | `id`, `merge_into` (optional), `force` (skip the open-session check) |
| `POST /api/backups/restore` | `name` |
| `POST /api/backups/delete` | `name` |
| `POST /api/backups/prune` | `days` (integer, 1 or more): permanently deletes the backups older than that |
| `POST /api/backups/auto` | `days` (`15`, `30`, `60` or `90`): the automatic cleanup; it also prunes at once |
| `POST /api/backups/keep` | `name`, `kept` (bool): keep a backup so no cleanup deletes it (and it cannot be deleted until `kept` is false), or let it go |
| `POST /api/update` | (none): runs the update for this install, then restarts the server; `{message, restarting}` |
| `POST /api/claude/install` | `method` (`native`, `brew`, `brew-latest`, `npm`) |
| `POST /api/shell` | `install` (`true` or `false`): adds the profile by folder line to the shell rc files, or removes it. Without anything to change it returns a `message` and no `backup` |

## Example

```sh
PORT=4777
TOKEN=$(curl -s http://127.0.0.1:$PORT/ | grep -o 'const TOKEN = "[a-f0-9]*"' | cut -d'"' -f2)
curl -s -H "X-Token: $TOKEN" http://127.0.0.1:$PORT/api/profiles
```
