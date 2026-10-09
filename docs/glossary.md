# Glossary

The words the app and this documentation use, in alphabetical order.

## Agent
A subagent: a file `agents/<name>.md` in a profile with a description, instructions, a model and the tools it may use. Claude hands it a task when the description fits, and it works in a context of its own. See [Agents](guides/agents.md).

## Backup
A folder in `~/.cc-profiles/backups/` saved before every change, with the original files and a journal of each step. **Restore** replays the journal backwards. See [Backups](guides/backups.md).

## Connector
A claude.ai connector (Gmail, Google Drive, Canva…): an MCP server that comes with your claude.ai account, so every profile signed in with it has it. A profile can keep any of them out from the MCP tab. See [claude.ai connectors](guides/skills-and-mcp.md#claudeai-connectors).

## GitHub CLI folder
Where the GitHub CLI (`gh`) keeps its sign-in: `~/.config/gh` for the Default profile and your terminal, `~/.config/gh-<id>` for each other profile. It decides which GitHub account `gh` and `git push` use in that profile's Claude Code sessions. See [A GitHub account per profile](guides/profiles.md#a-github-account-per-profile).

## Launcher
A small script in `~/.local/bin`, such as `claude-work`, that starts Claude Code in one profile by setting `CLAUDE_CONFIG_DIR`. cc-profiles creates one for each new profile. See [Getting started](getting-started.md#starting-claude-code-in-a-profile).

## Orphan project
A project whose folder no longer exists on disk, usually because it was moved or renamed. Its history is still there; **Relink…** reattaches it. See [Relink a moved folder](how-to/relink-a-moved-folder.md).

## Profile
A folder Claude Code uses for its configuration and history: `~/.claude` by default, or the one `CLAUDE_CONFIG_DIR` points to. Each has its own login, settings, memories and conversations. See [Concepts](concepts.md#profiles).

## Profile by folder
An option that makes `claude` start in the profile the rules give the folder you are in. See [Profile by folder](guides/profile-by-folder.md).

## Project
Everything Claude Code keeps about one working folder: conversations, memories, prompts and settings. It lives under `projects/` in each profile where you used it. See [Concepts](concepts.md#projects).

## Rule
A piece of a path and a profile, such as `code/work` → *Work*: every project whose path contains it belongs to that profile. See [Concepts](concepts.md#rules).

## Shared
Two meanings. A **shared item** (skills, plugins, `settings.json`…) is a link from a profile to the source profile's copy, so both see the same. A **shared rule** (`"profile": "shared"`) marks paths that may appear in every profile, like your home folder. See [Concepts](concepts.md#sharing).

## Source profile
The first profile in `config.json`, usually *Default* (`~/.claude`). Other profiles share items from it; it cannot be deleted. See [Concepts](concepts.md#the-source-profile).

## Template
A `.zip` with a profile's settings, `CLAUDE.md`, skills, agents, commands and MCP servers, used to start new profiles. It never holds conversations, memories or logins. See [Profiles and sharing](guides/profiles.md#templates).
