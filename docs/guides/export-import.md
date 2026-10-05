# Export and import a profile

Move a profile to another computer, or keep a copy of it: export it as a `.zip` from one cc-profiles and import it into another.

## Export

In the **Profiles** tab, click **Export…** on a profile. Choose whether to include conversations, prompt history and file snapshots, then the browser saves `cc-profiles-<id>-<date>.zip`.

The export holds:

| What | Notes |
|---|---|
| the profile folder | settings, `CLAUDE.md`, skills, agents, commands, output styles, plugins |
| its `.claude.json` | user MCP servers and preferences; per-project settings only with conversations |
| the general memory | the memories of your home folder's project, which load in every session |
| conversations, prompt history, file snapshots | only if you tick the box |
| `cc-profiles-export.json` | a manifest: format, cc-profiles version, profile name and id, date, what was included |

It never holds:

- **login credentials**: `.credentials.json` is skipped and the account (`oauthAccount`, `userID`) is removed from `.claude.json`. The imported profile logs in on its own, so a copied token cannot be invalidated when the original refreshes it;
- runtime and cache folders (`sessions`, `shell-snapshots`, `cache`, …);
- files outside your home folder, even when a link inside the profile points to them.

Items the profile **shares** with the source profile are exported with their real content, so the import works on a computer where nothing is shared. Skills linked from elsewhere in your home folder are exported the same way. Files that hold absolute paths to the profile folder (`settings.local.json`, the plugin lists) are rewritten so the import can point them to the new folder.

## Import

In the **Profiles** tab, click **Import profile…**, pick the `.zip`, and choose a name and an id (they are suggested from the file name). cc-profiles creates `~/.claude-<id>`, its `claude-<id>` command in `~/.local/bin` and the `/cc-profiles` command, and adds the profile to the list.

The archive is checked before anything is written: an entry with an absolute path, a `..`, a link or a device file, or anything that is not part of an export, refuses the whole import. Archives over 500 MB, or over 5 GB once unpacked, are refused too.

The imported profile is **not logged in**: run its command and log in with `/login`.

Conversations keep the project paths of the computer they come from. If your projects live elsewhere on the new computer, relink them from the **Projects** tab or from **Health**.

Like every operation, the import goes to the backup: **Restore** removes the profile, its command and its folder.
