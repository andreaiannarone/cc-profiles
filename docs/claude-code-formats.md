# Claude Code's on-disk formats

cc-profiles reads and writes files that Claude Code does not document as a public API. This page records what the app relies on, so that when Claude Code changes, it is clear what to check. Observed with Claude Code 2.1.x.

## A profile folder

```
~/.claude/                       (or the folder in CLAUDE_CONFIG_DIR)
├── settings.json                user settings
├── settings.local.json          local overrides (win over settings.json)
├── CLAUDE.md                    global instructions
├── history.jsonl                prompt history (arrow up)
├── projects/<name>/             per-project data
│   ├── <sessionId>.jsonl        one conversation
│   └── memory/                  auto-memory
│       ├── MEMORY.md            index
│       └── <memory>.md
├── file-history/<sessionId>/    file snapshots of a conversation
├── skills/  plugins/  agents/  commands/  output-styles/
└── .credentials.json            login (on some systems; never copied)
```

The profile's `.claude.json` is `<dir>/.claude.json`, except for the default profile: `~/.claude.json`, in the home folder.

## Project folder names

`projects/<name>` where `<name>` is the absolute project path with every character outside `[A-Za-z0-9]` replaced by `-`:

| Path | Folder |
|---|---|
| `/Users/me/code/api` | `-Users-me-code-api` |
| `/Users/me/Work Stuff/+site` | `-Users-me-Work-Stuff--site` |

The mapping is not reversible; see [Architecture](architecture.md#path-resolution).

## Conversations

`projects/<name>/<sessionId>.jsonl`, one JSON object per line. cc-profiles only reads the `cwd` field of the first lines, to learn the project path. File snapshots of the session are in `file-history/<sessionId>/`, and they must move together with the conversation.

## Prompt history

`history.jsonl`, one object per prompt:

```json
{"display": "fix the failing test", "timestamp": 1782679708827, "project": "/Users/me/code/api", "sessionId": "…"}
```

Claude Code filters it by `project` to offer arrow-up history in each folder. cc-profiles moves lines by `project` (an exact match or a sub-path), and avoids duplicates by `(timestamp, display)`.

## Per-project settings

The `projects` key of `.claude.json`, keyed by absolute path: trust, allowed tools, project MCP servers and more. Most other keys of `.claude.json` are internal state: caches, counters, tips seen. cc-profiles edits only `projects` and `autoUpdates`.

## Memories

Each memory is Markdown with frontmatter:

```markdown
---
name: api-uses-postgres
description: The API stores everything in Postgres, never in files
metadata:
  type: project
---
The body…
```

`MEMORY.md` has one line per memory:

```markdown
- [API uses Postgres](api-uses-postgres.md) — never store data in files
```

cc-profiles finds index lines by the `(file.md)` link.

## Settings schema

Claude Code validates settings with a schema compiled into its binary. To see the accepted values of a setting:

```sh
strings -n 6 "$(readlink -f "$(which claude)")" | grep -o 'effortLevel:()=>[^)]*)' | head -1
# effortLevel:()=>B(["low","medium","high","xhigh"])
```

- `B([...])` is an enum: the UI shows a dropdown.
- `o()` is any string: the UI shows a free text field.
- `B(name)` refers to a list defined elsewhere as `name=[...]`.

The values used by the UI are in `SETTING_FIELDS` in `server.py`, checked against `SCHEMA_VERSION`. When updating them, keep any current value that is not in the new list as a selectable option.

## Login

`claude auth status` prints JSON with `loggedIn`, `email`, `authMethod`, `subscriptionType`, `orgName`, `apiProvider`, `analyticsDisabled` and more. With `CLAUDE_CONFIG_DIR` set, it reports that profile. On macOS, credentials may be stored in the Keychain under `Claude Code-credentials-<hash>`, one entry per config folder, or in `.credentials.json` in the profile folder.
