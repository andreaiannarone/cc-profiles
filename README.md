<p align="center">
  <img src="docs/assets/logo.svg" alt="cc-profiles" width="360">
</p>

<p align="center"><strong>A local web UI to manage multiple <a href="https://code.claude.com">Claude Code</a> profiles on one machine.</strong></p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/HTML5-E34F26?logo=html5&logoColor=white" alt="HTML5">
  <img src="https://img.shields.io/badge/CSS-663399?logo=css&logoColor=white" alt="CSS">
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?logo=javascript&logoColor=black" alt="JavaScript">
  <img src="https://img.shields.io/badge/Claude_Code-D97757?logo=claude&logoColor=white" alt="Claude Code">
  <img src="https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white" alt="pytest">
  <img src="https://img.shields.io/badge/macOS-000000?logo=apple&logoColor=white" alt="macOS">
  <img src="https://img.shields.io/badge/Linux-FCC624?logo=linux&logoColor=black" alt="Linux">
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green" alt="MIT License"></a>
  <a href="https://buymeacoffee.com/andreaiannarone"><img src="https://img.shields.io/badge/Buy_me_a_coffee-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy me a coffee"></a>
</p>

Keep work and personal contexts apart, move projects and memories between profiles, share skills and plugins, edit settings with safe dropdowns, and undo anything you do.

> **Unofficial.** cc-profiles is a community project, not affiliated with or endorsed by Anthropic. It works with Claude Code's on-disk files, whose format is undocumented and may change between releases. That is why every operation it performs creates a backup you can restore with one click.

## Why

Claude Code reads its configuration from `~/.claude`, or from whatever directory `CLAUDE_CONFIG_DIR` points to. Each directory is a separate **profile** with its own memory, conversations, prompt history, settings and login:

```sh
claude                                     # default profile (~/.claude)
CLAUDE_CONFIG_DIR=~/.claude-work claude    # a second profile
```

That is great for keeping contexts apart, but maintaining profiles by hand is painful. Conversations live in folders named like `-Users-you-code-client--api`. The prompt history is one JSONL file to filter line by line. The default profile's settings live in `~/.claude.json`, *outside* `~/.claude`. And when you move a project folder, Claude Code silently loses its history.

cc-profiles does all of this for you, from a page in your browser.

## Features

- **Projects.** See which profile each project belongs to and what it holds in each one. Move a project to another profile (conversations, memories, file snapshots, prompt history and per-project settings move together). Relink a project whose folder you moved or renamed. Assign projects with simple path rules.
- **Memories.** Browse, edit, move and delete the memories of every project. `MEMORY.md` indexes stay in sync.
- **Profiles.** Create a profile, empty or copied from another one. Rename it, change its command, or delete it, optionally merging its content into another profile first.
- **Sharing.** Share `skills`, `plugins`, `agents`, `commands`, `CLAUDE.md` or `settings.json` with the source profile through symlinks. Install once, use everywhere.
- **Settings.** Edit model, effort, output style, theme and more. Dropdowns offer only the values Claude Code accepts, and the UI shows which file each value comes from. You can also edit `CLAUDE.md`, permissions (`allow` / `ask` / `deny`) and the raw JSON, with validation.
- **Backups.** Every operation is journaled. **Restore** undoes it, and a restore can itself be undone.
- **Health.** Check login status, config validity, broken links, memory indexes, and projects whose folder disappeared, with candidate folders to relink them to.
- **About.** See the Claude Code version, account and plan for each profile, and everything installed. If Claude Code is missing, you can install it with the official installer.
- **Inside Claude Code.** Type `/cc-profiles` in any session to open the app without leaving it.

## Requirements

- macOS or Linux (Windows is not supported yet)
- Python 3.9 or later; macOS's built-in Python works
- [pipx](https://pipx.pypa.io) or [uv](https://docs.astral.sh/uv/) to install it
- [Claude Code](https://code.claude.com/docs/en/setup), or let cc-profiles install it for you

No dependencies: cc-profiles uses only the Python standard library.

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
```

The script installs cc-profiles with `pipx` or `uv`, whichever you have, and adds the `/cc-profiles` command to Claude Code. Run it again to update. It never uses `sudo` and writes only in your home folder; read [install.sh](install.sh) first if you like. To install the app without touching your profiles, end the command with `sh -s -- --no-command`.

Or install it by hand:

```sh
pipx install git+https://github.com/andreaiannarone/cc-profiles.git    # or: uv tool install git+…
cc-profiles install-command     # optional: adds /cc-profiles to Claude Code
```

To try it without installing anything: `uvx --from git+https://github.com/andreaiannarone/cc-profiles.git cc-profiles`.

## Usage

```sh
cc-profiles                   # starts on http://127.0.0.1:4777 and opens the browser; ctrl+C stops it
cc-profiles --port 4800       # another port
cc-profiles --no-browser      # just the server
cc-profiles open              # starts it in the background if needed, opens the browser and returns
cc-profiles install-command   # adds the /cc-profiles command to Claude Code
cc-profiles label             # prints the name of the active profile (see below)
```

On the first run, cc-profiles finds `~/.claude` and every `~/.claude-<name>` folder that looks like a profile. You can rename profiles from the **Profiles** tab.

### Open it from Claude Code

Type `/cc-profiles` in any Claude Code session: the app starts in the background, your browser opens on it, and the session goes on. The command is a small file, `commands/cc-profiles.md`, that `cc-profiles install-command` writes in every profile. Profiles that share `commands` with the source profile get it through the link, and a `cc-profiles.md` that cc-profiles did not create is never overwritten.

This repository is also a Claude Code plugin marketplace, if you prefer a plugin:

```
/plugin marketplace add andreaiannarone/cc-profiles
/plugin install cc-profiles@cc-profiles
```

The plugin's command is `/cc-profiles:open`, because Claude Code prefixes plugin commands with the plugin's name. The plugin only opens the app, so install cc-profiles first.

### Commands for each profile

When cc-profiles creates a profile, it adds a small launcher script to `~/.local/bin`. For a profile called `work` that is `claude-work`:

```sh
#!/bin/sh
CLAUDE_CONFIG_DIR="$HOME/.claude-work" exec claude "$@"
```

The script works in every shell. Make sure `~/.local/bin` is in your `PATH`; the official Claude Code installer usually adds it.

### Show the profile in your status line

`cc-profiles label` prints the name of the profile in use, based on `CLAUDE_CONFIG_DIR`. Call it from your [Claude Code status line](https://code.claude.com/docs/en/statusline) script:

```sh
profile=$(cc-profiles label 2>/dev/null)
printf '(%s) ' "$profile"
```

### Rules

The **Projects** tab assigns each project to a profile using rules. Each rule says "a path containing this text belongs to that profile". Create rules from the UI with **Assign…**. They are stored in `~/.cc-profiles/config.json`:

```json
{ "match": "code/work", "profile": "work" }
```

Rules are checked in order and the first match wins; new rules go first. `"profile": "shared"` marks paths that may appear in every profile, like your home folder.

## Documentation

The full guide is in [docs/](docs/README.md): [getting started](docs/getting-started.md), [concepts](docs/concepts.md), a guide for every tab, the [configuration reference](docs/configuration.md) and [troubleshooting](docs/troubleshooting.md). For contributors: [architecture](docs/architecture.md), [Claude Code's on-disk formats](docs/claude-code-formats.md) and the [HTTP API](docs/api.md).

## Where your data lives

| Path | Content |
|---|---|
| `~/.cc-profiles/config.json` | profiles, rules, folders to search when relinking |
| `~/.cc-profiles/backups/` | one folder per operation: a `manifest.json` journal plus the original files |
| `~/.cc-profiles/server.log` | output of the server started by `cc-profiles open` |
| `~/.local/bin/claude-<id>` | launchers created for new profiles |
| `<profile>/commands/cc-profiles.md` | the `/cc-profiles` command, if you added it |

cc-profiles never sends anything anywhere. The only network access is the optional Claude Code installer, which runs only if you click **Install**.

## Security

- The server listens on `127.0.0.1` only and accepts only `Host: 127.0.0.1:<port>` or `localhost:<port>`, which blocks DNS rebinding.
- Every API call needs a random token, generated at each start and embedded in the page, so other websites cannot control the app.
- Writes are atomic (temporary file, then rename), so Claude Code never reads a half-written file, even while it is running.
- Names of projects, memories and backups are validated against path traversal.
- Login credentials are never copied between profiles: each profile logs in on its own.

See [SECURITY.md](SECURITY.md) to report a vulnerability.

## Limitations

- Claude Code's file formats are not a public API. Settings dropdowns were checked against Claude Code 2.1.287; the **About** panel shows which version you have.
- The "session open" warning is a heuristic: a conversation written in the last 2 minutes.
- Deleting a profile does not remove credentials that Claude Code may have stored in the macOS Keychain for it.

## Contributing

Contributions are welcome! See [CONTRIBUTING.md](CONTRIBUTING.md) for how to run the app and the tests locally. If you use Claude Code, the repository's `.claude/` folder keeps you on a sandbox and has skills for the common chores. Good first contributions:

- translations (the UI is English only for now)
- Windows support
- a "dry run" preview for big operations

## Support

cc-profiles is free and open source. If it saves you time, you can [buy me a coffee](https://buymeacoffee.com/andreaiannarone).

## License

[MIT](LICENSE) © Andrea Iannarone

---

<p align="center">Built with <a href="https://code.claude.com">Claude Code</a> | Made for <a href="https://code.claude.com">Claude Code</a></p>
