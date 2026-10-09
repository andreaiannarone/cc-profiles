"""Regenerate every image of the README from the real app, so they never fall behind the UI.

    .venv/bin/pip install -e ".[ui]" && .venv/bin/python -m playwright install chromium
    .venv/bin/python scripts/make_screenshots.py            # screenshots, the demo GIF, the social preview
    .venv/bin/python scripts/make_screenshots.py --no-gif   # skip the GIF (it needs ffmpeg)

It builds the /sandbox fake home, starts the app on it and drives it with Playwright:
- docs/assets/screenshots/<tab>-<theme>.jpg for the README gallery and the docs guides, in light and dark;
- docs/assets/demo-<theme>.gif, the animated preview under the logo (one frame per step);
- docs/assets/social-preview.png, rendered from social-preview.html (uses skills-dark.jpg).
Nothing outside the sandbox and docs/assets is touched.
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from conftest import App, FakeHome  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

ASSETS = ROOT / "docs" / "assets"
SHOTS = ASSETS / "screenshots"
VIEW = {"width": 1440, "height": 900}
THEMES = ("dark", "light")

# Hide what should not end up in a picture: scrollbars that shift the layout between frames,
# toasts left over from the previous step, the red counters of tabs.
CLEAN_CSS = """html, .modal-bg { scrollbar-width: none; }
html::-webkit-scrollbar, .modal-bg::-webkit-scrollbar { display: none; }
*, *::before, *::after { cursor: none !important; transition: none !important; animation: none !important; }"""


def sandbox():
    root = Path(tempfile.mkdtemp(prefix="cc-profiles-shots-"))
    subprocess.run([sys.executable, str(ROOT / ".claude" / "skills" / "sandbox" / "make_home.py"), str(root)],
                   check=True, capture_output=True)
    # a stand-in claude in the fake ~/.local/bin, also on PATH: no notice about installing Claude Code,
    # and `claude mcp list` answers with the sandbox's claude.ai connectors
    claude = root / ".local" / "bin" / "claude"
    claude.parent.mkdir(parents=True, exist_ok=True)
    claude.write_text("#!/bin/sh\n"
                      "if [ \"$1\" = mcp ]; then\n"
                      "  echo 'claude.ai Gmail: https://gmailmcp.googleapis.com/mcp/v1 - ✔ Connected'\n"
                      "  echo 'claude.ai Google Drive: https://drivemcp.googleapis.com/mcp/v1 - ✔ Connected'\n"
                      "  echo 'claude.ai Linear: https://mcp.linear.app/mcp - ✔ Connected'\n"
                      "  exit 0\n"
                      "fi\n"
                      "echo '2.1.0 (Claude Code)'\n")
    claude.chmod(0o755)
    return root


class Shooter:
    def __init__(self, page, app):
        self.page, self.app = page, app

    def go(self, theme):
        self.page.add_init_script(f"localStorage.setItem('cc-profiles.theme', '{theme}')")
        self.page.goto(self.app.base + "/")
        self.page.wait_for_selector(".pcard")
        self.page.add_style_tag(content=CLEAN_CSS)

    def js(self, code):
        return self.page.evaluate(f"async () => {{ {code} }}")

    def tab(self, name):
        self.page.click(f'#tabs button[data-tab="{name}"]')
        self.page.wait_for_function("() => { const m = document.querySelector('#main');"
                                    " return m.children.length && !m.querySelector('.spinner'); }", timeout=15000)

    def settle(self):
        self.page.wait_for_timeout(350)
        self.js("document.querySelectorAll('.toast').forEach(t => t.remove());")

    def shot(self, path, keep_toasts=False, crop=False):
        """The window; with crop, only down to the end of the tab's content (no empty band below)."""
        self.page.mouse.move(VIEW["width"] - 1, VIEW["height"] - 1)  # no hover left on what was clicked
        if not keep_toasts:
            self.settle()
        else:
            self.page.wait_for_timeout(350)
        clip = None
        if crop:
            bottom = self.js("return Math.ceil(document.querySelector('#main').getBoundingClientRect().bottom);")
            clip = {"x": 0, "y": 0, "width": VIEW["width"], "height": max(480, min(VIEW["height"], bottom + 28))}
        self.page.screenshot(path=str(path), type="jpeg", quality=82, clip=clip) if str(path).endswith(".jpg") \
            else self.page.screenshot(path=str(path), clip=clip)

    def dialog(self, path):
        """Only the open dialog, then close it."""
        self.settle()
        self.page.locator(".modal").screenshot(path=str(path), type="jpeg", quality=88)
        self.page.keyboard.press("Escape")
        self.page.wait_for_selector(".modal", state="detached")


def open_conversation(s, profile):
    """Conversations tab: the work/api project of `profile`, with its latest conversation open."""
    s.js(f"S.conv.profile = '{profile}'; await loadConvProjects(); renderConversations();"
         " await openConvProject(S.conv.projects.find(p => p.pretty.endsWith('work/api')).name);"
         " await openConversation(S.conv.list.conversations[0].session);")


def gallery(s, theme):
    """The README gallery and the guides of the docs site: one screenshot per tab."""
    s.go(theme)
    s.tab("projects")
    s.page.click('[data-filter="all"]')
    s.shot(crop=True, path=SHOTS / f"projects-{theme}.jpg")
    # the dialogs the How-to guides show: a move with its file list, a relink, a new profile
    s.page.click('button[data-act="fixmove"]')
    s.page.wait_for_selector(".modal")
    s.page.click(".modal details summary")
    s.dialog(SHOTS / f"move-{theme}.jpg")
    s.page.click('button[data-act="relink"]')
    s.page.wait_for_selector(".modal input.text")
    s.page.fill(".modal input.text", "~/code/new-name")
    s.dialog(SHOTS / f"relink-{theme}.jpg")
    s.tab("profiles")
    s.shot(crop=True, path=SHOTS / f"profiles-{theme}.jpg")
    s.page.click("[data-newprofile] >> nth=0")
    s.page.wait_for_selector(".modal")
    s.page.fill(".modal input >> nth=0", "Work 2")
    s.dialog(SHOTS / f"newprofile-{theme}.jpg")
    s.tab("backups")
    s.shot(crop=True, path=SHOTS / f"backups-{theme}.jpg")
    s.tab("health")
    s.shot(crop=True, path=SHOTS / f"health-{theme}.jpg")
    s.tab("memories")
    s.js("S.mem.profile = 'default'; await loadMemProjects();"
         " await openMemProject(S.mem.projects.find(p => p.pretty.endsWith('work/api')).name);"
         " await openMemFile('deploy.md');")
    s.shot(crop=True, path=SHOTS / f"memories-{theme}.jpg")
    s.tab("conversations")
    open_conversation(s, "default")
    s.shot(crop=True, path=SHOTS / f"conversations-{theme}.jpg")
    s.tab("skills")
    s.js("await loadExt('default'); await openSkill('release-notes');")
    s.shot(crop=True, path=SHOTS / f"skills-{theme}.jpg")
    s.page.click("#skall")
    s.page.wait_for_selector(".modal")
    s.page.wait_for_timeout(300)  # the preview of who gets it
    s.dialog(SHOTS / f"copyall-{theme}.jpg")
    s.tab("agents")
    s.js("await loadExt('default'); await openAgent('code-reviewer');")
    s.shot(crop=True, path=SHOTS / f"agents-{theme}.jpg")
    s.tab("mcp")
    s.js("await loadExt('default');")
    s.shot(crop=True, path=SHOTS / f"mcp-{theme}.jpg")
    s.tab("compare")
    s.shot(crop=True, path=SHOTS / f"compare-{theme}.jpg")
    s.tab("settings")
    s.js("await loadSettings('default');")
    s.shot(crop=True, path=SHOTS / f"settings-{theme}.jpg")
    s.tab("usage")
    s.shot(crop=True, path=SHOTS / f"usage-{theme}.jpg")
    # the status line editor: made by cc-profiles, a few pieces with their brackets
    s.tab("settings")
    s.js("await loadSettings('default'); S.set.slDraft.mode = 'builtin';"
         " S.set.slDraft.parts = ['path', 'branch', 'profile', 'model', 'context', 'limit', 'week'];"
         " S.set.slDraft.order = [...S.set.slDraft.parts, ...S.set.slDraft.order.filter(i => !S.set.slDraft.parts.includes(i))];"
         " S.set.slDraft.colors = true; renderStatusLine();"
         " await new Promise(r => setTimeout(r, 900));"
         " document.querySelector('#sl-sec').scrollIntoView({block: 'start'}); window.scrollBy(0, -16);")
    s.shot(crop=True, path=SHOTS / f"statusline-{theme}.jpg")


def demo_frames(s, theme, out):
    """The story of the demo GIF: (frame, seconds on screen)."""
    s.go(theme)
    frames = []

    def frame(seconds, keep_toasts=False):
        path = out / f"{len(frames):02d}.png"
        s.shot(path, keep_toasts)
        frames.append((path, seconds))

    s.tab("projects")
    s.page.click('[data-filter="all"]')
    frame(2.4)
    s.page.click('button[data-act="fixmove"]')
    s.page.wait_for_selector(".modal")
    frame(2.2)
    s.page.click('.modal [data-i="0"]')
    s.page.wait_for_selector(".toast")
    frame(2.6, keep_toasts=True)
    s.tab("memories")
    s.js("S.mem.profile = 'work'; await loadMemProjects();"
         " await openMemProject(S.mem.projects.find(p => p.pretty.endsWith('work/api')).name);"
         " await openMemFile('deploy.md');")
    frame(2.4)
    s.tab("conversations")
    open_conversation(s, "work")
    frame(2.4)
    s.tab("skills")
    s.js("await loadExt('default'); await openSkill('release-notes');")
    frame(2.2)
    s.tab("mcp")
    s.js("await loadExt('default');")
    s.page.click('[data-mcpedit="1"]')
    s.page.wait_for_selector(".modal")
    frame(2.4)
    s.page.click(".modal [data-close]")
    s.tab("compare")
    frame(2.4)
    s.tab("backups")
    frame(2.6)
    return frames


def make_gif(frames, target, fps=5, width=1200):
    """One still per step, repeated for its duration, then a palette-optimized GIF."""
    with tempfile.TemporaryDirectory() as tmp:
        n = 0
        for path, seconds in frames:
            for _ in range(round(seconds * fps)):
                n += 1
                shutil.copy(path, Path(tmp) / f"{n:04d}.png")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", f"{tmp}/%04d.png",
                        "-vf", f"scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=128:stats_mode=full[p];"
                               "[b][p]paletteuse=dither=none", "-loop", "0", str(target)], check=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--no-gif", action="store_true", help="skip the demo GIF (it needs ffmpeg)")
    args = ap.parse_args()
    if not args.no_gif and not shutil.which("ffmpeg"):
        sys.exit("ffmpeg is needed for the demo GIF: install it, or pass --no-gif")
    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in THEMES:
            for step in (gallery, ) + (() if args.no_gif else ("gif",)):
                root = sandbox()  # a fresh home for every run: the demo moves a project
                app = App(FakeHome(root), {"PATH": f"{root}/.local/bin:/usr/bin:/bin"})
                try:
                    app.post("/api/rules", {"match": "code/personal", "profile": "default"})
                    app.post("/api/rules", {"match": "code/work", "profile": "work"})
                    app.post("/api/rules", {"match": "code/client", "profile": "client"})
                    page = browser.new_page(viewport=VIEW, device_scale_factor=1)
                    s = Shooter(page, app)
                    if step == "gif":
                        with tempfile.TemporaryDirectory() as tmp:
                            make_gif(demo_frames(s, theme, Path(tmp)), ASSETS / f"demo-{theme}.gif")
                        print(f"demo-{theme}.gif")
                    else:
                        step(s, theme)
                        print(f"gallery {theme}")
                    page.close()
                finally:
                    app.stop()
                    shutil.rmtree(root, ignore_errors=True)
        page = browser.new_page(viewport={"width": 1280, "height": 640})
        page.goto((ASSETS / "social-preview.html").as_uri())
        page.wait_for_timeout(300)
        page.screenshot(path=str(ASSETS / "social-preview.png"))
        print("social-preview.png")
        browser.close()


if __name__ == "__main__":
    main()
