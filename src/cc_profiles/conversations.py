# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: Conversations."""

import json
import os
import re
import shutil

from .core import ApiError, Backup, pretty, profile, project_dir
from .paths import path_index, project_folders
from .projects import sessions_of

# ---------------------------------------------------------------------------
# Conversations
# ---------------------------------------------------------------------------
# projects/<name>/<session>.jsonl, one JSON object per line. Lines of type "user"
# and "assistant" carry message.content: a string, or a list of blocks (text,
# tool_use, tool_result, thinking, image). "ai-title" lines hold the title Claude
# Code generated. The file snapshots of a session live in file-history/<session>.
SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
VIEW_LIMIT = 300      # messages shown by the viewer, the most recent ones
TEXT_LIMIT = 4000     # characters per message in the viewer


def conversation_path(prof, name, session, must_exist=True):
    if not session or not SESSION_ID.fullmatch(session) or ".." in session:
        raise ApiError("Invalid conversation id")
    f = os.path.join(project_dir(prof, name), session + ".jsonl")
    if must_exist and not os.path.isfile(f):
        raise ApiError(f"Conversation not found in {prof['label']}: {session}", 404)
    return f


def message_of(j):
    """The "message" object of a line, or {} when a line is malformed."""
    m = j.get("message")
    return m if isinstance(m, dict) else {}


def prompt_text(j):
    """The text a person typed, or None for tool results, meta lines and commands."""
    if j.get("type") != "user" or j.get("isMeta"):
        return None
    c = message_of(j).get("content")
    if isinstance(c, list):
        c = "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(c, str) or not c.strip():
        return None
    t = c.strip()
    if t.startswith("<") and not t.startswith("<pasted"):  # <command-name>, <local-command-…>, <task-notification>…
        return None
    return t


def assistant_text(j):
    c = message_of(j).get("content")
    if isinstance(c, str):
        return c.strip() or None
    if isinstance(c, list):
        return "\n".join(b.get("text", "") for b in c if isinstance(b, dict) and b.get("type") == "text").strip() or None
    return None


def conversation_summary(f):
    """Title, counts and dates of one conversation, reading the file line by line."""
    title = ai_title = None
    users = replies = 0
    first = last = None
    with open(f, errors="replace") as fh:
        for line in fh:
            # cheap filter: most lines are tool output, snapshots and bookkeeping. It looks for the
            # values only, not '"type":"user"', so spacing in the JSON does not matter; json decides.
            if '"user"' not in line and '"assistant"' not in line and '"ai-title"' not in line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if not isinstance(j, dict):
                continue
            t = j.get("type")
            if t == "ai-title" and j.get("aiTitle"):
                ai_title = j["aiTitle"]
                continue
            ts = j.get("timestamp")
            if ts:
                first = first or ts
                last = ts
            if t == "user":
                p = prompt_text(j)
                if p:
                    users += 1
                    title = title or p
            elif t == "assistant" and assistant_text(j):
                replies += 1
    st = os.stat(f)
    t = " ".join((ai_title or title or "").split())
    return {"title": t[:120] + ("…" if len(t) > 120 else ""), "prompts": users, "replies": replies,
            "first": first, "last": last, "mtime": st.st_mtime, "size": st.st_size}


def list_conversations(pid, name):
    prof = profile(pid)
    d = project_dir(prof, name)
    out = []
    for sid in sessions_of(d):
        item = conversation_summary(os.path.join(d, sid + ".jsonl"))
        item.update(session=sid, snapshots=os.path.isdir(os.path.join(prof["dir_abs"], "file-history", sid)))
        out.append(item)
    out.sort(key=lambda c: c["mtime"], reverse=True)
    return {"conversations": out, "path": pretty(path_index().get(name) or name)}


def conversation_projects(pid):
    """Projects of a profile that have conversations, with how many."""
    prof = profile(pid)
    idx = path_index()
    out = []
    for name, _, convs in project_folders(prof):
        n = len(convs)
        if n:
            out.append({"name": name, "pretty": pretty(idx.get(name)) or name, "count": n})
    out.sort(key=lambda p: p["pretty"].lower())
    return out


def conversation_view(pid, name, session):
    f = conversation_path(profile(pid), name, session)
    msgs = []
    with open(f, errors="replace") as fh:
        for line in fh:
            if '"user"' not in line and '"assistant"' not in line:
                continue
            try:
                j = json.loads(line)
            except ValueError:
                continue
            if not isinstance(j, dict):
                continue
            ts = j.get("timestamp")
            if j.get("type") == "user":
                text = prompt_text(j)
                if text:
                    msgs.append({"role": "user", "time": ts, "text": text})
                continue
            c = message_of(j).get("content")
            text = assistant_text(j)
            if text:
                msgs.append({"role": "assistant", "time": ts, "text": text})
            if isinstance(c, list):
                for b in c:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        msgs.append({"role": "tool", "time": ts, "text": f"Tool: {b.get('name', '?')}"})
    total = len(msgs)
    truncated = total > VIEW_LIMIT
    msgs = msgs[-VIEW_LIMIT:]
    for m in msgs:
        if len(m["text"]) > TEXT_LIMIT:
            m["text"] = m["text"][:TEXT_LIMIT] + "…"
            truncated = True
    return {"messages": msgs, "truncated": truncated, "total": total}


def op_conversation_move(pid, name, session, to_pid):
    src, dst = profile(pid), profile(to_pid)
    if src["id"] == dst["id"]:
        raise ApiError("Pick another profile")
    f = conversation_path(src, name, session)
    tdir = project_dir(dst, name, must_exist=False)
    t = os.path.join(tdir, session + ".jsonl")
    if os.path.lexists(t):
        raise ApiError(f"{dst['label']} already has this conversation")
    bk = Backup(f"move-conversation-{src['id']}-{dst['id']}",
                f"Move conversation {session[:8]}: {src['label']} → {dst['label']}")
    bk.mkdir(tdir)
    shutil.move(f, t)
    bk.moved(f, t)
    fh, moved_fh = os.path.join(src["dir_abs"], "file-history", session), False
    tfh = os.path.join(dst["dir_abs"], "file-history", session)
    if os.path.isdir(fh) and not os.path.lexists(tfh):
        bk.mkdir(os.path.dirname(tfh))
        shutil.move(fh, tfh)
        bk.moved(fh, tfh)
        moved_fh = True
    bk.note(f"in {pretty(path_index().get(name)) or name}; file snapshots {'moved' if moved_fh else 'none'}")
    msg = f"Conversation moved to {dst['label']}" + (", with its file snapshots." if moved_fh else ".")
    return {"message": msg, "backup": bk.close()}


def op_conversation_delete(pid, name, session):
    prof = profile(pid)
    f = conversation_path(prof, name, session)
    bk = Backup(f"delete-conversation-{prof['id']}", f"Delete conversation {session[:8]} ({prof['label']})")
    bk.stash(f, f"{session}.jsonl")
    fh = os.path.join(prof["dir_abs"], "file-history", session)
    if os.path.isdir(fh):
        bk.stash(fh, f"file-history-{session}")
    return {"message": "Conversation moved to the backup.", "backup": bk.close()}
