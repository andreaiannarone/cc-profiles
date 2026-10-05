"""Browser smoke test: open every tab of the real page in Chromium and fail on JavaScript
errors, Content-Security-Policy violations or a tab stuck loading.

Needs the ui extra and a browser: pip install -e ".[ui]" && python -m playwright install chromium.
Skipped when Playwright is not installed, so the main suite keeps running without it."""
import subprocess
import sys

import pytest

from conftest import App, FakeHome, ROOT

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture
def page_on_sandbox(tmp_path):
    root = tmp_path / "sandbox"
    subprocess.run([sys.executable, str(ROOT / ".claude" / "skills" / "sandbox" / "make_home.py"), str(root)],
                   check=True, capture_output=True)
    app = App(FakeHome(root))
    errors = []
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as e:  # noqa: BLE001 - no browser downloaded
            app.stop()
            pytest.skip(f"Chromium is not installed for Playwright: {e}")
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("pageerror", lambda e: errors.append(f"page error: {e}"))
        page.on("console", lambda m: m.type == "error" and errors.append(f"console: {m.text}"))
        page.goto(app.base + "/")
        page.wait_for_selector(".pcard")
        try:
            yield page, errors
        finally:
            browser.close()
            app.stop()


def test_every_tab_renders_without_errors(page_on_sandbox):
    page, errors = page_on_sandbox
    tabs = page.eval_on_selector_all("#tabs button", "bs => bs.map(b => b.dataset.tab)")
    assert len(tabs) >= 8
    for tab in tabs:
        page.click(f'#tabs button[data-tab="{tab}"]')
        # a tab is done when it shows content and no spinner is left
        page.wait_for_function("() => { const m = document.querySelector('#main');"
                               " return m.children.length && !m.querySelector('.spinner'); }", timeout=10000)
        assert page.inner_text("#main").strip(), f"tab {tab} is empty"
    assert errors == []


def test_theme_and_about_panels_open(page_on_sandbox):
    page, errors = page_on_sandbox
    page.click("#theme-btn")
    page.click('.popover [data-theme-set="light"]')
    assert page.get_attribute("html", "data-theme") == "light"
    page.keyboard.press("Escape")
    assert page.query_selector(".popover") is None
    page.click("#about-btn")
    page.wait_for_selector("#upd-check", timeout=15000)
    assert "cc-profiles" in page.inner_text(".drawer")
    assert errors == []


def open_tab(page, tab):
    page.click(f'#tabs button[data-tab="{tab}"]')
    page.wait_for_function("() => { const m = document.querySelector('#main');"
                           " return m.children.length && !m.querySelector('.spinner'); }", timeout=10000)


def test_narrow_screens_show_one_group_at_a_time(page_on_sandbox):
    page, errors = page_on_sandbox
    page.set_viewport_size({"width": 375, "height": 800})
    assert page.is_visible("#ngroups")
    visible = page.eval_on_selector_all("#tabs button", "bs => bs.filter(b => b.offsetParent).map(b => b.dataset.tab)")
    assert visible == ["projects", "memories", "conversations"]
    page.click('#ngroups [data-group="system"]')
    page.wait_for_selector('#tabs button[data-tab="backups"].on')
    assert page.get_attribute('#ngroups [data-group="system"]', "aria-pressed") == "true"
    assert not page.is_visible('#tabs button[data-tab="projects"]')
    assert page.evaluate("document.documentElement.scrollWidth") <= 375  # nothing scrolls sideways
    page.set_viewport_size({"width": 1440, "height": 900})
    assert not page.is_visible("#ngroups") and page.is_visible('#tabs button[data-tab="projects"]')
    assert errors == []


def test_keyboard_shortcuts(page_on_sandbox):
    page, errors = page_on_sandbox
    page.keyboard.press("g")
    page.keyboard.press("h")
    page.wait_for_selector('#tabs button[data-tab="health"].on')
    page.keyboard.press("g")
    page.keyboard.press("x")
    page.wait_for_selector('#tabs button[data-tab="mcp"][aria-current="page"]')
    page.keyboard.press("?")
    page.wait_for_selector('.modal[aria-label="Keyboard shortcuts"]')
    page.keyboard.press("g")  # ignored while a dialog is open
    page.keyboard.press("p")
    assert page.get_attribute('#tabs button[data-tab="mcp"]', "class") == "on"
    page.keyboard.press("Escape")
    assert page.query_selector(".modal-bg") is None
    page.keyboard.press("/")
    assert page.evaluate("document.activeElement.id") == "gsearch"
    page.keyboard.type("gp")  # typing in a field is not a shortcut
    assert page.get_attribute('#tabs button[data-tab="mcp"]', "class") == "on"
    assert errors == []


def axe_violations(page):
    """Serious and critical axe-core violations on the page as it is now."""
    from axe_playwright_python.sync_playwright import Axe
    res = Axe().run(page, options={"resultTypes": ["violations"]}).response
    return [f"{v['id']} ({v['impact']}): {v['help']} at " + ", ".join(str(n["target"]) for n in v["nodes"][:4])
            for v in res["violations"] if v["impact"] in ("serious", "critical")]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_no_serious_accessibility_violations(page_on_sandbox, theme):
    pytest.importorskip("axe_playwright_python")
    page, errors = page_on_sandbox
    page.evaluate(f"setTheme('{theme}')")
    found = {}
    for tab in page.eval_on_selector_all("#tabs button", "bs => bs.map(b => b.dataset.tab)"):
        open_tab(page, tab)
        found[tab] = axe_violations(page)
    page.keyboard.press("?")
    page.wait_for_selector(".modal")
    found["shortcuts dialog"] = axe_violations(page)
    page.keyboard.press("Escape")
    page.click("#about-btn")
    page.wait_for_selector("#upd-check", timeout=15000)
    # the panel slides in fading from transparent: measure contrast once it has landed
    page.wait_for_function("() => document.querySelector('.drawer').getAnimations().every(a => a.playState === 'finished')")
    found["about panel"] = axe_violations(page)
    page.keyboard.press("Escape")
    page.set_viewport_size({"width": 375, "height": 800})
    open_tab(page, "health")
    found["phone width"] = axe_violations(page)
    found = {t: v for t, v in found.items() if v}
    assert found == {}, "\n".join(f"{t}: {x}" for t, vs in found.items() for x in vs)
    assert errors == []
