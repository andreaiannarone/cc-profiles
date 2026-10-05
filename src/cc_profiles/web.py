# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: HTTP."""

import json
import os
import shutil
import socketserver
import struct
import sys
import tempfile
import zlib
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.parse import parse_qs
from urllib.parse import urlparse

from . import __version__
from . import core
from .core import ApiError, STATIC_DIR, TOKEN, _lock, abort_open_backups
from .projects import list_projects, move_plan, op_delete, op_move, op_relink, op_rule
from .memories import (
    memory_list,
    memory_projects,
    memory_read,
    op_memory_delete,
    op_memory_move,
    op_memory_save,
)
from .sharing import list_sharing, op_share, share_plan
from .settings import (
    get_settings,
    get_statusline,
    op_claude_md,
    op_global,
    op_permission_all,
    op_permissions,
    op_setting,
    op_setting_all,
    op_settings_raw,
    op_statusline,
    op_statusline_all,
    permission_all_plan,
    setting_all_plan,
    statusline_all_plan,
    statusline_preview,
)
from .health import candidates, health, list_profiles
from .backups import backup_auto, list_backups, op_backup_auto, op_backup_delete, op_backup_prune, op_restore
from .info import about
from .extensions import (
    list_mcp,
    list_skills,
    mcp_all_plan,
    mcp_server,
    op_mcp_copy,
    op_mcp_copy_all,
    op_mcp_delete,
    op_mcp_save,
    op_skill_copy,
    op_skill_copy_all,
    op_skill_create,
    op_skill_delete,
    op_skill_save,
    skill_all_plan,
    skill_read,
)
from .conversations import (
    conversation_projects,
    conversation_view,
    list_conversations,
    op_conversation_delete,
    op_conversation_move,
)
from .search import compare, search
from .newprofile import op_create_profile
from .transfer import IMPORT_MAX, export_profile, op_import_profile
from .templates import list_templates, op_create_from_template, op_template_delete, op_template_save
from .plugins import list_plugins, op_plugin_enable
from .editprofile import delete_plan, op_delete_profile, op_update_profile
from .installer import claude_status, op_install
from .updater import check_update, op_update

# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
class Server(ThreadingHTTPServer):
    def server_bind(self):
        # HTTPServer.server_bind also calls socket.getfqdn(), a reverse DNS lookup
        # that can take 30 s on some Macs. The name is never used: skip it.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


# ---------------------------------------------------------------------------
# Favicon as PNG and ICO. The page links an inline SVG, which Safari ignores: it
# wants a PNG or /favicon.ico. Drawn here from the mascot of docs/assets/favicon.svg,
# so the repo holds no binary copy that could drift.
# ---------------------------------------------------------------------------
MASCOT = ("............",
          "......#.....",
          ".....#......",
          "..########..",
          ".##########.",
          ".##o####o##.",
          ".##o####o##.",
          ".##########.",
          ".##########.",
          ".##########.",
          "..##....##..",
          "............")
MASCOT_COLORS = {"#": (0xd9, 0x77, 0x57, 255), "o": (0x1d, 0x1c, 0x1a, 255)}


def mascot_png(scale, background=None):
    """The mascot as a PNG, each pixel of the grid a scale×scale square."""
    clear = background + (255,) if background else (0, 0, 0, 0)
    rows = []
    for line in MASCOT:
        row = b"".join(bytes(MASCOT_COLORS.get(c, clear)) * scale for c in line)
        rows += [b"\0" + row] * scale
    side = len(MASCOT) * scale

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def mascot_ico(scale):
    """A one-image .ico holding the PNG, which every current browser reads."""
    png, side = mascot_png(scale), len(MASCOT) * scale
    return (struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", side % 256, side % 256, 0, 0, 1, 32, len(png), 22) + png)


ICONS = {
    "/favicon.ico": lambda: (mascot_ico(4), "image/x-icon"),                                  # 48px
    "/favicon.png": lambda: (mascot_png(8), "image/png"),                                     # 96px
    "/apple-touch-icon.png": lambda: (mascot_png(15, (0xf5, 0xf3, 0xef)), "image/png"),       # 180px, opaque
}


class Handler(BaseHTTPRequestHandler):
    server_version = f"cc-profiles/{__version__}"

    def end_headers(self):
        # which process answers: `cc-profiles stop` and `restart` stop exactly this one
        self.send_header("X-CC-Profiles-Pid", str(os.getpid()))
        super().end_headers()

    def log_message(self, fmt, *args):
        if os.environ.get("CC_PROFILES_QUIET"):
            return
        sys.stderr.write("  " + (fmt % args) + "\n")

    # The page may run only its own inline code and talk only to this server: an escaping
    # mistake cannot load code from elsewhere or send data out. Inline <script>/<style>
    # are allowed because the whole UI is one file.
    CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; "
           "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", self.CSP)
            self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, ensure_ascii=False))

    def _send_file(self, path, name, ctype):
        """Stream a file as a download, then delete it (a temporary export)."""
        try:
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(os.path.getsize(path)))
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            with open(path, "rb") as f:
                shutil.copyfileobj(f, self.wfile, 1024 * 1024)
        finally:
            os.unlink(path)

    def _import(self, q):
        """POST /api/profiles/import: the request body is the zip itself, not JSON."""
        n = int(self.headers.get("Content-Length") or 0)
        if n <= 0:
            raise ApiError("Pick the .zip of an exported profile")
        if n > IMPORT_MAX:
            raise ApiError("The file is too big (over 500 MB)")
        fd, tmp = tempfile.mkstemp(prefix="cc-profiles-import-", suffix=".zip")
        try:
            with os.fdopen(fd, "wb") as f:
                left = n
                while left:
                    chunk = self.rfile.read(min(left, 1024 * 1024))
                    if not chunk:
                        raise ApiError("The upload was interrupted")
                    f.write(chunk)
                    left -= len(chunk)
            with _lock:
                return op_import_profile(tmp, q.get("label", ""), q.get("id", ""))
        finally:
            os.unlink(tmp)

    def _guard(self):
        # A fixed Host blocks DNS rebinding; the token blocks requests from other sites.
        if self.headers.get("Host") not in core.ALLOWED_HOSTS:
            self._json(403, {"error": "Host not allowed"})
            return False
        if self.path.startswith("/api/") and self.headers.get("X-Token") != TOKEN:
            self._json(403, {"error": "Missing or wrong token"})
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html"):
                html = open(os.path.join(STATIC_DIR, "index.html")).read().replace("__TOKEN__", TOKEN)
                return self._send(200, html, "text/html; charset=utf-8")
            if u.path in ICONS:
                return self._send(200, *ICONS[u.path]())
            if u.path == "/api/profiles/export":
                path, name = export_profile(q["id"], q.get("projects") == "1")
                return self._send_file(path, name, "application/zip")
            routes = {
                "/api/profiles": lambda: list_profiles(),
                "/api/projects": lambda: list_projects(),
                "/api/health": lambda: health(),
                "/api/candidates": lambda: candidates(q.get("name", "")),
                "/api/memory/projects": lambda: memory_projects(q["profile"]),
                "/api/memory/list": lambda: memory_list(q["profile"], q["project"]),
                "/api/memory/file": lambda: memory_read(q["profile"], q["project"], q["file"]),
                "/api/conversations/projects": lambda: conversation_projects(q["profile"]),
                "/api/conversations": lambda: list_conversations(q["profile"], q["project"]),
                "/api/conversations/view": lambda: conversation_view(q["profile"], q["project"], q["session"]),
                "/api/backups": lambda: list_backups(),
                "/api/search": lambda: search(q.get("q", "")),
                "/api/compare": lambda: compare(q["a"], q["b"]),
                "/api/projects/move/preview": lambda: move_plan(q["project"], q["from"], q["to"]),
                "/api/sharing": lambda: list_sharing(),
                "/api/sharing/preview": lambda: share_plan(q["profile"], q["item"], q["shared"] == "1"),
                "/api/profiles/delete/preview": lambda: delete_plan(q["id"], q.get("merge_into") or None),
                "/api/settings/field/all/preview": lambda: setting_all_plan(q["profile"], q["key"]),
                "/api/statusline": lambda: get_statusline(q["profile"]),
                "/api/statusline/preview": lambda: statusline_preview(q["profile"], q.get("parts", ""), q.get("separator", "space"),
                                                                     q.get("colors", "1")),
                "/api/statusline/all/preview": lambda: statusline_all_plan(q["profile"]),
                "/api/settings/permissions/all/preview": lambda: permission_all_plan(q["list"], q["rule"]),
                "/api/skills/copy-all/preview": lambda: skill_all_plan(q["profile"], q["name"]),
                "/api/mcp/copy-all/preview": lambda: mcp_all_plan(q["profile"], q["scope"], q["name"]),
                "/api/backups/auto": lambda: backup_auto(),
                "/api/templates": lambda: list_templates(),
                "/api/plugins": lambda: list_plugins(q["profile"]),
                "/api/settings": lambda: get_settings(q["profile"]),
                "/api/about": lambda: about(),
                "/api/claude/status": lambda: claude_status(),
                "/api/update": lambda: check_update(),
                "/api/skills": lambda: list_skills(q["profile"]),
                "/api/skills/file": lambda: skill_read(q["profile"], q["name"]),
                "/api/mcp": lambda: list_mcp(q["profile"]),
                "/api/mcp/server": lambda: mcp_server(q["profile"], q["scope"], q["name"]),
            }
            if u.path not in routes:
                return self._json(404, {"error": "Not found"})
            self._json(200, routes[u.path]())
        except ApiError as e:
            self._json(e.status, {"error": str(e)})
        except KeyError as e:
            self._json(400, {"error": f"Missing parameter: {e}"})
        except Exception as e:  # noqa: BLE001 - the error is shown in the UI
            self._json(500, {"error": f"{type(e).__name__}: {e}"})

    def do_POST(self):
        if not self._guard():
            return
        try:
            u = urlparse(self.path)
            if u.path == "/api/profiles/import":
                return self._json(200, self._import({k: v[0] for k, v in parse_qs(u.query).items()}))
            n = int(self.headers.get("Content-Length") or 0)
            b = json.loads(self.rfile.read(n) or b"{}")
            routes = {
                "/api/projects/move": lambda: op_move(b["project"], b["from"], b["to"]),
                "/api/projects/delete": lambda: op_delete(b["project"], b["profile"]),
                "/api/projects/relink": lambda: op_relink(b["project"], b["profile"], b["path"]),
                "/api/rules": lambda: op_rule(b["match"], b["profile"]),
                "/api/memory/save": lambda: op_memory_save(b["profile"], b["project"], b["file"], b["content"]),
                "/api/memory/move": lambda: op_memory_move(b["profile"], b["project"], b["file"],
                                                           b["to_profile"], b["to_project"]),
                "/api/memory/delete": lambda: op_memory_delete(b["profile"], b["project"], b["file"]),
                "/api/conversations/move": lambda: op_conversation_move(b["profile"], b["project"], b["session"], b["to"]),
                "/api/conversations/delete": lambda: op_conversation_delete(b["profile"], b["project"], b["session"]),
                "/api/backups/restore": lambda: op_restore(b["name"]),
                "/api/backups/delete": lambda: op_backup_delete(b["name"]),
                "/api/backups/prune": lambda: op_backup_prune(b.get("days")),
                "/api/backups/auto": lambda: op_backup_auto(b.get("days")),
                "/api/templates/save": lambda: op_template_save(b["profile"], b["name"]),
                "/api/templates/delete": lambda: op_template_delete(b["name"]),
                "/api/templates/create": lambda: op_create_from_template(b["name"], b["label"], b["id"]),
                "/api/sharing": lambda: op_share(b["profile"], b["item"], bool(b["shared"])),
                "/api/plugins/enable": lambda: op_plugin_enable(b["profile"], b["plugin"], b.get("enabled")),
                "/api/settings/field": lambda: op_setting(b["profile"], b["key"], b.get("value")),
                "/api/settings/permissions": lambda: op_permissions(b["profile"], b.get("rules") or {}),
                "/api/settings/field/all": lambda: op_setting_all(b["profile"], b["key"]),
                "/api/statusline": lambda: op_statusline(b["profile"], b),
                "/api/statusline/all": lambda: op_statusline_all(b["profile"]),
                "/api/settings/permissions/all": lambda: op_permission_all(b["list"], b["rule"]),
                "/api/settings/raw": lambda: op_settings_raw(b["profile"], b["file"], b["content"]),
                "/api/settings/claude-md": lambda: op_claude_md(b["profile"], b.get("content", "")),
                "/api/settings/global": lambda: op_global(b["profile"], b["key"], b.get("value")),
                "/api/claude/install": lambda: op_install(b.get("method", "")),
                "/api/update": lambda: op_update(),
                "/api/skills/save": lambda: op_skill_save(b["profile"], b["name"], b["content"]),
                "/api/skills/create": lambda: op_skill_create(b["profile"], b["name"], b.get("description", "")),
                "/api/skills/delete": lambda: op_skill_delete(b["profile"], b["name"]),
                "/api/skills/copy": lambda: op_skill_copy(b["profile"], b["name"], b["to"]),
                "/api/skills/copy-all": lambda: op_skill_copy_all(b["profile"], b["name"]),
                "/api/mcp/save": lambda: op_mcp_save(b["profile"], b["scope"], b["name"], b["config"],
                                                     b.get("old_name") or None),
                "/api/mcp/delete": lambda: op_mcp_delete(b["profile"], b["scope"], b["name"]),
                "/api/mcp/copy": lambda: op_mcp_copy(b["profile"], b["scope"], b["name"], b["to"]),
                "/api/mcp/copy-all": lambda: op_mcp_copy_all(b["profile"], b["scope"], b["name"]),
                "/api/profiles/update": lambda: op_update_profile(b["id"], b.get("label"), b.get("command")),
                "/api/profiles/delete": lambda: op_delete_profile(b["id"], b.get("merge_into") or None,
                                                                  bool(b.get("force"))),
                "/api/profiles/create": lambda: op_create_profile(
                    b["label"], b["id"], b.get("base") or None,
                    bool(b.get("include_projects")), b.get("share") or []),
            }
            if self.path not in routes:
                return self._json(404, {"error": "Not found"})
            with _lock:
                self._json(200, routes[self.path]())
        except ApiError as e:
            self._json(e.status, {"error": self._failed(str(e))})
        except KeyError as e:
            self._json(400, {"error": self._failed(f"Missing parameter: {e}")})
        except Exception as e:  # noqa: BLE001
            self._json(500, {"error": self._failed(f"{type(e).__name__}: {e}")})

    def _failed(self, error):
        if abort_open_backups(error):
            error += " Some changes were made before the error: restore the incomplete backup to undo them."
        return error
