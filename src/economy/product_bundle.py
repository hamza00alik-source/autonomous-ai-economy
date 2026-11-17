"""Build reproducible, integrity-manifested standalone product ZIP bundles."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

PRODUCT_SLUG = "store-catalog-cleaner"
_REQUIRED = ("index.html", "README.md", "listing-copy.md")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build_product_bundle(output: str | Path) -> dict:
    """Package the reviewed product directory into a deterministic ZIP.

    The archive always has index.html at its root, as required by Gumroad's
    browser-app upload workflow. It does not publish or upload the product.
    """
    root = Path(__file__).resolve().parents[2] / "products" / PRODUCT_SLUG
    if not root.is_dir():
        raise FileNotFoundError(f"product source directory not found: {root}")
    files: list[tuple[str, bytes]] = []
    for name in _REQUIRED:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"required product file is missing or unsafe: {name}")
        data = path.read_bytes()
        if not data:
            raise ValueError(f"required product file is empty: {name}")
        files.append((name, data))
    html = dict(files)["index.html"].decode("utf-8")
    if "<!doctype html>" not in html.lower() or "<script" not in html.lower():
        raise ValueError("product index.html must be a standalone interactive HTML app")
    if "Store Catalog Cleaner" not in html:
        raise ValueError("product identity does not match the bundle slug")
    manifest = {
        "schema": "aae.product-bundle/v1",
        "product": PRODUCT_SLUG,
        "files": [
            {"path": name, "size_bytes": len(data), "sha256": _sha256(data)}
            for name, data in files
        ],
        "notice": "Bundle integrity manifest; not proof of demand, sales, or marketplace approval.",
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in files + [("manifest.json", manifest_bytes)]:
                safe = PurePosixPath(name)
                if safe.is_absolute() or ".." in safe.parts or len(safe.parts) != 1:
                    raise ValueError("unsafe archive path")
                info = zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, data)
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return {
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "sha256": _sha256(target.read_bytes()),
        "manifest": manifest,
        "published": False,
        "uploaded": False,
        "sales_verified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a standalone Store Catalog Cleaner product ZIP")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build the private product ZIP")
    build.add_argument("--output", type=Path, default=Path("dist/store-catalog-cleaner.zip"))
    args = parser.parse_args()
    if args.command == "build":
        print(json.dumps(build_product_bundle(args.output), indent=2, sort_keys=True))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
