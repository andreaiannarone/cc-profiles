# Health and About

## Health

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../assets/screenshots/health-dark.jpg">
  <img src="../assets/screenshots/health-light.jpg" alt="The Health tab: the checks of each profile, and a project whose folder is gone with Relink and Delete" width="1440" height="789" loading="lazy">
</picture>

The **Health** tab checks every profile:

| Check | Fails when |
|---|---|
| Login | `claude auth status` says the profile is not logged in |
| `.claude.json`, `settings.json`, `settings.local.json` | the file is not valid JSON |
| Prompt history | some lines of `history.jsonl` are not valid JSON |
| `skills`, `plugins` | the folder is a broken link (shared items show where they point) |
| Plugins | an installed plugin's files are missing |
| Memory indexes | `MEMORY.md` lists a missing file (error), or a memory is not listed (warning) |
| Open session | warning only: a `claude` process is running in the profile, or one of its conversations was written in the last 2 minutes |

Below the checks, **Projects whose folder is gone** lists the [orphan projects](projects.md#orphan-projects) of the profile, with one-click **Relink to …** buttons for the candidate folders found, plus **Relink…** and **Delete**.

Health runs `claude auth status` once per profile, so it takes a few seconds. **Run the checks again** refreshes it.

## About

The ⓘ button at the top right opens a panel with:

- **Claude Code**: version, binary path, install method, auto-updates, and the Claude Code version the settings dropdowns were checked against.
- **Each profile**:
  - account, login method, plan, organization, API provider;
  - usage: startups, first start, conversations, projects, memories, prompts, disk usage;
  - contents: skills, plugins, subagents, slash commands, output styles, MCP servers, hooks, `CLAUDE.md`, shared items.
- **cc-profiles**: version, code and data locations, number and size of backups, address, Python version and system.

Below them, **What's new** shows the release notes of the last versions, and **Report a problem…** opens a bug report on GitHub with the versions of cc-profiles, Claude Code, Python and your system already filled in. Nothing is sent until you submit the form, and you can read and change every field first.

## What's new after an update

The release notes come with the app: after cc-profiles updates, from the app or from a terminal, the next time you open it a window shows what changed since the version you used before, once. It reads nothing from the internet. On a new installation it shows nothing; open it any time from **What's new** in the About panel, or see [every release](../changelog.md).

## Updating cc-profiles

cc-profiles asks PyPI for its latest version by itself, at most once a day: a few seconds after it starts, and again every day while it runs. When a newer version exists, the ⓘ button gets an orange dot, a notice says so once for each new version, and the **Update** button at the top of the About panel, next to **Refresh**, lights up in the logo's orange (it stays grey and cannot be clicked while cc-profiles is up to date). The line at the bottom of the panel says which version is available. Nothing is installed until you click. At the bottom of the About panel, **Check for updates** asks PyPI right away.

The check sends PyPI only a request for the version, and PyPI sees your IP address. To turn it off, untick **Check for updates automatically, once a day** in the About panel (it writes `"update_check": false` in `config.json`): then cc-profiles asks only when you click. With the Claude Code installer, these are the only times cc-profiles reaches the internet.

When a newer version exists, **Update** runs the update for the way you installed cc-profiles, `pipx upgrade cc-profiles`, `uv tool upgrade cc-profiles` or `brew upgrade cc-profiles`, then restarts the app on the same port; the page reloads by itself. Your profiles, backups and settings are not touched. A copy run from the source folder, or installed with plain pip, shows the command to run by hand instead. In the first minutes after a release, PyPI announces the new version before pip can download it: the update then changes nothing and says so: click **Update** again a few minutes later (pip's output is under *Details*). After updating from a terminal, run `cc-profiles restart` so the running app picks up the new version.

## Installing Claude Code

If Claude Code is not found, a notice at the top of the page offers **Install Claude Code…**. The same button is in the About panel. You pick one of the official methods from the [Claude Code setup guide](https://code.claude.com/docs/en/setup):

| Method | Command | Updates |
|---|---|---|
| Official installer (recommended) | `curl -fsSL https://claude.ai/install.sh \| bash` | automatic |
| Homebrew, stable | `brew install --cask claude-code` | `brew upgrade claude-code` |
| Homebrew, latest | `brew install --cask claude-code@latest` | `brew upgrade claude-code@latest` |
| npm (Node.js 22+) | `npm install -g @anthropic-ai/claude-code` | `npm install -g @anthropic-ai/claude-code@latest` |

Methods that cannot work on your machine are disabled, with the reason ("Homebrew is not installed", "needs Node.js 22 or later"). The installation output is shown live, and at the end the app checks that `claude` is really there.

If Claude Code is installed but your terminal cannot find it (usually because `~/.local/bin` is not in `PATH`), the notice tells you which line to add to your shell startup file.

cc-profiles looks for programs in your `PATH` plus `~/.local/bin`, `/opt/homebrew/bin` and `/usr/local/bin`, so it finds a fresh installation even if it was started from a terminal opened before installing.
