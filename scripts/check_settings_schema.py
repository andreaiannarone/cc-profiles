#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""Check SETTING_FIELDS against the settings schema inside a Claude Code binary.

    python scripts/check_settings_schema.py [path/to/claude] [--output report.md]

Without a path it checks the `claude` found on PATH. It reads the binary's bytes
(no `strings` needed), prints a Markdown report and exits with 1 when something
differs, 2 when the binary cannot be read or no longer looks like this script
expects, 0 when everything matches.

Claude Code does not document its settings schema: it is compiled into the binary
as minified JavaScript, so this script looks for shapes, not for names. A top-level
key is `key:()=>j(["a","b"]).optional()...`; a nested one (permissions.defaultMode)
is `defaultMode:j(...).optional()`. One-letter function names change between builds,
so the script learns them from keys whose type is known (REFERENCE_KEYS). Lists can
be inline, referenced by name (`j(abc)` with `abc=[...]`) or spread other lists
(`["auto",...abc]`).

Fields with "file": "global" live in .claude.json, not in the settings schema: they
are checked against the items of the /config panel instead (`{id:"...",label:...}`).
CONFIG_IDS maps every /config item this project knows to its SETTING_FIELDS key
(None: known, deliberately not in the Settings tab), so new and removed items show up.
"""

import argparse
import os
import re
import shutil
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

# /config item id -> SETTING_FIELDS key, or None for an item the Settings tab leaves out on purpose.
CONFIG_IDS = {
    "autoCompact": "autoCompactEnabled",
    "autoContinueAtUsageLimit": None,
    "remoteHomeSettings": None,
    "unattendedServing": None,
    "switchModelsOnFlag": None,
    "tips": "spinnerTipsEnabled",
    "feedbackDrafts": None,
    "reduceMotion": "prefersReducedMotion",
    "thinking": "alwaysThinkingEnabled",
    "fast": None,
    "promptSuggestionEnabled": "promptSuggestionEnabled",
    "recap": "awaySummaryEnabled",
    "checkpoints": "fileCheckpointingEnabled",
    "orgMemoryRead": None,
    "orgMemoryWrites": None,
    "workflows": None,
    "workflowKeywordTriggerEnabled": None,
    "workflowSizeGuideline": None,
    "artifacts": None,
    "verbose": "verbose",
    "progressBar": "terminalProgressBarEnabled",
    "showStatusInTerminalTab": None,
    "turnDuration": "showTurnDuration",
    "precomputeCompactionEnabled": "precomputeCompactionEnabled",
    "timestamps": None,
    "timeFormat": "timeFormat",
    "permissionMode": "permissions.defaultMode",
    "worktreeBaseRef": "worktree.baseRef",
    "useAutoModeDuringPlan": "useAutoModeDuringPlan",
    "gitignore": "respectGitignore",
    "copyFullResponse": "copyFullResponse",
    "copyOnSelect": "copyOnSelect",
    "autoScroll": "autoScrollEnabled",
    "agentsView": None,
    "defaultToAgentsView": None,
    "leftArrowOpensAgents": None,
    "autoUpdatesChannel": "autoUpdatesChannel",
    "theme": "theme",
    "notifChannel": "preferredNotifChannel",
    "inputNeededNotifEnabled": None,
    "agentPushNotifEnabled": None,
    "outputStyle": "outputStyle",
    "defaultView": "defaultView",
    "language": "language",
    "editor": "editorMode",
    "askUserQuestionTimeout": None,
    "modelProposedGoals": None,
    "externalEditorContext": "externalEditorContext",
    "prStatus": "prStatusFooterEnabled",
    "model": None,  # picked with /model; removed from the Settings tab in 0.4.3
    "diffTool": "diffTool",
    "autoConnectIde": "autoConnectIde",
    "autoInstallIdeExtension": "autoInstallIdeExtension",
    "chrome": None,
    "teammateMode": None,
    "dialogExpiry": None,
    "crossSessionInbound": None,
    "showExternalIncludesDialog": None,
    "apiKey": None,
}
# Values the schema accepts that the Settings tab leaves out on purpose: not reported as new.
LEFT_OUT = {
    "permissions.defaultMode": {"bypassPermissions"},  # only from the command line, never as a saved default
    "autoUpdatesChannel": {"rc"},  # the schema describes it as "latest or stable"; /config does not offer it
}
# Keys whose type is known, to learn the minified function names of this build.
REFERENCE_KEYS = {"enum": "effortLevel", "string": "language", "bool": "prefersReducedMotion",
                  "number": "cleanupPeriodDays"}
PANEL_START = b'{id:"autoCompact",label:"Auto-compact"'
MODIFIERS = ("optional", "describe", "catch", "default", "nullable", "transform", "refine", "superRefine")
IDENT = rb"[A-Za-z_$][\w$]*"


class SchemaError(Exception):
    """The binary does not look like a Claude Code build this script understands."""


def find_claude():
    path = shutil.which("claude")
    if not path:
        for d in ("~/.local/bin", "/opt/homebrew/bin", "/usr/local/bin"):
            p = os.path.join(os.path.expanduser(d), "claude")
            if os.path.exists(p):
                path = p
                break
    return os.path.realpath(path) if path else None


def find_version(data):
    m = re.search(rb'VERSION:"(\d+\.\d+\.\d+)"', data)
    return m.group(1).decode() if m else None


def scan_expr(data, start, limit=4000, commas=True):
    """The JavaScript expression starting at `start`, up to its end (`,` `}` `)` `]` at
    depth 0) or to a zod modifier at depth 0 (`.optional(`, `.describe(`...). Returns
    (base expression, full expression). With commas=False a comma does not end it: for
    the body of a list, up to its closing bracket."""
    depth, i, quote, base_end = 0, start, None, None
    end = min(len(data), start + limit)
    while i < end:
        c = data[i:i + 1]
        if quote:
            if c == b"\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in (b'"', b"'", b"`"):
            quote = c
        elif c in b"([{":
            depth += 1
        elif c in b")]}":
            if depth == 0:
                break
            depth -= 1
        elif c == b"," and depth == 0 and commas:
            break
        elif c == b"." and depth == 0 and base_end is None:
            m = re.match(rb"\.(\w+)\(", data[i:i + 20])
            if m and m.group(1).decode() in MODIFIERS:
                base_end = i
        i += 1
    return data[start:base_end if base_end is not None else i], data[start:i]


def finds(data, needle, lo=0, hi=None):
    """Positions of `needle` in data[lo:hi]. bytes.find is much faster than a regex
    on a 200 MB binary."""
    hi = len(data) if hi is None else hi
    pos = data.find(needle, lo, hi)
    while pos >= 0:
        yield pos
        pos = data.find(needle, pos + 1, hi)


def schema_expr(data, key):
    """(base, full, position) of the schema of a SETTING_FIELDS key, or None. A top-level
    key is `key:()=>X(...)`; a nested one, or one inside an object schema, `key:X(...)`."""
    parts = key.split(".")
    needle = parts[-1].encode() + b":"
    tries = []
    if len(parts) > 1:  # first look right after the parent's own schema, if it has one inline
        parent = parts[-2].encode() + b":()=>"
        tries += [(False, p, p + 6000) for p in finds(data, parent) if data[p - 1:p] in (b",", b"{")]
    tries += [(True, 0, len(data)), (False, 0, len(data))]
    for lazy, lo, hi in tries:
        for p in finds(data, needle, lo, hi):
            if data[p - 1:p] not in (b",", b"{", b"("):
                continue
            start = p + len(needle)
            if lazy:
                if not data.startswith(b"()=>", start):
                    continue
                start += 4
            if not re.match(IDENT + rb"\(", data[start:start + 40]):
                continue
            base, full = scan_expr(data, start)
            if (b".optional(" in full or b".describe(" in full) and not base.startswith(b"import("):
                return base, full, start
    return None


def head(expr):
    m = re.match(rb"(" + IDENT + rb")\(", expr)
    return m.group(1) if m else None


def learn_letters(data):
    letters = {}
    for kind, key in REFERENCE_KEYS.items():
        found = schema_expr(data, key)
        if not found:
            raise SchemaError(f"Reference key `{key}` not found: cannot learn this build's {kind} function.")
        letters[kind] = head(found[0])
    return letters


def split_items(text):
    """Items of a JavaScript array body, split on top-level commas."""
    items, depth, quote, cur = [], 0, None, ""
    i = 0
    while i < len(text):
        c = text[i]
        if quote:
            cur += c
            if c == "\\" and i + 1 < len(text):
                cur += text[i + 1]
                i += 1
            elif c == quote:
                quote = None
        elif c in "\"'`":
            quote = c
            cur += c
        elif c in "([{":
            depth += 1
            cur += c
        elif c in ")]}":
            depth -= 1
            cur += c
        elif c == "," and depth == 0:
            items.append(cur.strip())
            cur = ""
        else:
            cur += c
        i += 1
    if cur.strip():
        items.append(cur.strip())
    return items


def list_body_at(data, pos):
    """The body of the array literal starting at data[pos] == '['."""
    _, full = scan_expr(data, pos + 1, commas=False)
    return full.decode("utf-8", "replace")


def resolve_name(data, name, near, expect=(), seen=None):
    """Values of the list defined as `name=[...]`. Minified names repeat across modules:
    of several definitions, the one sharing most values with `expect` (what this project
    lists), then the closest to `near`. Returns (values, dynamic), where dynamic means
    some values are computed at runtime."""
    seen = set() if seen is None else seen
    if name in seen:
        return [], True
    seen.add(name)
    needle = name.encode() + b"=["
    best, best_rank = None, None
    for p in finds(data, needle):
        if re.match(rb"[\w$.]", data[p - 1:p]):
            continue
        vals = parse_list(data, list_body_at(data, p + len(needle) - 1), p, expect, set(seen))
        rank = (-len(set(vals[0]) & set(expect)), abs(p - near))
        if best_rank is None or rank < best_rank:
            best, best_rank = vals, rank
    return best if best is not None else ([], True)


def parse_list(data, body, near, expect=(), seen=None):
    values, dynamic = [], False
    for item in split_items(body):
        if len(item) >= 2 and item[0] == item[-1] and item[0] in "\"'":
            values.append(item[1:-1])
        elif re.fullmatch(r"\.\.\.[A-Za-z_$][\w$]*", item):
            v, d = resolve_name(data, item[3:], near, expect, seen)
            values += v
            dynamic = dynamic or d
        elif item:
            dynamic = True
    return values, dynamic


def parse_values(data, ref, near, expect=()):
    """Values of an enum argument or `options:` value: `[...]` or a list name."""
    ref = ref.strip()
    if ref.startswith("["):
        return parse_list(data, ref[1:-1], near, expect)
    if re.fullmatch(r"[A-Za-z_$][\w$]*", ref):
        return resolve_name(data, ref, near, expect)
    return [], True


def schema_type(data, base, near, letters, expect=()):
    """{"kind": enum|string|bool|number|other, "values": [...], "dynamic": bool}"""
    enum = re.escape(letters["enum"])
    calls = list(re.finditer(rb"(?<![\w$.])" + enum + rb"\(", base))
    if calls:
        values, dynamic = [], False
        for c in calls:
            _, arg = scan_expr(base, c.end())
            v, d = parse_values(data, arg.decode("utf-8", "replace"), near, expect)
            values += [x for x in v if x not in values]
            dynamic = dynamic or d
        return {"kind": "enum", "values": values, "dynamic": dynamic}
    h = head(base)
    for kind in ("string", "bool", "number"):
        if h == letters[kind]:
            return {"kind": kind, "values": [], "dynamic": False}
    return {"kind": "other", "values": [], "dynamic": False, "expr": base[:80].decode("utf-8", "replace")}


def panel_items(data, expect=None):
    """{id: {"label", "type", "values", "dynamic"}} for the /config panel's items."""
    start = data.find(PANEL_START)
    if start < 0:
        raise SchemaError("The /config panel was not found (no `{id:\"autoCompact\",label:\"Auto-compact\"`).")
    open_at = data.rfind(b"[", 0, start)
    _, full = scan_expr(data, open_at + 1, limit=400000, commas=False)
    region = data[open_at:open_at + 1 + len(full)]
    items = {}
    item_re = re.compile(rb'\{id:"([^"]+)",(?:\w+:[^,{}()]*,){0,4}label:')
    found = list(item_re.finditer(region))
    for n, m in enumerate(found):
        iid = m.group(1).decode()
        if iid in items:
            continue
        end = found[n + 1].start() if n + 1 < len(found) else len(region)
        text = region[m.start():min(end, m.start() + 3000)]
        label = re.match(rb'\{id:"[^"]+",(?:\w+:[^,{}()]*,){0,4}label:(?:\w+\()?"([^"]*)"', text)
        typ = re.search(rb'type:"(\w+)"', text)
        opts = re.search(rb"options:(\[[^\]]*\]|" + IDENT + rb"(?:\.\w+)*\([^)]*\)|" + IDENT + rb")", text)
        values, dynamic = [], False
        if opts and (expect or {}).get(iid):  # only the lists of the items this project edits
            values, dynamic = parse_values(data, opts.group(1).decode("utf-8", "replace"), open_at + m.start(),
                                           expect[iid])
        items[iid] = {"label": label.group(1).decode() if label else "", "type": typ.group(1).decode() if typ else "",
                      "values": values, "dynamic": dynamic, "has_options": bool(opts)}
    return items


def expected_kind(fd):
    if fd["type"] == "select":
        return "string" if isinstance(fd.get("options"), str) else "enum"
    if fd["type"] == "bool":
        return "string" if "off_value" in fd else "bool"
    return {"text": "string", "number": "number"}.get(fd["type"], fd["type"])


def option_values(fd):
    return [o[0] if isinstance(o, (list, tuple)) else o for o in fd.get("options") or []]


def fmt(values):
    return ", ".join(f"`{v}`" for v in values)


def compare_values(fd, values, dynamic):
    """Problems between a select field's options and the values Claude Code accepts."""
    out, ours = [], option_values(fd)
    added = [v for v in values if v not in ours and v not in LEFT_OUT.get(fd["key"], ())]
    removed = [v for v in ours if v not in values]
    if added:
        out.append(f"new values {fmt(added)}")
    if removed and not dynamic:
        out.append(f"values no longer listed {fmt(removed)}")
    elif removed:
        out.append(f"values not found {fmt(removed)} (part of the list is computed at runtime: check by hand)")
    return out


def check(data, fields):
    """(version, {key: [problems]}, [ok keys], panel notes) for a binary's bytes."""
    letters = learn_letters(data)
    key_to_id = {v: k for k, v in CONFIG_IDS.items() if v}
    by_key = {fd["key"]: fd for fd in fields}
    panel = panel_items(data, {i: option_values(by_key[k]) for k, i in key_to_id.items() if k in by_key})
    problems, ok = {}, []
    for fd in fields:
        key, issues = fd["key"], []
        if fd.get("deprecated"):  # kept only so it can be removed: just check it still exists
            if not schema_expr(data, key):
                issues.append("missing from the schema: the field can go")
        elif fd.get("file") == "global":
            iid = key_to_id.get(key)
            item = panel.get(iid) if iid else None
            if not iid:
                issues.append("no /config item id is mapped to this key in CONFIG_IDS")
            elif not item:
                issues.append(f"/config item `{iid}` not found")
            else:
                want = "boolean" if fd["type"] == "bool" else "enum"
                got = "enum" if item["type"] in ("enum", "managedEnum") else item["type"]
                if got != want:
                    issues.append(f"type changed: /config item `{iid}` is now `{item['type']}`")
                elif want == "enum":
                    if not item["has_options"]:
                        issues.append(f"/config item `{iid}` has no options list")
                    else:
                        issues += compare_values(fd, item["values"], item["dynamic"])
        else:
            found = schema_expr(data, key)
            if not found:
                issues.append("missing from the schema (removed or renamed)")
            else:
                st = schema_type(data, found[0], found[2], letters, option_values(fd))
                want = expected_kind(fd)
                if st["kind"] != want:
                    shown = st["kind"] if st["kind"] != "other" else f"`{st['expr']}`"
                    issues.append(f"type changed: the schema says {shown}, the field expects {want}")
                elif want == "enum":
                    issues += compare_values(fd, st["values"], st["dynamic"])
        if issues:
            problems[key] = issues
        else:
            ok.append(key)
    new_items = [(i, panel[i]["label"]) for i in panel if i not in CONFIG_IDS]
    gone_items = [i for i in CONFIG_IDS if i not in panel]
    return problems, ok, new_items, gone_items


def report(path, version, schema_version, fields, problems, ok, new_items, gone_items):
    labels = {fd["key"]: fd["label"] for fd in fields}
    lines = ["# Claude Code settings schema check", "",
             f"Claude Code **{version or 'unknown version'}** (`{path}`), compared with `SETTING_FIELDS` "
             f"(last checked against {schema_version}).", ""]
    differs = bool(problems or new_items or gone_items)
    if not differs:
        lines += ["No differences: every field and every /config item matches.", ""]
    if problems:
        lines += ["## Fields", ""]
        lines += [f"- `{k}` ({labels[k]}): " + "; ".join(v) for k, v in problems.items()]
        lines.append("")
    if new_items or gone_items:
        lines += ["## /config panel", ""]
        lines += [f"- New item `{i}` ({label}): map it in `CONFIG_IDS` (to a key, or to None to leave it out)"
                  for i, label in new_items]
        lines += [f"- Item `{i}` is gone" + (f" (it edits `{CONFIG_IDS[i]}`)" if CONFIG_IDS[i] else "")
                  for i in gone_items]
        lines.append("")
    lines += [f"Unchanged: {len(ok)} of {len(fields)} fields.", ""]
    if differs:
        lines += ["Next: follow `.claude/skills/check-settings-schema/SKILL.md` to update `SETTING_FIELDS` "
                  "and `SCHEMA_VERSION`.", ""]
    return "\n".join(lines), differs


def main(argv=None):
    ap = argparse.ArgumentParser(description="Check SETTING_FIELDS against a Claude Code binary.")
    ap.add_argument("binary", nargs="?", help="path to the Claude Code binary (default: claude on PATH)")
    ap.add_argument("--output", help="also write the report to this file")
    args = ap.parse_args(argv)
    from cc_profiles.settings import SCHEMA_VERSION, SETTING_FIELDS
    path = os.path.realpath(args.binary) if args.binary else find_claude()
    if not path or not os.path.isfile(path):
        print(f"Claude Code binary not found: {args.binary or 'no claude on PATH'}. Pass its path.", file=sys.stderr)
        return 2
    with open(path, "rb") as f:
        data = f.read()
    try:
        problems, ok, new_items, gone_items = check(data, SETTING_FIELDS)
    except SchemaError as e:
        print(f"{e} The binary's layout changed: update scripts/check_settings_schema.py.", file=sys.stderr)
        return 2
    text, differs = report(path, find_version(data), SCHEMA_VERSION, SETTING_FIELDS, problems, ok, new_items, gone_items)
    print(text)
    if args.output:
        with open(args.output, "w") as f:
            f.write(text)
    return 1 if differs else 0


if __name__ == "__main__":
    sys.exit(main())
