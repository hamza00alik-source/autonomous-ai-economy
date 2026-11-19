import hashlib, json
from src.economy.moba_hud_kit import SHAPES, build
def test_vector_pack_is_complete_and_hash_verified(tmp_path):
    archive=build(tmp_path/"pack")
    root=tmp_path/"pack"
    assert len(list((root/"icons").glob("*.svg")))==24
    assert len(list((root/"hud").glob("*.svg")))==6
    manifest=json.loads((root/"manifest.json").read_text())
    for rel,meta in manifest.items():
        data=(root/rel).read_bytes()
        assert hashlib.sha256(data).hexdigest()==meta["sha256"]
        assert len(data)==meta["bytes"]
    assert archive.is_file() and len(SHAPES)==24
    assert all(f.read_text().startswith("<svg ") for f in root.rglob("*.svg"))
