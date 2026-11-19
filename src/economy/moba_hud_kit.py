"""Dependency-free generator for an original MOBA HUD SVG asset pack."""
from __future__ import annotations
import argparse, hashlib, json, zipfile
from pathlib import Path

SHAPES = {
"sword": '<path d="M25 103 72 56l-9-9 10-10 10 9 22-22 4 4-22 22 9 9-10 10-9-9-47 47z"/>',
"shield": '<path d="M64 12 105 28v29c0 28-17 46-41 59C40 103 23 85 23 57V28z"/>',
"heart": '<path d="M64 108 20 64C-2 35 34 8 64 39 94 8 130 35 108 64z"/>',
"mana": '<path d="M64 10 99 57 64 116 29 57z"/>',
"coin": '<circle cx="64" cy="64" r="45"/><path d="M64 29v70M81 43H55c-16 0-16 20 0 20h18c17 0 17 22 0 22H44" fill="none" stroke="#fff0b2" stroke-width="8"/>',
"potion": '<path d="M48 12h32v18l-7 9v10c22 8 31 22 31 39 0 19-18 29-40 29S24 107 24 88c0-17 9-31 31-39V39l-7-9z"/>',
"boots": '<path d="M34 19h35v47l16 12 24 8v18H17V88l17-13z"/>',
"bow": '<path d="M27 15Q112 64 27 113M29 15l65 98" fill="none" stroke="#f4d58a" stroke-width="8"/>',
"arrow": '<path d="m15 101 73-73 5 5-73 73zM78 28l26-9-9 26z"/>',
"orb": '<circle cx="64" cy="64" r="42"/><path d="M64 18v92M18 64h92" stroke="#b9f4ff" stroke-width="5"/>',
"crown": '<path d="m15 39 25 18 24-37 24 37 25-18-10 63H25z"/>',
"gem": '<path d="m30 17 68 0 18 31-52 65L12 48z"/>',
"skull": '<path d="M64 13c-30 0-48 22-45 49 2 15 12 23 20 30v18h50V92c8-7 18-15 20-30 3-27-15-49-45-49z"/>',
"flag": '<path d="M27 14v100" stroke="#f4d58a" stroke-width="8"/><path d="M34 20h65l-14 23 14 23H34z"/>',
"hourglass": '<path d="M30 14h68M30 114h68M38 18c0 23 52 38 52 46S38 87 38 110M90 18c0 23-52 38-52 46s52 23 52 46" fill="none" stroke="#f4d58a" stroke-width="8"/>',
"eye": '<path d="M10 64Q64 8 118 64 64 120 10 64z"/><circle cx="64" cy="64" r="19" fill="#242333"/>',
"bolt": '<path d="m72 8-48 62h31l-7 50 48-68H65z"/>',
"target": '<circle cx="64" cy="64" r="48" fill="none" stroke="#f4d58a" stroke-width="9"/><circle cx="64" cy="64" r="27" fill="none" stroke="#f4d58a" stroke-width="8"/>',
"portal": '<path d="M64 10C22 10 16 113 64 113s42-103 0-103z" fill="none" stroke="#a6efff" stroke-width="10"/>',
"helmet": '<path d="M18 69a46 46 0 0 1 92 0v15H18z"/>',
"hammer": '<path d="m22 36 22-22 35 35-22 22zM54 63l12 12-34 34-12-12z"/>',
"leaf": '<path d="M106 17C40 15 13 43 18 82c4 32 42 37 64 15 18-18 25-45 24-80z"/>',
"flame": '<path d="M67 9c8 31-15 34-4 55 9-9 15-17 16-29 24 25 36 47 23 67-17 27-67 25-83-1-14-23 1-50 20-68-1 21 7 27 14 30C59 43 54 27 67 9z"/>',
"rune": '<path d="M28 20h72v14H42v27h48v14H42v25h58v14H28z"/>',
"crystal": '<path d="m64 8 35 35-10 58-25 15-25-15-10-58z"/>'
}
PALETTE=["#e6b85c","#3d9ca0","#b94e59","#4b7eae","#5e9b72","#8266b1"]
PANELS=["Bottom Ability Bar","Health and Mana Panel","Objective Alert Banner","Match Status Panel","Item Shop Card","Scoreboard Panel"]
def make_svg(body,color):
 return f'<svg xmlns="http://www.w3.org/2000/svg" width="128" height="128" viewBox="0 0 128 128"><circle cx="64" cy="64" r="58" fill="#242333" stroke="#e6b85c" stroke-width="5"/><circle cx="64" cy="64" r="49" fill="{color}"/><g fill="#fff0c2" stroke="#242333" stroke-width="2" stroke-linejoin="round">{body}</g></svg>'
def build(out:Path):
 out.mkdir(parents=True,exist_ok=True); (out/"icons").mkdir(exist_ok=True); (out/"hud").mkdir(exist_ok=True)
 for i,(name,body) in enumerate(SHAPES.items()): (out/"icons"/(name+".svg")).write_text(make_svg(body,PALETTE[i%len(PALETTE)]),encoding="utf-8")
 for i,title in enumerate(PANELS):
  slug=["bottom-bar","health-mana","objective-alert","match-status","item-shop","scoreboard"][i]
  svg=f'<svg xmlns="http://www.w3.org/2000/svg" width="900" height="240" viewBox="0 0 900 240"><rect x="8" y="8" width="884" height="224" rx="28" fill="#242333" stroke="{PALETTE[i]}" stroke-width="8"/><path d="M30 48H870" stroke="#e6b85c" stroke-width="5"/><text x="48" y="105" fill="#fff0c2" font-family="sans-serif" font-size="34">{title}</text><rect x="48" y="132" width="804" height="66" rx="14" fill="#39374c" stroke="{PALETTE[i]}" stroke-width="4"/></svg>'
  (out/"hud"/(slug+".svg")).write_text(svg,encoding="utf-8")
 (out/"README.md").write_text("# MOBA HUD Vector Kit\n\n24 original SVG icons and six scalable HUD panel frames. Import into Godot 4, Unity, Unreal or web UI. Art assets only: no gameplay code, working HUD, multiplayer integration or PNG exports. Includes SHA-256 manifest. AI-assisted procedural vector generation. Draft license permits personal/commercial game use but prohibits standalone redistribution; review before sale.\n",encoding="utf-8")
 manifest={}
 for f in sorted(p for p in out.rglob("*") if p.is_file() and p.name!="manifest.json"):
  data=f.read_bytes(); manifest[f.relative_to(out).as_posix()]={"sha256":hashlib.sha256(data).hexdigest(),"bytes":len(data)}
 (out/"manifest.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
 archive=out.parent/"moba-hud-vector-kit.zip"
 with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
  for f in sorted(p for p in out.rglob("*") if p.is_file()): z.write(f,f.relative_to(out.parent).as_posix())
 return archive
def main():
 p=argparse.ArgumentParser(); p.add_argument("--output",default="dist/moba-hud-vector-kit"); a=p.parse_args(); print(build(Path(a.output)))
if __name__=="__main__": main()
