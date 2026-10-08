# Uninstall

Removing cc-profiles never touches your Claude Code profiles: their conversations, memories, settings and logins stay where they are, and Claude Code keeps working in each of them. Only what cc-profiles added goes away.

## With one command

```sh
cc-profiles uninstall            # keeps ~/.cc-profiles (settings, templates, backups)
cc-profiles uninstall --purge    # deletes it too
```

It lists what it is going to do and asks first (`--yes` skips the question). Then it stops the server, stops adding `/cc-profiles` and removes the copies it wrote (a copy you wrote yourself stays), removes the profile by folder line from your shell files, and uninstalls the app with the tool you installed it with: pipx, uv, Homebrew or pip. The command and the shell line go to a backup in `~/.cc-profiles`, unless you delete that folder with `--purge`.

If something is broken and you want to keep using cc-profiles, `cc-profiles reinstall` installs it again from scratch instead, keeping your settings and backups.

The rest of this page does the same by hand, and says what stays.

## By hand

Do the steps in this order: the app helps with the first ones.

### 1. Turn off profile by folder

If you turned on [Profile by folder](guides/profile-by-folder.md), turn it off in the **Profiles** tab. That removes the line ending in `# cc-profiles: profile by folder` from `~/.zshrc`, `~/.bashrc` or `~/.bash_profile`.

You can skip this: the line checks that `cc-profiles` exists, so once it is uninstalled `claude` simply runs as usual. Remove the line by hand later if you like.

### 2. Remove the /cc-profiles command

cc-profiles wrote `commands/cc-profiles.md` in each profile. First tell it to stop, or it adds them again at its next start, then remove the ones it wrote, which start with `# managed by cc-profiles`:

```sh
cc-profiles install-command --off
grep -l "managed by cc-profiles" ~/.claude*/commands/cc-profiles.md | xargs rm
```

If you installed the plugin instead, in Claude Code:

```
/plugin uninstall cc-profiles@cc-profiles
/plugin marketplace remove cc-profiles
```

### 3. Uninstall the app

With the tool you installed it with:

```sh
cc-profiles stop              # stop the server if it is running
pipx uninstall cc-profiles    # or: uv tool uninstall cc-profiles, brew uninstall cc-profiles
```

### 4. Remove its data (optional)

`~/.cc-profiles` holds the app's configuration (profile names, rules, search folders), its templates and every **backup**. Backups are the only way to undo past changes: keep the folder until you are sure you do not need them.

```sh
rm -rf ~/.cc-profiles
```

## What stays, and still works

| What | Still works without cc-profiles | To remove it |
|---|---|---|
| your profiles (`~/.claude`, `~/.claude-<id>`) | yes: they are Claude Code's own folders | delete a profile from the **Profiles** tab *before* uninstalling, or remove its folder by hand |
| launchers such as `claude-work` in `~/.local/bin` | yes: each one only sets `CLAUDE_CONFIG_DIR` and runs `claude` | `grep -l "managed by cc-profiles" ~/.local/bin/claude-* \| xargs rm` |
| GitHub CLI folders (`~/.config/gh-<id>`, `~/.config/gh-accounts`) and `GH_CONFIG_DIR` in each profile's `settings.json` | yes: each profile keeps its GitHub account | `rm -rf ~/.config/gh-<id>`, then remove `GH_CONFIG_DIR` from the profile's `env` (**Settings → Advanced editor**); keep `~/.config/gh`, your terminal's |
| shared items (links such as `~/.claude-work/skills → ../.claude/skills`) | yes: they are plain symlinks | turn sharing off in the **Profiles** tab before uninstalling, to give each profile its own copy |
| the status line made by cc-profiles (`statusline.sh` in each profile) | yes; without `~/.cc-profiles/config.json` it shows the folder name (`work`) instead of the profile name | **Settings → Status line → Off** before uninstalling, or edit `statusLine` in `settings.json` |

To keep only one profile and forget the others, delete them from the **Profiles** tab first: **First move conversations, memories and history to …** brings their history into the profile you keep. See [Profiles and sharing](guides/profiles.md#delete-a-profile).
