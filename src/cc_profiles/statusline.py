# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: the status line cc-profiles writes for a profile, and its preview."""

import json
import os
import shlex
import shutil
import subprocess
import tempfile
import time

from .core import ApiError, Backup, find_tool, pretty, profile, profiles, tool_env, write_text
from .settings import effective, field_path, file_error, no_targets, plan_message, setting_targets, write_field


# ---------------------------------------------------------------------------
# Status line
# ---------------------------------------------------------------------------
# statusLine in settings.json runs a command that prints one line. cc-profiles can write
# that command itself: a POSIX sh script in the profile folder that reads the JSON Claude
# Code sends on stdin with jq. It finds the profile's label at run time (in
# ~/.cc-profiles/config.json), so a script reached through a shared settings.json still
# names the right profile. Only a script with STATUS_MARK on its first line is rewritten.
STATUS_MARK = "# managed by cc-profiles: status line"
# Tokens since the last prompt typed by the user (a user line whose content is a string, not
# a tool result) and in the whole session, from the usage of every assistant line of the
# conversation file. Lines that do not parse (one being written) are skipped.
STATUS_TOKENS_JQ = (
    'def h: if . >= 1000000 then ((. * 10 / 1000000 | floor) / 10 | tostring) + "M" '
    'elif . >= 1000 then (. / 1000 | floor | tostring) + "k" else tostring end; '
    'reduce (inputs | fromjson? | objects) as $l ({s: 0, t: 0}; '
    'if $l.type == "user" and ($l.message.content | type) == "string" then .t = 0 '
    'elif $l.type == "assistant" then ($l.message.usage // {}) as $u '
    '| (($u.input_tokens // 0) + ($u.cache_creation_input_tokens // 0) + ($u.cache_read_input_tokens // 0) + ($u.output_tokens // 0)) as $x '
    '| .s += $x | .t += $x else . end) | "question:\\(.t | h) session:\\(.s | h)"')
# (id, label, sample, brackets by default, sh code). The code reads the JSON with j and
# adds one piece with add TEXT [SGR color]; $cwd is the session's folder, $cfg the
# profile's .claude.json. Colors are the terminal's own 16 (90 is its grey).
STATUS_PARTS = [
    ("path", "Path", "~/code/api", "none",
     'if [ -n "$cwd" ]; then case $cwd in "$HOME") p="~" ;; "$HOME"/*) p="~${cwd#"$HOME"}" ;; *) p=$cwd ;; esac; add "$p" 36; fi'),
    ("folder", "Folder", "api", "none", '[ -n "$cwd" ] && add "$(basename "$cwd")" 36'),
    ("branch", "Git branch (* when changed)", "main*", "round",
     'if [ -n "$cwd" ]; then b=$(git -C "$cwd" --no-optional-locks branch --show-current 2>/dev/null)\n'
     '[ -z "$b" ] && b=$(git -C "$cwd" --no-optional-locks rev-parse --short HEAD 2>/dev/null)\n'
     'if [ -n "$b" ]; then git -C "$cwd" --no-optional-locks diff --quiet --ignore-submodules HEAD 2>/dev/null || b="$b*"; '
     'add "$b" "2;36"; fi; fi'),
    ("profile", "Profile", "Default", "round",
     'label=$(jq -r --arg d "$dir" --arg h "$(cd "$HOME" 2>/dev/null && pwd -P)" \'.profiles[]? | select((.dir | sub("^~"; $h) | rtrimstr("/")) == $d) | .label\' '
     '"$HOME/.cc-profiles/config.json" 2>/dev/null | head -n 1)\nadd "${label:-$name}" 1'),
    ("email", "Account email", "me@example.com", "none", 'add "$(jq -r \'.oauthAccount.emailAddress // empty\' "$cfg" 2>/dev/null)" 90'),
    ("model", "Model", "Opus", "square", 'add "$(j .model.display_name)" 35'),
    ("effort", "Effort", "high", "none", 'add "$(j .effort.level)" 35'),
    ("style", "Output style", "Explanatory", "curly", 'add "$(j .output_style.name)" 33'),
    ("pr", "Pull request", "PR #42", "none", 'v=$(j .pr.number); [ -n "$v" ] && add "PR #$v" 35'),
    ("context", "Context used", "ctx:42%", "angle",
     'v=$(j \'.context_window.used_percentage | floor\'); if [ -n "$v" ]; then c=34; [ "$v" -ge 70 ] && c=33; '
     '[ "$v" -ge 90 ] && c=31; add "ctx:$v%" $c; fi'),
    ("cost", "Session cost", "$1.27", "none", 'v=$(j .cost.total_cost_usd); [ -n "$v" ] && add "$(printf \'$%.2f\' "$v")" 32'),
    ("lines", "Lines changed", "+120 -34", "none",
     'a=$(j .cost.total_lines_added); r=$(j .cost.total_lines_removed)\n'
     'if [ -n "$a$r" ]; then if [ "$C" = 1 ]; then add "$(printf \'\\033[32m+%s\\033[0m \\033[31m-%s\\033[0m\' "${a:-0}" "${r:-0}")"; '
     'else add "+${a:-0} -${r:-0}"; fi; fi'),
    ("duration", "Session time", "12m", "none",
     'v=$(j \'.cost.total_duration_ms | floor\'); if [ -n "$v" ]; then m=$((v / 60000)); '
     'if [ "$m" -ge 60 ]; then add "$((m / 60))h $(printf %02d $((m % 60)))m" 2; else add "${m}m" 2; fi; fi'),
    ("tokens", "Tokens (reads the whole conversation file at each refresh)", "question:12k session:340k", "none",
     't=$(j .transcript_path); if [ -n "$t" ] && [ -f "$t" ]; then v=$(jq -n -R -r \'' + STATUS_TOKENS_JQ + '\' "$t" 2>/dev/null)\n'
     'add "$v" 90; fi'),
    ("limit", "5-hour limit", "5h:78%", "none", 'lim five_hour 5h'),
    ("week", "Weekly limit", "7d:41%", "none", 'lim seven_day 7d'),
    ("terminal", "Terminal", "iTerm", "round",
     'case $TERM_PROGRAM in Apple_Terminal) t=Terminal ;; iTerm.app) t=iTerm ;; WarpTerminal) t=Warp ;; vscode) t="VS Code" ;; '
     'ghostty) t=Ghostty ;; "") t=$TERM ;; *) t=$TERM_PROGRAM ;; esac; add "$t" 32'),
    ("time", "Time", "14:05", "none", 'add "$(date +%H:%M)" 2'),
]
STATUS_CODE = {x[0]: x[4] for x in STATUS_PARTS}
STATUS_DEFAULT_BRACKETS = {x[0]: x[3] for x in STATUS_PARTS}
STATUS_DEFAULT_PARTS = ["path", "branch", "profile", "model", "context"]
STATUS_SEPARATORS = {"space": " ", "dot": " · ", "bar": " | ", "arrow": " › "}
STATUS_BRACKETS = {"none": ("", ""), "round": ("(", ")"), "square": ("[", "]"), "curly": ("{", "}"), "angle": ("⟨", "⟩")}
# How the 5-hour and weekly limits read: the share used, or the share left with the time
# until the reset when half or less is left. Scripts without it in their header show "used".
STATUS_LIMITS = ("used", "left")
# Presets that fill the editor in one click (nothing is saved until Save): (id, label,
# description, parts in order, brackets, separator, colors, limits). Brackets "default" gives
# every piece its own (STATUS_PARTS), any other id the same brackets to all of them.
STATUS_PRESETS = [
    ("essential", "Essential", "Profile, model and context used, between dots",
     ["profile", "model", "context"], "none", "dot", True, "used"),
    ("developer", "Developer", "Path, git branch, profile, model and context, each in its own brackets",
     ["path", "branch", "profile", "model", "context"], "default", "space", True, "used"),
    ("usage", "Usage", "Model, tokens, cost and the quota left on the 5-hour and weekly limits",
     ["model", "tokens", "cost", "limit", "week"], "none", "bar", True, "left"),
    ("handmade", "Like a hand-made one", "Everything a typical hand-written status line shows, quota left included",
     ["path", "branch", "profile", "email", "model", "style", "tokens", "context", "limit", "week", "terminal"],
     "default", "space", True, "left"),
]


def status_presets():
    """STATUS_PRESETS as the editor uses them: parts as "id:brackets" in line order."""
    return [{"id": pid, "label": label, "description": desc,
             "parts": [f"{p}:{STATUS_DEFAULT_BRACKETS[p] if br == 'default' else br}" for p in parts],
             "brackets": None if br == "default" else br, "separator": sep, "colors": colors, "limits": limits}
            for pid, label, desc, parts, br, sep, colors, limits in STATUS_PRESETS]


STATUS_SAMPLE_LEFT = {"limit": "5h:22%→1h20m", "week": "7d:59%"}
# The preview's data. No transcript_path: the preview adds one to a sample conversation of its
# own, so it never reads a file it did not write. resets_at is added relative to now.
STATUS_SAMPLE = {
    "model": {"id": "claude-opus-5-5", "display_name": "Opus"},
    "effort": {"level": "high"},
    "output_style": {"name": "Explanatory"},
    "pr": {"number": 42},
    "context_window": {"used_percentage": 42.4},
    "cost": {"total_cost_usd": 1.27, "total_lines_added": 120, "total_lines_removed": 34, "total_duration_ms": 754000},
    "rate_limits": {"five_hour": {"used_percentage": 78}, "seven_day": {"used_percentage": 41}},
}
# The preview's conversation: 12k tokens since the last prompt, 340k in all (a tool result
# is not a prompt).
STATUS_SAMPLE_TRANSCRIPT = [
    {"type": "user", "message": {"role": "user", "content": "add a login page"}},
    {"type": "assistant", "message": {"usage": {"input_tokens": 3000, "cache_creation_input_tokens": 20000,
                                                "cache_read_input_tokens": 290000, "output_tokens": 15000}}},
    {"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "content": "ok"}]}},
    {"type": "user", "message": {"role": "user", "content": "now the tests"}},
    {"type": "assistant", "message": {"usage": {"input_tokens": 1000, "cache_read_input_tokens": 9000, "output_tokens": 2000}}},
]


def status_parts(items):
    """[(id, brackets)] from "id" or "id:brackets" items: unknown ids and repeats dropped."""
    out, seen = [], set()
    for item in items:
        pid, _, br = str(item).partition(":")
        if pid not in STATUS_CODE or pid in seen:
            continue
        if br and br not in STATUS_BRACKETS:
            raise ApiError("Unknown brackets")
        seen.add(pid)
        out.append((pid, br or STATUS_DEFAULT_BRACKETS[pid]))
    return out


def status_style(separator, colors, limits="used"):
    if separator not in STATUS_SEPARATORS:
        raise ApiError("Unknown separator")
    if limits not in STATUS_LIMITS:
        raise ApiError("Unknown way to show the rate limits: expected used or left")
    return separator, bool(colors), limits


def status_script(parts, separator="space", colors=True, limits="used"):
    """The status line script: parts are (id, brackets) in the order to show them."""
    body = "\n".join(f"L='{STATUS_BRACKETS[br][0]}' R='{STATUS_BRACKETS[br][1]}'\n{STATUS_CODE[pid]}" for pid, br in parts)
    return f"""#!/bin/sh
{STATUS_MARK}
# parts: {" ".join(f"{pid}:{br}" for pid, br in parts)}
# style: separator={separator} colors={1 if colors else 0} limits={limits}
# Made in the Settings tab of cc-profiles, which rewrites it. To edit it by hand, delete the second line.
# Bytes stay bytes (LC_ALL=C): the shell cannot mangle ⟨ ⟩ or · whatever the terminal's locale.
export LC_ALL=C
C={1 if colors else 0}
LIM={limits}
SEP='{STATUS_SEPARATORS[separator]}'
[ "$C" = 1 ] && SEP=$(printf '\\033[2m%s\\033[0m' "$SEP")
input=$(cat)
dir=$(cd "${{CLAUDE_CONFIG_DIR:-$HOME/.claude}}" 2>/dev/null && pwd -P)
name=$(basename "$dir"); case $name in .claude-*) name=${{name#.claude-}} ;; *) name=default ;; esac
cfg="$dir/.claude.json"; [ -f "$cfg" ] || cfg="$HOME/.claude.json"  # the default profile keeps it in the home
if ! command -v jq >/dev/null 2>&1; then printf '%s (install jq for the rest)' "$name"; exit 0; fi
j() {{ printf '%s' "$input" | jq -r "$1 // empty" 2>/dev/null; }}
out=
add() {{
  [ -n "$1" ] || return 0
  s="$L$1$R"
  [ "$C" = 1 ] && [ -n "$2" ] && s=$(printf '\\033[%sm%s\\033[0m' "$2" "$s")
  out="${{out:+$out$SEP}}$s"
}}
# lim KEY LABEL: a rate limit, used or left (LIM), yellow from 70% used, red from 90%
lim() {{
  v=$(j ".rate_limits.$1.used_percentage | floor"); [ -n "$v" ] || return 0
  c=90; [ "$v" -ge 70 ] && c=33; [ "$v" -ge 90 ] && c=31
  if [ "$LIM" != left ]; then add "$2:$v%" $c; return 0; fi
  s="$2:$((100 - v))%"
  r=$(j ".rate_limits.$1.resets_at | floor")
  if [ "$v" -ge 50 ] && [ -n "$r" ]; then  # half or less left: the time until the reset
    d=$((r - $(date +%s)))
    if [ "$d" -ge 86400 ]; then s=$(printf '%s→%sd%sh' "$s" $((d / 86400)) $((d % 86400 / 3600)))
    elif [ "$d" -ge 3600 ]; then s=$(printf '%s→%sh%sm' "$s" $((d / 3600)) $((d % 3600 / 60)))
    elif [ "$d" -ge 60 ]; then s=$(printf '%s→%sm' "$s" $((d / 60)))
    elif [ "$d" -gt 0 ]; then s=$(printf '%s→<1m' "$s"); fi
  fi
  add "$s" $c
}}
cwd=$(j .workspace.current_dir)
{body}
printf '%s' "$out"
"""


def status_script_path(prof):
    return os.path.join(prof["dir_abs"], "statusline.sh")


def status_script_info(path):
    """{parts: [(id, brackets)], separator, colors, limits} of a script cc-profiles wrote, or
    None for any other file. Scripts from before per-piece brackets list bare ids, and those
    from before limits=left show the limits used."""
    try:
        with open(path) as f:
            head = f.read(800).split("\n")
    except OSError:
        return None
    if len(head) < 3 or head[1] != STATUS_MARK or not head[2].startswith("# parts:"):
        return None
    old = ":" not in head[2][len("# parts:"):]
    try:
        parts = status_parts(head[2][len("# parts:"):].split())
    except ApiError:
        return None
    if old:
        parts = [(pid, "none") for pid, _ in parts]
    info = {"parts": parts, "separator": "dot", "colors": False, "limits": "used"}
    if len(head) > 3 and head[3].startswith("# style:"):
        style = dict(x.split("=", 1) for x in head[3][len("# style:"):].split() if "=" in x)
        info["separator"] = style.get("separator") if style.get("separator") in STATUS_SEPARATORS else "dot"
        info["colors"] = style.get("colors") == "1"
        info["limits"] = style.get("limits") if style.get("limits") in STATUS_LIMITS else "used"
    return info


def status_command(prof):
    return "sh " + shlex.quote(status_script_path(prof))


def get_statusline(pid):
    prof = profile(pid)
    value, src = effective(prof, "statusLine")
    value = value if isinstance(value, dict) else None
    path = status_script_path(prof)
    info = status_script_info(path)
    mode = "off"
    if value:
        mode = "builtin" if value.get("command") == status_command(prof) and info is not None else "custom"
    info = info or {"parts": status_parts(STATUS_DEFAULT_PARTS), "separator": "space", "colors": True, "limits": "used"}
    return {"value": value, "source": src, "mode": mode, "parts": [f"{pid}:{br}" for pid, br in info["parts"]],
            "separator": info["separator"], "colors": info["colors"], "limits": info["limits"], "script": pretty(path), "script_is_other": os.path.exists(path) and not status_script_info(path),
            "jq": bool(find_tool("jq")), "presets": status_presets(), "separators": [{"id": k, "text": v} for k, v in STATUS_SEPARATORS.items()],
            "brackets": [{"id": k, "left": v[0], "right": v[1]} for k, v in STATUS_BRACKETS.items()],
            "parts_available": [dict({"id": x[0], "label": x[1], "sample": x[2], "brackets": x[3]},
                                     **({"sample_left": STATUS_SAMPLE_LEFT[x[0]]} if x[0] in STATUS_SAMPLE_LEFT else {}))
                                for x in STATUS_PARTS]}


def statusline_sample(tmp):
    """STATUS_SAMPLE with its conversation written in tmp and the limits resetting from now."""
    transcript = os.path.join(tmp, "sample.jsonl")
    with open(transcript, "w") as f:
        f.write("".join(json.dumps(x) + "\n" for x in STATUS_SAMPLE_TRANSCRIPT))
    now = int(time.time())
    limits = {k: dict(v, resets_at=now + secs) for (k, v), secs in
              zip(STATUS_SAMPLE["rate_limits"].items(), (80 * 60 + 30, (3 * 24 + 11) * 3600 + 30))}
    # a sample project: a fresh git repository on main, so the branch shows as "main*"
    project = os.path.join(tmp, "code", "api")
    os.makedirs(project)
    git = find_tool("git")
    if git:
        subprocess.run([git, "init", "-q", "-b", "main", project], capture_output=True, timeout=5)
    return dict(STATUS_SAMPLE, workspace={"current_dir": project}, transcript_path=transcript, rate_limits=limits)


def statusline_preview(pid, parts, separator="space", colors="1", limits="used"):
    """What the script prints on sample data, and the script itself. It runs from a
    temporary folder, never the profile's, on a sample conversation of its own: read-only."""
    prof = profile(pid)
    parts = status_parts(x for x in parts.split(",") if x)
    separator, colors, limits = status_style(separator, colors == "1", limits)
    script = status_script(parts, separator, colors, limits)
    if not parts:
        return {"text": "", "script": script}
    tmp = tempfile.mkdtemp(prefix="cc-profiles-statusline-")
    try:
        path = os.path.join(tmp, "statusline.sh")
        with open(path, "w") as f:
            f.write(script)
        env = dict(tool_env(), CLAUDE_CONFIG_DIR=prof["dir_abs"])
        r = subprocess.run(["sh", path], input=json.dumps(statusline_sample(tmp)), capture_output=True, text=True,
                           timeout=5, env=env)
        # the sample project lives in a temporary folder: show it where a real one would be
        text = r.stdout.strip("\n")
        for prefix in {os.path.realpath(tmp), tmp}:
            text = text.replace(prefix, "~")
        return {"text": text, "script": script}
    except (OSError, subprocess.SubprocessError) as e:
        return {"text": "", "script": script, "error": str(e)}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def statusline_value(prof, body):
    """(statusLine object, script info) a request asks for, checked. (None, None) turns it off;
    the info is None for a command of the user's own."""
    mode = body.get("mode")
    if mode == "off":
        return None, None
    if mode == "builtin":
        parts = status_parts(body.get("parts") or [])
        if not parts:
            raise ApiError("Pick at least one thing to show")
        separator, colors, limits = status_style(body.get("separator") or "space", body.get("colors", True),
                                                 body.get("limits") or "used")
        info = {"parts": parts, "separator": separator, "colors": colors, "limits": limits}
        command = status_command(prof)
    elif mode == "custom":
        command, info = str(body.get("command") or "").strip(), None
        if not command:
            raise ApiError("Write the command that prints the status line")
    else:
        raise ApiError("Unknown status line mode")
    value = {"type": "command", "command": command}
    for key, low in (("padding", 0), ("refreshInterval", 1)):
        n = body.get(key)
        if n in (None, ""):
            continue
        if not isinstance(n, int) or isinstance(n, bool) or n < low:
            raise ApiError(f"Invalid {'padding' if key == 'padding' else 'refresh interval'}: expected a whole number from {low}")
        value[key] = n
    if body.get("hideVimModeIndicator") is True:
        value["hideVimModeIndicator"] = True
    return value, info


def write_statusline(prof, value, info, bk):
    """Write a profile's statusLine (and its script for the built-in one), inside a backup."""
    path = status_script_path(prof)
    if info is not None:
        if os.path.exists(path) and status_script_info(path) is None:
            raise ApiError(f"{pretty(path)} exists and was not made by cc-profiles: rename it, or use it as your own command")
        bk.copy(path, "statusline.sh")
        write_text(path, status_script(info["parts"], info["separator"], info["colors"], info["limits"]))
    elif status_script_info(path) is not None:
        bk.stash(path, "statusline.sh")  # the old built-in script is no longer used
    targets = setting_targets(prof, "statusLine", value) if value is None else [effective(prof, "statusLine")[1] or "settings"]
    for which in targets:
        write_field(prof, which, "statusLine", value, bk)


def op_statusline(pid, body):
    prof = profile(pid)
    value, info = statusline_value(prof, body)
    bk = Backup("statusline", f"Status line of {prof['label']}")
    write_statusline(prof, value, info, bk)
    bk.note(f"statusLine = {json.dumps(value)}" + (f", script: {' '.join(p for p, _ in info['parts'])}" if info else ""))
    msg = "Status line turned off." if value is None else "Status line saved: it shows from the next Claude Code session."
    return {"message": msg, "backup": bk.close()}


def status_signature(sl):
    """What makes two profiles' status lines the same, the script's own path aside."""
    if sl["mode"] == "off":
        return ("off",)
    rest = {k: v for k, v in sl["value"].items() if k != "command" or sl["mode"] == "custom"}
    script = (sl["parts"], sl["separator"], sl["colors"], sl["limits"]) if sl["mode"] == "builtin" else None
    return (sl["mode"], json.dumps(rest, sort_keys=True), script)


def statusline_all_plan(pid):
    """Which profiles get this profile's status line, and which are skipped, with the reason."""
    prof = profile(pid)
    cur = get_statusline(pid)
    apply, skip, written = [], [], {}
    for o in profiles():
        if o["id"] == pid:
            continue
        mine = get_statusline(o["id"])
        where = effective(o, "statusLine")[1] or "settings"
        target = field_path(o, where)
        if status_signature(mine) == status_signature(cur):
            reason = "already has it"
        elif file_error(o, where):
            reason = f"{os.path.basename(target)} has an error: fix it in the advanced editor"
        elif cur["mode"] == "builtin" and mine["script_is_other"]:
            reason = f"{mine['script']} was not made by cc-profiles"
        elif os.path.realpath(target) in written:
            reason = f"shares {os.path.basename(target)} with {written[os.path.realpath(target)]}"
        else:
            written[os.path.realpath(target)] = o["label"]
            apply.append({"id": o["id"], "label": o["label"], "detail": f"{mine['mode']} → {cur['mode']}"})
            continue
        skip.append({"id": o["id"], "label": o["label"], "reason": reason})
    return {"from": prof["label"], "mode": cur["mode"], "apply": apply, "skip": skip}


def op_statusline_all(pid):
    plan = statusline_all_plan(pid)
    if not plan["apply"]:
        raise no_targets(plan)
    cur = get_statusline(pid)
    info = ({"parts": status_parts(cur["parts"]), "separator": cur["separator"], "colors": cur["colors"], "limits": cur["limits"]}
            if cur["mode"] == "builtin" else None)
    bk = Backup("statusline-all", f"Status line of {plan['from']} in every profile")
    for t in plan["apply"]:
        o = profile(t["id"])
        if cur["mode"] == "off":
            value = None
        elif cur["mode"] == "builtin":
            value = dict(cur["value"], command=status_command(o))
        else:
            value = dict(cur["value"])
        write_statusline(o, value, info, bk)
        bk.note(f"{o['label']}: {t['detail']}")
    for x in plan["skip"]:
        bk.note(f"skipped {x['label']}: {x['reason']}")
    return {"message": plan_message("Status line set", plan), "backup": bk.close()}
