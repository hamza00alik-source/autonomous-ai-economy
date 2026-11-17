from __future__ import annotations

import hashlib
import json
import zipfile

from economy.product_bundle import build_product_bundle


def test_product_bundle_is_rooted_and_manifested(tmp_path):
    output = tmp_path / "store-catalog-cleaner.zip"
    result = build_product_bundle(output)
    assert output.is_file()
    assert result["published"] is False
    assert result["uploaded"] is False
    assert result["sales_verified"] is False
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        assert names == ["index.html", "README.md", "listing-copy.md", "manifest.json"]
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema"] == "aae.product-bundle/v1"
        for item in manifest["files"]:
            content = archive.read(item["path"])
            assert len(content) == item["size_bytes"]
            assert hashlib.sha256(content).hexdigest() == item["sha256"]
        html = archive.read("index.html").decode("utf-8")
        assert "function parseCSV" in html
        assert "function applyCleanup" in html
        assert "function download" in html
        assert "createObjectURL" in html


def test_product_bundle_is_reproducible(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    build_product_bundle(first)
    build_product_bundle(second)
    assert first.read_bytes() == second.read_bytes()
