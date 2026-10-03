# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Documentation in `docs/`: getting started, concepts, a guide per tab, status line, configuration reference, troubleshooting, architecture, Claude Code's on-disk formats, HTTP API.
- Tests that check every relative link and anchor in the documentation.
- `cc-profiles open`: starts the server in the background if needed, opens the browser and returns.
- `cc-profiles install-command`: adds the `/cc-profiles` command to Claude Code in every profile, with a backup.
- `install.sh`: installs cc-profiles with pipx or uv and adds the `/cc-profiles` command.
- `.claude/` folder for contributors using Claude Code: permissions, a hook that blocks starting the app on the real home folder, and the `/sandbox` and `/check-settings-schema` skills.
- CI runs `install.sh` on Linux and macOS and lints it with shellcheck.
- Claude Code plugin marketplace in this repository, with the `/cc-profiles:open` command that runs `cc-profiles open`.
- Project logo, also next to the web UI's title, a one-mascot favicon, and technology badges in the README.
- Skills & MCP tab: for each profile, browse, create, edit, copy and delete skills, and add, edit, copy and remove MCP servers (user or project scope). Values of environment variables and headers stay out of the list.
- Profile cards and the Profiles tab show the account each profile is signed in with.

### Changed
- License: GPL-3.0-or-later instead of MIT, from this release on. Version 0.1.0 stays available under MIT.
- Settings: output styles use Claude Code's own descriptions, shown under the menu, are grouped into built-in and custom, and the duplicate "Default" entry is gone.

## [0.1.0] - 2026-10-02

First public release.

### Added
- Projects tab: see where each project lives, move it between profiles, relink it after moving its folder, assign it with path rules.
- Memories tab: browse, edit, move and delete project memories, keeping `MEMORY.md` in sync.
- Profiles tab: create (empty or copied), rename, change the command, delete (optionally merging into another profile); share skills, plugins, agents, commands, `CLAUDE.md` and `settings.json` through symlinks.
- Settings tab: general settings with dropdowns checked against the Claude Code settings schema, `CLAUDE.md` editor, permissions, raw JSON editor, auto-updates.
- Backups tab: every operation is journaled and can be restored; restores can be undone too.
- Health tab: login, config validity, links, memory indexes, orphan projects with candidate folders.
- About panel: Claude Code version, account and plan per profile, installed content; installs Claude Code with the official installer if missing.
- `cc-profiles label` command for status lines.
- Launcher scripts in `~/.local/bin` for new profiles.
- End-to-end test suite on a fake home.

[Unreleased]: https://github.com/andreaiannarone/cc-profiles/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/andreaiannarone/cc-profiles/releases/tag/v0.1.0
