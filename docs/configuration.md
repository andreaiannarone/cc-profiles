# Configuration reference

## Command line

```
cc-profiles [--port PORT] [--no-browser]
cc-profiles label
cc-profiles --version
```

| Option | Default | Effect |
|---|---|---|
| `--port PORT` | `4777`, or `CC_PROFILES_PORT` | port to listen on (always on `127.0.0.1`) |
| `--no-browser` | off | do not open the browser |
| `label` | | print the active profile's name and exit (see [Status line](status-line.md)) |
| `--version` | | print the version and exit |

You can also run it as a module: `python3 -m cc_profiles`.

## Environment variables

| Variable | Effect |
|---|---|
| `CC_PROFILES_PORT` | default port |
| `CC_PROFILES_HOME` | data folder instead of `~/.cc-profiles` |
| `CC_PROFILES_QUIET` | if set, do not log HTTP requests to the terminal |
| `CC_PROFILES_INSTALL_DRYRUN` | **for tests**: the Claude Code installer runs `echo` instead of installing |
| `CC_PROFILES_INSTALL_DRYRUN_CODE` | **for tests**: exit code of the dry-run installer (simulates failures) |
| `CLAUDE_CONFIG_DIR` | read by `cc-profiles label` to know the active profile |

## `~/.cc-profiles/config.json`

Written on the first run and updated by the UI. You can edit it by hand while the app is stopped.

```json
{
  "profiles": [
    { "id": "default", "label": "Default", "dir": "~/.claude",
      "config": "~/.claude.json", "command": "claude" },
    { "id": "work", "label": "Work", "dir": "~/.claude-work",
      "config": "~/.claude-work/.claude.json", "command": "claude-work" }
  ],
  "rules": [
    { "match": "code/work", "profile": "work" },
    { "exact": "~", "profile": "shared" }
  ],
  "search_roots": ["~"]
}
```

### `profiles`

The order matters: the first profile is the [source profile](concepts.md#the-source-profile), and badge colors follow the order.

| Field | Meaning |
|---|---|
| `id` | stable identifier, used by rules; lowercase letters, digits and dashes |
| `label` | name shown in the UI and printed by `cc-profiles label` |
| `dir` | the profile folder (`~` is expanded) |
| `config` | its `.claude.json`. For `~/.claude` it is `~/.claude.json`, outside the folder |
| `command` | the command that starts Claude Code in this profile |

### `rules`

Checked in order; the first match wins. Each rule has a `profile` (a profile `id`, or `shared`) and one of:

| Field | Matches |
|---|---|
| `match` | any project path that contains this text |
| `exact` | exactly this path (`~` is expanded) |

Defaults on first run: your home folder and `/` as exact rules, plus `/private/var/folders`, `/private/tmp`, `/tmp/` and `Library/Application Support`, all `shared`.

### `search_roots`

Folders searched (5 levels deep) for candidate folders when relinking an [orphan project](guides/projects.md#orphan-projects). Default `["~"]`. Folders such as `node_modules`, `Library`, build folders and hidden folders are skipped.

## Files cc-profiles writes outside its data folder

| Path | When |
|---|---|
| profile folders and `~/.claude.json` | the operations you run |
| `~/.local/bin/<command>` | creating, editing or deleting a profile (launcher scripts). Only files containing `# managed by cc-profiles` are ever rewritten or removed |
| `~/.zshrc`, `~/.bashrc`, `~/.bash_profile` | only to rename or remove a profile alias that was already there, together with the `# Claude Code:` comment line above it |
