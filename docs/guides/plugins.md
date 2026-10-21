# Plugins

The **Plugins** tab shows, for one profile at a time, the Claude Code plugins installed in it, lets you turn each one on or off, and copies a plugin to another profile. Installing, updating and removing plugins stays with Claude Code: use `/plugin` in a session.

## What you see

For each plugin:

- its name and the **marketplace** it comes from (a plugin is identified as `name@marketplace`);
- the installed **version** and date, and its install folder;
- the **scope**: `user` for every project, or `project` / `local` with the project it belongs to;
- whether it is **enabled**, and in which file: the `enabledPlugins` key of `settings.json`, or of `settings.local.json`, which wins. A plugin that neither file mentions follows Claude Code's default.

Below the plugins, **Marketplaces** lists where Claude Code finds plugins to install, read from `plugins/known_marketplaces.json`.

The tab reads `plugins/installed_plugins.json` in the profile folder. If the profile **shares** `plugins` with the source profile, the header says so: the installed plugins are the same for both, while `enabledPlugins` lives in each profile's settings unless `settings.json` is shared too.

## Mods

A **mod** changes Claude Code itself: a pane beside the chat, a band above the prompt, a status line entry, a slash command, or a hook that blocks or rewrites tool calls and prompts. For Claude Code a mod is a plugin, installed with `/plugin` like any other; what sets it apart is a hooks module named under `modules` in its `hooks/hooks.json`.

cc-profiles marks these plugins **mod** and says what each one does, read from its source code without running it:

- **Adds**: what it shows or adds (a pane, the band above the prompt, the status line, notifications, sounds, tools Claude can call, subagent types) and its slash commands;
- **hooks**: the events it hooks, such as *Tool calls (can block or change them)* or *Prompts you send (can change them)*;
- **Can reach**, in orange: the network, programs it runs, files it writes, calls to a model. Worth reading before you turn a mod on in another profile.

This is a description, not a guarantee: code can reach the same things in ways a reading of the source does not see. A mod you are writing in a Claude Code session lives in that session's mods folder and is not listed: it shows here once it is installed with `/plugin`.

## Copy to another profile

**Copy to…** on a plugin copies it to another profile as `/plugin` would have installed it there: its files under `plugins/cache/`, its entry in `installed_plugins.json` (with the paths moved to the other profile's folder), and its marketplace in `known_marketplaces.json` with the marketplace's copy under `plugins/marketplaces/`, if the other profile does not have it yet. The plugin is then enabled there, from its next Claude Code session. Every file that changes goes to the backup first, and **Restore** in the **Backups** tab undoes the copy.

Only plugins installed for every project (scope `user`) can be copied. The copy is refused when the other profile already has the plugin (remove it there with `/plugin` first) or shares its `plugins` folder with this one. Updating a copied plugin later is again `/plugin`'s job, in each profile.

Unlike sharing the `plugins` folder (below), a copy brings one plugin and leaves the rest of the other profile's plugins as they are.

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
