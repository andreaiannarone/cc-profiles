# Profiles and sharing

## Create a profile

**+ New profile** asks for:

- **Name**: shown in the UI and the [status line](../status-line.md), for example *Work*.
- **Id**: lowercase letters, digits and dashes, for example `work`. It defines the folder `~/.claude-work` and the command `claude-work`.
- **Base**:
  - *Copy of …* copies settings, `CLAUDE.md`, skills, plugins, agents, MCP servers and per-project settings from an existing profile. Optionally it also copies conversations, history and project memories. General memories (your home project) are always copied.
  - *Empty* starts from scratch, with only the status line setting of the source profile.
- **Share with the source profile**: which items become [links](../concepts.md#sharing) instead of copies. Skills and plugins are ticked by default.

What a new profile never gets:

- **login credentials** (`.credentials.json`) and account data (`oauthAccount`, `userID`): run the new command and use `/login`. A copied token could be invalidated when the original profile refreshes it.
- runtime state: caches, open sessions, telemetry.

cc-profiles also creates the launcher `~/.local/bin/claude-<id>` (see [Getting started](../getting-started.md#starting-claude-code-in-a-profile)).

## Edit a profile

**Edit** changes:

- **Name**: updates the UI and the status line right away.
- **Command**: renames the launcher, or rewrites the alias if the profile was set up with a shell alias before. The source profile's command is `claude` and cannot change. A command that already exists as another program is refused.

The **folder never changes**: the profile's files store absolute paths to it, so renaming it would break them.

## Delete a profile

**Delete** offers two options:

- **Delete everything**: the whole folder goes to the backup.
- **First move conversations, memories and history to …**: every project with content is [moved](projects.md#move-a-project-to-another-profile) to another profile, together with the remaining prompt history, and then the folder goes to the backup.

In both cases the profile leaves `config.json` and its launcher (or shell alias) is removed. Type the profile's name to enable the button.

Deleting is refused:

- for the source profile, because the others share from it;
- while a session is open in the profile (a conversation was written in the last 2 minutes), because a running Claude Code would keep writing into a folder that is gone.

## Share items

Under **Sharing**, each secondary profile has a switch per item:

| Item | What sharing means |
|---|---|
| `skills` | same local skills everywhere |
| `plugins` | same installed plugin files (enabling is per profile, in `settings.json`) |
| `agents` | same custom subagents |
| `commands` | same custom slash commands |
| `CLAUDE.md` | same global instructions |
| `settings.json` | same settings, status line, enabled plugins, permissions and hooks |

Turning a switch **on** replaces the profile's own copy with a link. The old copy goes to the backup, and the confirmation lists anything the source profile does not have, so you can copy it over first. Turning it **off** gives the profile an independent copy of the current source content.
