# Getting started

## Requirements

- macOS or Linux; on Windows, [WSL 2](#windows-wsl)
- Python 3.9 or later (the one that ships with macOS works)
- [pipx](https://pipx.pypa.io), [uv](https://docs.astral.sh/uv/) or [Homebrew](https://brew.sh)
- Claude Code, or let cc-profiles install it for you (see [Health and About](guides/health.md#installing-claude-code))

## Install

```sh
curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
```

The script installs cc-profiles with `pipx` or `uv`, whichever you have, then adds the `/cc-profiles` command to Claude Code (see [Open it from Claude Code](#open-it-from-claude-code)). Run it again to update. To install the app only, end the command with `sh -s -- --no-command`.

Or install it by hand:

```sh
pipx install cc-profiles
# or
uv tool install cc-profiles
```

Both put a `cc-profiles` command in `~/.local/bin`, in an isolated environment, so nothing else on your system is affected.

With [Homebrew](https://brew.sh), on macOS or Linux:

```sh
brew install andreaiannarone/cc-profiles/cc-profiles
cc-profiles install-command     # optional: adds /cc-profiles to Claude Code
```

Homebrew gets each new version shortly after it is on PyPI. To try it once without installing:

```sh
uvx cc-profiles
```

### Windows (WSL)

Claude Code runs on Windows inside [WSL 2](https://learn.microsoft.com/windows/wsl/install), and so does cc-profiles: open your WSL terminal, in the same Linux distribution where you use Claude Code, and install it with the commands above. Its profiles are the ones in your Linux home (`~/.claude`), as Claude Code sees them.

The app still opens in your Windows browser: cc-profiles uses `wslview` when it is installed (package `wslu`), or else Windows' own `start`. WSL 2 forwards `127.0.0.1` to Windows, so the address works as it is. WSL support is new: if something does not work, [report it](troubleshooting.md#reporting-a-bug).

## First run

```sh
cc-profiles
```

The server starts on `http://127.0.0.1:4777` and your browser opens on it. Stop it with `ctrl+C`. If cc-profiles is already running, for example started by `/cc-profiles`, the command only opens your browser on it.

On the very first run, cc-profiles writes `~/.cc-profiles/config.json` with:

- **profiles**: `~/.claude` (called *Default*, command `claude`) plus every `~/.claude-<id>` folder that looks like a Claude Code profile, meaning it contains `settings.json`, `projects`, `history.jsonl`, `.claude.json` or `skills`. Empty folders and symlinks are ignored.
- **rules**: only the defaults that mark your home folder and temporary folders as *shared* (see [Concepts](concepts.md#rules)).

Rename profiles from the **Profiles** tab. The first profile in the list is the [source profile](concepts.md#the-source-profile).

## Open it from Claude Code

Type `/cc-profiles` in any Claude Code session. It runs `cc-profiles open`, which starts the server in the background if it is not running yet, opens your browser and returns, so the session goes on.

| In Claude Code | Runs | Does |
|---|---|---|
| `/cc-profiles` | `cc-profiles open` | starts the server if needed and opens the browser |
| `/cc-profiles restart` | `cc-profiles open restart` | stops the server and starts it again, e.g. after an update; then reload the page |
| `/cc-profiles stop` | `cc-profiles open stop` | stops the server |

From a terminal, `cc-profiles restart` and `cc-profiles stop` do the same. A command added by an older version of cc-profiles does not take `restart` or `stop` yet: run `cc-profiles install-command` (or the install script) again to update it.

The [install script](https://github.com/andreaiannarone/cc-profiles/blob/main/install.sh) adds the command for you. Otherwise run:

```sh
cc-profiles install-command
```

It writes `commands/cc-profiles.md` in every profile, skips profiles that share `commands` with the [source profile](concepts.md#the-source-profile) (they get it through the link), and never overwrites a `cc-profiles.md` it did not create. Like every change cc-profiles makes, it is saved in a backup you can restore from the **Backups** tab. Sessions that are already open see the command after a restart.

### As a plugin

The repository is also a Claude Code plugin marketplace. Install the plugin once:

```
/plugin marketplace add andreaiannarone/cc-profiles
/plugin install cc-profiles@cc-profiles
```

The plugin's command is `/cc-profiles:open`, because Claude Code always prefixes plugin commands with the plugin's name; it does the same as `/cc-profiles`, `restart` and `stop` included (`/cc-profiles:open restart`). The plugin only opens the app: install `cc-profiles` first. To get it in every profile, install it in the source profile and share `plugins` from the **Profiles** tab.

## Starting Claude Code in a profile

Claude Code picks its profile from the `CLAUDE_CONFIG_DIR` environment variable:

```sh
claude                                     # ~/.claude
CLAUDE_CONFIG_DIR=~/.claude-work claude    # ~/.claude-work
```

When cc-profiles creates a profile, it also creates a **launcher**: a small script in `~/.local/bin` named after the profile's command.

```sh
claude-work          # same as: CLAUDE_CONFIG_DIR=~/.claude-work claude
```

Launchers work in every shell, right away. They need `~/.local/bin` in your `PATH`; the official Claude Code installer usually adds it. If it is missing, add this line to your shell startup file (`~/.zshrc`, `~/.bashrc`, …):

```sh
export PATH="$HOME/.local/bin:$PATH"
```

Each new profile must log in once: run its command and use `/login`. Credentials are never copied between profiles.

## Finding your way

The tabs sit in one row under the profile cards. On a narrow window the ones that do not fit are in the **More** menu at the end of the row.

### Keyboard shortcuts

| Keys | What they do |
|---|---|
| `/` | Search everything |
| `g` then `p`, `m`, `c`, `u` | Projects, Memories, Conversations, Usage |
| `g` then `s`, `x`, `l` | Skills, MCP, Plugins |
| `g` then `r`, `o` | Profiles, Compare |
| `g` then `b`, `h`, `t` | Backups, Health, Settings |
| `?` | Show the list of shortcuts |
| `Esc` | Close the search, a dialog or a panel |

Shortcuts are ignored while you type in a field or while a dialog is open. The keyboard button in the header shows the same list.

## Next steps

- Read [Concepts](concepts.md): five minutes that make everything else obvious.
- Open the **Projects** tab: it starts on *Needs attention*, which lists what to fix first.
