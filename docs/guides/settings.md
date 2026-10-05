# Settings

The **Settings** tab edits one profile at a time; pick it at the top. Changes apply from the next Claude Code session in that profile, and every save goes to the backup.

If a file is [shared](../concepts.md#sharing), a *shared with …* label warns that the change applies to every sharing profile.

## General

The same settings as the `/config` panel of Claude Code, in five groups, plus the attribution texts.

| Setting | Key | Control |
|---|---|---|
| **Model and replies** | | |
| Model | `model` | free text with suggestions (`opus`, `sonnet`, `haiku`, values used in your profiles) |
| Thinking mode | `alwaysThinkingEnabled` | on/off, on by default |
| Output style | `outputStyle` | built-in styles plus the profile's custom styles in `output-styles/` |
| Language | `language` | free text |
| Prompt suggestions | `promptSuggestionEnabled` | on/off, on by default |
| Session recap | `awaySummaryEnabled` | on/off, on by default |
| Auto-compact | `autoCompactEnabled` ¹ | on/off, on by default |
| Precompute compaction | `precomputeCompactionEnabled` | on/off, on by default |
| Rewind code (checkpoints) | `fileCheckpointingEnabled` ¹ | on/off, on by default |
| Default permission mode | `permissions.defaultMode` | `default`, `plan`, `acceptEdits`, `auto`, `dontAsk` |
| Use auto mode during plan | `useAutoModeDuringPlan` | on/off, on by default |
| **Interface** | | |
| Theme | `theme` ² | `auto`, `dark`, `light`, `dark-daltonized`, `light-daltonized`, `dark-ansi`, `light-ansi` |
| Show tips | `spinnerTipsEnabled` | on/off, on by default |
| Reduce motion | `prefersReducedMotion` | on/off |
| Verbose output | `verbose` ¹ | on/off |
| Terminal progress bar | `terminalProgressBarEnabled` ¹ | on/off, on by default |
| Show turn duration | `showTurnDuration` ¹ | on/off, on by default |
| Time format | `timeFormat` | `auto`, `12-hour`, `24-hour`, `24-hour-utc` |
| Default view | `defaultView` | `transcript`, `chat` |
| Auto-scroll | `autoScrollEnabled` ¹ | on/off, on by default |
| Show PR status footer | `prStatusFooterEnabled` ¹ | on/off, on by default |
| **Editor and files** | | |
| Editor mode | `editorMode` ² | `normal`, `vim` |
| Respect .gitignore in file picker | `respectGitignore` ¹ | on/off, on by default |
| Skip the /copy picker | `copyFullResponse` ¹ | on/off |
| Copy on select | `copyOnSelect` ¹ | on/off, on by default |
| Show last response in external editor | `externalEditorContext` ¹ | on/off |
| Diff tool | `diffTool` ¹ | `auto`, `terminal` |
| Auto-connect to IDE (external terminal) | `autoConnectIde` ¹ | on/off |
| Auto-install IDE extension | `autoInstallIdeExtension` ¹ | on/off, on by default |
| Worktree base ref | `worktree.baseRef` | `fresh`, `head` |
| **Notifications and updates** | | |
| Notifications | `preferredNotifChannel` ¹ | `auto`, `iterm2`, `terminal_bell`, `iterm2_with_bell`, `kitty`, `ghostty`, `notifications_disabled` |
| Auto-update channel | `autoUpdatesChannel` | `latest`, `stable` |
| **Commits and pull requests** | | |
| Commit attribution | `attribution.commit` | free text; empty means no attribution |
| Pull request attribution | `attribution.pr` | free text; empty means no attribution |
| Co-authored-by in commits | `includeCoAuthoredBy` | shown only while a profile has it: deprecated by Claude Code, remove it with × |

¹ Kept in the profile's `.claude.json`, as `/config` does, not in `settings.json`. Claude Code re-reads that file before it writes it, so a change made here is not lost; an open session picks it up when it restarts.
² Edited where a settings file already has it, otherwise in `.claude.json`, as `/config` does.

Settings that `/config` turns on by removing the key (Thinking mode, Prompt suggestions, Session recap) are removed here too when you turn them on. Effort level, the renderer and the days to keep conversations are not in `/config`: edit them in the advanced editor.

Dropdowns list the values the Claude Code settings schema accepts. They were checked against the version shown in the tab. A value already in your file that is not in the list stays selectable as *(current value)*, so nothing is lost.

For each setting you see:

- **where the value comes from**: `settings.local.json` (amber, because it wins over `settings.json`), `settings.json`, `.claude.json`, or *default*. Saving writes to the file the value comes from, so a change is never hidden by a local override.
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
