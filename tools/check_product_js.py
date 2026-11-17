"""Check the standalone product's inline JavaScript syntax with Node.js."""
from __future__ import annotations

import subprocess
import tempfile
from html.parser import HTMLParser
from pathlib import Path


class InlineScriptExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.in_script = False
        self.parts: list[str] = []
        self.count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "script":
            if dict(attrs).get("src"):
                raise ValueError("product must not load remote scripts")
            self.in_script = True
            self.count += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "script":
            self.in_script = False

    def handle_data(self, data: str) -> None:
        if self.in_script:
            self.parts.append(data)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    html = (root / "products" / "store-catalog-cleaner" / "index.html").read_text(encoding="utf-8")
    parser = InlineScriptExtractor()
    parser.feed(html)
    if parser.count != 1:
        raise SystemExit("expected exactly one inline script block")
    source = "".join(parser.parts)
    if not source.strip():
        raise SystemExit("product script is empty")
    with tempfile.NamedTemporaryFile("w", suffix=".js", encoding="utf-8") as handle:
        handle.write(source)
        handle.flush()
        subprocess.run(["node", "--check", handle.name], check=True)
    print("Store Catalog Cleaner JavaScript syntax: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
