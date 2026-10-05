# Settings

The **Settings** tab edits one profile at a time; pick it at the top. Changes apply from the next Claude Code session in that profile, and every save goes to the backup.

If a file is [shared](../concepts.md#sharing), a *shared with …* label warns that the change applies to every sharing profile.

## General

| Setting | Key | Control |
|---|---|---|
| Model | `model` | free text with suggestions (`opus`, `sonnet`, `haiku`, values used in your profiles) |
| Effort level | `effortLevel` | `low`, `medium`, `high`, `xhigh` |
| Output style | `outputStyle` | built-in styles (`default`, `Proactive`, `Concise`, `Explanatory`, `Learning`) plus the profile's custom styles in `output-styles/` |
| Response language | `language` | free text |
| Theme | `theme` | `auto`, `dark`, `light`, `dark-daltonized`, `light-daltonized`, `dark-ansi`, `light-ansi` |
| Editor mode | `editorMode` | `normal`, `vim` |
| Renderer | `tui` | `default`, `fullscreen` |
| Co-authored-by in commits | `includeCoAuthoredBy` | on/off; deprecated by Claude Code in favor of `attribution` |
| Days to keep conversations | `cleanupPeriodDays` | whole number, at least 1 (Claude Code's default is 30) |
| Reduce motion | `prefersReducedMotion` | on/off |

Dropdowns list the values the Claude Code settings schema accepts. They were checked against the version shown in the tab. A value already in your file that is not in the list stays selectable as *(current value)*, so nothing is lost.

For each setting you see:

- **where the value comes from**: `settings.local.json` (amber, because it wins over `settings.json`), `settings.json`, or *default*. Saving writes to the file the value comes from, so a change is never hidden by a local override.
- **×** to remove the setting and go back to the default.
- **the other profiles' values**, with *copy* to take one.
- **Apply to all…**, when another profile has a different value: gives every other profile the value saved in this one.

### Apply a setting to every profile

**Apply to all…** first shows which profiles change (old value → new value, and the file) and which are skipped, with the reason:

- the profile already has that value;
- it shares the file with a profile that is already being changed (for example a shared `settings.json`);
- the value is not available there (a custom output style the profile does not have);
- its settings file has a JSON error.

Each profile is written where its value lives, as with a normal save. If the value is the default, the setting is removed wherever it is set. It is **one operation with one backup** covering every profile: one Restore in the Backups tab undoes it all.

## CLAUDE.md

`CLAUDE.md` in the profile folder holds global instructions, loaded at the start of **every** session in that profile. It is the right place for context that must always apply ("in this profile you work for …", conventions, tools to prefer). If it does not exist, saving creates it.

## Permissions

Rules in `settings.json`, one per line, in three lists:

- **allow**: run without asking
- **ask**: always ask
- **deny**: never allow

Precedence: `deny` wins over `ask`, which wins over `allow`. Examples:

```
Bash(npm run test:*)
Read(~/Documents/**)
mcp__claude_ai_Gmail
```

Other keys of `permissions` (such as `defaultMode`) are preserved. Rules in `settings.local.json` are shown as a count; edit them in the advanced editor.

**Add a rule to every profile…** adds one rule to one list (`allow`, `ask` or `deny`) in the `settings.json` of every profile. The confirmation lists the profiles that change and the ones skipped: those that already have the rule in that list, those sharing `settings.json` with a profile already changed, and those whose `settings.json` has an error. If a profile has the same rule in another list, the confirmation says so. One backup covers every profile.

## Advanced editor

Edits the whole `settings.json` or `settings.local.json`: hooks, `env`, `attribution`, and anything else. The JSON is checked as you type, **Format** re-indents it, and invalid JSON or a non-object cannot be saved.

## Global

`.claude.json` is mostly Claude Code's internal state (caches, counters, tips already seen) and is shown read-only. The only setting you can change here is **Auto-updates** (`autoUpdates`).
