"""Prepare the Python Worker's vendored package from the canonical source tree."""
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src" / "economy" / "game_asset_pack.py"
DESTINATION = ROOT / "cloudflare" / "python-runtime" / "python_modules" / "economy"

if not SOURCE.is_file():
    raise SystemExit("canonical game_asset_pack.py source is missing")
DESTINATION.mkdir(parents=True, exist_ok=True)
shutil.copyfile(SOURCE, DESTINATION / "game_asset_pack.py")
(DESTINATION / "__init__.py").write_text('"""Canonical AAE product producer package, vendored for Workers."""\n', encoding="utf-8")
print("Prepared Cloudflare Python runtime from src/economy/game_asset_pack.py")
