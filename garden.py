#!/usr/bin/env python3
import argparse, base64, hashlib, json, os, time
from io import BytesIO
from typing import Dict, Any, List, Tuple, Optional

STATE_PATH = os.path.expanduser("~/.local/state/terminal-garden/garden.json")
ASSETS_DIR = os.path.expanduser("~/.local/state/terminal-garden/assets/pixel")

# Per-instance plant sprites:
#   ASSETS_DIR/plants/<plant_id>/<stage>.png
# Stones:
#   ASSETS_DIR/tiles/stone/<ground_seed>.png
# (Optional fallback, if you ever want it):
#   ASSETS_DIR/global/<species>/<stage>.png

SPECIES_STAGES = {
    "fern": [
        (0,     "seed"),
        (60,    "sprout"),
        (5*60,  "leafy"),
        (20*60, "mature"),
    ],
    "flower": [
        (0,     "seed"),
        (60,    "sprout"),
        (8*60,  "bud"),
        (25*60, "bloom"),
    ],
}

GROUND_GLYPH = {"soil": "  ", "stone": "⬚ ", "path": "··"}


# ------------------ util ------------------
def stable_u32(*parts: Any) -> int:
    h = hashlib.sha256()
    for p in parts:
        h.update(str(p).encode("utf-8"))
        h.update(b"|")
    return int.from_bytes(h.digest()[:4], "big")

def plant_id_for(species: str, x: int, y: int, planted_at: int, seed: int) -> str:
    h = hashlib.sha1(f"{species}|{x}|{y}|{planted_at}|{seed}".encode("utf-8")).hexdigest()
    return h[:12]

def idx(x: int, y: int, w: int) -> int:
    return y * w + x


# ------------------ persistence ------------------
def load_state() -> Dict[str, Any]:
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(st: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)


# ------------------ growth ------------------
def plant_stage(plant: Dict[str, Any], now: int) -> str:
    species = plant["species"]
    planted_at = plant["planted_at"]
    age = max(0, now - planted_at)
    stages = SPECIES_STAGES.get(species, [(0, "unknown")])
    s = stages[0][1]
    for t, name in stages:
        if age >= t:
            s = name
    return s


# ------------------ deps ------------------
def _require_pil_and_term_image():
    try:
        from PIL import Image
    except Exception as e:
        raise SystemExit("Missing Pillow. Install: python3 -m pip install --user pillow") from e
    try:
        from term_image.image import AutoImage
    except Exception as e:
        raise SystemExit("Missing term-image. Install: python3 -m pip install --user term-image") from e
    return Image, AutoImage

def _require_openai_client():
    try:
        from openai import OpenAI
    except Exception as e:
        raise SystemExit("Missing openai. Install: python3 -m pip install --user openai") from e
    return OpenAI


# ------------------ asset paths ------------------
def plant_sprite_path(plant_id: str, stage: str) -> str:
    return os.path.join(ASSETS_DIR, "plants", plant_id, f"{stage}.png")

def stone_tile_path(seed: int) -> str:
    return os.path.join(ASSETS_DIR, "tiles", "stone", f"{seed}.png")

def load_rgba(Image, path: str) -> Optional["Image.Image"]:
    if not os.path.exists(path):
        return None
    im = Image.open(path)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    return im


# ------------------ rendering (kitty/TGP via term-image) ------------------
def _colors_for_ground(ground: str) -> Tuple[int, int, int]:
    if ground == "path":
        return (150, 150, 150)
    return (88, 60, 35)  # soil default

def render_text(st: Dict[str, Any]) -> str:
    w, h = st["width"], st["height"]
    now = int(time.time())
    out: List[str] = []
    out.append(f"Terminal Garden ({w}x{h})  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}")
    out.append("+" + "-" * (w * 2) + "+")
    for y in range(h):
        row = ["|"]
        for x in range(w):
            cell = st["cells"][idx(x, y, w)]
            if cell.get("plant"):
                species = cell["plant"]["species"]
                stage = plant_stage(cell["plant"], now)
                glyph = {
                    ("fern", "seed"): "·", ("fern", "sprout"): "˘", ("fern", "leafy"): "☘", ("fern", "mature"): "♣",
                    ("flower", "seed"): "·", ("flower", "sprout"): "˘", ("flower", "bud"): "✿", ("flower", "bloom"): "❀",
                }.get((species, stage), "?")
                row.append(glyph + " ")
            else:
                row.append(GROUND_GLYPH.get(cell.get("ground", "soil"), "  "))
        row.append("|")
        out.append("".join(row))
    out.append("+" + "-" * (w * 2) + "+")
    return "\n".join(out)

def render_kitty(st: Dict[str, Any], cell_px: int = 32, clear: bool = True) -> None:
    Image, AutoImage = _require_pil_and_term_image()
    w, h = st["width"], st["height"]
    now = int(time.time())

    canvas = Image.new("RGBA", (w * cell_px, h * cell_px), (0, 0, 0, 255))
    resized_cache: Dict[str, Optional["Image.Image"]] = {}

    for y in range(h):
        for x in range(w):
            cell = st["cells"][idx(x, y, w)]
            x0, y0 = x * cell_px, y * cell_px

            ground = cell.get("ground", "soil")

            # Ground base
            if ground == "stone":
                # stone uses generated tile if present; otherwise draw soil fallback
                seed = int(cell.get("ground_seed", 0))
                key = f"stone:{seed}:{cell_px}"
                spr = resized_cache.get(key)
                if key not in resized_cache:
                    base = load_rgba(Image, stone_tile_path(seed))
                    spr = base.resize((cell_px, cell_px), resample=Image.NEAREST) if base else None
                    resized_cache[key] = spr
                if spr is not None:
                    canvas.alpha_composite(spr, (x0, y0))
                else:
                    bg = _colors_for_ground("soil")
                    tile = Image.new("RGBA", (cell_px, cell_px), (bg[0], bg[1], bg[2], 255))
                    canvas.alpha_composite(tile, (x0, y0))
            else:
                bg = _colors_for_ground(ground)
                tile = Image.new("RGBA", (cell_px, cell_px), (bg[0], bg[1], bg[2], 255))
                canvas.alpha_composite(tile, (x0, y0))

            # Plant overlay (instance-specific sprite)
            plant = cell.get("plant")
            if plant:
                stage = plant_stage(plant, now)
                pid = plant["id"]
                ppath = plant_sprite_path(pid, stage)
                key = f"plant:{pid}:{stage}:{cell_px}"
                spr = resized_cache.get(key)
                if key not in resized_cache:
                    base = load_rgba(Image, ppath)
                    spr = base.resize((cell_px, cell_px), resample=Image.NEAREST) if base else None
                    resized_cache[key] = spr
                if spr is not None:
                    canvas.alpha_composite(spr, (x0, y0))

    if clear:
        print("\x1b[2J\x1b[H", end="")

    print(AutoImage(canvas.convert("RGB")))


# ------------------ AI generation ------------------
def _openai_image_png_bytes(prompt: str, model: str, quality: str) -> bytes:
    OpenAI = _require_openai_client()
    client = OpenAI()

    result = client.images.generate(
        model=model,
        prompt=prompt,
        size="1024x1024",
        quality=quality,
        output_format="png",
        background="transparent",
    )
    b64 = result.data[0].b64_json
    return base64.b64decode(b64)

def _save_rgba(Image, im: "Image.Image", path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    im.save(path, format="PNG")

def _plant_sheet_prompt(style: str, species: str, plant_id: str, seed: int,
                        stages: List[str], tile_px_hint: int) -> str:
    # We generate 2x2 sheet for 4 stages (fern/flower). For flower, stages are seed,sprout,bud,bloom.
    stages_str = ", ".join(stages)
    order = (
        f"Top-left: {stages[0]}\nTop-right: {stages[1]}\n"
        f"Bottom-left: {stages[2]}\nBottom-right: {stages[3]}"
    )

    return f"""
Create a 2x2 pixel-art sprite sheet PNG with TRANSPARENT background.

GOAL:
- Depict the SAME unique individual plant across growth stages (consistent palette, silhouette language).
- This plant is uniquely identified by: plant_id={plant_id}, variation_seed={seed}.

STYLE:
- Pixel art, crisp, limited palette (<=16 colors).
- Clean 1px outlines where appropriate.
- Top-down or slight isometric, but consistent across all tiles.
- No text, no border, no ground tile, no pot, no UI.

SUBJECT:
- Species: {species}
- Stages: {stages_str}

LAYOUT:
- Exactly 2 rows x 2 columns. All tiles same size.
- Arrange as:
{order}

FRAMING:
- Single object per tile (just the plant).
- Centered, with a little padding so it reads well when downscaled.
- Each tile should look good when downscaled to ~{tile_px_hint}x{tile_px_hint} pixels.

ART DIRECTION:
{style}
""".strip()

def _stone_prompt(style: str, seed: int, tile_px_hint: int) -> str:
    return f"""
Create a single pixel-art TILE PNG with TRANSPARENT background.

SUBJECT:
- A stepping stone / walking stone tile suitable for a garden path.
- Variation seed: {seed} (use it to vary cracks, shape, moss pattern, etc.).

STYLE:
- Pixel art, crisp, limited palette (<=16 colors).
- Top-down.
- No text, no border.
- Stone centered; tile reads clearly when downscaled to ~{tile_px_hint}x{tile_px_hint}.

IMPORTANT:
- This should be a ground tile (stone surface), NOT a plant.
- Keep alpha around the edges (stone doesn’t have to fill the whole tile).

ART DIRECTION:
{style}
""".strip()

def generate_plant_instance_sprites(plant: Dict[str, Any], sprite_px: int,
                                   model: str, quality: str, style: str) -> None:
    Image, _ = _require_pil_and_term_image()
    species = plant["species"]
    pid = plant["id"]
    seed = plant["seed"]

    stages = [name for _, name in SPECIES_STAGES[species]]
    if len(stages) != 4:
        raise SystemExit(f"Expected 4 stages for {species}, got {len(stages)}")

    # If all stage files exist, skip
    out_paths = [plant_sprite_path(pid, st) for st in stages]
    if all(os.path.exists(p) for p in out_paths):
        return

    prompt = _plant_sheet_prompt(
        style=style, species=species, plant_id=pid, seed=seed,
        stages=stages, tile_px_hint=sprite_px
    )
    png_bytes = _openai_image_png_bytes(prompt, model=model, quality=quality)
    sheet = Image.open(BytesIO(png_bytes)).convert("RGBA")

    # Slice into 2x2
    W, H = sheet.size
    tw, th = W // 2, H // 2
    tiles = [
        sheet.crop((0, 0, tw, th)),          # TL
        sheet.crop((tw, 0, W, th)),          # TR
        sheet.crop((0, th, tw, H)),          # BL
        sheet.crop((tw, th, W, H)),          # BR
    ]

    for st, tile, outp in zip(stages, tiles, out_paths):
        final = tile.resize((sprite_px, sprite_px), resample=Image.NEAREST)
        _save_rgba(Image, final, outp)

def generate_stone_tile(seed: int, tile_px: int, model: str, quality: str, style: str) -> None:
    Image, _ = _require_pil_and_term_image()
    outp = stone_tile_path(seed)
    if os.path.exists(outp):
        return

    prompt = _stone_prompt(style=style, seed=seed, tile_px_hint=tile_px)
    png_bytes = _openai_image_png_bytes(prompt, model=model, quality=quality)
    im = Image.open(BytesIO(png_bytes)).convert("RGBA")
    im = im.resize((tile_px, tile_px), resample=Image.NEAREST)
    _save_rgba(Image, im, outp)


# ------------------ commands ------------------
def cmd_init(args: argparse.Namespace) -> None:
    w, h = args.width, args.height
    base_seed = stable_u32("garden", "base", int(time.time()))
    cells = []
    for y in range(h):
        for x in range(w):
            cells.append({
                "ground": "soil",
                "ground_seed": stable_u32(base_seed, "ground", x, y),
                "plant": None,
            })
    st = {"width": w, "height": h, "base_seed": base_seed, "cells": cells}
    save_state(st)

def cmd_set(args: argparse.Namespace) -> None:
    st = load_state()
    w, h = st["width"], st["height"]
    if not (0 <= args.x < w and 0 <= args.y < h):
        raise SystemExit("x/y out of bounds")

    cell = st["cells"][idx(args.x, args.y, w)]

    if args.ground:
        cell["ground"] = args.ground
        # ensure ground_seed exists for deterministic stone generation
        if "ground_seed" not in cell:
            base_seed = int(st.get("base_seed", stable_u32("garden", "base", 0)))
            cell["ground_seed"] = stable_u32(base_seed, "ground", args.x, args.y)

    if args.plant:
        planted_at = int(time.time())
        seed = stable_u32(st.get("base_seed", 0), "plant", args.plant, args.x, args.y, planted_at)
        pid = plant_id_for(args.plant, args.x, args.y, planted_at, seed)
        cell["plant"] = {"species": args.plant, "planted_at": planted_at, "seed": seed, "id": pid}

    if args.clear_plant:
        cell["plant"] = None

    save_state(st)

def cmd_show(args: argparse.Namespace) -> None:
    st = load_state()
    if args.kitty:
        render_kitty(st, cell_px=args.cell_px, clear=not args.no_clear)
    else:
        print(render_text(st))

def cmd_assets_generate(args: argparse.Namespace) -> None:
    st = load_state()
    sprite_px = args.sprite_px
    model = args.model
    quality = args.quality
    style = args.style

    # scan
    plants: List[Dict[str, Any]] = []
    stone_seeds: List[int] = []

    w, h = st["width"], st["height"]
    for y in range(h):
        for x in range(w):
            cell = st["cells"][idx(x, y, w)]
            if args.plants and cell.get("plant"):
                plants.append(cell["plant"])
            if args.stones and cell.get("ground") == "stone":
                stone_seeds.append(int(cell.get("ground_seed", stable_u32("stone", x, y))))

    # de-dupe stones
    stone_seeds = sorted(set(stone_seeds))

    if args.dry_run:
        if args.plants:
            print(f"Would generate plant instances: {len(plants)}")
        if args.stones:
            print(f"Would generate stone tiles: {len(stone_seeds)}")
        return

    if args.plants:
        print(f"Generating plant instance sprites: {len(plants)} (each is its own set)")
        for i, plant in enumerate(plants, 1):
            print(f"[{i}/{len(plants)}] plant_id={plant['id']} species={plant['species']}")
            generate_plant_instance_sprites(
                plant=plant, sprite_px=sprite_px, model=model, quality=quality, style=style
            )

    if args.stones:
        print(f"Generating stone tiles: {len(stone_seeds)}")
        for i, seed in enumerate(stone_seeds, 1):
            print(f"[{i}/{len(stone_seeds)}] stone_seed={seed}")
            generate_stone_tile(
                seed=seed, tile_px=sprite_px, model=model, quality=quality, style=style
            )

    print(f"Done. Assets in: {ASSETS_DIR}")

def main() -> None:
    p = argparse.ArgumentParser(prog="garden")
    sp = p.add_subparsers(required=True)

    pi = sp.add_parser("init")
    pi.add_argument("width", type=int)
    pi.add_argument("height", type=int)
    pi.set_defaults(fn=cmd_init)

    ps = sp.add_parser("set")
    ps.add_argument("x", type=int)
    ps.add_argument("y", type=int)
    ps.add_argument("--ground", choices=["soil", "stone", "path"])
    ps.add_argument("--plant", choices=sorted(SPECIES_STAGES.keys()))
    ps.add_argument("--clear-plant", action="store_true")
    ps.set_defaults(fn=cmd_set)

    pv = sp.add_parser("show")
    pv.add_argument("--kitty", action="store_true")
    pv.add_argument("--cell-px", type=int, default=32)
    pv.add_argument("--no-clear", action="store_true")
    pv.set_defaults(fn=cmd_show)

    pg = sp.add_parser("assets-generate")
    pg.add_argument("--model", default="gpt-image-1")
    pg.add_argument("--quality", default="low", choices=["low", "medium", "high", "auto"])
    pg.add_argument("--sprite-px", type=int, default=16, help="Base tile/sprite resolution stored on disk.")
    pg.add_argument("--plants", action="store_true", help="Generate missing per-plant instance sprites.")
    pg.add_argument("--stones", action="store_true", help="Generate missing stone ground tiles.")
    pg.add_argument("--dry-run", action="store_true")
    pg.add_argument(
        "--style",
        default="Cozy pixel-art garden sprites. Consistent palette, readable silhouettes, minimal noise.",
        help="Global art direction (keep constant to make the set cohesive)."
    )
    pg.set_defaults(fn=cmd_assets_generate)

    args = p.parse_args()

    # default: generate both if neither flag specified
    if getattr(args, "fn", None) is cmd_assets_generate:
        if not args.plants and not args.stones:
            args.plants = True
            args.stones = True

    args.fn(args)

if __name__ == "__main__":
    main()
