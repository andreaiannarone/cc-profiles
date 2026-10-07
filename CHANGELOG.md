# Changelog

All notable changes to this project are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- cc-profiles checks for updates by itself, at most once a day: a few seconds after it starts and every day while it runs. A new version shows an orange dot on the ⓘ button, a notice once per version, and the **Update** button at the top of the About panel, next to Refresh, lights up (grey and not clickable while there is nothing new); nothing is installed until you click. PyPI sees your IP address: untick **Check for updates automatically** in the About panel (`"update_check": false`) to check only when you click.

## [0.5.1] - 2026-10-07

### Added
- **What's new** after an update: the next time you open cc-profiles, a window shows what changed since the version you used before (once; nothing is fetched from the internet, the notes come with the app). Open it any time from the About panel.
- **Report a problem…** in the About panel opens a GitHub bug report with the versions of cc-profiles, Claude Code, Python and your system filled in. The About panel also shows the system.
- **Homebrew**: `brew install andreaiannarone/cc-profiles/cc-profiles`, and **Update to …** in the app runs `brew upgrade cc-profiles` for a Homebrew install. The release script updates the tap at every release.
- **Windows through WSL 2**: under WSL the app opens in the Windows browser (`wslview`, or Windows' `start`), and the About panel and bug reports say WSL. The documentation explains how to install it there.
- Documentation: new pages Why cc-profiles, Uninstall, Glossary and What's new (the changelog, rebuilt by the release script). Search finds sections, not only pages, and opens the page at that section. Screenshots open full size on click, are cropped to the content, and the How-to guides show the dialogs they talk about (move, relink, new profile, copy to all). The page-not-found page suggests the pages closest to the address you typed. Each page ends with a link to open an issue about it.
- Documentation: four How-to guides (separate work and personal, move a project, relink a moved folder, share skills between profiles), worked examples in Memories, Conversations and Plugins, and a screenshot of the tab in each guide, in light or dark like the site. Each page ends with links to the previous and next page and shows the date it was last updated; section titles have a # link to share them.
- A test checks the images and HTML links of the documentation, and anchors with an underscore (`#search_roots`) are now checked like the site builds them.

### Changed
- Screenshots and demo GIFs regenerated: the light ones showed a "Claude Code is not installed" notice that came from the screenshot sandbox. `make_screenshots.py` also captures Projects, Profiles, Backups and Health.
- Documentation site: the sidebar looks like On this page (a thin line on the left, the current page in orange with its bar). Each sidebar group has an icon, like On this page. Each page shows its group above the title. On tablets and phones, a bar under the header shows where you are (Guides › Settings) and opens the menu as a drawer from the left (closes with Esc, a tap outside or a link). Responsive: from 561 to 860 px wide the page now switches to one column with the Menu (the sidebar was hidden there); on phones, tables are more compact and show a shadow where they continue sideways. Less empty space at the bottom of the page. The sidebar and On this page show their scrollbar only while the pointer is over them, fading in and out.
- Documentation site: the page uses the full width of the window, aligned with the header; long commands no longer slide under the copy icon; thinner scrollbars. README images regenerated.

## [0.5.0] - 2026-10-06

### Changed
- README: the status line editor has its own line in Key Features.

## [0.4.9] - 2026-10-06

### Added
- Documentation site, search engines and AI assistants: a meta description per page, canonical URLs, link previews (Open Graph, Twitter), structured data (the app, each page, breadcrumbs, the FAQ), `sitemap.xml`, `robots.txt` that welcomes AI crawlers, `llms.txt` and `llms-full.txt`, a 404 page, and a new **FAQ** page.
- Documentation site: a copy icon on every code block copies the command with one click (a check mark confirms it); an **On this page** column on the right lists the page's sections and highlights the one you are reading, and scrolls smoothly to the one you click (unless the system asks for reduced motion); an **Install** button in the header opens the install instructions.

## [0.4.8] - 2026-10-06

### Added
- Backups: **Keep** marks a backup that no cleanup deletes, automatic or by hand; it cannot be deleted until Keep is turned off.

### Changed
- Backups: the automatic cleanup is always on, 90 days by default (or 15, 30, 60); *never* is gone. On the first start after updating, backups older than 90 days are deleted unless you keep them.

## [0.4.7] - 2026-10-06

### Changed
- Usage: the periods are 7, 14, 30 and 90 days (365 is gone).

## [0.4.6] - 2026-10-06

### Added
- Settings → Status line: **Presets** fill the editor in one click (pieces, order, brackets, separator, colors and rate limits): *Essential*, *Developer*, *Usage* and *Like a hand-made one*. Nothing is saved until **Save status line**; the preset that matches the editor is shown as selected.
- Search in the documentation site: a box in the header (`/` focuses it, arrow keys and Enter pick a result, Esc closes) over `search.json`, built by GitHub Pages from the sidebar's pages. Every word must match; titles rank first; up to 8 results with the words highlighted.
- © 2026 Andrea Iannarone, linking https://andreaiannarone.com, in the README footer, the documentation site's footer and the About panel.
- Backups: **Show changes** lists what an operation did in plain words (files copied before a change, files that did not exist, moves from → to, folders and links created, items kept instead of deleted) and, for each copied text file, a diff between the copy in the backup and the file as it is now. JSON is compared with sorted keys; login credentials, MCP environment variables and headers and token-like values are never shown. Diffs stop at 2,000 lines, and files over 512 KB or binary are only named. `GET /api/backups/changes`, read-only.
- Usage: **Export CSV** downloads the current profile and period, one row per day and model with tokens by kind, replies and estimated cost (`GET /api/usage.csv`).
- Usage: **Most expensive sessions**, the 10 conversations with the highest estimated cost in the period, with their first prompt, project, profile, date, replies and tokens; a click opens the conversation in the Conversations tab.
- **Profile by folder**: `claude` can start in the profile of the folder you are in. `cc-profiles which [PATH]` prints the profile the rules give a folder (`--dir` prints its config folder), with the same matching as the Projects tab, and runs in about 50 ms without loading the server. `cc-profiles shell-init zsh|bash` prints a `claude` shell function that sets `CLAUDE_CONFIG_DIR` from it, leaves it unset for the default profile and for folders without a rule, never overrides a value you set, and falls back to plain `claude` when cc-profiles is missing. The Profiles tab has a **Profile by folder** section: the rules as folder → profile, a switch that adds or removes one marked line in `~/.zshrc` (or the bash files, for bash users) with a backup, and a field to try a folder. New endpoints `GET /api/shell`, `GET /api/shell/which` and `POST /api/shell`.

### Changed
- Tests: coverage of the servers the tests start is measured again (their SIGTERM handler skipped saving it), new tests bring it from 90% to 94%, and CI fails when the total drops below 92%.
- New profile from a template: the same "Share with Default" choices as the other bases. A shared item is linked to the source profile instead of being filled from the template, and the dialog and the confirmation say what that skips (*skills: shared with Default, the template's 3 skills are not copied*). Templates never hold plugins: sharing `plugins` is how such a profile gets the source's plugins. With a template only `plugins` is ticked by default.
- `/api/templates` lists what each shareable item of a template holds (`counts`), and `/api/templates/create` takes `share` like `/api/profiles/create`.

### Fixed
- Status line: with the rate limits shown as left, a reset less than a minute away reads `<1m` instead of `0m`.
- Accessibility: section titles in the tabs are `h2` (and their groups `h3`) under the page's `h1`, instead of skipping a level; they look the same. The browser test now also fails on axe's `heading-order` rule.
- `scripts/release.py`: the last step deletes the release branch on origin only if `git ls-remote` still lists it, and otherwise says GitHub already deleted it, instead of printing a failed push.
- The Conversations tab no longer fails on a conversation with a malformed line (a `message` that is not an object).

## [0.4.5] - 2026-10-06

### Added
- The documentation has its own site, https://cc-profiles.andreaia.com, with the app's logo, colors and theme switch; PyPI links to it.

### Changed
- README: links and images are absolute, so the PyPI page shows the screenshots and opens the guides; the documentation list has every guide, and the status line page is described as the Settings editor it now is.
- Documentation brought up to date with the code: the architecture (a package, not one file), what is read from conversations, the Save changes bar and status line editor in DESIGN.md, the test-only environment variables, and `cc-profiles restart` wherever a restart is needed.

## [0.4.4] - 2026-10-06

### Added
- **Usage** tab (`g u`): tokens and an estimated cost for all profiles or one, over the last 7, 30, 90 or 365 days: totals, cache read share, a bar chart per day, the top projects, every model and, for all profiles, each profile. It reads the usage Claude Code records on every reply, counting each reply once even when it is split over several lines, copied into a resumed conversation or present in two profiles, and includes subagent conversations. The cost uses Anthropic's list prices per model family and says so: subscription plans are not billed per token. Read-only, and each conversation file is parsed once until it changes.
- Settings → Status line: a **Tokens** piece shows `question:12k session:1.2M`, the tokens since your last prompt and in the whole session, read from the conversation file at each refresh. **Rate limits: Used / Left** shows the 5-hour and weekly limits as the share left, with the time until the reset once half or less is left (`5h:22%→1h20m 7d:59%`). Status lines saved before keep showing the share used.
- `/cc-profiles restart` and `/cc-profiles stop` inside Claude Code restart or stop the app, like `cc-profiles restart` and `cc-profiles stop` in a terminal. They run `cc-profiles open restart` and `cc-profiles open stop`. A command added by an older version gets them when you run `cc-profiles install-command` (or the install script) again.
- `scripts/release.py next` (or `<version>`) makes a release from start to finish: checks, version bump, dated CHANGELOG section, pull request, merge, tag, then waits for the wheel on PyPI. `--dry-run` prints every step.
- A weekly workflow installs the latest Claude Code, checks the Settings tab's options against its settings schema and `/config` panel with `scripts/check_settings_schema.py`, and opens an issue when they differ. The `/check-settings-schema` skill runs the same script first.
- `scripts/check_js.py` type-checks the UI's JavaScript with TypeScript (`--checkJs`, no build step), in CI too.

### Changed
- Updating from the About panel right after a release: when PyPI's download index does not have the new version yet (pip's *No matching distribution found*, pipx's *already at latest version*, or an update that changed nothing), the app says the version was just published and to try again in a few minutes, with a **Try again** button. pip's output is under *Details*.

### Fixed
- The status line preview runs in a sample project (`~/code/api`, branch `main`) instead of the app's own folder, and the profile's name is found even when the home folder is reached through a symlink.
- The README shows the Usage tab and the status line editor.
- Confirmations opened from the About panel (such as **Update to …**) now show above it: on windows narrower than about 1600px, their buttons were hidden under the panel.

## [0.4.3] - 2026-10-06

### Changed
- Settings → General no longer lists Model: pick it with `/model` in Claude Code, or edit `model` in the advanced editor. The first group is now called Replies.
- Settings → General: changes wait for **Save changes** (or **Cancel**) in a bar at the bottom, which counts them and marks the changed rows, and are saved together in one backup. The page no longer jumps to the top after a save, in General, CLAUDE.md, permissions and the advanced editor.

## [0.4.2] - 2026-10-06

### Added
- Settings → **Status line**: build one from 17 pieces (path or folder, git branch with `*` for uncommitted changes, profile, account email, model, effort, output style, pull request, context used, session cost, lines changed, session time, 5-hour and weekly limits, terminal, time), in the order you drag them into, each with its own brackets (none, `( )`, `[ ]`, `{ }`, `⟨ ⟩`), with a separator and colors of your choice and a live preview in color; or set your own command. Padding, refresh interval and the vim indicator too. The built-in one is a small `sh` + `jq` script in the profile folder, shown before you save, that names the right profile even through a shared `settings.json` and keeps working in a shell with a broken locale. **Apply to all…** puts it in every profile in one backup.

### Changed
- Automatic backup cleanup: pick 15, 30, 60 or 90 days. A 180 or 365 already set keeps working until you change it.
- Settings: the **General** section now has the same settings as Claude Code's `/config` panel, in groups (Model and replies, Interface, Editor and files, Notifications and updates, Commits and pull requests), plus the commit and pull request attribution as on/off switches. The keys `/config` keeps in `.claude.json` (Auto-compact, Verbose output, Diff tool, Editor mode and more) are written there, so Editor mode now goes where Claude Code reads it. Dropdowns name their default value. Effort level, Renderer, Days to keep conversations and Session link are no longer listed: they are not in `/config` (edit them in the advanced editor).

## [0.4.1] - 2026-10-05

### Added
- `cc-profiles restart` stops the server running in the background and starts it again, for example after an update; `cc-profiles stop` only stops it. A write in progress finishes first, and only cc-profiles is ever stopped: every response now carries the server's pid.

### Changed
- Settings: **Commit attribution**, **Pull request attribution** and **Session link in commits** edit Claude Code's `attribution` object, which replaces the deprecated `includeCoAuthoredBy`. An empty text is kept, since it means no attribution. *Co-authored-by in commits* now shows only while a profile still has it, without copy or apply-to-all, so it can be removed.
- The tabs are a single row again, under the profile cards, styled like GitHub's: an icon before each name, an orange underline on the active one. The sidebar and the group switcher of 0.4.0 are gone: on a narrow window the tabs that do not fit go into a **More** menu, and the active tab always stays in view.

### Fixed
- The favicon now shows in Safari, which ignores the inline SVG one: the server also sends it as PNG, `/favicon.ico` and `apple-touch-icon.png`, drawn from the same pixel mascot.
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

[Unreleased]: https://github.com/andreaiannarone/cc-profiles/compare/v0.5.1...HEAD
[0.5.1]: https://github.com/andreaiannarone/cc-profiles/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/andreaiannarone/cc-profiles/compare/v0.4.9...v0.5.0
[0.4.9]: https://github.com/andreaiannarone/cc-profiles/compare/v0.4.8...v0.4.9
[0.4.8]: https://github.com/andreaiannarone/cc-profiles/compare/v0.4.7...v0.4.8
[0.4.7]: https://github.com/andreaiannarone/cc-profiles/compare/v0.4.6...v0.4.7
[0.4.6]: https://github.com/andreaiannarone/cc-profiles/compare/v0.4.5...v0.4.6
[0.4.5]: https://github.com/andreaiannarone/cc-profiles/compare/v0.4.4...v0.4.5
[0.4.4]: https://github.com/andreaiannarone/cc-profiles/compare/v0.4.3...v0.4.4
[0.4.3]: https://github.com/andreaiannarone/cc-profiles/compare/v0.4.2...v0.4.3
[0.4.2]: https://github.com/andreaiannarone/cc-profiles/compare/v0.4.1...v0.4.2
[0.4.1]: https://github.com/andreaiannarone/cc-profiles/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/andreaiannarone/cc-profiles/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/andreaiannarone/cc-profiles/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/andreaiannarone/cc-profiles/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/andreaiannarone/cc-profiles/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/andreaiannarone/cc-profiles/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/andreaiannarone/cc-profiles/releases/tag/v0.1.0
