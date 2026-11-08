# Privacy

cc-profiles runs on your computer and has no server of its own: nothing you do in it is sent to its author or to anyone else. This page lists what it reads, what it keeps, and the few services it talks to. It applies to the app, the `/cc-profiles` command and the Claude Code plugin, which only opens the app.

## What it reads

To show and manage your profiles, cc-profiles reads the files of Claude Code and of the GitHub CLI on your computer:

- your Claude Code profiles (`~/.claude`, `~/.claude-<id>`, the `.claude.json` files): projects, conversations, memories, settings, skills, agents, plugins and MCP servers;
- the claude.ai account each profile is signed in to, as Claude Code keeps it in `.claude.json`: name, email, organization, role and plan;
- the GitHub user names in the GitHub CLI's `hosts.yml`, and each profile's commit identity (name and email).

It never reads GitHub tokens. It reads a profile's claude.ai sign-in only to ask for that account's plan limits (below), and never copies, stores, refreshes or shows it.

## What it keeps

Everything stays on your computer, in `~/.cc-profiles`:

- its settings (`config.json`): profiles, folder rules, your choices in the app;
- the backups of every change, so it can be undone;
- the plan limits history, by account email, for 90 days (`quota-history.json`).

The automatic export is off until you turn it on. Then it writes a copy of each profile, conversations included and never the sign-in, to `iCloud Drive/cc-profiles exports` when iCloud Drive is there, where iCloud syncs it like any other file, or else to `~/.cc-profiles/exports`.

Deleting `~/.cc-profiles` (or `cc-profiles uninstall --purge`) removes all of it.

## The services it talks to

| Service | When | What it sends |
|---|---|---|
| **pypi.org** | once a day, to learn the latest version; turn it off in the About panel to check only when you click | a request for the version; PyPI sees your IP address |
| **api.anthropic.com** | when it shows the plan limits: in the Profiles tab, every 15 minutes while the page is open (the Mac app also with its window closed), or when you click **Refresh** | the profile's own claude.ai sign-in, to read that account's usage limits, the way Claude Code's `/usage` does; read-only |
| **api.github.com** | when it suggests a commit identity | a GitHub user name, to the public API, without a token; the GitHub CLI (`gh api user`) may also ask whose account a sign-in is, with its own sign-in |
| **The Claude Code installer** | only when you click **Install** | what the official installer downloads |
| **pipx, uv or Homebrew** | only when you click **Update to …** in the About panel | what they download to update cc-profiles |

The list of your claude.ai connectors comes from `claude mcp list`: that request is Claude Code's own, with its own sign-in.

cc-profiles has no analytics, no tracking and no advertising, and sends no data to its author.

## The local server

The page talks to a server that listens only on `127.0.0.1`, checks the `Host` header and a random token on every call, so other websites and other computers cannot reach it. See [Security](https://github.com/andreaiannarone/cc-profiles#security).

## Contact

Questions about this page: open an issue on [GitHub](https://github.com/andreaiannarone/cc-profiles/issues). Security problems: [report them privately](https://github.com/andreaiannarone/cc-profiles/security/advisories/new).
