# Skills and MCP servers

Two tabs manage, for one profile at a time, the skills in its `skills/` folder (**Skills**) and the MCP servers in its `.claude.json` (**MCP**). Pick the profile at the top of either tab: the choice carries over when you switch between the two. You can also click **Skills** or **MCP** on a profile in the **Profiles** tab. The line next to the selector shows the account the profile is signed in with.

Every change goes to a backup first, like any other operation, and applies from the next Claude Code session in that profile.

## Skills

A skill is a folder `skills/<name>/` with a `SKILL.md` file: a frontmatter with `name` and `description`, then the instructions. Claude reads the description to decide when to use the skill.

- **Browse**: each card shows the skill's name and description, how many files its folder holds, and **linked** when the folder is a link to somewhere else (tools such as `npx skills` install skills this way). Type in *Filter skills…* to narrow the list.
- **Edit**: click a card to open its `SKILL.md`. The other files of the folder are listed above the editor. **Save** keeps the previous version in the backup.
- **New skill…**: asks for a name (lowercase letters, digits and dashes) and a description, and creates `skills/<name>/SKILL.md` ready to fill in.
- **Copy to…**: copies the whole folder to another profile. It is refused if that profile already has a skill with the same name, or if the two profiles [share](profiles.md) their skills (they already see the same ones).
- **Copy to all…**: copies the folder to every profile that does not have the skill. The confirmation lists the profiles that get it and the ones skipped, with the reason: they already have a skill with that name, or they share their skills with the source profile (or with a profile that gets it), so they already see it. One backup covers every profile: one Restore undoes it all.
- **Delete**: moves the folder to the backup. For a linked skill only the link is removed; the folder it points to is untouched.

If the profile shares `skills` with others, the header says so: editing, adding or deleting a skill changes it for all of them.

Skills that come from plugins are not listed here: manage them with `/plugin` in Claude Code.

## MCP servers

The tab lists the servers configured in the profile's `.claude.json` (for the default profile, `~/.claude.json`):

- **All projects**: the `mcpServers` key, what `claude mcp add --scope user` writes. These servers are available in every project.
- **a project**: `projects.<path>.mcpServers`, what `claude mcp add` writes by default (local scope). The badge shows the project folder; hover it for the full path.

Each row shows the type (`stdio`, `http` or `sse`), the command or URL, and the *names* of its environment variables and headers. Their values are not shown in the list, because they often hold tokens; **Edit…** shows them.

- **Add server…**: name, where it is available, type, then the command, arguments (one per line) and environment variables (`NAME=value`, one per line) for a local `stdio` server, or the URL and headers (`Name: value`) for a remote one.
- **Edit…**: the same form, filled in. You can rename the server or change its type; where it is available cannot change (remove it and add it again). Fields the form does not show, such as `timeout`, are kept.
- **Copy to…**: adds the server to another profile, available in all projects. Only the configuration is copied: if the server needs a sign-in (OAuth), run `/mcp` in the other profile to authenticate there.
- **Copy to all…**: adds the server, available in all projects, to every profile that does not have a server with that name. The confirmation lists the profiles that get it and the ones skipped: those that already have a server with that name, those using the same `.claude.json`, and those whose `.claude.json` cannot be read yet (start Claude Code in them once). One backup covers every profile. Sign-ins are not copied.
- **Delete**: removes it from `.claude.json`, after saving the file in the backup.

Not listed here, because they are configured elsewhere:

- servers in a project's `.mcp.json`, which is part of the project and usually committed with it
- servers from plugins
- claude.ai connectors (Gmail, Google Drive, Canva…), which belong to your claude.ai account

Claude Code keeps `.claude.json` in memory while it runs. Close open sessions in the profile before changing its MCP servers, or restart them afterwards.
