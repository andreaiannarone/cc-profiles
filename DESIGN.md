# DESIGN.md

The visual system of the cc-profiles UI (`src/cc_profiles/static/index.html`). Read it before adding or changing anything in the interface.

## Principles

1. **A tool, not a showcase.** People open the app to fix something, so density is high, hierarchy is clear and nothing is decorative. Color carries information; it is not there to look nice.
2. **Every action that writes says what it will do, and friction grows with the stakes.** Assigning takes one click, moving takes a confirmation, deleting a profile requires typing its name. Confirmations give concrete numbers ("3 conversations, 2 memories") and say where data goes ("anything the target already has goes to the backup").
3. **Problems before lists.** The Projects tab opens on *Needs attention*, and every row with a problem has exactly one primary button that fixes it.
4. **No dead ends.** Every operation reports its result in a toast with the backup path. Empty states say why they are empty.

## Color

All colors are custom properties on `:root`. Dark mode redefines the same properties under `@media (prefers-color-scheme: dark)`, respecting `data-theme="light"`, and again under `:root[data-theme="dark"]` for a forced dark theme: keep the two dark blocks identical. The theme button in the header (**System / Light / Dark**) sets `data-theme` and remembers the choice in `localStorage`; a tiny script in `<head>` applies it before the first paint. Do not hard-code colors outside these properties, except the white text of error toasts and the status line preview, which imitates a dark terminal in both themes (`.slpreview`: its background and the 8 ANSI colors).

| Property | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#f6f5f2` | `#161513` | page background (warm paper, not pure white) |
| `--panel` | `#ffffff` | `#1f1e1b` | cards, tables, modals, inputs |
| `--panel-2` | `#f0eee9` | `#282723` | table headers, hover, options in modals |
| `--line` | `#e2dfd8` | `#353330` | borders and separators |
| `--text` | `#1d1c1a` | `#ecebe7` | main text; also the background of active chips and segments |
| `--muted` | `#6e6a62` | `#a29e95` | secondary text, counts, labels |
| `--faint` | `#9b968c` | `#75716a` | hover borders |
| `--accent` / `--accent-soft` | `#c2410c` / `#fbe9df` | `#fb8a4c` / `#3a2418` | primary action, active tab, focus, switches that are on, selection |
| `--on-accent` | `#ffffff` | `#1d1c1a` | text on `--accent`; in dark mode the orange is light, so the text turns dark |
| `--p0` … `--p5` (+ `-soft`) | green, blue, pink, teal, indigo, amber | lighter versions | profile badges, assigned by the profile's position in the config |
| `--shared` / `--shared-soft` | `#6d28d9` / `#ede5fb` | `#c4a5ff` / `#2a2140` | the "All profiles" badge |
| `--ok` | `#15803d` | `#4ade80` | passed checks, "✓ all good" |
| `--warn` / `--warn-soft` | `#a84d08` / `#fdf1dc` | `#fbbf24` / `#3a2c10` | fixable problems, "session open" |
| `--err` / `--err-soft` | `#b91c1c` / `#fbe3e3` | `#f87171` / `#3d1a1a` | errors, missing folders, destructive actions, tab counters |
| `--logo` / `--logo-back` / `--logo-eye` | `#d97757` / `#e9a98c` / `#1d1c1a` | `#d97757` / `#8a4a33` / `#1d1c1a` | the two pixel mascots next to the page title and in loading panels, nothing else (same colors as `docs/assets/logo.svg`) |

Rules:
- **Orange `--accent` is reserved for action.** Do not use it for states or badges: if something is orange, it can be clicked or it is the current selection.
- **Profiles get colors by position.** The first profile in the config is `b-p0`, the second `b-p1`, and so on, wrapping after six. Never tie a color to a profile id.
- **State is never conveyed by color alone.** There is always text ("folder not found on disk") or an icon (✓ ! ✕) as well.

## Typography

- **UI text**: `-apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", sans-serif`, 14px, line height 1.45. System fonts only, so the app works offline and loads nothing from the internet.
- **Paths, commands, file names**: `--mono` (`ui-monospace, "SF Mono", Menlo, monospace`), 12–12.5px. Anything a user might type or search for in a terminal is monospace (`<code>` or `.mono`).
- **Scale**: page title 20px · card and modal titles 15–16px · body 14px · secondary 12.5–13px · badges and meta 11.5–12px.
- **Weights**: 400 body; 550 tabs, buttons and table headers; 600–650 titles and badges.
- **Numbers**: `font-variant-numeric: tabular-nums` on counts and tables, so columns line up.

## Space and shape

- The container spans the full window width, with 24px at the top and 28px at the sides (16px below 820px).
- 12–16px between cards; 14–16px inside cards, 9–12px inside table cells.
- Radii: `--radius` 10px for cards and tables, 12px for modals, 8px for buttons and inputs, `99px` for chips, badges and switches.
- Shadows only for things that float above the page: modals, toasts, the drawer and the switch knob. Cards only have a border.

## Components

| Component | Class | Notes |
|---|---|---|
| Profile card | `.pcard` | name and badge, monospace meta line, three big numbers; `.live` for "session open". `.pcard.add` is the dashed "+ New profile" variant |
| Navigation | `nav.tabs#tabs` > `.tabrow`, `.more` | an underline nav like GitHub's, under the profile cards: each tab is a 16px stroke icon (`.ti`) plus its name, muted until hovered (a `--panel-2` rounded background) or active (full text color and a 2px orange underline on the nav's bottom line). Tabs that do not fit move, in order, into the **More** menu (`#moremenu`); the active tab always stays in the row, More is underlined when the active tab is in it, and a red dot marks it when a tab inside has a counter. Tab buttons keep `data-tab` and get `aria-current="page"` when active; a red `.count` shows the number of problems |
| Keyboard shortcuts | `#keys-btn`, `showKeys()` | `/` search, `g` + letter for a tab, `?` the list in a modal. Ignored while typing in a field or with a modal, drawer or popover open. The header button is hidden on touch screens (`hover: none`) |
| Filters | `.chip` / `.chip.on` | the active chip is inverted (background `--text`) |
| Buttons | `.btn` | `.primary` (orange, at most one per row or modal), `.danger` (red text), `.small` |
| Badges | `.badge` + `.b-p0`…`.b-p5`, `.b-shared`, `.b-none`, `.b-default`, `.b-warn`, `.b-err` | always short text, never an icon alone; `.b-default` (outlined) marks a setting left at its default. Never fade a badge with `opacity`: it breaks contrast |
| Table | `.table > table` | header on `--panel-2`; paths in `td.path` (monospace, wrap anywhere); actions aligned right |
| Side list | `.side` + `.plist` | scrolls on its own (max 62vh); the selected item is on `--accent-soft` |
| Memory card | `.mcard` / `.mcard.on` | focusable; orange border while open in the editor |
| Editor | `.editor` | monospace textarea; actions at the bottom right: Delete · Move… · **Save** |
| Switch | `.switch` | hidden checkbox plus a `span`; on = `--accent`. Changes always go through a confirmation and flip back if cancelled |
| Health check | `.check.ok` `.warn` `.error` | ✓ ! ✕ icon in a 16px column |
| Modal | `modal({ title, sub, body, actions })` | closes with Esc, a click outside, or Cancel; the first field gets focus; actions without a `label` do not appear in the footer |
| Typed confirmation | "Type *Name* to confirm" field | only for the biggest operations (deleting a profile): the button stays disabled until the text matches |
| Plan preview | `planDetails(items, to)` → `<details>` with `ul.plan` | "Show the N files and folders it touches", one line per item with its action; `li.conflict` in amber. Used by move, delete profile, share and separate |
| Apply to all | `applyAll(title, preview, intro, okLabel, post)` | confirmation listing the profiles that change (with the old → new detail) and the ones skipped with the reason; says that one Restore undoes it all |
| Danger box | `.danger-box` | red border and background, for a risk to read before confirming (e.g. an open session) |
| Notice | `.notice` | a bar above the profiles for a system-level state (Claude Code missing, installing, not in `PATH`) |
| Drawer | `.drawer` | right side panel for the About information; sticky header with Refresh and Close |
| Setting row | `.srow` | three columns: name and help · input with a badge for the file it comes from (`settings.local.json` in amber, because it wins) and × · the other profiles' values with *copy*. A changed row gets `.changed` (an orange bar on the left); nothing is saved until the bar below |
| Save bar | `.savebar#gen-bar` | sticky at the bottom of Settings → General while there are unsaved changes: "N unsaved changes" with **Cancel** and **Save changes**, which saves them all in one backup |
| Status line editor | `.slpresets`, `.slgrid`, `.slparts`, `.slpreview`, `.slopts`, `.slsep` | a row of preset `.chip`s (the one matching the draft is `.on`; a click fills the draft, never saves); a list of pieces (grip, checkbox, brackets select, sample, ↑↓) in line order, ticked ones first; side controls as `.seg` (separator, brackets for all, rate limits); a terminal-like preview rendering the script's ANSI colors; *Save status line* enabled only with changes |
| Section | `.sec` | header with title, explanation and `.shared-note` if the file is shared |
| Usage chart | `.uchart`, `usageChart(daily)` | inline SVG bars, one `g.day` per day with a `<title>` tooltip and an `aria-label` summary on the `svg`; segments use `--p1` (output), `--p3` (input and cache write) and `--faint` (cache read), with a legend, never the accent. Summary numbers are `.ucard`s |
| Changes drawer | `.drawer.wide`, `showChanges(name, trigger)` | Backups → *Show changes*: a wider drawer with the steps in plain words and one `details.chg` per copied file; `pre.diff` lines are `.a` (added, `--ok` mixed into `--panel`), `.d` (removed, `--err-soft`), `.h` (hunk, `--panel-2`), always with the `+`/`-` prefix so color is not the only cue |
| Download | `download(path, fallback)` | fetches with the token and saves the Blob under the server's file name: profile export, usage CSV |
| Toast | `toast(msg, sub, err)` | bottom right, 6 s (9 s for errors); `sub` in monospace for the backup path; `role="status"` or `alert` |
| Loading | `LOADER` (`.spinner.loader`), `.spinner` | a panel that loads (an `.empty` state, the restart dialog, the Claude Code install notice) shows `LOADER`: the header's logo, its two mascots hopping in turn by whole pixels. Small inline waits (a status next to a button) keep the round `.spinner`. Always with a sentence about what we are waiting for when the wait is long |

## Writing

- **English, sentence case**: "New profile", not "New Profile".
- **Describe and ask**: "Moved to Work: 3 conversations", "Move to Work?". No "we", no "please".
- **Buttons name the action**, never "OK": *Move*, *Relink*, *Restore*, *Delete permanently*. Modals always have *Cancel*.
- **Concrete numbers instead of adjectives**: "1 conversation, 3 memories", not "some data". Use `plural()` so that 1 is singular.
- **Say where data goes**: "goes to the backup", "kept in the backup", "cannot be restored afterwards".
- No emoji, except ✓ for completion.
- An ellipsis (…) ends a label only when the button opens a modal that asks for more: *Relink…*, *Move…*, *Assign…*.

## Accessibility and behavior

- Visible focus everywhere: a 2px `--accent` outline.
- Modals and the drawer have `role="dialog"`, `aria-modal="true"` and a label; Esc closes them and focus returns to the trigger.
- Inputs without a visible label have an `aria-label`.
- Search fields keep the caret position when the list re-renders.
- Contrast: main and secondary text pass WCAG AA (4.5:1) on `--bg` and `--panel` in both themes. Primary buttons use `--on-accent` (5.2:1 light, 7.2:1 dark). Profile badges measure, light/dark: p0 4.7/7.4, p1 5.6/6.9, p2 4.9/8.4, p3 4.6/9.1, p4 6.4/7.7, p5 6.0/9.8, shared 5.8/7.3. Measure every new color in both themes before using it.
- `prefers-reduced-motion` disables the drawer's slide-in and the mascots' hops and blink (the header logo stays still, `LOADER` only fades in and out).
- The header logo hops and blinks once when the page opens. Each time the pointer reaches the title it makes the next of five gestures, in turn: blink twice, look at each other, wiggle the antennas, peek (the back mascot slips behind the front one and pops up), jump together. Never in a loop. The SVG groups each mascot (`g.m-back`, `g.m-front`), marks the antennas `.lg-ant`, and has body-colored pixels under the eyes, so an eye that moves or closes never leaves a hole. Under each mascot, `g.lg-e` repeats its pixels as a thin stroke of `--logo-edge` (the background: `--bg`, `--panel` in a modal, `--warn-soft` in the install notice), so when they overlap the one in front never seems to cut the other.
- Landmarks: one `header`, `nav` labelled *Sections*, `main`; the profile cards are a labelled `section`.
- Headings never skip a level: the page title is the only `h1`; section titles inside a tab are `h2` and their groups `h3`, sized by class so the level does not change the look; modals and the About panel start at `h2`.
- `tests/test_ui.py` runs axe-core on every tab, the shortcuts dialog, the About panel and phone width, in both themes, and fails on *serious* or *critical* violations, and on `heading-order` at any impact.

## Responsive

The navigation needs no breakpoint: it measures itself and moves what does not fit into **More** (see *Navigation*), so nothing scrolls sideways even at 375px.

At **820px** the memories grid becomes one column, search fields go full width, settings rows and permission columns stack, and tables scroll horizontally inside their container (the page itself never does). Profile and health cards adapt by themselves with `grid-template-columns: repeat(auto-fit, minmax(…))`.
