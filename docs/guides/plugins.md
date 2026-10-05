# Plugins

The **Plugins** tab shows, for one profile at a time, the Claude Code plugins installed in it and lets you turn each one on or off. Installing, updating and removing plugins stays with Claude Code: use `/plugin` in a session.

## What you see

For each plugin:

- its name and the **marketplace** it comes from (a plugin is identified as `name@marketplace`);
- the installed **version** and date, and its install folder;
- the **scope**: `user` for every project, or `project` / `local` with the project it belongs to;
- whether it is **enabled**, and in which file: the `enabledPlugins` key of `settings.json`, or of `settings.local.json`, which wins. A plugin that neither file mentions follows Claude Code's default.

Below the plugins, **Marketplaces** lists where Claude Code finds plugins to install, read from `plugins/known_marketplaces.json`.

The tab reads `plugins/installed_plugins.json` in the profile folder. If the profile **shares** `plugins` with the source profile, the header says so: the installed plugins are the same for both, while `enabledPlugins` lives in each profile's settings unless `settings.json` is shared too.

## Enable or disable

Use the switch on a plugin. After a confirmation, cc-profiles writes `enabledPlugins` in the file where that plugin's value already is (`settings.local.json` or `settings.json`), or in `settings.json` if neither has it. The file goes to the backup first. The change applies from the next Claude Code session in the profile.
