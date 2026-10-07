"""Documentation checks: every relative link and #anchor must point somewhere real.

Anchors are computed like GitHub does from headings. Code blocks and inline code
are ignored, because they contain example links on purpose.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = sorted(ROOT.glob("docs/**/*.md")) + [ROOT / f for f in
        ("README.md", "CONTRIBUTING.md", "CLAUDE.md", "DESIGN.md", "SECURITY.md", "CHANGELOG.md")]


def strip_code(text):
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def slug(heading):
    # underscores stay, as on GitHub and the docs site: ### `search_roots` → #search_roots
    h = re.sub(r"[`*]", "", heading.strip().lower())
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def anchors(path):
    # only code blocks go: inline code in a title is part of its anchor
    text = re.sub(r"```.*?```", "", path.read_text(), flags=re.S)
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.*)$", text, re.M)}


def test_relative_links_and_anchors_exist():
    broken = []
    for doc in DOCS:
        for target in re.findall(r"\]\(([^)\s]+)\)", strip_code(doc.read_text())):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            path, _, anchor = target.partition("#")
            dest = (doc.parent / path).resolve() if path else doc
            if not dest.exists():
                broken.append(f"{doc.relative_to(ROOT)} → {target} (file not found)")
            elif anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                broken.append(f"{doc.relative_to(ROOT)} → {target} (no such heading)")
    assert not broken, "broken links:\n" + "\n".join(broken)


def test_html_images_and_links_in_docs_exist():
    """Screenshots are <picture>s written in HTML: their src, srcset and href must exist too,
    and every screenshot comes in both themes."""
    broken, single = [], []
    for doc in ROOT.glob("docs/**/*.md"):
        text = strip_code(doc.read_text())
        for target in re.findall(r'(?:src|srcset|href)="([^"#]+)', text):
            if target.startswith(("http://", "https://", "mailto:")):
                continue
            if not (doc.parent / target).resolve().exists():
                broken.append(f"{doc.relative_to(ROOT)} → {target}")
        for pic in re.findall(r"<picture>.*?</picture>", text, re.S):
            if not ("-dark." in pic and "-light." in pic):
                single.append(f"{doc.relative_to(ROOT)}: {pic[:80]}")
    assert not broken, "missing files:\n" + "\n".join(broken)
    assert not single, "a <picture> needs a -light and a -dark image:\n" + "\n".join(single)


def test_every_doc_page_is_linked_from_the_index():
    index = (ROOT / "docs" / "README.md").read_text()
    pages = [p.relative_to(ROOT / "docs").as_posix() for p in ROOT.glob("docs/**/*.md")
             if p.name not in ("README.md", "404.md")]  # 404.md: the site's "page not found", reached by mistake only
    missing = [p for p in pages if f"({p}" not in index]
    assert not missing, f"pages not linked from docs/README.md: {missing}"


def test_copyright_links_to_the_author():
    line = '© 2026 <a href="https://andreaiannarone.com">Andrea Iannarone</a>'
    assert line in (ROOT / "README.md").read_text(), "README footer: absolute link, it is shown on PyPI too"
    assert line in (ROOT / "docs" / "_layouts" / "default.html").read_text()
    ui = (ROOT / "src" / "cc_profiles" / "static" / "index.html").read_text()
    assert '© 2026 <a href="https://andreaiannarone.com" target="_blank" rel="noopener">Andrea Iannarone</a>' in ui
