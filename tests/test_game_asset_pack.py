from __future__ import annotations

import hashlib
import json
import struct
import zipfile

from economy.game_asset_pack import build_game_asset_pack


def _glb_document(data):
    magic, version, total = struct.unpack_from("<4sII", data, 0)
    assert magic == b"glTF"
    assert version == 2
    assert total == len(data)
    length, kind = struct.unpack_from("<I4s", data, 12)
    assert kind == b"JSON"
    return json.loads(data[20:20 + length].decode("utf-8").rstrip(" "))


def test_game_asset_pack_contains_real_glb_geometry(tmp_path):
    output = tmp_path / "moba-objective-props.zip"
    result = build_game_asset_pack(output)
    assert output.is_file()
    assert result["published"] is False
    assert result["sales_verified"] is False
    with zipfile.ZipFile(output) as archive:
        names = archive.namelist()
        for slug in ("mana_crystal", "health_vial", "rune_altar", "supply_chest", "coin_stack"):
            path = "assets/" + slug + ".glb"
            assert path in names
            doc = _glb_document(archive.read(path))
            assert doc["asset"]["version"] == "2.0"
            assert doc["meshes"]
            assert doc["nodes"]
            assert doc["accessors"]
            assert doc["bufferViews"]
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["schema"] == "aae.game-asset-pack/v1"
        assert manifest["assets"]["preview"]["meshes"] == 5
        assert manifest["assets"]["preview"]["triangles"] > 100
        for item in manifest["files"]:
            data = archive.read(item["path"])
            assert len(data) == item["size_bytes"]
            assert hashlib.sha256(data).hexdigest() == item["sha256"]
        assert "godot/MOBAObjectiveProps.tscn" in names
        scene = archive.read("godot/MOBAObjectiveProps.tscn").decode("utf-8")
        assert "ExtResource" in scene
        assert "PackedScene" in scene


def test_game_asset_pack_is_reproducible(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    build_game_asset_pack(first)
    build_game_asset_pack(second)
    assert first.read_bytes() == second.read_bytes()
