---
target: cc-profiles web UI
total_score: 28
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 3
target_identity: "file:/Users/andreaiannarone/Sites/Personal/cc-profiles/src/cc_profiles/static/index.html"
target_fingerprint: "sha256:7769f5829b48a78efe3737c0babaf3cfc7426c3eb673d1482d72a97af58487e7"
target_path: /Users/andreaiannarone/Sites/Personal/cc-profiles/src/cc_profiles/static/index.html
timestamp: 2026-11-01T19-23-49Z
slug: src-cc-profiles-static-index-html
---
Method: dual-agent (A: design review · B: detector + browser)

## Design Health Score: 28/40 (Good)
1 Visibility of status 3 (toasts with the backup path vanish in 6 s; plan left only in Profiles) · 2 Real world 3 (Assign creates a hidden substring rule; "1 conv · 0 mem") · 3 Control and freedom 3 (no one-click Undo) · 4 Consistency 2 (Settings saves five ways; Manage has five "Choose"; Compare uses dropdowns, other tabs segments) · 5 Error prevention 3 (Delete profile preselects Delete everything; Restore primary next to Delete) · 6 Recognition 3 (raw YAML in the memory editor) · 7 Efficiency 3 (no multi-select Assign) · 8 Minimalism 2 (profile cards on every tab; Compare/Settings show every row) · 9 Error recovery 3 · 10 Help 3 (source, Shared, rules, Merge into… unexplained in place)

## Design specificity
Grounded in the product (position-colored profile badges, mono paths, Needs attention with one fix per row, concrete confirmations, typed-name delete, plan bars, mascot loader); the frame (stat cards, 13-tab nav, long uniform tables) is generic. Detector: source scan 3 findings (2 side-tab on unsaved-change markers, 1 cramped-padding on .gdot: false positives), live page 1 advisory (11px toast small text, real, minor).

## Priority issues
1. [P1] Undo is not where the user is: add Undo to the result toast (core.js toast), longer and paused on hover/focus.
2. [P1] Phone layout of Projects and Backups: paths wrap per character, actions off screen; stacked rows under 820px, compact profile cards.
3. [P1] Modal focus: modal() does not return focus to the trigger nor trap Tab, against DESIGN.md.
4. [P2] Projects: unassigned shown as problems with a red counter; Assign hides a substring rule. Separate broken from unassigned, batch Assign, live preview of matches.
5. [P2] Compare and Settings bury differences; Settings saves five ways. Differences-only by default; one save path or labeled Saves.

## Persona red flags
Alex (power user): five Assign dialogs, shortcuts only for tabs. Sam (keyboard/screen reader): focus lost after dialogs, no Tab trap, timed toasts carry the only undo. Riley (stress tester): substring rules capture more than intended; Restore does not list what it overwrites. Casey (phone): Projects actions unreachable, Backups unreadable.

## Minor
Restore orange on every backup row; current plan use not in Usage/cards; Memories empty state says "left" on phone; Merge into… unexplained; editing border looks like focus ring; 11px toast text.

## Questions
Could Move be immediate with an Undo toast? Should the profile cards show plan left or go? Is "unassigned" a problem at all?
