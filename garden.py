#!/usr/bin/env python3
import argparse, base64, json, os, time
from io import BytesIO
from typing import Dict, Any, List, Tuple, Optional

STATE_PATH = os.path.expanduser("~/.local/state/terminal-garden/garden.json")
SPRITES_DIR = os.path.expanduser("~/.local/state/terminal-garden/sprites/pixel")

SPECIES = {
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

# ---------- persistence ----------
def load_state() -> Dict[str, Any]:
    with open(STATE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(st: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2, sort_keys=True)
    os.replace(tmp, STATE_PATH)

def idx(x: int, y: int, w: int) -> int:
    return y * w + x

# ---------- growth ----------
def plant_stage(plant: Dict[str, Any], now: int) -> str:
    species = plant["species"]
    planted_at = plant["planted_at"]
    age = max(0, now - planted_at)
    stages = SPECIES.get(species, [(0, "unknown")])
    s = stages[0][1]
    for t, name in stages:
        if age >= t:
            s = name
    return s

# ---------- text render ----------
def render_text(st: Dict[str, Any]) -> str:
    w, h = st["width"], st["height"]
    now = int(time.time())
    out: List[str] = []
    out.append(f"Terminal Garden  ({w}x{h})  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}")
    out.append("+" + "-" * (w * 2) + "+")
    for y in range(h):
        row = ["|"]
        for x in range(w):
            cell = st["cells"][idx(x, y, w)]
            if cell.get("plant") is not None:
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

# ---------- deps ----------
def _require_pil_and_term_image():
    try:
        from PIL import Image, ImageDraw
    except Exception as e:
        raise SystemExit("Missing Pillow. Install: python3 -m pip install --user pillow") from e
    try:
        from term_image.image import AutoImage
    except Exception as e:
        raise SystemExit("Missing term-image. Install: python3 -m pip install --user term-image") from e
    return Image, ImageDraw, AutoImage

# ---------- sprite cache ----------
def sprite_path(species: str, stage: str) -> str:
    return os.path.join(SPRITES_DIR, species, f"{stage}.png")

def load_sprite(Image, species: str, stage: str) -> Optional["Image.Image"]:
    path = sprite_path(species, stage)
    if not os.path.exists(path):
        return None
    im = Image.open(path)
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    return im

def list_required_sprites() -> List[Tuple[str, str]]:
    req: List[Tuple[str, str]] = []
    for sp, stages in SPECIES.items():
        for _, st in stages:
            req.append((sp, st))
    return req

# ---------- kitty/TGP render via Pillow + term-image ----------
def _colors_for_ground(ground: str) -> Tuple[int, int, int]:
    if ground == "stone":
        return (90, 90, 95)
    if ground == "path":
        return (150, 150, 150)
    return (88, 60, 35)  # soil

def render_kitty(st: Dict[str, Any], cell_px: int = 32, clear: bool = True) -> None:
    Image, _, AutoImage = _require_pil_and_term_image()

    w, h = st["width"], st["height"]
    now = int(time.time())

    canvas = Image.new("RGBA", (w * cell_px, h * cell_px), (0, 0, 0, 255))
    resized: Dict[Tuple[str, str], Optional["Image.Image"]] = {}

    for y in range(h):
        for x in range(w):
            cell = st["cells"][idx(x, y, w)]
            ground = cell.get("ground", "soil")
            x0, y0 = x * cell_px, y * cell_px

            bg = _colors_for_ground(ground)
            tile = Image.new("RGBA", (cell_px, cell_px), (bg[0], bg[1], bg[2], 255))
            canvas.alpha_composite(tile, (x0, y0))

            if cell.get("plant") is not None:
                species = cell["plant"]["species"]
                stage = plant_stage(cell["plant"], now)
                key = (species, stage)

                spr = resized.get(key, None)
                if key not in resized:
                    base = load_sprite(Image, species, stage)
                    if base is None:
                        spr = None
                    else:
                        spr = base.resize((cell_px, cell_px), resample=Image.NEAREST)
                    resized[key] = spr

                if spr is not None:
                    canvas.alpha_composite(spr, (x0, y0))

    if clear:
        print("\x1b[2J\x1b[H", end="")

    print(AutoImage(canvas.convert("RGB")))

# ---------- AI sprite generation (OpenAI Images API) ----------
def _require_openai_client():
    try:
        from openai import OpenAI
    except Exception as e:
        raise SystemExit("Missing openai. Install: python3 -m pip install --user openai") from e
    return OpenAI

def sprite_prompt(style: str, species: str, stage: str, sprite_px: int) -> str:
    # Keep this prompt stable so all sprites match.
    # The API will generate a large image; we'll downscale to sprite_px.
    return f"""
Create a single pixel-art SPRITE for a terminal garden game.

STYLE:
- Pixel-art, clean, crisp, limited palette (<= 16 colors).
- 1px outline where appropriate.
- No text, no border, no shadow drop.
- Centered subject, fits fully inside the frame with a little padding.
- Transparent background (alpha).

SUBJECT:
- Species: {species}
- Growth stage: {stage}

FRAMING:
- Single object only (the plant), no ground tile, no pot, no UI elements.
- Sprite should still read well when downscaled to {sprite_px}x{sprite_px}.

Overall art direction: {style}
""".strip()

def generate_sprite_openai(species: str, stage: str, out_path: str, sprite_px: int,
                           model: str, quality: str, style: str) -> None:
    Image, _, _ = _require_pil_and_term_image()
    OpenAI = _require_openai_client()

    client = OpenAI()
    prompt = sprite_prompt(style=style, species=species, stage=stage, sprite_px=sprite_px)

    # GPT Image models return base64-encoded image data (b64_json). :contentReference[oaicite:3]{index=3}
    result = client.images.generate(
        model=model,
        prompt=prompt,
        size="1024x1024",
        quality=quality,
        output_format="png",
        background="transparent",
    )

    img_b64 = result.data[0].b64_json
    img_bytes = base64.b64decode(img_b64)

    im = Image.open(BytesIO(img_bytes)).convert("RGBA")
    # Downscale to sprite resolution with nearest-neighbor to preserve the pixel look
    im = im.resize((sprite_px, sprite_px), resample=Image.NEAREST)

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    im.save(out_path, format="PNG")

def cmd_sprites_generate(args: argparse.Namespace) -> None:
    req = list_required_sprites()
    todo: List[Tuple[str, str, str]] = []
    for species, stage in req:
        path = sprite_path(species, stage)
        if args.overwrite or (not os.path.exists(path)):
            todo.append((species, stage, path))

    if args.only:
        # args.only is a list like ["fern:leafy", "flower:bloom"]
        wanted = set(args.only)
        todo = [(sp, st, p) for (sp, st, p) in todo if f"{sp}:{st}" in wanted]

    if not todo:
        print("No sprites to generate (everything present).")
        return

    if args.dry_run:
        print("Would generate:")
        for sp, st, p in todo:
            print(f"  {sp}:{st} -> {p}")
        return

    print(f"Generating {len(todo)} sprites into: {SPRITES_DIR}")
    for i, (sp, st, p) in enumerate(todo, 1):
        print(f"[{i}/{len(todo)}] {sp}:{st}")
        try:
            generate_sprite_openai(
                species=sp,
                stage=st,
                out_path=p,
                sprite_px=args.sprite_px,
                model=args.model,
                quality=args.quality,
                style=args.style,
            )
        except Exception as e:
            print(f"  ERROR: {e}")
            if args.fail_fast:
                raise SystemExit(1)

    print("Done.")

# ---------- commands ----------
def cmd_init(args: argparse.Namespace) -> None:
    w, h = args.width, args.height
    st = {"width": w, "height": h, "cells": [{"ground": "soil", "plant": None} for _ in range(w * h)]}
    save_state(st)

def cmd_set(args: argparse.Namespace) -> None:
    st = load_state()
    w, h = st["width"], st["height"]
    if not (0 <= args.x < w and 0 <= args.y < h):
        raise SystemExit("x/y out of bounds")
    cell = st["cells"][idx(args.x, args.y, w)]
    if args.ground:
        cell["ground"] = args.ground
    if args.plant:
        cell["plant"] = {"species": args.plant, "planted_at": int(time.time())}
    if args.clear_plant:
        cell["plant"] = None
    save_state(st)

def cmd_show(args: argparse.Namespace) -> None:
    st = load_state()
    if args.kitty:
        render_kitty(st, cell_px=args.cell_px, clear=not args.no_clear)
    else:
        print(render_text(st))

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
    ps.add_argument("--plant", choices=sorted(SPECIES.keys()))
    ps.add_argument("--clear-plant", action="store_true")
    ps.set_defaults(fn=cmd_set)

    pv = sp.add_parser("show")
    pv.add_argument("--kitty", action="store_true", help="Render as an image using Kitty/TGP.")
    pv.add_argument("--cell-px", type=int, default=32, help="Pixel size per cell for --kitty.")
    pv.add_argument("--no-clear", action="store_true", help="Don't clear screen before drawing in --kitty mode.")
    pv.set_defaults(fn=cmd_show)

    pg = sp.add_parser("sprites-generate")
    pg.add_argument("--model", default="gpt-image-1", help="OpenAI image model (e.g., gpt-image-1).")
    pg.add_argument("--quality", default="low", choices=["low", "medium", "high", "auto"], help="Lower is cheaper + more sprite-like.")
    pg.add_argument("--sprite-px", type=int, default=16, help="Final sprite resolution (e.g., 16).")
    pg.add_argument("--overwrite", action="store_true", help="Regenerate sprites even if PNGs exist.")
    pg.add_argument("--dry-run", action="store_true", help="List what would be generated, then exit.")
    pg.add_argument("--fail-fast", action="store_true", help="Stop on first API error.")
    pg.add_argument(
        "--only",
        nargs="*",
        help='Generate only specific sprites, like: --only fern:leafy flower:bloom',
    )
    pg.add_argument(
        "--style",
        default="Cozy garden sprites. Consistent palette and silhouette language across all stages.",
        help="Global art-direction string to keep the set consistent.",
    )
    pg.set_defaults(fn=cmd_sprites_generate)

    args = p.parse_args()
    args.fn(args)

if __name__ == "__main__":
    main()
