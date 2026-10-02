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
    h = re.sub(r"[`*_]", "", heading.strip().lower())
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def anchors(path):
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.*)$", strip_code(path.read_text()), re.M)}


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


def test_every_doc_page_is_linked_from_the_index():
    index = (ROOT / "docs" / "README.md").read_text()
    pages = [p.relative_to(ROOT / "docs").as_posix() for p in ROOT.glob("docs/**/*.md") if p.name != "README.md"]
    missing = [p for p in pages if f"({p}" not in index]
    assert not missing, f"pages not linked from docs/README.md: {missing}"
