# Getting started

## Requirements

- macOS or Linux
- Python 3.9 or later (the one that ships with macOS works)
- Claude Code, or let cc-profiles install it for you (see [Health and About](guides/health.md#installing-claude-code))

## Install

```sh
pipx install cc-profiles
# or
uv tool install cc-profiles
```

Both put a `cc-profiles` command in `~/.local/bin`, in an isolated environment, so nothing else on your system is affected. To try it once without installing:

```sh
uvx cc-profiles
```

## First run

```sh
cc-profiles
```

The server starts on `http://127.0.0.1:4777` and your browser opens on it. Stop it with `ctrl+C`.

On the very first run, cc-profiles writes `~/.cc-profiles/config.json` with:

- **profiles**: `~/.claude` (called *Default*, command `claude`) plus every `~/.claude-<id>` folder that looks like a Claude Code profile, meaning it contains `settings.json`, `projects`, `history.jsonl`, `.claude.json` or `skills`. Empty folders and symlinks are ignored.
- **rules**: only the defaults that mark your home folder and temporary folders as *shared* (see [Concepts](concepts.md#rules)).

Rename profiles from the **Profiles** tab. The first profile in the list is the [source profile](concepts.md#the-source-profile).

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

## Next steps

- Read [Concepts](concepts.md): five minutes that make everything else obvious.
- Open the **Projects** tab: it starts on *Needs attention*, which lists what to fix first.
