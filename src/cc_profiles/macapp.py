# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Andrea Iannarone
"""cc-profiles: the Mac app (cc-profiles install-app)."""

import json
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib

from . import __version__, core
from .core import HOME, ApiError, Backup, find_tool, pretty, write_json

# ---------------------------------------------------------------------------
# The Mac app
# ---------------------------------------------------------------------------
# ~/Applications/cc-profiles.app is a window around the web UI: app/main.swift, compiled for
# Intel and Apple Silicon when the package is built (scripts/build_app.py) and shipped inside
# it. The app is put together on this Mac, so macOS does not hold it in quarantine and opens it
# without asking, though it carries no Apple signature: only an ad hoc one. Its Info.plist
# has APP_MARK: only an app with it is rewritten or removed. Resources/launch.json names the
# cc-profiles command the app runs, which is why the server rewrites the app at start when
# that command or the version changes (ensure_app).
APP_PATH = os.path.join(HOME, "Applications", "cc-profiles.app")
APP_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app")
APP_BINARY = os.path.join(APP_SOURCE, "cc-profiles-app")
APP_MARK = "CCProfilesManaged"
BUNDLE_ID = "com.andreaiannarone.cc-profiles"
MIN_MACOS = "12.0"


def supported():
    """macOS only; tests elsewhere pass a fake program in CC_PROFILES_APP_BINARY."""
    return sys.platform == "darwin" or bool(os.environ.get("CC_PROFILES_APP_BINARY"))


def launch_command():
    """How the app starts cc-profiles: the launcher on PATH or in the usual folders, which
    stays put across updates, else this Python with -m (pip --user, a checkout)."""
    exe = find_tool("cc-profiles")
    return [exe] if exe else [sys.executable, "-m", "cc_profiles"]


def build_binary(out, archs=None):
    """Compile app/main.swift into out with swiftc (Xcode or its command line tools): both
    architectures for a release, only this Mac's for a checkout. Returns out."""
    swiftc = find_tool("swiftc")
    if not swiftc:
        raise ApiError("This copy of cc-profiles has no Mac app (a source checkout) and swiftc is missing: "
                       "install the command line tools with xcode-select --install, or install cc-profiles with pipx")
    archs = archs or [os.uname().machine]
    with tempfile.TemporaryDirectory() as tmp:
        parts = []
        for arch in archs:
            part = os.path.join(tmp, arch)
            r = subprocess.run([swiftc, "-O", "-swift-version", "5", "-target", f"{arch}-apple-macos{MIN_MACOS}",
                                "-o", part, os.path.join(APP_SOURCE, "main.swift")], capture_output=True, text=True)
            if r.returncode:
                raise ApiError(f"swiftc could not build the Mac app: {(r.stderr or r.stdout).strip()[-2000:]}")
            parts.append(part)
        if len(parts) == 1:
            shutil.copy2(parts[0], out)
        else:
            subprocess.run([find_tool("lipo") or "lipo", "-create", "-output", out] + parts, check=True)
    return out


def app_binary(tmp):
    """The compiled app: CC_PROFILES_APP_BINARY (tests), the one shipped in the package,
    or one compiled now into tmp."""
    for path in (os.environ.get("CC_PROFILES_APP_BINARY"), APP_BINARY):
        if path and os.path.isfile(path):
            return path
    return build_binary(os.path.join(tmp, "cc-profiles-app"))


def app_info(path=APP_PATH):
    """The app's Info.plist, or None when there is no readable one."""
    try:
        with open(os.path.join(path, "Contents", "Info.plist"), "rb") as f:
            info = plistlib.load(f)
        return info if isinstance(info, dict) else None
    except (OSError, plistlib.InvalidFileException, ValueError):
        return None


def app_launch(path=APP_PATH):
    try:
        with open(os.path.join(path, "Contents", "Resources", "launch.json")) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def is_our_app(path=APP_PATH):
    return (app_info(path) or {}).get(APP_MARK) is True


def app_state():
    """"missing", "foreign" (an app cc-profiles did not make), "outdated" or "current"."""
    if not os.path.lexists(APP_PATH):
        return "missing"
    if not is_our_app():
        return "foreign"
    launch = app_launch() or {}
    current = app_info().get("CFBundleShortVersionString") == __version__ and launch.get("command") == launch_command()
    return "current" if current else "outdated"


def info_plist():
    return {
        "CFBundleName": "cc-profiles",
        "CFBundleDisplayName": "cc-profiles",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleExecutable": "cc-profiles",
        "CFBundleIconFile": "AppIcon",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": __version__,
        "CFBundleVersion": __version__,
        "CFBundleInfoDictionaryVersion": "6.0",
        "LSMinimumSystemVersion": MIN_MACOS,
        "LSApplicationCategoryType": "public.app-category.developer-tools",
        "NSHighResolutionCapable": True,
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},  # http://127.0.0.1
        "NSHumanReadableCopyright": "© 2026 Andrea Iannarone, GPL-3.0-or-later",
        APP_MARK: True,
    }


def assemble(dest, binary, port):
    """The .app folder at dest (which must not exist yet)."""
    contents = os.path.join(dest, "Contents")
    os.makedirs(os.path.join(contents, "MacOS"))
    os.makedirs(os.path.join(contents, "Resources"))
    exe = os.path.join(contents, "MacOS", "cc-profiles")
    shutil.copyfile(binary, exe)
    os.chmod(exe, 0o755)
    with open(os.path.join(contents, "Info.plist"), "wb") as f:
        plistlib.dump(info_plist(), f)
    with open(os.path.join(contents, "PkgInfo"), "w") as f:
        f.write("APPL????")
    with open(os.path.join(contents, "Resources", "AppIcon.icns"), "wb") as f:
        f.write(app_icns())
    write_json(os.path.join(contents, "Resources", "launch.json"), {"command": launch_command(), "port": port})
    codesign = find_tool("codesign") if sys.platform == "darwin" else None
    if codesign:  # ad hoc: no identity, but a sealed bundle that Apple Silicon is happy to run
        subprocess.run([codesign, "--force", "--sign", "-", dest], capture_output=True)


def write_app(port, bk):
    """Put the app in ~/Applications, replacing an older one cc-profiles made (kept in the backup)."""
    folder = os.path.dirname(APP_PATH)
    bk.mkdir(folder)
    tmp = tempfile.mkdtemp(prefix=".cc-profiles-app-", dir=folder)
    try:
        staged = os.path.join(tmp, "cc-profiles.app")
        assemble(staged, app_binary(tmp), port)
        bk.stash(APP_PATH, "cc-profiles.app")
        os.rename(staged, APP_PATH)
        bk.created(APP_PATH)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def install_app(port):
    """cc-profiles install-app: create or update the app. Returns (lines to print, backup path)."""
    if not supported():
        raise ApiError(f"The app is for macOS only: on Linux, open http://127.0.0.1:{port} in your browser")
    state = app_state()
    if state == "foreign":
        raise ApiError(f"{pretty(APP_PATH)} exists and was not created by cc-profiles: move it away first")
    if state == "current" and (app_launch() or {}).get("port") == port:
        return [f"{pretty(APP_PATH)} is already up to date."], None
    bk = Backup("mac-app", "Update the Mac app" if state != "missing" else "Add the Mac app")
    write_app(port, bk)
    bk.note(f"Mac app: {pretty(APP_PATH)}, port {port}")
    verb = "Updated" if state != "missing" else "Created"
    return [f"{verb} {pretty(APP_PATH)}: open cc-profiles from Spotlight, Launchpad or Applications in Finder."], bk.close()


def app_status():
    """GET /api/macapp, for the About panel. "outdated" also when the app uses another port
    than this server: installing it again moves it to this one."""
    if not supported():
        return {"supported": False}
    state = app_state()
    port = (app_launch() or {}).get("port")
    if state == "current" and port != core.PORT:
        state = "outdated"
    return {"supported": True, "state": state, "path": pretty(APP_PATH), "port": port}


def op_install_app():
    """POST /api/macapp: what install-app does, on this server's port."""
    lines, backup = install_app(core.PORT)
    return dict(app_status(), message=lines[0], backup=backup)


def ensure_app():
    """At every start of the server: an app cc-profiles made, from an older version or with a
    command that moved (installed another way), is rewritten, keeping its port. An app that is
    not there is not added. Returns (lines to print, backup path or None)."""
    if not supported() or app_state() != "outdated":
        return [], None
    port = (app_launch() or {}).get("port")
    port = port if isinstance(port, int) else core.PORT
    bk = Backup("mac-app", "Update the Mac app")
    write_app(port, bk)
    return [f"updated {pretty(APP_PATH)}"], bk.close()


# ---------------------------------------------------------------------------
# The icon: the two mascots of docs/assets/logo-mark.svg on a rounded square, drawn here
# like the favicons in web.py, so the repo holds no binary copy that could drift.
# ---------------------------------------------------------------------------
LOGO = ("............b.....",
        "...........b......",
        "......#.bbbbbbbb..",
        ".....#.....bbbbbb.",
        "..########..bbobb.",
        ".##########.bbobb.",
        ".##o####o##.bbbbb.",
        ".##o####o##.bbbbb.",
        ".##########.bbbbb.",
        ".##########...bb..",
        ".##########.......",
        "..##....##........")
LOGO_COLORS = {"#": (0xd9, 0x77, 0x57), "b": (0xe9, 0xa9, 0x8c), "o": (0x1d, 0x1c, 0x1a)}
TILE_TOP, TILE_BOTTOM, TILE_EDGE = (0xfb, 0xfa, 0xf8), (0xee, 0xeb, 0xe5), (0xd8, 0xd4, 0xcc)


def icon_png(side):
    """A macOS icon side×side: a rounded square on Apple's grid (824 of 1024, radius 185)
    with a soft edge, and the mascots drawn as crisp squares in the middle."""
    k = side / 1024
    x0, size, radius = 100 * k, 824 * k, 185 * k
    cell = max(1, round(36 * k))
    lx = (side - cell * len(LOGO[0])) // 2
    ly = (side - cell * len(LOGO)) // 2 + cell // 2

    def coverage(x, y):
        """How much of pixel (x, y) the rounded square covers, 0..1 (one sample, smoothed)."""
        cx = min(max(x + 0.5, x0 + radius), x0 + size - radius)
        cy = min(max(y + 0.5, x0 + radius), x0 + size - radius)
        d = ((x + 0.5 - cx) ** 2 + (y + 0.5 - cy) ** 2) ** 0.5
        return min(1.0, max(0.0, radius - d + 0.5))

    def edge_pixel(x, y, tile):
        a = coverage(x, y)
        if a <= 0:
            return b"\0\0\0\0"
        inner = coverage(x - 2 * k, y - 2 * k) * coverage(x + 2 * k, y + 2 * k)  # a thin darker rim
        return bytes(round(e + (c - e) * inner) for c, e in zip(tile, TILE_EDGE)) + bytes([round(255 * a)])

    # Pixel by pixel only near the edge: the rows' middle is the tile's color, the mascots go on top
    rows = []
    for y in range(side):
        t = min(1.0, max(0.0, (y - x0) / size))
        tile = tuple(round(a + (b - a) * t) for a, b in zip(TILE_TOP, TILE_BOTTOM))
        row = bytearray((bytes(tile) + b"\xff") * side)
        if not x0 + 3 <= y <= x0 + size - 4:
            edges = range(side)  # top and bottom edge: every pixel
        else:  # elsewhere only the pixels near the curve: transparent before them, the tile after
            dy = max(0.0, abs(y + 0.5 - min(max(y + 0.5, x0 + radius), x0 + size - radius)))
            arc = lambda r: x0 + radius - max(0.0, r * r - dy * dy) ** 0.5  # where a circle of radius r crosses
            left = max(int(arc(radius + 1)) - 1, 0)
            right = int(arc(radius - 3 * k - 2)) + 2  # past it, the rim is behind too
            row[:4 * left] = bytes(4 * left)
            row[4 * (side - left):] = bytes(4 * left)
            edges = list(range(left, right)) + list(range(side - right, side - left))
        for x in edges:
            row[4 * x:4 * x + 4] = edge_pixel(x, y, tile)
        gy = (y - ly) // cell
        if y >= ly and gy < len(LOGO):
            for gx, c in enumerate(LOGO[gy]):
                if c in LOGO_COLORS:
                    row[4 * (lx + gx * cell):4 * (lx + (gx + 1) * cell)] = (bytes(LOGO_COLORS[c]) + b"\xff") * cell
        rows.append(b"\0" + bytes(row))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", side, side, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"".join(rows), 9)) + chunk(b"IEND", b""))


def app_icns():
    """An .icns of PNGs: 128, 256, 512 and 1024 pixels (macOS scales them for the small sizes)."""
    pngs = {s: icon_png(s) for s in (128, 256, 512, 1024)}
    entries = [(b"ic07", pngs[128]), (b"ic08", pngs[256]), (b"ic09", pngs[512]), (b"ic10", pngs[1024]),
               (b"ic13", pngs[256]), (b"ic14", pngs[512])]  # 128@2x and 256@2x
    body = b"".join(kind + struct.pack(">I", len(data) + 8) + data for kind, data in entries)
    return b"icns" + struct.pack(">I", len(body) + 8) + body
