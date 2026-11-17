from __future__ import annotations

import hashlib
import json
import struct
import zipfile

from economy.game_asset_pack import GameAssetBuilderAgent, build_game_asset_pack


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
        assert "listing-copy.md" in names
        scene = archive.read("godot/MOBAObjectiveProps.tscn").decode("utf-8")
        assert "ExtResource" in scene
        assert "PackedScene" in scene


def test_game_asset_pack_is_reproducible(tmp_path):
    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"
    build_game_asset_pack(first)
    build_game_asset_pack(second)
    assert first.read_bytes() == second.read_bytes()

from collections import defaultdict

from economy.game_asset_pack import _cylinder, _crystal


def _cross(a, b, c):
    u = tuple(b[i] - a[i] for i in range(3))
    v = tuple(c[i] - a[i] for i in range(3))
    return (
        u[1] * v[2] - u[2] * v[1],
        u[2] * v[0] - u[0] * v[2],
        u[0] * v[1] - u[1] * v[0],
    )


def test_primitive_face_winding_points_outward():
    cylinder = defaultdict(list)
    _cylinder(cylinder, (0, 0, 0), 1.0, 2.0, "stone", sides=8)
    side_normal = _cross(*cylinder["stone"][0])
    side_center = tuple(sum(v[i] for v in cylinder["stone"][0]) / 3 for i in range(3))
    assert side_normal[0] * side_center[0] + side_normal[2] * side_center[2] > 0
    bottom_normal = _cross(*cylinder["stone"][2])
    top_normal = _cross(*cylinder["stone"][3])
    assert bottom_normal[1] < 0
    assert top_normal[1] > 0

    crystal = defaultdict(list)
    _crystal(crystal, (0, 0, 0), 1.0, 2.0, sides=8)
    normal = _cross(*crystal["crystal_light"][0])
    center = tuple(sum(v[i] for v in crystal["crystal_light"][0]) / 3 for i in range(3))
    assert normal[0] * center[0] + normal[2] * center[2] > 0


def test_named_asset_builder_agent_produces_the_sold_product(tmp_path):
    agent = GameAssetBuilderAgent()
    output = tmp_path / "agent-produced-pack.zip"
    result = agent.build(output)
    assert agent.agent_id == "game-asset-builder"
    assert agent.role == "procedural 3D game asset production"
    assert output.is_file()
    assert result["published"] is False
    assert result["sales_verified"] is False
