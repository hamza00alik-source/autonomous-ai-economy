"""Generate an original, low-poly MOBA prop pack as engine-importable glTF 2.0 assets.

No external models, textures, paid APIs, or network access are used.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import tempfile
import zipfile
from collections import defaultdict
from pathlib import Path, PurePosixPath

PRODUCT_SLUG = "moba-objective-props"
MATERIALS = {
    "stone": {"baseColorFactor": [0.24, 0.30, 0.34, 1], "metallicFactor": 0.05, "roughnessFactor": 0.92},
    "dark_stone": {"baseColorFactor": [0.10, 0.15, 0.18, 1], "metallicFactor": 0.1, "roughnessFactor": 0.85},
    "crystal": {"baseColorFactor": [0.10, 0.72, 0.90, 1], "metallicFactor": 0.15, "roughnessFactor": 0.28, "emissiveFactor": [0.02, 0.28, 0.42]},
    "crystal_light": {"baseColorFactor": [0.55, 0.94, 1.0, 1], "metallicFactor": 0.08, "roughnessFactor": 0.22, "emissiveFactor": [0.12, 0.42, 0.55]},
    "ruby": {"baseColorFactor": [0.78, 0.055, 0.12, 1], "metallicFactor": 0.12, "roughnessFactor": 0.3, "emissiveFactor": [0.18, 0.0, 0.015]},
    "wood": {"baseColorFactor": [0.34, 0.16, 0.07, 1], "metallicFactor": 0.0, "roughnessFactor": 0.88},
    "wood_light": {"baseColorFactor": [0.55, 0.29, 0.12, 1], "metallicFactor": 0.0, "roughnessFactor": 0.82},
    "iron": {"baseColorFactor": [0.12, 0.17, 0.21, 1], "metallicFactor": 0.82, "roughnessFactor": 0.32},
    "gold": {"baseColorFactor": [0.92, 0.57, 0.10, 1], "metallicFactor": 0.86, "roughnessFactor": 0.25},
    "cork": {"baseColorFactor": [0.48, 0.25, 0.11, 1], "metallicFactor": 0.0, "roughnessFactor": 0.95},
}


def _v(x, y, z):
    return (float(x), float(y), float(z))


def _triangle(parts, material, a, b, c):
    parts[material].append((a, b, c))


def _box(parts, center, size, material):
    x, y, z = center
    sx, sy, sz = (v / 2 for v in size)
    p = [
        _v(x-sx,y-sy,z-sz), _v(x+sx,y-sy,z-sz), _v(x+sx,y+sy,z-sz), _v(x-sx,y+sy,z-sz),
        _v(x-sx,y-sy,z+sz), _v(x+sx,y-sy,z+sz), _v(x+sx,y+sy,z+sz), _v(x-sx,y+sy,z+sz),
    ]
    faces = [(0,3,2,1),(4,5,6,7),(0,1,5,4),(3,7,6,2),(0,4,7,3),(1,2,6,5)]
    for a,b,c,d in faces:
        _triangle(parts, material, p[a], p[b], p[c])
        _triangle(parts, material, p[a], p[c], p[d])


def _cylinder(parts, center, radius, height, material, sides=10, top_radius=None):
    import math
    x, y, z = center
    top_radius = radius if top_radius is None else top_radius
    lower = [_v(x + radius*math.cos(2*math.pi*i/sides), y-height/2, z + radius*math.sin(2*math.pi*i/sides)) for i in range(sides)]
    upper = [_v(x + top_radius*math.cos(2*math.pi*i/sides), y+height/2, z + top_radius*math.sin(2*math.pi*i/sides)) for i in range(sides)]
    bottom_center, top_center = _v(x,y-height/2,z), _v(x,y+height/2,z)
    for i in range(sides):
        j=(i+1)%sides
        _triangle(parts, material, lower[i], upper[j], lower[j])
        _triangle(parts, material, lower[i], upper[i], upper[j])
        _triangle(parts, material, bottom_center, lower[i], lower[j])
        _triangle(parts, material, top_center, upper[j], upper[i])


def _cone(parts, center, radius, height, material, sides=8):
    import math
    x,y,z=center
    ring=[_v(x+radius*math.cos(2*math.pi*i/sides),y-height/2,z+radius*math.sin(2*math.pi*i/sides)) for i in range(sides)]
    tip=_v(x,y+height/2,z)
    base=_v(x,y-height/2,z)
    for i in range(sides):
        j=(i+1)%sides
        _triangle(parts,material,ring[i],tip,ring[j])
        _triangle(parts,material,base,ring[i],ring[j])


def _crystal(parts, center, radius, height, material="crystal", light="crystal_light", sides=8):
    import math
    x,y,z=center
    lower_y=y-height*0.30
    mid_y=y+height*0.18
    tip_y=y+height*0.52
    lower=[_v(x+radius*0.68*math.cos(2*math.pi*i/sides),lower_y,z+radius*0.68*math.sin(2*math.pi*i/sides)) for i in range(sides)]
    middle=[_v(x+radius*math.cos(2*math.pi*i/sides),mid_y,z+radius*math.sin(2*math.pi*i/sides)) for i in range(sides)]
    tip=_v(x,y+height*0.5,z)
    for i in range(sides):
        j=(i+1)%sides
        mat=light if i%2==0 else material
        _triangle(parts,mat,lower[i],middle[j],lower[j])
        _triangle(parts,mat,lower[i],middle[i],middle[j])
        _triangle(parts,mat,middle[i],tip,middle[j])


def _new_parts():
    return defaultdict(list)


def _mana_crystal():
    p=_new_parts()
    _cylinder(p,(0,0.12,0),0.62,0.24,"dark_stone",8)
    _cylinder(p,(0,0.31,0),0.42,0.18,"gold",8)
    _crystal(p,(0,1.12,0),0.46,1.45)
    return p


def _health_vial():
    p=_new_parts()
    _cylinder(p,(0,0.58,0),0.38,0.86,"ruby",10,top_radius=0.30)
    _cylinder(p,(0,1.10,0),0.18,0.30,"iron",8)
    _cylinder(p,(0,1.32,0),0.23,0.18,"cork",8)
    _cylinder(p,(0,0.13,0),0.43,0.16,"gold",10)
    _box(p,(0,0.62,0.36),(0.11,0.48,0.035),"crystal_light")
    return p


def _rune_altar():
    p=_new_parts()
    _cylinder(p,(0,0.12,0),1.0,0.24,"dark_stone",12)
    _cylinder(p,(0,0.31,0),0.78,0.18,"stone",10)
    _cylinder(p,(0,0.47,0),0.58,0.14,"gold",10)
    for x,z in [(-0.56,-0.56),(0.56,-0.56),(-0.56,0.56),(0.56,0.56)]:
        _box(p,(x,0.82,z),(0.16,0.66,0.16),"stone")
        _cylinder(p,(x,1.18,z),0.12,0.12,"gold",6)
    _cylinder(p,(0,1.28,0),0.48,0.16,"dark_stone",10)
    _crystal(p,(0,1.90,0),0.30,1.08)
    return p


def _supply_chest():
    p=_new_parts()
    _box(p,(0,0.42,0),(1.38,0.72,0.92),"wood")
    _box(p,(0,0.84,0),(1.42,0.18,0.96),"wood_light")
    _box(p,(0,0.48,0.48),(1.48,0.12,0.06),"iron")
    _box(p,(0,0.48,-0.48),(1.48,0.12,0.06),"iron")
    _box(p,(-0.67,0.48,0),(0.08,0.72,0.96),"iron")
    _box(p,(0.67,0.48,0),(0.08,0.72,0.96),"iron")
    _box(p,(0,0.52,0.51),(0.24,0.30,0.08),"gold")
    _cylinder(p,(0,0.53,0.58),0.075,0.10,"iron",8)
    return p


def _coin_stack():
    p=_new_parts()
    for i in range(5):
        _cylinder(p,(0,0.12+i*0.13,0),0.43,0.09,"gold",12)
    _cylinder(p,(0,0.78,0),0.22,0.05,"wood_light",10)
    _cylinder(p,(0,0.82,0),0.12,0.06,"gold",8)
    return p



def _ward_totem():
    p=_new_parts()
    _cylinder(p,(0,0.12,0),0.58,0.24,"dark_stone",10)
    _cylinder(p,(0,0.28,0),0.42,0.12,"gold",8)
    _cylinder(p,(0,0.88,0),0.24,1.12,"wood",8,top_radius=0.18)
    _box(p,(0,0.88,0.24),(0.12,0.82,0.04),"gold")
    _cylinder(p,(0,1.55,0),0.38,0.14,"dark_stone",8)
    _crystal(p,(0,2.02,0),0.27,0.82)
    return p


def _battle_banner():
    p=_new_parts()
    _cylinder(p,(0,0.12,0),0.48,0.22,"dark_stone",10)
    _cylinder(p,(0,1.18,0),0.075,2.05,"iron",8)
    _box(p,(0.36,1.82,0),(0.78,0.78,0.055),"ruby")
    _box(p,(0.36,2.18,0.035),(0.78,0.08,0.035),"gold")
    _box(p,(0.36,1.46,0.035),(0.78,0.08,0.035),"gold")
    _box(p,(0.36,1.82,0.055),(0.10,0.42,0.025),"gold")
    _cylinder(p,(0,2.28,0),0.12,0.18,"gold",8)
    return p


def _jungle_brazier():
    p=_new_parts()
    _cylinder(p,(0,0.12,0),0.62,0.24,"dark_stone",10)
    _cylinder(p,(0,0.62,0),0.24,0.82,"stone",8)
    _cylinder(p,(0,1.12,0),0.48,0.20,"iron",10,top_radius=0.62)
    _cylinder(p,(0,1.28,0),0.52,0.12,"gold",10)
    _cone(p,(0,1.72,0),0.34,0.82,"crystal_light",8)
    _crystal(p,(0,1.82,0),0.16,0.72,"crystal","crystal_light",6)
    return p


def _lane_turret():
    p=_new_parts()
    _cylinder(p,(0,0.14,0),0.82,0.28,"dark_stone",12)
    _cylinder(p,(0,0.82,0),0.50,1.18,"stone",8,top_radius=0.38)
    _cylinder(p,(0,1.48,0),0.62,0.30,"dark_stone",8)
    for i in range(4):
        import math
        angle=math.pi*i/2
        x,z=0.48*math.cos(angle),0.48*math.sin(angle)
        _box(p,(x,1.72,z),(0.22,0.42,0.22),"stone")
    _cylinder(p,(0,1.76,0),0.30,0.16,"gold",8)
    _crystal(p,(0,2.25,0),0.25,0.88)
    return p


def _rune_gate():
    p=_new_parts()
    _box(p,(0,0.10,0),(2.05,0.20,0.62),"dark_stone")
    for x in (-0.78,0.78):
        _box(p,(x,1.05,0),(0.34,1.72,0.42),"stone")
        _box(p,(x,1.90,0),(0.48,0.18,0.54),"gold")
        _cylinder(p,(x,2.10,0),0.14,0.22,"gold",8)
    _box(p,(0,2.02,0),(1.92,0.34,0.48),"dark_stone")
    _box(p,(0,2.20,0),(1.66,0.10,0.40),"gold")
    _crystal(p,(0,1.20,0),0.22,0.74,"crystal","crystal_light",6)
    return p


_ASSETS = [
    ("mana_crystal", "Mana Crystal", _mana_crystal),
    ("health_vial", "Health Vial", _health_vial),
    ("rune_altar", "Rune Altar", _rune_altar),
    ("supply_chest", "Supply Chest", _supply_chest),
    ("coin_stack", "Ancient Coin Stack", _coin_stack),
    ("ward_totem", "Arcane Ward Totem", _ward_totem),
    ("battle_banner", "Battle Banner", _battle_banner),
    ("jungle_brazier", "Jungle Brazier", _jungle_brazier),
    ("lane_turret", "Lane Turret", _lane_turret),
    ("rune_gate", "Rune Gate", _rune_gate),
]


def _glb(scene_objects):
    """Create a binary glTF 2.0 scene from named triangle/material collections."""
    materials=list(MATERIALS)
    binary=bytearray()
    buffer_views=[]
    accessors=[]
    meshes=[]
    nodes=[]

    def add_buffer(data, target):
        while len(binary)%4:
            binary.append(0)
        offset=len(binary)
        binary.extend(data)
        view={"buffer":0,"byteOffset":offset,"byteLength":len(data)}
        if target:
            view["target"]=target
        buffer_views.append(view)
        return len(buffer_views)-1

    for name, parts, translation in scene_objects:
        primitives=[]
        for material_name, triangles in parts.items():
            if not triangles:
                continue
            positions=[]
            normals=[]
            indices=[]
            for tri in triangles:
                a,b,c=tri
                ux,uy,uz=(b[i]-a[i] for i in range(3))
                vx,vy,vz=(c[i]-a[i] for i in range(3))
                nx,ny,nz=(uy*vz-uz*vy,uz*vx-ux*vz,ux*vy-uy*vx)
                length=(nx*nx+ny*ny+nz*nz)**0.5 or 1.0
                normal=(nx/length,ny/length,nz/length)
                for vertex in tri:
                    positions.extend(vertex)
                    normals.extend(normal)
                    indices.append(len(indices))
            vertex_count=len(indices)
            position_bytes=struct.pack("<"+"f"*len(positions),*positions)
            normal_bytes=struct.pack("<"+"f"*len(normals),*normals)
            index_bytes=struct.pack("<"+"H"*len(indices),*indices)
            pos_view=add_buffer(position_bytes,34962)
            norm_view=add_buffer(normal_bytes,34962)
            index_view=add_buffer(index_bytes,34963)
            mins=[min(positions[i::3]) for i in range(3)]
            maxs=[max(positions[i::3]) for i in range(3)]
            pos_accessor=len(accessors)
            accessors.append({"bufferView":pos_view,"componentType":5126,"count":vertex_count,"type":"VEC3","min":mins,"max":maxs})
            norm_accessor=len(accessors)
            accessors.append({"bufferView":norm_view,"componentType":5126,"count":vertex_count,"type":"VEC3"})
            index_accessor=len(accessors)
            accessors.append({"bufferView":index_view,"componentType":5123,"count":len(indices),"type":"SCALAR","min":[0],"max":[max(indices)]})
            primitives.append({"attributes":{"POSITION":pos_accessor,"NORMAL":norm_accessor},"indices":index_accessor,"material":materials.index(material_name),"mode":4})
        meshes.append({"name":name,"primitives":primitives})
        nodes.append({"name":name,"mesh":len(meshes)-1,"translation":list(translation)})

    document={
        "asset":{"version":"2.0","generator":"Autonomous AI Economy original procedural mesh builder"},
        "scene":0,"scenes":[{"nodes":list(range(len(nodes)))}],
        "nodes":nodes,"meshes":meshes,
        "materials":[{"name":name,"pbrMetallicRoughness":{k:v for k,v in props.items() if k in ("baseColorFactor","metallicFactor","roughnessFactor")},**({"emissiveFactor":props["emissiveFactor"]} if "emissiveFactor" in props else {})} for name,props in MATERIALS.items()],
        "buffers":[{"byteLength":len(binary)}],
        "bufferViews":buffer_views,"accessors":accessors,
    }
    json_bytes=json.dumps(document,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    while len(json_bytes)%4:
        json_bytes+=b" "
    while len(binary)%4:
        binary.append(0)
    total=12+8+len(json_bytes)+8+len(binary)
    return struct.pack("<4sII",b"glTF",2,total)+struct.pack("<I4s",len(json_bytes),b"JSON")+json_bytes+struct.pack("<I4s",len(binary),b"BIN\x00")+bytes(binary)


def _read_glb_summary(data):
    if len(data)<20:
        raise ValueError("GLB is truncated")
    magic,version,total=struct.unpack_from("<4sII",data,0)
    if magic!=b"glTF" or version!=2 or total!=len(data):
        raise ValueError("invalid GLB header")
    json_length,chunk_type=struct.unpack_from("<I4s",data,12)
    if chunk_type!=b"JSON":
        raise ValueError("GLB JSON chunk is missing")
    doc=json.loads(data[20:20+json_length].decode("utf-8").rstrip(" "))
    triangle_count=0
    vertex_count=0
    for mesh in doc.get("meshes",[]):
        for primitive in mesh.get("primitives",[]):
            accessor=doc["accessors"][primitive["indices"]]
            triangle_count+=accessor["count"]//3
            vertex_count+=doc["accessors"][primitive["attributes"]["POSITION"]]["count"]
    if not doc.get("nodes") or not doc.get("meshes") or not triangle_count:
        raise ValueError("GLB contains no renderable mesh geometry")
    return {"nodes":len(doc["nodes"]),"meshes":len(doc["meshes"]),"triangles":triangle_count,"vertices":vertex_count,"materials":len(doc.get("materials",[]))}


def build_game_asset_pack(output: str | Path) -> dict:
    """Generate individual GLB assets, a combined preview, Godot scene and manifest."""
    assets_dir=Path("assets")
    files=[]
    summaries={}
    objects=[]
    for index,(slug,name,builder) in enumerate(_ASSETS):
        parts=builder()
        data=_glb([(name,parts,(0,0,0))])
        summaries[slug]=_read_glb_summary(data)
        files.append((f"assets/{slug}.glb",data))
        objects.append((name,parts,((index % 5 - 2)*2.8,0,(index // 5 - 0.5)*5.0)))
    preview=_glb(objects)
    summaries["preview"]=_read_glb_summary(preview)
    files.append(("preview.glb",preview))
    scene_lines=[f"[gd_scene load_steps={len(_ASSETS)+4} format=3]",""]
    for i,(slug,name,_) in enumerate(_ASSETS,1):
        scene_lines.append(f'[ext_resource type="PackedScene" path="res://assets/{slug}.glb" id="{i}"]')
    scene_lines.extend([
        "",
        '[sub_resource type="Environment" id="Environment_default"]',
        "background_mode = 1",
        "background_color = Color(0.025, 0.035, 0.055, 1)",
        "ambient_light_source = 2",
        "ambient_light_color = Color(0.45, 0.52, 0.68, 1)",
        "ambient_light_energy = 0.75","",
        '[sub_resource type="PlaneMesh" id="PlaneMesh_floor"]',
        "size = Vector2(24, 22)","",
        '[sub_resource type="StandardMaterial3D" id="StandardMaterial3D_floor"]',
        "albedo_color = Color(0.06, 0.08, 0.12, 1)",
        "roughness = 0.92","",
        '[node name="MOBAObjectiveProps" type="Node3D"]',"",
        '[node name="WorldEnvironment" type="WorldEnvironment" parent="."]',
        'environment = SubResource("Environment_default")',"",
        '[node name="KeyLight" type="DirectionalLight3D" parent="."]',
        "rotation_degrees = Vector3(-48, -32, 0)",
        "light_energy = 1.6",
        "shadow_enabled = true","",
        '[node name="Camera3D" type="Camera3D" parent="."]',
        "position = Vector3(0, 12.5, 23.0)",
        "rotation_degrees = Vector3(-28, 0, 0)",
        "current = true","",
        '[node name="Floor" type="MeshInstance3D" parent="."]',
        "position = Vector3(0, -0.04, 0)",
        'mesh = SubResource("PlaneMesh_floor")',
        'material_override = SubResource("StandardMaterial3D_floor")',"",
    ])
    for i,(slug,name,_) in enumerate(_ASSETS,1):
        node_name="".join(part.title() for part in slug.split("_"))
        x=((i-1) % 5 - 2)*2.8
        scene_lines.extend([f'[node name="{node_name}" parent="." instance=ExtResource("{i}")]',
                           f"position = Vector3({x:.2f}, 0, {(i-1)//5*5.0-2.5:.2f})",""])
    files.append(("godot/MOBAObjectiveProps.tscn",("\n".join(scene_lines)+"\n").encode("utf-8")))
    project_config="""config_version=5

[application]
config/name="MOBA Objective Props"
run/main_scene="res://godot/MOBAObjectiveProps.tscn"
config/features=PackedStringArray("4.7", "GL Compatibility")

[rendering]
renderer/rendering_method="gl_compatibility"
renderer/rendering_method.mobile="gl_compatibility"
"""
    files.append(("project.godot",project_config.encode("utf-8")))
    readme="""# MOBA Objective Props — Low-Poly 3D Asset Pack

Ten original, procedurally generated low-poly fantasy props for game prototypes:
- Mana Crystal
- Health Vial
- Rune Altar
- Supply Chest
- Ancient Coin Stack
- Arcane Ward Totem
- Battle Banner
- Jungle Brazier
- Lane Turret
- Rune Gate

## Formats and use
- Individual glTF 2.0 binary models (.glb), one object per file.
- Combined preview scene (preview.glb).
- A complete Godot 4.7 project (project.godot) with a lit demo scene, camera and floor.
- Open the extracted folder containing project.godot directly in Godot 4.7 or later and press F6/F5 to preview the scene.

The assets use simple PBR materials and flat-shaded polygon geometry. No external textures, scripts, plugins, fonts, or network calls are required.

## Technical scope
These are low-poly static props, not rigged characters. They include no animation, collision shapes, LODs, or platform-specific import presets. Review scale and materials in your target engine before production use. The included Godot project is a layout/demo scene, not a complete game.

All meshes are original procedural geometry created for this pack. The pack is not affiliated with Mobile Legends, Unity, Godot, or any game publisher.
"""

    license_text="""# License

Original project-created 3D mesh assets. The purchaser may use and modify the assets in personal and commercial games and interactive projects. The assets may not be resold, redistributed, sublicensed, or shared as standalone source files or as a competing asset pack. No trademark or affiliation rights are granted. This is a draft license; confirm marketplace and local legal requirements before sale.
"""
    files.append(("LICENSE.txt",license_text.encode("utf-8")))
    listing_copy="""# MOBA Objective Props — draft marketplace listing

**Status:** product candidate; not published and not commercially validated.

## Title

MOBA Objective Props — 10 Low-Poly Fantasy 3D Models for Godot

## Description

Add ten original low-poly fantasy props to a game prototype, including objectives, consumables, map utilities, and defensive structures. Each asset is supplied as an individual glTF 2.0 binary model (.glb), with a combined preview scene and a Godot 4 demo scene.

## Included

- 10 individual GLB models
- 1 combined preview GLB
- 1 complete Godot 4.7+ project with a camera-lit demo scene, floor and project.godot
- PBR material definitions
- README and draft license

## Technical limits

Static low-poly props only. No rigging, animation, collision shapes, LODs, texture maps, or platform-specific import presets. Open the included project.godot in Godot 4.7 or later and test the scene. Adjust scale/materials in your target engine. This is not a complete game or a character pack.

## AI disclosure

The mesh geometry and packaging were procedurally generated with AI-assisted development. Confirm marketplace disclosure requirements before publishing.

## Price

No price or willingness-to-pay has been validated. Compare competing asset packs and test a low one-time price only after product QA and marketplace approval.

## Claims not to make

Do not claim sales, reviews, engine certification, affiliation with Mobile Legends or any publisher, or guaranteed compatibility with all engine versions.
"""
    files.append(("listing-copy.md",listing_copy.encode("utf-8")))
    manifest={"schema":"aae.game-asset-pack/v1","product":PRODUCT_SLUG,"asset_format":"glTF 2.0 binary (.glb)","assets":summaries,"files":[{"path":name,"size_bytes":len(data),"sha256":hashlib.sha256(data).hexdigest()} for name,data in files],"notice":"Procedural geometry pack; manifest verifies file integrity, not market demand, engine QA, or revenue."}
    files.append(("manifest.json",(json.dumps(manifest,indent=2,sort_keys=True)+"\n").encode("utf-8")))
    target=Path(output)
    target.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(prefix=f".{target.name}.",suffix=".tmp",dir=target.parent)
    os.close(fd)
    try:
        with zipfile.ZipFile(tmp,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
            for name,data in files:
                safe=PurePosixPath(name)
                if safe.is_absolute() or ".." in safe.parts:
                    raise ValueError("unsafe archive path")
                info=zipfile.ZipInfo(name,date_time=(2020,1,1,0,0,0))
                info.compress_type=zipfile.ZIP_DEFLATED
                info.external_attr=0o100644<<16
                archive.writestr(info,data)
        os.replace(tmp,target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return {"path":str(target),"size_bytes":target.stat().st_size,"sha256":hashlib.sha256(target.read_bytes()).hexdigest(),"manifest":manifest,"published":False,"uploaded":False,"sales_verified":False}


class GameAssetBuilderAgent:
    """Deterministic production agent for original procedural 3D game props.

    The agent ID is an internal attribution label, not a legal identity or
    cryptographic participant credential. Its output is still subject to QA.
    """

    agent_id = "game-asset-builder"
    role = "procedural 3D game asset production"

    def build(self, output: str | Path) -> dict:
        return build_game_asset_pack(output)


def main() -> int:
    parser=argparse.ArgumentParser(description="Build the MOBA Objective Props GLB asset pack")
    sub=parser.add_subparsers(dest="command",required=True)
    build=sub.add_parser("build",help="generate the GLB assets and deterministic ZIP")
    build.add_argument("--output",type=Path,default=Path("dist/moba-objective-props.zip"))
    args=parser.parse_args()
    agent = GameAssetBuilderAgent()
    print(json.dumps(agent.build(args.output),indent=2,sort_keys=True))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
