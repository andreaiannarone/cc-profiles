"""Print the Homebrew formula for a released version of cc-profiles.

    python3 scripts/homebrew_formula.py 0.4.3 > Formula/cc-profiles.rb

It reads the sdist's URL and SHA-256 from PyPI, so run it after the release is
published. scripts/release.py does it at every release and writes the result in the
tap, github.com/andreaiannarone/homebrew-cc-profiles (brew install andreaiannarone/cc-profiles/cc-profiles).
"""
import json
import sys
import urllib.request

FORMULA = """class CcProfiles < Formula
  include Language::Python::Virtualenv

  desc "Local web UI to manage multiple Claude Code profiles"
  homepage "https://github.com/andreaiannarone/cc-profiles"
  url "{url}"
  sha256 "{sha256}"
  license "GPL-3.0-or-later"

  depends_on "python-setuptools" => :build  # the sdist builds with setuptools; Homebrew builds without isolation
  depends_on "python@3.13"

  def install
    virtualenv_install_with_resources
  end

  def caveats
    <<~EOS
      Open it with: cc-profiles open
      The first start adds /cc-profiles to Claude Code in every profile.
    EOS
  end

  test do
    assert_match version.to_s, shell_output("#{{bin}}/cc-profiles --version")
  end
end
"""


def sdist(version):
    with urllib.request.urlopen(f"https://pypi.org/pypi/cc-profiles/{version}/json", timeout=20) as r:
        data = json.load(r)
    for f in data["urls"]:
        if f["packagetype"] == "sdist":
            return f["url"], f["digests"]["sha256"]
    raise SystemExit(f"No sdist on PyPI for cc-profiles {version}")


def formula(version):
    url, sha256 = sdist(version)
    return FORMULA.format(url=url, sha256=sha256)


def main():
    if len(sys.argv) != 2:
        raise SystemExit(__doc__.strip().splitlines()[2].strip())
    sys.stdout.write(formula(sys.argv[1]))


if __name__ == "__main__":
    main()
