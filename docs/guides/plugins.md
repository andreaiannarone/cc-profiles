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

## Example: the same plugins in two profiles

You use the plugins of your Default profile and want them in Work too.

1. In the **Profiles** tab, under **Sharing**, turn on **plugins** for *Work*. Work now sees the plugin files installed in Default.
2. Open the **Plugins** tab and pick *Work*. The header says the profile shares `plugins` with Default. Each plugin shows whether it is enabled in Work.
3. Turn on the plugins you want in Work. They load from the next Claude Code session there.

To keep the same plugins *enabled* everywhere without switching them one by one, share `settings.json` too. That also shares every other setting, so do it only if the two profiles should behave the same way.

## Example: turn a plugin off in one profile only

A plugin is useful at work but noisy in personal projects. Pick the personal profile in the **Plugins** tab and turn the plugin off: only that profile's settings change, and the plugin stays installed and enabled in the others. If the two profiles share `settings.json`, the switch changes both.
