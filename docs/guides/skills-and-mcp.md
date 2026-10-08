# Skills and MCP servers

Two tabs manage, for one profile at a time, the skills in its `skills/` folder (**Skills**) and the MCP servers in its `.claude.json` (**MCP**). Pick the profile at the top of either tab: the choice carries over when you switch between the two. You can also click **Skills** or **MCP** on a profile in the **Profiles** tab. The line next to the selector shows the account the profile is signed in with.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../assets/screenshots/skills-dark.jpg">
  <img src="../assets/screenshots/skills-light.jpg" alt="The Skills tab: the skills of the Default profile, with release-notes open in the editor" width="1440" height="900" loading="lazy">
</picture>

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

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="../assets/screenshots/mcp-dark.jpg">
  <img src="../assets/screenshots/mcp-light.jpg" alt="The MCP tab: the MCP servers of the Default profile, for all projects and for one project, with their type and command or URL, and the claude.ai connectors with a switch each" width="1440" height="900" loading="lazy">
</picture>

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

Claude Code keeps `.claude.json` in memory while it runs. Close open sessions in the profile before changing its MCP servers, or restart them afterwards.

## claude.ai connectors

Connectors (Gmail, Google Drive, Canva…) belong to your claude.ai account, not to the profile: every profile signed in with the same account gets the same ones, and you connect or remove them on [claude.ai](https://claude.ai/customize/connectors). What a profile can do is keep some of them out, and the **claude.ai connectors** section under the MCP servers does that with a switch:

- **A connector's switch** adds a deny rule for the whole connector, such as `mcp__claude_ai_Gmail`, to the profile's `settings.json`: in that profile Claude can no longer use any of its tools. Turning it back on removes that rule from `settings.json` and from `settings.local.json`; rules for a single tool of the connector (`mcp__claude_ai_Gmail__send_email`) are left alone.
- **All connectors** sets `"disableClaudeAiConnectors": true` in `settings.json`: Claude Code does not even connect them in that profile. While it is on, the switches of single connectors are greyed out.

The list shows the connectors Claude Code has connected in the profile at least once (it records them in `.claude.json`), plus any connector a deny rule names.

Claude Code only ever adds to that list, so a connector you removed or renamed on claude.ai would stay there. cc-profiles keeps it in step with your account by itself: when you open the MCP tab it runs `claude mcp list` in the profile, which asks claude.ai for the account's connectors with the profile's own sign-in (cc-profiles never reads the token). Then:

- a connector no longer on the account leaves the profile's list (with a backup);
- a new one appears right away, without waiting for a Claude Code session;
- a renamed one is both: the old name leaves, the new one appears. If the old name was blocked, its deny rule stays and the row says **not on the account**: turn it on to remove the rule, and it leaves the list.

`claude mcp list` also starts every MCP server of the profile to check it, so the check runs at most once an hour per profile; **Check now** runs it again. It is skipped when Claude Code is not installed, when the profile is not signed in, or when all connectors are off. If claude.ai lists no connectors at all, nothing is taken off, because that is also what a failed answer looks like.

**Forget** takes a connector off the profile's list by hand, when the check cannot run (the switch must be on, so no deny rule is left behind). If the connector still exists, Claude Code adds it back at its next session, so forgetting one by mistake loses nothing.

The connector itself stays connected on your account, and other profiles keep using it. To give two profiles different connectors, for example a work Google Drive and a personal one, sign them in with two different accounts.

Every change goes to the backup, and an open session picks it up when it restarts.
