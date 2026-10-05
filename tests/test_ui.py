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


def cancel(page):
    page.click(".modal [data-close]")
    page.wait_for_selector(".modal", state="detached")


def test_previews_and_apply_to_all_confirmations_render(page_on_sandbox):
    page, errors = page_on_sandbox
    open_tab(page, "profiles")
    page.click('[data-pdel="work"]')
    page.click('.modal input[name="pd"][value="default"]')
    page.wait_for_selector("#pd-plan details")
    assert "Moves to Default" in page.inner_text("#pd-plan")
    cancel(page)
    page.click('label.switch:has([data-share="agents"][data-prof="work"])')
    page.wait_for_selector(".modal details")
    cancel(page)
    page.click("#ptemplates")
    page.wait_for_selector("#tp-name")
    cancel(page)
    page.click("[data-newprofile]")
    page.wait_for_selector("#np-label")
    cancel(page)

    open_tab(page, "settings")
    page.click("[data-sall]")
    page.wait_for_selector(".modal ul.plan")
    cancel(page)
    open_tab(page, "backups")
    assert page.query_selector("#bk-auto") is not None
    assert errors == []
