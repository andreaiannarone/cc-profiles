# Configuration reference

## Command line

```
cc-profiles [--port PORT] [--no-browser]
cc-profiles open [restart|stop] [--port PORT] [--no-browser]
cc-profiles stop [--port PORT]
cc-profiles restart [--port PORT]
cc-profiles install-command
cc-profiles label
cc-profiles --version
```

| Option | Default | Effect |
|---|---|---|
| `--port PORT` | `4777`, or `CC_PROFILES_PORT` | port to listen on (always on `127.0.0.1`) |
| `--no-browser` | off | do not open the browser |
| `open` | | start the server in the background unless it is already running, open the browser and return at once. Prints the server's pid; its output goes to `~/.cc-profiles/server.log`. Used by the `/cc-profiles` command (see [Getting started](getting-started.md#open-it-from-claude-code)). `open restart` and `open stop` do the same as `restart` and `stop`: they are what `/cc-profiles restart` and `/cc-profiles stop` run. Any other word is an error |
| `stop` | | stop the server running on the port. A write in progress finishes first; another program on the port is left alone |
| `restart` | | `stop`, then `open` without the browser: use it after an update, then reload the page |
| `install-command` | | add the `/cc-profiles` command to Claude Code: writes `commands/cc-profiles.md` in every profile that does not share `commands`, with a backup. Never overwrites a file it did not create, and does nothing if the command is up to date |
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
| `CC_PROFILES_PYPI_URL` | **for tests**: where *Check for updates* reads the latest version (a `file://` URL), instead of pypi.org |
| `CC_PROFILES_UPDATE_DRYRUN` | **for tests**: *Update* says what it would run instead of updating and restarting |
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
  "search_roots": ["~"],
  "backup_keep_days": 90
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

### `backup_keep_days`

Optional. When set to `15`, `30`, `60` or `90` (`180` and `365`, offered by 0.4.0 and 0.4.1, still work), the backups older than that many days are deleted automatically when cc-profiles starts and once a day while it runs. Backups of the last 24 hours and incomplete backups not restored yet are always kept. Absent (the default) means backups are kept until you delete them. Set it from the [Backups tab](guides/backups.md#automatic-cleanup).

## Templates

Profile templates are `.zip` files in `~/.cc-profiles/templates/<name>.zip`, in the export format without conversations, memories or credentials. See [Templates](guides/profiles.md#templates).

## Files cc-profiles writes outside its data folder

| Path | When |
|---|---|
| profile folders and `~/.claude.json` | the operations you run |
| `~/.local/bin/<command>` | creating, editing or deleting a profile (launcher scripts). Only files containing `# managed by cc-profiles` are ever rewritten or removed |
| `~/.zshrc`, `~/.bashrc`, `~/.bash_profile` | only to rename or remove a profile alias that was already there, together with the `# Claude Code:` comment line above it |
