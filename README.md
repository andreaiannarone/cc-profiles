<h1 align="center">
  <br>
  <a href="https://github.com/andreaiannarone/cc-profiles">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/logo-dark.svg">
      <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/logo-light.svg">
      <img src="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/logo-light.svg" alt="cc-profiles" width="400">
    </picture>
  </a>
</h1>

<h4 align="center">A local web UI to manage multiple <a href="https://code.claude.com" target="_blank">Claude Code</a> profiles on one machine.</h4>

<p align="center">
  <a href="https://github.com/andreaiannarone/cc-profiles/blob/main/LICENSE"><img src="https://img.shields.io/badge/License-GPL--3.0--or--later-blue" alt="License: GPL-3.0-or-later"></a>
  <a href="https://pypi.org/project/cc-profiles/"><img src="https://img.shields.io/pypi/v/cc-profiles?color=green" alt="cc-profiles on PyPI"></a>
  <img src="https://img.shields.io/badge/dependencies-none-brightgreen" alt="No dependencies">
  <a href="https://buymeacoffee.com/andreaiannarone"><img src="https://img.shields.io/badge/Buy_me_a_coffee-FFDD00?logo=buymeacoffee&logoColor=black" alt="Buy me a coffee"></a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?logo=python&logoColor=white" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/HTML5-E34F26?logo=html5&logoColor=white" alt="HTML5">
  <img src="https://img.shields.io/badge/CSS-663399?logo=css&logoColor=white" alt="CSS">
  <img src="https://img.shields.io/badge/JavaScript-F7DF1E?logo=javascript&logoColor=black" alt="JavaScript">
  <img src="https://img.shields.io/badge/Claude_Code-D97757?logo=claude&logoColor=white" alt="Claude Code">
  <img src="https://img.shields.io/badge/pytest-0A9EDC?logo=pytest&logoColor=white" alt="pytest">
  <img src="https://img.shields.io/badge/macOS-000000?logo=apple&logoColor=white" alt="macOS">
  <img src="https://img.shields.io/badge/Linux-FCC624?logo=linux&logoColor=black" alt="Linux">
</p>

<br>

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/demo-dark.gif">
    <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/demo-light.gif">
    <img src="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/demo-light.gif" alt="cc-profiles in use: a project is moved from the Default profile to Work with one click, then its memories, a conversation, the skills, an MCP server, the comparison of two profiles and the backup of the move are shown" width="860">
  </picture>
</p>

<p align="center">
  <a href="#quick-start">Quick Start</a> •
  <a href="#key-features">Features</a> •
  <a href="#screenshots">Screenshots</a> •
  <a href="#how-it-works">How It Works</a> •
  <a href="#usage">Usage</a> •
  <a href="https://cc-profiles.andreaia.com">Documentation</a> •
  <a href="#configuration">Configuration</a> •
  <a href="#troubleshooting">Troubleshooting</a> •
  <a href="#license">License</a>
</p>

<p align="center">
  cc-profiles keeps your Claude Code profiles in order: work and personal accounts side by side, each with its own memory, conversations, skills, MCP servers and settings. Move projects and memories between profiles, relink projects whose folder moved, share skills and plugins, and edit settings with safe dropdowns, all from a page in your browser. Every change is backed up first, so anything you do can be undone with one click.
</p>

---

## Quick Start

Install with a single command:

```bash
curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
```

The script installs cc-profiles with `pipx` or `uv`, whichever you have, and adds a `/cc-profiles` command to Claude Code in every profile. It never uses `sudo` and writes only in your home folder; [read it](https://github.com/andreaiannarone/cc-profiles/blob/main/install.sh) first if you like. Run it again to update. To install the app without touching your profiles:

```bash
curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh -s -- --no-command
```

Then open it, from a terminal or from inside Claude Code:

```bash
cc-profiles          # starts on http://127.0.0.1:4777 and opens your browser
```

```
/cc-profiles         # inside any Claude Code session: opens the app and the session goes on
/cc-profiles restart # restarts it, e.g. after an update (/cc-profiles stop stops it)
```

On the first run, cc-profiles finds `~/.claude` and every `~/.claude-<name>` folder that looks like a profile. Rename them from the **Profiles** tab.

<details>
<summary><b>Other ways to install</b></summary>

By hand, with pipx or uv:

```bash
pipx install cc-profiles        # or: uv tool install cc-profiles
cc-profiles install-command     # optional: adds /cc-profiles to Claude Code
```

With Homebrew:

```bash
brew install andreaiannarone/cc-profiles/cc-profiles
```

Try it without installing anything:

```bash
uvx cc-profiles
```

From the Claude Code plugin marketplace. The command is then `/cc-profiles:open`, because Claude Code prefixes plugin commands with the plugin's name. The plugin only opens the app, so install cc-profiles first:

```
/plugin marketplace add andreaiannarone/cc-profiles
/plugin install cc-profiles@cc-profiles
```

From source:

```bash
git clone https://github.com/andreaiannarone/cc-profiles.git
cd cc-profiles
python3 -m pip install -e .
cc-profiles
```

</details>

> **Unofficial.** cc-profiles is a community project, not affiliated with or endorsed by Anthropic. It works with Claude Code's on-disk files, whose format is undocumented and may change between releases. That is why every operation it performs creates a backup you can restore with one click.

### Key Features

- 🗂️ **Projects**: see which profile each project belongs to and what it holds in each one. Move a project to another profile with its conversations, memories, file snapshots, prompt history and per-project settings, after a preview of every file it touches. Relink a project whose folder you moved or renamed. Assign projects with simple path rules.
- 🧠 **Memories**: browse, edit, move and delete the memories of every project, with the `MEMORY.md` indexes kept in sync.
- 💬 **Conversations**: read the conversations of every project, and move a single one to another profile, with its file snapshots, or delete it.
- 📊 **Usage**: tokens per day, per project, per model and per profile, with an estimated cost at list price (subscription plans are not billed per token), read from the conversations Claude Code saves.
- 👤 **Profiles**: see the account each profile is signed in with. Create a profile, empty, copied from another one or from a template you saved (settings, permissions, skills, MCP servers; never conversations or credentials); rename it, change its command, or delete it, optionally merging its content into another profile first, after a preview of everything it touches.
- 🧩 **Skills**: browse, create, edit, copy and delete the skills of each profile, or copy one to every profile at once.
- 🔌 **MCP servers**: add, edit, copy (to one profile or to all) and remove MCP servers, for every project or for one. Tokens in environment variables and headers stay out of the list.
- 🧳 **Export and import**: move a profile to another computer as a `.zip`, with or without conversations. Login credentials never travel.
- 🧷 **Plugins**: see the plugins installed in each profile, their version and marketplace, and turn them on or off.
- 📁 **Profile by folder**: type `claude` in a work folder and it starts in your Work profile. One switch in the Profiles tab adds one marked line to your `~/.zshrc` (backed up, undoable); the folder rules you already use for projects decide the profile, and a `CLAUDE_CONFIG_DIR` you set yourself still wins.
- 🔗 **Sharing**: share `skills`, `plugins`, `agents`, `commands`, `CLAUDE.md` or `settings.json` with the source profile through symlinks. Install once, use everywhere. The confirmation previews what the link replaces.
- ⚙️ **Settings**: every setting of Claude Code's `/config` panel, in groups, plus the commit and pull request attribution switches. Dropdowns offer only the values Claude Code accepts and show which file each value comes from. Apply a value or a permission rule to every profile in one undoable step. Edit `CLAUDE.md`, permissions and the raw JSON, with validation.
- 📟 **Status line**: build Claude Code's status line without writing a script. Tick what to show (profile, model, path, git branch, context used, tokens, session cost, 5-hour and weekly limits and more), drag it into order, pick brackets, separator and colors or start from a preset, and check the live preview; one click puts it in every profile. A small `sh` + `jq` script, never your own one overwritten. [How it works](https://cc-profiles.andreaia.com/status-line.html)
- ⏪ **Backups**: every operation is journaled. **Restore** undoes it, and a restore can itself be undone. Old ones are deleted automatically after 90 days (or 15, 30, 60), except those you mark **Keep**.
- 🩺 **Health**: login status, config validity, broken links, memory indexes, and projects whose folder disappeared, with candidate folders to relink them to.
- 🔍 **Search everything**: one field searches projects, memories, skills, MCP servers and `CLAUDE.md` in every profile, and opens what you pick.
- ⚖️ **Compare two profiles**: settings, permissions, skills, MCP servers, `CLAUDE.md` and plugins side by side, with one-click copies of what differs.
- 🧭 **Fast to get around**: keyboard shortcuts (`/` to search, `g` then a letter to open a tab, `?` for the list), and quick even on homes with thousands of projects.
- ⌨️ **Inside Claude Code**: `/cc-profiles` opens the app from any session, `/cc-profiles restart` restarts it after an update; `cc-profiles label` shows the active profile in your status line.
- 🌓 **Light and dark**: the theme button in the header picks System, Light or Dark; System follows your operating system.
- 🔒 **Local and private**: listens on `127.0.0.1` only, with a token on every request. Nothing is sent anywhere unless you click to check for updates or to install Claude Code.
- 🔄 **Updates from the app**: cc-profiles checks PyPI once a day (or when you click **Check for updates** in the (i) panel) and shows a dot when a new version is out; one click updates and restarts it (pipx, uv or Homebrew), then it shows what's new. **Report a problem…** opens a bug report with the versions filled in.

---

## Screenshots

<table>
  <tr>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/memories-dark.jpg">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/memories-light.jpg">
        <img src="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/memories-light.jpg" alt="The Memories tab: projects on the left, the memories of the selected project with their descriptions, and an editor">
      </picture>
      <p align="center"><b>Memories</b>: every project's memories, with an editor</p>
    </td>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/conversations-dark.jpg">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/conversations-light.jpg">
        <img src="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/conversations-light.jpg" alt="The Conversations tab: the projects of a profile, the conversations of the selected one, and a read-only viewer of its messages">
      </picture>
      <p align="center"><b>Conversations</b>: read, move or delete a single conversation</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/usage-dark.jpg">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/usage-light.jpg">
        <img src="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/usage-light.jpg" alt="The Usage tab: total tokens, estimated cost, replies and cache share, then a bar chart of tokens per day over the last 30 days">
      </picture>
      <p align="center"><b>Usage</b>: tokens and estimated cost per day, project and model</p>
    </td>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/statusline-dark.jpg">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/statusline-light.jpg">
        <img src="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/statusline-light.jpg" alt="The status line editor: pieces to tick and reorder, each with its brackets, a separator, colors and a live preview of the line">
      </picture>
      <p align="center"><b>Status line</b>: build it by ticking boxes, with a live preview</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/skills-dark.jpg">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/skills-light.jpg">
        <img src="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/skills-light.jpg" alt="The Skills tab: a grid of skill cards with their descriptions, and the SKILL.md of the selected skill">
      </picture>
      <p align="center"><b>Skills</b>: browse, create, edit and copy skills</p>
    </td>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/mcp-dark.jpg">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/mcp-light.jpg">
        <img src="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/mcp-light.jpg" alt="The MCP tab: the MCP servers of a profile with their type, command or URL, and where they are available">
      </picture>
      <p align="center"><b>MCP</b>: servers for every project or for one</p>
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/compare-dark.jpg">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/compare-light.jpg">
        <img src="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/compare-light.jpg" alt="The Compare tab: the settings of two profiles side by side, with the differences highlighted and buttons to copy them">
      </picture>
      <p align="center"><b>Compare</b>: two profiles side by side, one-click copies</p>
    </td>
    <td width="50%" valign="top">
      <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/settings-dark.jpg">
        <source media="(prefers-color-scheme: light)" srcset="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/settings-light.jpg">
        <img src="https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/docs/assets/screenshots/settings-light.jpg" alt="The Settings tab: the settings of Claude Code's /config panel in groups, the file each value comes from, and the values of the other profiles">
      </picture>
      <p align="center"><b>Settings</b>: everything in /config, applied to one profile or all</p>
    </td>
  </tr>
</table>

The screenshots show sample data from the [/sandbox skill](https://github.com/andreaiannarone/cc-profiles/blob/main/.claude/skills/sandbox/SKILL.md). GitHub shows them in your theme, light or dark.

---

## Why

Claude Code reads its configuration from `~/.claude`, or from whatever directory `CLAUDE_CONFIG_DIR` points to. Each directory is a separate **profile** with its own memory, conversations, prompt history, settings and login:

```bash
claude                                     # default profile (~/.claude)
CLAUDE_CONFIG_DIR=~/.claude-work claude    # a second profile
```

That is great for keeping contexts apart, but maintaining profiles by hand is painful:

- Conversations live in folders named like `-Users-you-code-client--api`, one per project path.
- The prompt history is one JSONL file to filter line by line.
- The default profile's settings live in `~/.claude.json`, *outside* `~/.claude`.
- When you move a project folder, Claude Code silently loses its history.

cc-profiles does all of this for you, from a page in your browser.

---

## How It Works

**Core components:**

1. **Local server**: a small Python package, standard library only, one module per area. It listens on `127.0.0.1`, checks the `Host` header against DNS rebinding and a random token against requests from other websites.
2. **Single-page UI**: one HTML file with inline CSS and vanilla JavaScript, no build step and nothing loaded from the internet. Light and dark themes, or the system's.
3. **Backups with a journal**: before any change, the files it touches are copied to `~/.cc-profiles/backups/<date>_<operation>/`, and every step (copy, move, new folder, new link) is written to a `manifest.json`. **Restore** replays the journal backwards.
4. **Atomic writes**: every file is written to a temporary file in the same folder and then renamed, so a running Claude Code never reads a half-written file. Writes follow symlinks, so shared files stay shared.
5. **Path recovery**: Claude Code's project folder names cannot be turned back into paths. cc-profiles rebuilds them from config files, prompt history and the `cwd` of conversations, and walks the disk when nothing mentions them.
6. **Launchers and commands**: new profiles get a small `claude-<id>` script in `~/.local/bin`; `cc-profiles install-command` adds `/cc-profiles` to Claude Code. Files cc-profiles creates carry a mark, and it never overwrites a file without it.

See [Architecture](https://cc-profiles.andreaia.com/architecture.html) and [Claude Code's on-disk formats](https://cc-profiles.andreaia.com/claude-code-formats.html) for details.

---

## Usage

```bash
cc-profiles                   # starts on http://127.0.0.1:4777 and opens the browser; ctrl+C stops it
cc-profiles --port 4800       # another port
cc-profiles --no-browser      # just the server
cc-profiles open              # starts it in the background if needed, opens the browser and returns
cc-profiles restart           # stops it and starts it again, e.g. after an update (cc-profiles stop only stops it)
cc-profiles install-command   # adds the /cc-profiles command to Claude Code in every profile
cc-profiles label             # prints the name of the active profile, for status lines
```

### Open it from Claude Code

Type `/cc-profiles` in any Claude Code session: the app starts in the background, your browser opens on it, and the session goes on. `/cc-profiles restart` and `/cc-profiles stop` restart or stop the app. The command is a small file, `commands/cc-profiles.md`, that `cc-profiles install-command` writes in every profile; profiles you create from the app get it automatically. Profiles that share `commands` with the source profile get it through the link.

### Commands for each profile

When cc-profiles creates a profile, it adds a launcher to `~/.local/bin`. For a profile called `work` that is `claude-work`:

```bash
#!/bin/sh
CLAUDE_CONFIG_DIR="$HOME/.claude-work" exec claude "$@"
```

The script works in every shell. Make sure `~/.local/bin` is in your `PATH`; the official Claude Code installer usually adds it.

### Show the profile in your status line

`cc-profiles label` prints the name of the profile in use, based on `CLAUDE_CONFIG_DIR`. Call it from your [Claude Code status line](https://code.claude.com/docs/en/statusline) script:

```bash
profile=$(cc-profiles label 2>/dev/null)
printf '(%s) ' "$profile"
```

### Rules

The **Projects** tab assigns each project to a profile using rules: "a path containing this text belongs to that profile". Create them from the UI with **Assign…**. They are checked in order, the first match wins and new rules go first:

```json
{ "match": "code/work", "profile": "work" }
```

`"profile": "shared"` marks paths that may appear in every profile, like your home folder.

---

## Documentation

📚 **[Full documentation](https://cc-profiles.andreaia.com)** at cc-profiles.andreaia.com

### Getting Started

- **[Why cc-profiles](https://cc-profiles.andreaia.com/why.html)**: what it adds to `CLAUDE_CONFIG_DIR` and shell aliases
- **[Getting started](https://cc-profiles.andreaia.com/getting-started.html)**: install, first run, launcher commands, `/cc-profiles`
- **[Concepts](https://cc-profiles.andreaia.com/concepts.html)**: profiles, the source profile, projects, rules, sharing, backups
- **[FAQ](https://cc-profiles.andreaia.com/faq.html)**: several accounts, a profile per project, credentials, safety, undo

### How-to

- **[Separate work and personal](https://cc-profiles.andreaia.com/how-to/work-and-personal.html)**: a Work profile in five minutes
- **[Move a project](https://cc-profiles.andreaia.com/how-to/move-a-project.html)**: with its conversations, memories, history and settings
- **[Relink a moved folder](https://cc-profiles.andreaia.com/how-to/relink-a-moved-folder.html)**: get the history back after renaming a folder
- **[Share skills between profiles](https://cc-profiles.andreaia.com/how-to/share-skills.html)**: share the folder or copy one skill

### Guides by Tab

- **[Projects](https://cc-profiles.andreaia.com/guides/projects.html)**: move, relink, assign
- **[Memories](https://cc-profiles.andreaia.com/guides/memories.html)**: browse, edit, move
- **[Conversations](https://cc-profiles.andreaia.com/guides/conversations.html)**: read, move one to another profile, delete
- **[Usage](https://cc-profiles.andreaia.com/guides/usage.html)**: tokens and estimated cost per day, project, model and profile
- **[Profiles and sharing](https://cc-profiles.andreaia.com/guides/profiles.html)**: create, edit, delete, share
- **[Profile by folder](https://cc-profiles.andreaia.com/guides/profile-by-folder.html)**: `claude` starts in the profile of the folder you are in
- **[Skills and MCP servers](https://cc-profiles.andreaia.com/guides/skills-and-mcp.html)**: create, edit, copy, delete
- **[Plugins](https://cc-profiles.andreaia.com/guides/plugins.html)**: see the installed plugins and turn them on or off
- **[Search and compare](https://cc-profiles.andreaia.com/guides/search-and-compare.html)**: search every profile at once, compare two side by side
- **[Export and import](https://cc-profiles.andreaia.com/guides/export-import.html)**: move a profile to another computer
- **[Settings](https://cc-profiles.andreaia.com/guides/settings.html)**: the `/config` settings, `CLAUDE.md`, permissions, raw JSON
- **[Status line](https://cc-profiles.andreaia.com/status-line.html)**: build Claude Code's status line in Settings, or write your own
- **[Backups](https://cc-profiles.andreaia.com/guides/backups.html)**: what gets saved and how restoring works
- **[Health and About](https://cc-profiles.andreaia.com/guides/health.html)**: checks, orphan projects, installing Claude Code

### Reference

- **[Configuration](https://cc-profiles.andreaia.com/configuration.html)**: `config.json`, command line, environment variables
- **[Troubleshooting](https://cc-profiles.andreaia.com/troubleshooting.html)**: common problems and their fixes
- **[Glossary](https://cc-profiles.andreaia.com/glossary.html)**: the words the app uses
- **[Uninstall](https://cc-profiles.andreaia.com/uninstall.html)**: remove cc-profiles; your profiles stay as they are
- **[What's new](https://cc-profiles.andreaia.com/changelog.html)**: every release

### For Contributors

- **[Architecture](https://cc-profiles.andreaia.com/architecture.html)**: how the code is organized and why
- **[Claude Code's on-disk formats](https://cc-profiles.andreaia.com/claude-code-formats.html)**: what the app reads and writes
- **[HTTP API](https://cc-profiles.andreaia.com/api.html)**: every endpoint the UI uses
- **[Contributing](https://github.com/andreaiannarone/cc-profiles/blob/main/CONTRIBUTING.md)** and **[design system](https://github.com/andreaiannarone/cc-profiles/blob/main/DESIGN.md)**

---

## Configuration

cc-profiles keeps its own data in `~/.cc-profiles/`, never in the repository:

| Path | Content |
|---|---|
| `~/.cc-profiles/config.json` | profiles, rules, folders to search when relinking |
| `~/.cc-profiles/backups/` | one folder per operation: a `manifest.json` journal plus the original files |
| `~/.cc-profiles/server.log` | output of the server started by `cc-profiles open` |
| `~/.local/bin/claude-<id>` | launchers created for new profiles |
| `<profile>/commands/cc-profiles.md` | the `/cc-profiles` command, if you added it |

| Environment variable | Effect |
|---|---|
| `CC_PROFILES_PORT` | default port instead of 4777 |
| `CC_PROFILES_HOME` | data folder instead of `~/.cc-profiles` |
| `CC_PROFILES_QUIET` | if set, do not log HTTP requests to the terminal |

See the **[Configuration reference](https://cc-profiles.andreaia.com/configuration.html)** for `config.json` and every option.

---

## System Requirements

- **macOS or Linux**; on Windows, inside [WSL 2](https://cc-profiles.andreaia.com/getting-started.html#windows-wsl)
- **Python 3.9 or later**: macOS's built-in Python works
- **pipx, uv or Homebrew** to install it
- **[Claude Code](https://code.claude.com/docs/en/setup)**, or let cc-profiles install it for you with the official installer

No dependencies: cc-profiles uses only the Python standard library.

---

## Security

- The server listens on `127.0.0.1` only and accepts only `Host: 127.0.0.1:<port>` or `localhost:<port>`, which blocks DNS rebinding.
- Every API call needs a random token, generated at each start and embedded in the page, so other websites cannot control the app.
- Writes are atomic (temporary file, then rename), so Claude Code never reads a half-written file, even while it is running.
- Names of projects, memories, skills and backups are validated against path traversal.
- Login credentials are never copied between profiles: each profile signs in on its own. Copying an MCP server copies its configuration, never its sign-in.
- cc-profiles reaches the internet only to ask pypi.org for its latest version, once a day (PyPI sees your IP address; turn it off in the (i) panel to check only when you click), and when you click **Install** to run the official Claude Code installer.

See [SECURITY.md](https://github.com/andreaiannarone/cc-profiles/blob/main/SECURITY.md) to report a vulnerability.

---

## Limitations

- Claude Code's file formats are not a public API. Settings dropdowns were checked against Claude Code 2.1.289; the **About** panel shows which version you have.
- "Session open" means a `claude` process is running in the profile (read from the process list on macOS and from `/proc` on Linux), or a conversation was written in the last 2 minutes.
- Claude Code keeps `.claude.json` in memory while it runs: restart open sessions after changing their MCP servers.
- Deleting a profile does not remove credentials that Claude Code may have stored in the macOS Keychain for it.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| "Port 4777 is busy" | cc-profiles is already running: open the URL, or start it with `--port 4778` |
| A tab says the page is newer than the server | you updated cc-profiles while it was running: run `cc-profiles restart` (or `/cc-profiles restart` in Claude Code), then reload the page |
| `cc-profiles: command not found` | run `pipx ensurepath` (or `uv tool update-shell`) and open a new terminal |
| `/cc-profiles` does not appear in Claude Code | run `cc-profiles install-command`, then restart the session |
| A project shows "folder not found on disk" | click **Relink…** and pick the folder where it lives now |
| A setting has no effect | the **Settings** tab shows which file the value comes from: `settings.local.json` wins over `settings.json` |

See the **[Troubleshooting guide](https://cc-profiles.andreaia.com/troubleshooting.html)** for more.

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository and create a branch
2. Make your changes with tests: every operation that writes must go through `Backup` and have a test that restores it
3. Keep it standard library only and compatible with Python 3.9
4. Update the documentation and `CHANGELOG.md`
5. Open a pull request

See [CONTRIBUTING.md](https://github.com/andreaiannarone/cc-profiles/blob/main/CONTRIBUTING.md) to run the app and the tests locally. If you use Claude Code, the repository's `.claude/` folder keeps you on a sandbox and has skills for the common chores. Good first contributions: translations (the UI is English only), Windows support, a "dry run" preview for big operations.

---

## License

cc-profiles is licensed under the **[GNU General Public License v3.0 or later](https://github.com/andreaiannarone/cc-profiles/blob/main/LICENSE)**. © Andrea Iannarone

You can use, study, change and share it freely. If you distribute it, modified or not, you must do so under the same license and with the source code. Version 0.1.0 was released under MIT and stays available under it.

---

## Support

- **Documentation**: [cc-profiles.andreaia.com](https://cc-profiles.andreaia.com)
- **Issues**: [GitHub Issues](https://github.com/andreaiannarone/cc-profiles/issues)
- **Repository**: [github.com/andreaiannarone/cc-profiles](https://github.com/andreaiannarone/cc-profiles)
- **Buy me a coffee**: [buymeacoffee.com/andreaiannarone](https://buymeacoffee.com/andreaiannarone)
- **Author**: Andrea Iannarone ([@andreaiannarone](https://github.com/andreaiannarone))

---

<p align="center"><b>Built with Claude Code</b> | <b>Made for Claude Code</b> | <b>Pure Python standard library</b></p>
<p align="center">© 2026 <a href="https://andreaiannarone.com">Andrea Iannarone</a></p>
