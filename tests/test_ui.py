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
    tabs = page.eval_on_selector_all("#tabs button[data-tab]", "bs => bs.map(b => b.dataset.tab)")
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
    link = page.locator('.drawer a[href="https://andreaiannarone.com"]')
    assert link.inner_text() == "Andrea Iannarone" and link.get_attribute("rel") == "noopener"
    assert link.get_attribute("target") == "_blank" and "© 2026" in page.inner_text(".drawer")
    assert errors == []


def test_new_profile_from_a_template_offers_sharing(page_on_sandbox):
    page, errors = page_on_sandbox
    page.evaluate('api("/api/templates/save", { profile: "default", name: "Base" })')
    page.click("[data-newprofile]")
    page.wait_for_selector("#np-label")
    shared = 'input[name="share"]'
    assert page.eval_on_selector_all(shared + ":checked", "cs => cs.map(c => c.value)") == ["skills", "plugins"]
    page.check('input[name="base"][value="template:Base"]')
    assert page.is_visible("#np-share") and page.is_visible("#np-tpl")
    assert page.eval_on_selector_all(shared + ":checked", "cs => cs.map(c => c.value)") == ["plugins"]
    assert "Plugins are never in a template" in page.inner_text("#np-tpl")
    page.check(shared + '[value="skills"]')
    assert "skills: shared with Default, the template's" in page.inner_text("#np-tpl")
    assert "skills are not copied" in page.inner_text("#np-tpl")
    page.check('input[name="base"][value=""]')
    assert page.is_hidden("#np-tpl") and page.is_checked(shared + '[value="skills"]'), "a choice made by hand stays"
    cancel(page)
    assert errors == []


def open_tab(page, tab):
    if not page.is_visible(f'#tabs button[data-tab="{tab}"]'):  # in the More menu on narrow screens
        page.click("#tabs-more")
    page.click(f'#tabs button[data-tab="{tab}"]')
    page.wait_for_function("() => { const m = document.querySelector('#main');"
                           " return m.children.length && !m.querySelector('.spinner'); }", timeout=10000)


def test_tabs_that_do_not_fit_go_into_the_more_menu(page_on_sandbox):
    page, errors = page_on_sandbox
    assert not page.is_visible("#tabs-more")  # 1440px: every tab fits
    page.set_viewport_size({"width": 375, "height": 800})
    page.wait_for_selector("#tabs-more")
    row = lambda: page.eval_on_selector_all(".tabrow button", "bs => bs.map(b => b.dataset.tab)")
    assert row()[0] == "projects" and "settings" not in row()
    page.click("#tabs-more")
    page.click('#moremenu button[data-tab="health"]')
    page.wait_for_selector('.tabrow button[data-tab="health"].on')  # the active tab moves into the row
    assert page.is_hidden("#moremenu") and page.get_attribute("#tabs-more", "aria-expanded") == "false"
    assert page.evaluate("document.documentElement.scrollWidth") <= 375  # nothing scrolls sideways
    page.set_viewport_size({"width": 1440, "height": 900})
    page.wait_for_selector("#tabs-more", state="hidden")
    assert len(row()) == 12
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


def test_usage_tab(page_on_sandbox):
    page, errors = page_on_sandbox
    page.keyboard.press("g")
    page.keyboard.press("u")
    page.wait_for_selector('#tabs button[data-tab="usage"][aria-current="page"]')
    page.wait_for_selector(".uchart svg g.day")
    assert page.eval_on_selector_all(".uchart g.day", "gs => gs.length") == 30
    assert "estimate" in page.inner_text("#main") and "not billed per token" in page.inner_text("#main")
    assert page.query_selector("text=Profiles") is not None  # per-profile table with All profiles
    page.click('[data-udays="7"]')
    page.wait_for_function("() => document.querySelectorAll('.uchart g.day').length === 7")
    assert page.get_attribute('[data-udays="7"]', "aria-pressed") == "true"
    page.click('[data-uprof="work"]')
    page.wait_for_selector('[data-uprof="work"].on')
    page.wait_for_selector(".uchart svg")
    assert "~/code/work/api" in page.inner_text("#main")  # work, last 7 days
    assert "~/code/personal/blog" not in page.inner_text("#main")
    page.click('[data-udays="365"]')
    page.wait_for_function("() => document.querySelectorAll('.uchart g.day').length === 365")
    assert page.evaluate("document.documentElement.scrollWidth") <= 1440
    assert errors == []


# Rules that fail the test at any impact: headings that skip a level (h1 then h3) are only
# "moderate" for axe, but they break navigating the page by headings.
AXE_ALWAYS = {"heading-order"}


def axe_violations(page):
    """Serious and critical axe-core violations on the page as it is now, plus AXE_ALWAYS."""
    from axe_playwright_python.sync_playwright import Axe
    res = Axe().run(page, options={"resultTypes": ["violations"]}).response
    return [f"{v['id']} ({v['impact']}): {v['help']} at " + ", ".join(str(n["target"]) for n in v["nodes"][:4])
            for v in res["violations"] if v["impact"] in ("serious", "critical") or v["id"] in AXE_ALWAYS]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_no_serious_accessibility_violations(page_on_sandbox, theme):
    pytest.importorskip("axe_playwright_python")
    page, errors = page_on_sandbox
    page.evaluate(f"setTheme('{theme}')")
    found = {}
    for tab in page.eval_on_selector_all("#tabs button[data-tab]", "bs => bs.map(b => b.dataset.tab)"):
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
    page.wait_for_selector("#tabs-more")  # the row has made room for the More menu
    open_tab(page, "health")
    found["phone width"] = axe_violations(page)
    found = {t: v for t, v in found.items() if v}
    assert found == {}, "\n".join(f"{t}: {x}" for t, vs in found.items() for x in vs)


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


def test_status_line_section(page_on_sandbox):
    page, errors = page_on_sandbox
    open_tab(page, "settings")
    assert page.is_disabled("#sl-save")  # nothing to save yet
    page.click('[data-slmode="builtin"]')
    page.wait_for_function("() => document.querySelector('#sl-preview')?.textContent.length > 3")
    page.click('[data-slmove="profile"][data-dir="1"]')  # profile after model
    page.click('[data-slsep="bar"]')
    page.click('[data-slbrall="square"]')
    page.select_option('[data-slbr="profile"]', "curly")
    page.wait_for_function("() => /\\[Opus\\].*\\|.*\\{Default\\}/.test(document.querySelector('#sl-preview').textContent)")
    assert page.is_enabled("#sl-save") and page.inner_text("#sl-dirty") == "Unsaved changes"
    page.click('[data-slpart="time"]')  # ticked: it joins the end of the line
    order = page.eval_on_selector_all("[data-slitem]", "ls => ls.map(l => l.dataset.slitem)")
    assert order.index("time") == 5
    page.click('[data-slpart="limit"]')
    page.click('[data-slpart="tokens"]')
    page.wait_for_function("() => /5h:78%.*question:12k session:340k/.test(document.querySelector('#sl-preview').textContent)")
    page.click('[data-sllim="left"]')  # the quota left, with the time to the reset
    assert page.get_attribute('[data-sllim="left"]', "aria-pressed") == "true"
    page.wait_for_function("() => /5h:22%→1h20m/.test(document.querySelector('#sl-preview').textContent)")
    assert "limits=left" in page.text_content("#sl-script")
    assert page.inner_text('[data-slitem="limit"] .smp') == "[5h:22%→1h20m]"  # square brackets for all, above
    page.click('[data-sllim="used"]')
    page.wait_for_function("() => /5h:78%/.test(document.querySelector('#sl-preview').textContent)")
    page.click('[data-slmode="custom"]')
    page.wait_for_selector("#sl-cmd")
    page.click('[data-slmode="off"]')
    assert page.query_selector("#sl-cmd") is None and page.query_selector("#sl-preview") is None
    assert errors == []


def test_status_line_presets_fill_the_draft(page_on_sandbox):
    page, errors = page_on_sandbox
    open_tab(page, "settings")
    page.click('[data-slmode="builtin"]')
    pressed = lambda: page.eval_on_selector_all("[data-slpreset][aria-pressed=true]", "bs => bs.map(b => b.dataset.slpreset)")
    assert pressed() == ["developer"]  # the editor starts from the same pieces
    page.click("#sl-save")
    page.wait_for_function("() => document.querySelector('#sl-save')?.disabled")
    page.click('[data-slpreset="usage"]')
    assert pressed() == ["usage"] and page.is_enabled("#sl-save")  # filled, not saved
    assert page.get_attribute('[data-slpreset="usage"]', "title").startswith("Model, tokens")
    page.wait_for_function("() => /^Opus \\| question:12k session:340k \\| \\$1\\.27 \\| 5h:22%→1h20m \\| 7d:59%$/"
                           ".test(document.querySelector('#sl-preview').textContent)")
    order = page.eval_on_selector_all("[data-slitem] input:checked", "cs => cs.map(c => c.dataset.slpart)")
    assert order == ["model", "tokens", "cost", "limit", "week"]
    assert page.get_attribute('[data-sllim="left"]', "aria-pressed") == "true"
    page.click("#sl-colors")  # any change of its own: no preset matches any more
    assert pressed() == []
    page.click('[data-slpreset="essential"]')
    page.wait_for_function("() => document.querySelector('#sl-preview').textContent === 'Default · Opus · ctx:42%'")
    page.click('[data-slpreset="developer"]')  # back to what is saved
    assert page.is_disabled("#sl-save") and pressed() == ["developer"]
    assert errors == []


def test_general_settings_wait_for_save(page_on_sandbox):
    page, errors = page_on_sandbox
    open_tab(page, "settings")
    assert page.is_hidden("#gen-bar")
    page.select_option('[data-sfield="timeFormat"]', "12-hour")
    page.wait_for_selector("#gen-bar:not([hidden])")
    assert page.inner_text("#gen-count") == "1 unsaved change"
    assert page.get_attribute('[data-srow="timeFormat"]', "class") == "srow changed"
    page.select_option('[data-sfield="timeFormat"]', "24-hour")  # back to the saved value: no change left
    page.wait_for_selector("#gen-bar[hidden]", state="attached")
    page.select_option('[data-sfield="editorMode"]', "vim")
    page.click("#gen-cancel")
    assert page.input_value('[data-sfield="editorMode"]') == ""
    page.select_option('[data-sfield="editorMode"]', "vim")
    y = page.evaluate("window.scrollY")
    page.click("#gen-save")
    page.wait_for_selector(".toast")
    page.wait_for_selector("#gen-bar[hidden]", state="attached")
    assert page.input_value('[data-sfield="editorMode"]') == "vim"
    assert abs(page.evaluate("window.scrollY") - y) < 5  # the page stays where it was
    assert errors == []

