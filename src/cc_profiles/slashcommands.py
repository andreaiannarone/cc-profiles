# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: custom slash commands."""

import os
import re

from .core import ApiError, Backup, pretty, profile, profiles, read_json, session_hint, write_text
from .command import COMMAND_MARK
from .sharing import primary, share_state
from .settings import no_targets, plan_message
from .agents import entry_value, split_agent, unquote
from .info import claude_binary, claude_version
from .claudebinary import read_installed

# ---------------------------------------------------------------------------
# Custom slash commands
# ---------------------------------------------------------------------------
# <profile>/commands/<name>.md is the command /<name>; a subfolder adds a namespace:
# commands/frontend/test.md is /frontend:test. The file is a prompt, with optional
# frontmatter (description, argument-hint, allowed-tools, model…) that Claude Code reads.
# The editor edits the whole file. /cc-profiles (COMMAND_MARK) is cc-profiles' own, kept
# up to date at start: shown, never edited or deleted here. Plugins bring commands of their own.
SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
FRONT_KEYS = ("description", "argument-hint", "allowed-tools", "model", "disable-model-invocation", "user-invocable")
NEW_COMMAND = "---\ndescription: \nargument-hint: \n---\n\n$ARGUMENTS\n"


# Claude Code's own commands, shown read-only. From the command definitions inside the Claude
# Code binary (BUILTIN_COMMANDS_VERSION), with their descriptions as written there; the few
# whose description depends on the setup carry a plain one. Internal ones, and those for one
# kind of setup only (Bedrock, Vertex, cloud sessions…), are left out: scripts/check_settings_schema.py
# knows them (BUILTIN_LEFT_OUT) and reports only the commands a new version adds or removes.
# (name, argument hint, description, aliases)
BUILTIN_COMMANDS_VERSION = "2.1.326"
BUILTIN_COMMANDS = [
    ("Conversation", [
        ("clear", "[name]", "Start a new session with empty context; previous session stays on disk (resumable with /resume)", ["reset", "new"]),
        ("compact", "<optional custom summarization instructions>", "Free up context by summarizing the conversation so far", []),
        ("resume", "", "Resume a previous session", ["continue"]),
        ("rename", "[name]", "Rename the current conversation", ["name"]),
        ("branch", "[name]", "Create a branch of the current conversation at this point", []),
        ("rewind", "", "Restore earlier code, conversation, or both", ["checkpoint", "undo"]),
        ("export", "[filename]", "Export this session to a file or clipboard", []),
        ("copy", "", "Copy the last response to clipboard (/copy 2 for the one before)", []),
        ("btw", "[question]", "Ask a side question without interrupting Claude", []),
        ("recap", "", "Generate a one-line session recap now", []),
        ("goal", "[<condition> | clear]", "Set a goal Claude checks before stopping", []),
        ("plan", "[open|<description>]", "Turn on plan mode or view the plan", []),
        ("diff", "", "View uncommitted changes and per-turn diffs", []),
        ("add-dir", "<path>", "Add a working directory", []),
        ("background", "[prompt]", "Send this session to the background and free the terminal", ["bg"]),
        ("fork", "<directive>", "Start a background agent with the full conversation", []),
        ("subtask", "<task>", "Send a subagent off with your full context; its result comes back here", []),
        ("tasks", "", "View and manage everything running in the background", ["bashes"]),
        ("restart", "", "Restart Claude Code and keep this session", ["update"]),
        ("exit", "", "Exit the CLI", ["quit"]),
    ]),
    ("Model and context", [
        ("model", "<model>", "Set the AI model for Claude Code", []),
        ("effort", "", "Set the model's effort level", []),
        ("fast", "[on|off]", "Toggle fast mode", []),
        ("advisor", "", "Let Claude consult a stronger model at key moments", []),
        ("context", "[all]", "Show what fills the context", []),
        ("autocompact", "[auto|<tokens>]", "Set how full the context gets before auto-summarizing", []),
        ("output-style", "[style]", "List output styles or switch to one", []),
        ("focus", "[on|off]", "Toggle focus view: just your prompt, summary, and response", []),
    ]),
    ("Settings", [
        ("config", "[key=value]", "Open settings", ["settings"]),
        ("permissions", "", "Manage allow and deny tool permission rules", ["allowed-tools"]),
        ("hooks", "", "View hook configurations for tool events", []),
        ("keybindings", "", "Open your keyboard shortcuts file", []),
        ("statusline", "", "Set up Claude Code's status line UI", []),
        ("memory", "", "Edit CLAUDE.md files and memory settings", []),
        ("init", "", "Initialize a new CLAUDE.md file with codebase documentation", []),
        ("theme", "", "Change the theme", []),
        ("tui", "[default|fullscreen]", "Set the terminal UI renderer (default | fullscreen)", []),
        ("terminal-setup", "", "Check the terminal's setup for Shift+Enter newlines", []),
        ("scroll-speed", "", "Adjust mouse wheel scroll speed", []),
        ("voice", "[hold|tap|off]", "Toggle voice mode", []),
        ("privacy-settings", "", "View and update your privacy settings", []),
        ("sandbox", "", "Turn the sandbox for Bash commands on or off, and see its state", []),
    ]),
    ("Extensions", [
        ("mcp", "[reconnect|enable|disable [<server>|all]]", "Manage MCP servers", []),
        ("plugin", "", "Manage Claude Code plugins", ["plugins", "marketplace"]),
        ("reload-plugins", "[--force]", "Activate pending plugin changes in the current session", []),
        ("skills", "", "List available skills", []),
        ("reload-skills", "", "Pick up skills added or changed on disk during this session", []),
        ("skill-doctor", "", "Show which loaded skills are unused and costing context", []),
        ("loops", "", "List, create, and delete loops", []),
        ("ide", "[open]", "Manage IDE integrations and show status", []),
        ("chrome", "", "Open Claude in Chrome settings", []),
        ("install-github-app", "", "Set up Claude GitHub Actions for a repository", []),
    ]),
    ("Account and help", [
        ("usage", "", "Show session cost, plan usage, and activity stats", ["cost", "stats"]),
        ("status", "", "Show version, account, model, MCP servers and setup warnings", []),
        ("login", "", "Sign in with your Anthropic account", []),
        ("logout", "", "Sign out from your Anthropic account", []),
        ("upgrade", "", "Upgrade your plan for higher rate limits and more Opus", []),
        ("insights", "", "Generate a report analyzing your Claude Code sessions", []),
        ("doctor", "[prompt-audit [<path>]]", "Health-check your setup and fix issues: installation, unused extensions, duplicated or bloated memory files, slow hooks, updates, permissions", ["checkup"]),
        ("help", "[command]", "Show help and available commands", []),
        ("powerup", "", "Learn Claude Code features in short lessons", []),
        ("release-notes", "", "View release notes", []),
        ("version", "", "Show this session's version (autoupdate may have a newer one)", []),
        ("feedback", "[report]", "Send feedback to Anthropic or report a bug", []),
        ("bug", "[report]", "Report a bug or share your session", ["share"]),
    ]),
]
# The skills that come with Claude Code and can be typed as a command, with their menu text
# from the binary (BUILTIN_COMMANDS_VERSION). Others are internal or only for some accounts.
BUILTIN_SKILLS = [
    ("batch", "<instruction>", "Plan a large change; background agents each open a PR"),
    ("claude-api", "", "Build and debug apps that use the Claude API"),
    ("claude-in-chrome", "", "Let Claude browse and interact with pages in your Chrome"),
    ("code-review", "", "Review the current diff or a PR for bugs and cleanups"),
    ("debug", "[issue description]", "Turn on debug logging and investigate problems"),
    ("fewer-permission-prompts", "", "Pre-approve safe read-only commands based on your usage"),
    ("loop", "[interval] [prompt]", "Repeat a prompt or command on an interval (e.g. /loop 5m /foo)"),
    ("run", "", "Launch this project\u2019s app to see your change working"),
    ("run-skill-generator", "", "Create a skill that knows how to run this project\u2019s app"),
    ("schedule", "", "Create and manage routines: cloud agents on a schedule"),
    ("security-review", "", "Complete a security review of the pending changes on the current branch"),
    ("simplify", "[<target>]", "Clean up the changed code without changing behavior"),
    ("update-config", "", "Change settings: hooks, permissions, environment variables"),
]


# Claude Code's own commands and skills known and deliberately not shown: internal, for one
# kind of setup or account (Bedrock, Vertex, cloud sessions, Slack, Design…), or removed.
# Read from the binary, any other new one is shown under NEW_GROUP; scripts/check_settings_schema.py
# reports it, to sort it into BUILTIN_COMMANDS / BUILTIN_SKILLS or here.
BUILTIN_LEFT_OUT = {
    "agents", "artifacts", "auto-mode-setup", "autofix-pr", "brief", "cd", "cloud-plugins", "color", "daemon",
    "design-consent", "design-login", "design-revoke", "desktop", "extra-usage", "heapdump", "import", "install",
    "install-slack-app", "list-agents", "mobile", "passes", "pause-memory", "pro-trial-expired", "project", "radio",
    "rate-limit-options", "remote-control", "remote-env", "schedule", "session", "setup-bedrock", "setup-vertex",
    "stickers", "stop", "team-onboarding", "teleport", "ultraplan", "ultrareview", "usage-credits", "use-case",
    "web-setup", "wellbeing", "workflow-launch-exec", "workflows",
}
SKILLS_LEFT_OUT = {
    "artifact-capabilities", "artifact-design", "artifact-diagramming", "commit", "cowork-plugin", "dataviz", "design",
    "design-sync", "explain-usage", "keybindings-help", "pr", "send-to-project", "setup-claude", "verify",
    "workflow-authoring",
}
NEW_GROUP = "New in your version"


def skill_entry(folder, slash_name, source):
    """A skill as it appears among the commands, or None when it cannot be typed (user-invocable: false)."""
    try:
        text = open(os.path.join(folder, "SKILL.md"), errors="replace").read(8000)
    except OSError:
        return None
    f = front(text)
    if f.get("user-invocable", "").strip().lower() == "false":
        return None
    return {"slash": "/" + slash_name, "hint": f.get("argument-hint", ""), "source": source,
            "description": f.get("description", "") or f.get("fallback", "")}


def skill_commands(prof):
    """Every skill that can be typed as /name: the profile's own, the plugins' (/plugin:name), and
    the ones that come with Claude Code. Read-only here: the Skills tab edits the profile's."""
    out = []
    root = os.path.join(prof["dir_abs"], "skills")
    for n in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        if not n.startswith("."):
            item = skill_entry(os.path.join(root, n), n, "profile")
            if item:
                out.append(item)
    inst = read_json(os.path.join(prof["dir_abs"], "plugins", "installed_plugins.json"), {}) or {}
    for plugin, installs in sorted((inst.get("plugins") or {}).items() if isinstance(inst.get("plugins"), dict) else []):
        installs = [installs] if isinstance(installs, dict) else (installs or [])
        path = (installs[0] if installs and isinstance(installs[0], dict) else {}).get("installPath") or ""
        sroot = os.path.join(path, "skills") if path else ""
        for n in sorted(os.listdir(sroot)) if sroot and os.path.isdir(sroot) else []:
            if not n.startswith("."):
                item = skill_entry(os.path.join(sroot, n), f"{plugin.split('@')[0]}:{n}", plugin)
                if item:
                    out.append(item)
    return out


_installed = {}


def installed_claude():
    """The installed Claude Code's version, asked once per binary (a new version is a new file)."""
    b = claude_binary()
    if not b:
        return None
    try:
        key = (b, os.stat(b).st_mtime)
    except OSError:
        return None
    if key not in _installed:
        _installed.clear()
        _installed[key] = claude_version()
    return _installed[key]


def builtin():
    """(commands, skills, version, source): Claude Code's own commands and bundled skills, read
    from the installed binary (source "installed"), or this list when it cannot be read ("list").
    From the binary: what this list knows and the binary still has, with the binary's texts
    where they are plain strings; what is new (and not left out on purpose) under NEW_GROUP."""
    info = read_installed([(n, d) for n, _, d in BUILTIN_SKILLS])
    def cmd(n, hint, desc, aliases, group):
        return {"name": n, "slash": "/" + n, "hint": hint, "description": desc, "aliases": ["/" + a for a in aliases],
                "group": group}

    def skill(n, hint, desc):
        return {"slash": "/" + n, "hint": hint, "description": desc, "source": "builtin"}
    if not info:
        return ([cmd(n, h, d, a, g) for g, items in BUILTIN_COMMANDS for n, h, d, a in items],
                [skill(*s) for s in BUILTIN_SKILLS], BUILTIN_COMMANDS_VERSION, "list")
    found = dict(info["skills"], **info["commands"])
    known_cmds = {n for _, items in BUILTIN_COMMANDS for n, *_ in items}
    known_skills = {n for n, *_ in BUILTIN_SKILLS}
    cmds = [cmd(n, found[n]["hint"] or "", found[n]["description"] or d, found[n]["aliases"] or a, g)
            for g, items in BUILTIN_COMMANDS for n, h, d, a in items if n in found]
    cmds += [cmd(n, c["hint"] or "", c["description"] or "", c["aliases"], NEW_GROUP)
             for n, c in sorted(info["commands"].items())
             if n not in known_cmds and n not in BUILTIN_LEFT_OUT and not c["hidden"]]
    skills = []
    for n, h, d in BUILTIN_SKILLS:
        if n in info["skills"]:
            skills.append(skill(n, info["skills"][n]["hint"] or "", info["skills"][n]["description"] or d))
        elif n in info["present"]:
            skills.append(skill(n, h, d))
    skills += [skill(n, c["hint"] or "", c["description"] or "") for n, c in sorted(info["skills"].items())
               if n not in known_skills | known_cmds | SKILLS_LEFT_OUT and c["user"] and not c["hidden"]]
    return cmds, skills, info["version"] or installed_claude(), "installed"


def commands_dir(prof):
    return os.path.join(prof["dir_abs"], "commands")


def check_name(name):
    """A command name: folders and file, without .md, separated by /."""
    parts = str(name or "").strip().strip("/").split("/")
    if len(parts) > 3 or not all(SEGMENT.fullmatch(p) and ".." not in p for p in parts) or parts[-1].endswith(".md"):
        raise ApiError("Invalid name: letters, digits, dots, dashes and underscores; a folder/name for a namespace")
    return "/".join(parts)


def command_path(prof, name, must_exist=True):
    name = check_name(name)
    path = os.path.join(commands_dir(prof), *name.split("/")) + ".md"
    if must_exist and not os.path.isfile(path):
        raise ApiError(f"Command not found in {prof['label']}: /{slash(name)}", 404)
    return path


def slash(name):
    return name.replace("/", ":")


def command_names(prof):
    """Every command file of the profile, as names: frontend/test for commands/frontend/test.md."""
    root = commands_dir(prof)
    out = []
    for cur, dirs, files in os.walk(root, followlinks=True):
        rel = os.path.relpath(cur, root)
        depth = 0 if rel == "." else rel.count(os.sep) + 1
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and depth < 2)
        for f in sorted(files):
            if f.endswith(".md") and not f.startswith("."):
                n = f[:-3] if rel == "." else rel.replace(os.sep, "/") + "/" + f[:-3]
                try:
                    out.append(check_name(n))
                except ApiError:
                    continue
    return sorted(out)


def is_managed(text):
    return COMMAND_MARK in text[:400]


def commands_note(prof):
    """Who else sees a change to this profile's commands."""
    src = primary()
    if prof["id"] != src["id"]:
        return f"shared with {src['label']}" if share_state(prof, "commands", "dir")["shared"] else ""
    users = [p["label"] for p in profiles()[1:] if share_state(p, "commands", "dir")["shared"]]
    return f"shared with {', '.join(users)}" if users else ""


def front(text):
    """The frontmatter keys Claude Code reads, as text."""
    entries, body = split_agent(text)
    out = {}
    for key, lines in entries or []:
        if key in FRONT_KEYS:
            v = entry_value(lines) if key == "allowed-tools" else unquote(lines[0].split(":", 1)[1])
            out[key] = ", ".join(v) if isinstance(v, list) else v
    if not out.get("description"):  # Claude Code falls back to the first line of the prompt
        first = next((l.strip().lstrip("#").strip() for l in body.splitlines() if l.strip()), "")
        out["fallback"] = first[:200]
    return out


def command_summary(name, text, linked=False):
    f = front(text)
    return {"name": name, "slash": "/" + slash(name), "description": f.get("description", ""),
            "fallback": f.get("fallback", ""), "hint": f.get("argument-hint", ""), "model": f.get("model", ""),
            "tools": f.get("allowed-tools", ""), "linked": linked, "managed": is_managed(text)}


def plugin_commands(prof):
    """Commands that installed plugins bring: /plugin:name, read-only."""
    inst = read_json(os.path.join(prof["dir_abs"], "plugins", "installed_plugins.json"), {}) or {}
    out = []
    for plugin, installs in sorted((inst.get("plugins") or {}).items() if isinstance(inst.get("plugins"), dict) else []):
        installs = [installs] if isinstance(installs, dict) else (installs or [])
        path = (installs[0] if installs and isinstance(installs[0], dict) else {}).get("installPath") or ""
        for n in command_names({"dir_abs": path}) if path else []:
            try:
                text = open(os.path.join(path, "commands", *n.split("/")) + ".md", errors="replace").read(8000)
            except OSError:
                continue
            item = command_summary(n, text)
            item.update(plugin=plugin, slash=f"/{plugin.split('@')[0]}:{slash(n)}")
            out.append(item)
    return out


def list_commands(pid):
    prof = profile(pid)
    cmds, skills, version, source = builtin()
    items = []
    for n in command_names(prof):
        path = command_path(prof, n)
        try:
            items.append(command_summary(n, open(path, errors="replace").read(20000), os.path.islink(path)))
        except OSError:
            continue
    return {"commands": items, "dir": pretty(commands_dir(prof)), "shared": commands_note(prof),
            "plugins": plugin_commands(prof), "template": NEW_COMMAND, "builtin": cmds, "skills": skill_commands(prof) + skills,
            "builtin_version": version, "builtin_source": source, "installed_version": installed_claude()}


def command_read(pid, name):
    prof = profile(pid)
    path = command_path(prof, name)
    content = open(path, errors="replace").read()
    return dict(command_summary(check_name(name), content, os.path.islink(path)), content=content)


def check_content(content):
    if not isinstance(content, str) or not content.strip():
        raise ApiError("Write the prompt the command sends")
    entries, _ = split_agent(content)
    if content.lstrip().startswith("---") and entries is None:
        raise ApiError("The frontmatter is not closed: end it with a --- line")
    if is_managed(content):
        raise ApiError("Remove the line “" + COMMAND_MARK + "”: it marks cc-profiles' own command")
    return content if content.endswith("\n") else content + "\n"


def op_command_save(pid, name, content, new=False):
    """Create a command (new) or save the file of an existing one."""
    prof = profile(pid)
    name = check_name(name)
    path = command_path(prof, name, must_exist=not new)
    if new and os.path.lexists(path):
        raise ApiError(f"{prof['label']} already has /{slash(name)}")
    if not new and is_managed(open(path, errors="replace").read(400)):
        raise ApiError("/cc-profiles is cc-profiles' own command: it is kept up to date at every start")
    text = check_content(content)
    bk = Backup("command-create" if new else "command-save", f"{'New' if new else 'Edit'} command /{slash(name)} ({prof['label']})")
    bk.mkdir(os.path.dirname(path))
    bk.copy(path, os.path.basename(path))
    write_text(path, text)
    verb = "created" if new else "saved"
    return {"message": f"/{slash(name)} {verb} in {prof['label']}." + session_hint(prof), "backup": bk.close()}


def op_command_delete(pid, name):
    prof = profile(pid)
    path = command_path(prof, name)
    if is_managed(open(path, errors="replace").read(400)):
        raise ApiError("/cc-profiles is cc-profiles' own command: turn it off with cc-profiles install-command --off")
    linked = os.path.islink(path)
    bk = Backup("command-delete", f"Delete command /{slash(check_name(name))} ({prof['label']})")
    bk.stash(path, "command-" + os.path.basename(path))
    msg = f"/{slash(check_name(name))} removed from {prof['label']}" + (" (only the link; its file is untouched)." if linked else ".")
    return {"message": msg, "backup": bk.close()}


def command_copy_plan(pid, name, only=None):
    src = profile(pid)
    path = command_path(src, name)
    if is_managed(open(path, errors="replace").read(400)):
        raise ApiError("/cc-profiles is cc-profiles' own command: every profile gets it at start")
    written = {os.path.realpath(commands_dir(src)): src["label"]}
    apply, skip = [], []
    for o in profiles():
        if o["id"] == pid or (only and o["id"] != only):
            continue
        t = command_path(o, name, must_exist=False)
        root = os.path.realpath(commands_dir(o))
        if root in written:
            reason = f"shares its commands with {written[root]}"
        elif os.path.lexists(t):
            reason = f"already has /{slash(check_name(name))}"
        else:
            written[root] = o["label"]
            apply.append({"id": o["id"], "label": o["label"], "detail": f"copied to {pretty(t)}"})
            continue
        skip.append({"id": o["id"], "label": o["label"], "reason": reason})
    return {"name": check_name(name), "from": src["label"], "apply": apply, "skip": skip}


def copy_command(pid, plan, title):
    if not plan["apply"]:
        raise no_targets(plan)
    text = open(os.path.realpath(command_path(profile(pid), plan["name"])), errors="replace").read()
    bk = Backup("command-copy", title)
    for t in plan["apply"]:
        dst = command_path(profile(t["id"]), plan["name"], must_exist=False)
        bk.mkdir(os.path.dirname(dst))
        bk.copy(dst)
        write_text(dst, text)
        bk.note(f"{t['label']}: {t['detail']}")
    for s in plan["skip"]:
        bk.note(f"skipped {s['label']}: {s['reason']}")
    return bk.close()


def op_command_copy(pid, name, to):
    dst = profile(to)
    if dst["id"] == profile(pid)["id"]:
        raise ApiError("Pick another profile")
    plan = command_copy_plan(pid, name, only=dst["id"])
    if plan["skip"]:
        raise ApiError(f"{dst['label']} {plan['skip'][0]['reason']}")
    backup = copy_command(pid, plan, f"Copy command /{slash(plan['name'])}: {plan['from']} → {dst['label']}")
    return {"message": f"/{slash(plan['name'])} copied to {dst['label']}." + session_hint(dst), "backup": backup}


def op_command_copy_all(pid, name):
    plan = command_copy_plan(pid, name)
    backup = copy_command(pid, plan, f"Copy command /{slash(plan['name'])} from {plan['from']} to every profile")
    return {"message": plan_message(f"/{slash(plan['name'])} copied", plan), "backup": backup}
