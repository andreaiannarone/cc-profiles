# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `cc-profiles restart` stops the server running in the background and starts it again, for example after an update; `cc-profiles stop` only stops it. A write in progress finishes first, and only cc-profiles is ever stopped: every response now carries the server's pid.

### Changed
- The tabs are a single row under the header again, styled like GitHub's: an icon before each name, an orange underline on the active one. The sidebar and the group switcher of 0.4.0 are gone: on a narrow window the tabs that do not fit go into a **More** menu, and the active tab always stays in view.

### Fixed
- The *cc-profiles* title no longer wraps at its hyphen on medium-width windows.

## [0.4.0] - 2026-10-05

### Added
- Keyboard shortcuts: `/` focuses the search, `g` then a letter opens a tab (`g p` Projects, `g h` Health…), `?` lists them all. A keyboard button in the header shows the same list.
- The browser smoke test runs axe-core on every tab, the shortcuts dialog, the About panel and phone width, in light and dark themes, and fails on serious or critical accessibility problems (`axe-playwright-python` in the `ui` extra).
- Previews for deleting a profile (what is merged where, the launcher or alias removed, the config entry, the folder that goes to the backup) and for sharing or separating an item (the own copy and the items only it has, the link, what is created in the source), shown in their confirmations. New read-only endpoints `GET /api/profiles/delete/preview` and `GET /api/sharing/preview`.
- Apply to all profiles: a setting's value (Settings, **Apply to all…**), a permission rule (**Add a rule to every profile…**), a skill and an MCP server (**Copy to all…**). Each is one operation with one backup covering every profile, and the confirmation lists the profiles changed and the ones skipped, with the reason.
- Automatic backup cleanup, off by default: in the Backups tab, delete backups older than 30, 90, 180 or 365 days when the app starts and once a day. It never deletes a backup from the last 24 hours, nor an incomplete one that has not been restored. Stored as `backup_keep_days` in `config.json`.
- Profile templates: save a profile's settings, `CLAUDE.md`, permissions, skills, agents, commands, output styles and MCP servers as `~/.cc-profiles/templates/<name>.zip` (never conversations, memories or credentials) and pick *From template: …* in New profile. **Templates…** in the Profiles tab lists, saves and deletes them.
- Test coverage, servers started by the tests included, measured in CI and shown in the run summary (see CONTRIBUTING).
- `tests/bench_home.py` times every tab on a large generated home.
- `scripts/make_screenshots.py` regenerates the README screenshots (now six: Conversations and Compare added), the demo GIF and the social preview from the real app on the sandbox home.
- A test that starts a real process named `claude` and checks that its profile is reported as in use.

### Changed
- The eleven tabs are grouped: Content, Extensions, Profiles and System. From 1100px they form a sidebar; on narrower windows a group switcher shows one group's tabs at a time, with a red dot on a group that needs attention.
- Better contrast: the amber of "session open" and warnings is darker in the light theme, and the *default* badge in Settings is outlined instead of faded (both were under 4.5:1).
- Much faster on large homes. On a test home with 2,000 projects and 20,000 conversations, Projects opens in 0.4–0.6 s instead of 25–26 s, Memories and Conversations in 0.3 s instead of 20–22 s, Health in 0.8–2.2 s instead of 31–37 s, and Search in 0.4–1.9 s instead of 16–23 s. Files that did not change since the last read are not read again: each cached result is checked against the file's modification time and size first. The app also reads the first tabs' data in the background when it starts.
- Health looks for moved project folders with a single walk of the search roots, instead of one walk per missing folder.

### Fixed
- A prompt-history line that is valid JSON but not an object (for example `3`) no longer breaks the project list. Health counts it as a broken line.

## [0.3.0] - 2026-10-05

### Added
- Conversations tab: read the conversations of each project (title, dates, prompt and reply counts, a read-only viewer), and move one to another profile with its file snapshots, or delete it.
- A browser smoke test (`tests/test_ui.py`, run in CI) opens every tab in Chromium and fails on JavaScript errors or Content-Security-Policy violations.
- Search everything: a field in the header searches projects, memories, skills, MCP servers and CLAUDE.md in every profile, with highlighted excerpts; clicking a result opens it.
- Compare tab: two profiles side by side (settings, permissions, skills, MCP servers, CLAUDE.md, plugins), with copies of what differs through the usual operations.
- Export a profile as a `.zip` (with or without conversations, never with login credentials) and import it on another computer, from the Profiles tab.
- Plugins tab: the plugins installed in each profile, their version, marketplace and scope, with a switch to enable or disable each one.

### Fixed
- Conversations are read whatever the spacing of their JSON lines.

### Changed
- An operation that fails halfway keeps its backup: the steps done so far are journaled, the backup is labelled "incomplete" and Restore undoes them.
- The page is served with a strict Content-Security-Policy and cannot be framed by other sites.
- CI and release workflows use the current GitHub Actions (checkout and setup-python v7, upload-artifact v7, download-artifact v8), off the deprecated Node 20.
- Dependabot opens one weekly pull request with GitHub Actions updates; CodeQL scans the Python server and the UI's JavaScript.
- Security issues are reported privately through GitHub's *Report a vulnerability* (see SECURITY.md).
- A social preview image for the repository (`docs/assets/social-preview.png`).

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

[Unreleased]: https://github.com/andreaiannarone/cc-profiles/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/andreaiannarone/cc-profiles/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/andreaiannarone/cc-profiles/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/andreaiannarone/cc-profiles/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/andreaiannarone/cc-profiles/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/andreaiannarone/cc-profiles/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/andreaiannarone/cc-profiles/releases/tag/v0.1.0
