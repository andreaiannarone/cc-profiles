# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- Conversations tab: read the conversations of each project (title, dates, prompt and reply counts, a read-only viewer), and move one to another profile with its file snapshots, or delete it.

## [0.2.2] - 2026-10-05

### Added
- Check for updates in the (i) panel: asks PyPI for the latest version only when you click, and updates a pipx or uv install with one click, then restarts the app.

## [0.2.1] - 2026-10-05

### Added
- New profiles get the `/cc-profiles` command automatically.

### Fixed
- Creating an empty profile that shares `settings.json` failed with "File exists".
- Items chosen for sharing when creating a profile are created in the source profile if missing, instead of being silently left out.
- For contributors: the sandbox hook no longer reads the body of a here-document (a commit message, say) as commands.

### Changed
- cc-profiles is on PyPI: the install script and the docs install it from there (`pipx install cc-profiles`).

## [0.2.0] - 2026-10-05

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
- Skills and MCP tabs: for each profile, browse, create, edit, copy and delete skills, and add, edit, copy and remove MCP servers (user or project scope). Values of environment variables and headers stay out of the list.
- Profile cards and the Profiles tab show the account each profile is signed in with.

- Theme button next to (i): System, Light or Dark, remembered per browser and applied before the page is drawn.

- Move preview: every file and folder a project move touches, before confirming.
- Delete old backups: every backup older than 7, 30, 90 or 365 days, in one go.

### Changed
- "Session open" also detects running `claude` processes and the profile they use, not only conversations written in the last 2 minutes. Moves warn when a session may write `.claude.json` back.
- Settings checked against Claude Code 2.1.289; custom themes (`custom:…`) are kept.
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

[Unreleased]: https://github.com/andreaiannarone/cc-profiles/compare/v0.2.2...HEAD
[0.2.2]: https://github.com/andreaiannarone/cc-profiles/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/andreaiannarone/cc-profiles/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/andreaiannarone/cc-profiles/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/andreaiannarone/cc-profiles/releases/tag/v0.1.0
