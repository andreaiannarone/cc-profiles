# Profiles and sharing

The **Profiles** tab lists your profiles with their command, folder and how many conversations, projects and memories each has. From here you create, edit and delete profiles, start one from a template, choose what each profile shares with the source profile, and turn on [profile by folder](profile-by-folder.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../assets/screenshots/profiles-dark.jpg">
  <img src="../assets/screenshots/profiles-light.jpg" alt="The Profiles tab: three profiles with their command, folder and counts, and the Sharing switches below" width="1440" height="900" loading="lazy">
</picture>

## Create a profile

**New profile** (in the Profiles tab, or the **+ New profile** card at the top) asks for:

- **Name**: shown in the UI and the [status line](../status-line.md), for example *Work*.
- **Id**: lowercase letters, digits and dashes, for example `work`. It defines the folder `~/.claude-work` and the command `claude-work`.
- **Base**:
  - *Copy of …* copies settings, `CLAUDE.md`, skills, plugins, agents, MCP servers and per-project settings from an existing profile. Optionally it also copies conversations, history and project memories. General memories (your home project) are always copied.
  - *From template: …* starts from a [template](#templates): its settings, `CLAUDE.md`, permissions, skills, agents, commands, output styles and MCP servers, as the profile's own copies, except the items you share. No conversation comes along.
  - *Empty* starts from scratch, with only the status line setting of the source profile.
- **Share with the source profile**: which items become [links](../concepts.md#sharing) instead of copies. Skills and plugins are ticked by default; with a template only plugins are, so the template's own skills are used. You can change the choice later, under **Sharing**.

With a template, an item you share is linked to the source profile **instead of** being filled from the template: the template's copy of it is not used. The dialog lists what each shared item skips, for example *skills: shared with Default, the template's 3 skills are not copied*, and the confirmation after creating says the same. Templates never hold plugins, so sharing `plugins` is how a profile created from a template gets the plugins of the source profile.

What a new profile never gets:

- **login credentials** (`.credentials.json`) and account data (`oauthAccount`, `userID`): run the new command and use `/login`. A copied token could be invalidated when the original profile refreshes it.
- runtime state: caches, open sessions, telemetry.

cc-profiles also creates the launcher `~/.local/bin/claude-<id>` (see [Getting started](../getting-started.md#starting-claude-code-in-a-profile)) and adds the `/cc-profiles` command to the new profile, so you can open this app from it right away. If the profile shares `commands` with the source profile, the command goes into the source and reaches both through the link. A `cc-profiles.md` that cc-profiles did not write is left as it is.

Items you choose to share that the source profile does not have yet are created there, empty, so the link always works.

## Templates

A template is a reusable starting point for new profiles. **Templates…** in the Profiles tab lists them and saves a new one from any profile.

A template holds the profile's `settings.json` and `settings.local.json` (with permissions and hooks), `CLAUDE.md`, `skills/`, `agents/`, `commands/`, `output-styles/` and the MCP servers of `.claude.json` (user scope). It **never** holds conversations, prompt history, memories, plugins, login credentials (`.credentials.json`) or account data (`oauthAccount`, `userID`). Shared items are saved as real files, so the template does not depend on the source profile.

Templates are `.zip` files in `~/.cc-profiles/templates/`, in the same format as an [export](export-import.md) without conversations. Creating a profile from a template uses the import code, so paths inside `settings.local.json` point to the new folder.

Saving, deleting and creating a profile from a template each have a backup. A deleted template goes to the backup and Restore brings it back.

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

The dialog shows what the chosen option does before you confirm: how many projects, conversations, memories and prompts move and where, and under **Show the files and folders it touches** every item, including the launcher, the alias line in your shell file, the entry in `config.json` and the folder that goes to the backup. The preview changes nothing.

Deleting is refused:

- for the source profile, because the others share from it;
- while a session is open in the profile (a `claude` process is running in the profile, or one of its conversations was written in the last 2 minutes), because a running Claude Code would keep writing into a folder that is gone.

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

Both confirmations have **Show the files and folders it touches**: the own copy that goes to the backup, each item only that copy has, the link and its target, and what is created in the source profile when it does not have the item yet; when separating, the link that goes to the backup and the files copied in its place.

## A GitHub account per profile

Signing in to GitHub is not part of a profile: the GitHub CLI (`gh`) keeps one sign-in for your whole user, so by default every profile pushes and opens pull requests as the same account. The **GitHub** section at the bottom of the Profiles tab gives each profile its own.

The profile cards show the GitHub account next to the Claude account: **GitHub as …**.

### New profiles

**New profile** has the option *its own GitHub account folder* (on by default when `gh` is signed in). The new profile then gets `~/.config/gh-<id>`, next to its `~/.claude-<id>`, with `GH_CONFIG_DIR` pointing to it. The folder starts signed in as the account of `~/.config/gh`: cc-profiles copies `config.yml` and `hosts.yml` without any token line, and `gh` finds the token in the keychain by the user's name. To move that profile to another account, sign in there:

```sh
GH_CONFIG_DIR=~/.config/gh-<id> gh auth login
```

If your token is written in `hosts.yml` rather than in the keychain (`gh auth login --insecure-storage`), it is not copied, and the message says to sign in to the new folder. A profile whose `settings.json` is shared also shares its GitHub account, so it gets no folder. Two folders signed in as the same user share the keychain token: `gh auth logout` in one signs the other out too.

### Existing profiles

1. Sign in with the other account once, in a terminal, in a separate folder of the GitHub CLI. **Add account…** writes the command for you, with a button to copy it:
   ```sh
   GH_CONFIG_DIR=~/.config/gh-work gh auth login
   ```
   Any `~/.config/gh-<name>` folder works. Then click **I signed in, refresh**.
2. In the table, pick the account in the profile's **GitHub account** menu: it is saved right away. **Commit identity…** sets the name and email of its commits (both or neither), for example the `…@users.noreply.github.com` address of that account.

cc-profiles writes them in the `env` of the profile's `settings.json`, which Claude Code passes to every command it runs:

| Variable | Effect |
|---|---|
| `GH_CONFIG_DIR` | `gh` signs in as that account; left out for the default folder (`~/.config/gh`) |
| `GIT_AUTHOR_NAME`, `GIT_COMMITTER_NAME` | the name on commits made in that profile |
| `GIT_AUTHOR_EMAIL`, `GIT_COMMITTER_EMAIL` | the email on those commits |

A variable already in `settings.local.json` is changed there, so it keeps winning. Picking the default account with an empty name and email removes the variables and leaves the rest of `env` alone. Every change goes to the backup.

For `git push` to follow the account too, git must ask `gh` for GitHub passwords: run `gh auth setup-git` once. The section warns when it is not set up, with a button to copy the command. It applies to Claude Code sessions in the profile, not to your own terminal, and an open session picks it up when it restarts.

cc-profiles reads only which user each folder is signed in as (the `user:` line of `hosts.yml`). Tokens stay in the GitHub CLI and the system keychain, and are never read or copied.
