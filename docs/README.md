# cc-profiles documentation

cc-profiles is a local web UI to manage several [Claude Code](https://code.claude.com) profiles on one machine: move projects, memories and conversations between them, share skills and plugins, edit every setting of `/config`, build the status line, see the tokens you use, and undo any change from a backup.

```sh
curl -fsSL https://raw.githubusercontent.com/andreaiannarone/cc-profiles/main/install.sh | sh
cc-profiles open
```

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/demo-dark.gif">
  <img src="assets/demo-light.gif" alt="cc-profiles in use: a project moved between profiles, then its memories, a conversation, skills, an MCP server, a comparison and the backup">
</picture>

Source code, issues and releases are on [GitHub](https://github.com/andreaiannarone/cc-profiles); the package is on [PyPI](https://pypi.org/project/cc-profiles/).

## Using cc-profiles

1. [Getting started](getting-started.md): install, first run, launcher commands, [keyboard shortcuts](getting-started.md#keyboard-shortcuts)
2. [Concepts](concepts.md): profiles, the source profile, projects, rules, sharing, backups
3. [FAQ](faq.md): several accounts, a profile per project, credentials, safety, undo
4. Guides by tab:
   - [Projects](guides/projects.md): move, relink, assign
   - [Memories](guides/memories.md): browse, edit, move
   - [Conversations](guides/conversations.md): read, move one to another profile, delete
   - [Usage](guides/usage.md): tokens and estimated cost per day, project, model and profile
   - [Profiles and sharing](guides/profiles.md): create, edit, delete, share
   - [Profile by folder](guides/profile-by-folder.md): `claude` starts in the profile of the folder you are in
   - [Skills and MCP servers](guides/skills-and-mcp.md): browse, create, edit, copy and delete skills and MCP servers
   - [Search and compare](guides/search-and-compare.md): search every profile at once, compare two profiles side by side
   - [Plugins](guides/plugins.md): see the installed plugins and turn them on or off
   - [Export and import](guides/export-import.md): move a profile to another computer
   - [Settings](guides/settings.md): the `/config` settings, `CLAUDE.md`, permissions, raw JSON
   - [Status line](status-line.md): build the line under Claude Code's prompt, or write your own
   - [Backups](guides/backups.md): what gets saved and how restoring works
   - [Health and About](guides/health.md): checks, orphan projects, installing Claude Code
5. [Configuration reference](configuration.md): `config.json`, command line, environment variables
6. [Troubleshooting](troubleshooting.md)

## Working on cc-profiles

- [Architecture](architecture.md): how the code is organized and why
- [Claude Code's on-disk formats](claude-code-formats.md): what the app reads and writes
- [HTTP API](api.md): every endpoint the UI uses
- [Contributing](https://github.com/andreaiannarone/cc-profiles/blob/main/CONTRIBUTING.md) and [design system](https://github.com/andreaiannarone/cc-profiles/blob/main/DESIGN.md)
