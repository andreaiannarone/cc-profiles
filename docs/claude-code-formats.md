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

`projects/<name>/<sessionId>.jsonl`, one JSON object per line. cc-profiles reads the `cwd` field to learn the project path, the messages for the Conversations viewer and the token usage for the [Usage](guides/usage.md) tab; it never changes a line. File snapshots of the session are in `file-history/<sessionId>/`, and they must move together with the conversation.

Lines with `"type": "assistant"` carry the token usage of the reply, which the [Usage](guides/usage.md) tab adds up:

```json
{"type": "assistant", "timestamp": "2026-10-06T09:12:00.000Z", "requestId": "req_…",
 "message": {"id": "msg_…", "model": "claude-opus-5-5",
             "usage": {"input_tokens": 12, "output_tokens": 840, "cache_creation_input_tokens": 3100,
                       "cache_read_input_tokens": 52000,
                       "cache_creation": {"ephemeral_5m_input_tokens": 3100, "ephemeral_1h_input_tokens": 0}}}}
```

One reply can span several lines (one per content block, all with the same `message.id` and `requestId`), and a resumed conversation copies earlier replies into its new file: count each `message.id` + `requestId` once. Subagents write their own conversations in `projects/<name>/<sessionId>/subagents/*.jsonl`.

## Prompt history

`history.jsonl`, one object per prompt:

```json
{"display": "fix the failing test", "timestamp": 1782679708827, "project": "/Users/me/code/api", "sessionId": "…"}
```

Claude Code filters it by `project` to offer arrow-up history in each folder. cc-profiles moves lines by `project` (an exact match or a sub-path), and avoids duplicates by `(timestamp, display)`.

## Per-project settings

The `projects` key of `.claude.json`, keyed by absolute path: trust, allowed tools, project MCP servers and more. Most other keys of `.claude.json` are internal state: caches, counters, tips seen. cc-profiles edits only `projects`, `autoUpdates` and the keys the `/config` panel keeps there (see [Settings](guides/settings.md#general)).

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

The values used by the UI are in `SETTING_FIELDS` in `settings.py`, checked against `SCHEMA_VERSION`. When updating them, keep any current value that is not in the new list as a selectable option.

## Login

`claude auth status` prints JSON with `loggedIn`, `email`, `authMethod`, `subscriptionType`, `orgName`, `apiProvider`, `analyticsDisabled` and more. With `CLAUDE_CONFIG_DIR` set, it reports that profile. On macOS, credentials may be stored in the Keychain under `Claude Code-credentials-<hash>`, one entry per config folder, or in `.credentials.json` in the profile folder.

## claude.ai connectors

Connectors come from the claude.ai account, fetched by Claude Code at start. Each one is an MCP server named `claude.ai <name>`; its tools are `mcp__claude_ai_<name>__<tool>`, where every character other than letters, digits, `_` and `-` becomes `_`, and runs of `_` collapse into one (`claude.ai vidIQ for Claude` → `mcp__claude_ai_vidIQ_for_Claude`).

- `.claude.json` lists the ones connected in the profile at least once in `claudeAiMcpEverConnected`, as `"claude.ai Gmail"`. Claude Code appends to it and never removes an entry, even when the connector is gone from the account.
- A deny rule with only the server name (`mcp__claude_ai_Gmail`, or `mcp__claude_ai_Gmail__*`) blocks all its tools.
- `"disableClaudeAiConnectors": true` in any settings file stops Claude Code from fetching or connecting them; so does the environment variable `ENABLE_CLAUDEAI_MCP_SERVERS=false`.

Checked against Claude Code 2.1.294.
