#!/usr/bin/env python3
import argparse, json, os, time
from typing import Dict, Any, List, Tuple, Optional

STATE_PATH = os.path.expanduser("~/.local/state/terminal-garden/garden.json")
SPRITES_DIR = os.path.expanduser("~/.local/state/terminal-garden/sprites/pixel")  # style="pixel"

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

# ---------- pixel-art starter pack (generated once) ----------
def _putpx(img, x: int, y: int, rgba: Tuple[int, int, int, int]) -> None:
    if 0 <= x < img.size[0] and 0 <= y < img.size[1]:
        img.putpixel((x, y), rgba)

def _disk(img, cx: int, cy: int, r: int, rgba: Tuple[int, int, int, int]) -> None:
    rr = r * r
    for y in range(cy - r, cy + r + 1):
        for x in range(cx - r, cx + r + 1):
            if (x - cx) * (x - cx) + (y - cy) * (y - cy) <= rr:
                _putpx(img, x, y, rgba)

def _line(img, x0: int, y0: int, x1: int, y1: int, rgba: Tuple[int, int, int, int]) -> None:
    # simple Bresenham
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    x, y = x0, y0
    while True:
        _putpx(img, x, y, rgba)
        if x == x1 and y == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x += sx
        if e2 <= dx:
            err += dx
            y += sy

def make_sprite(Image, species: str, stage: str, size: int) -> "Image.Image":
    # transparent sprite
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # palette
    soil_brown = (60, 40, 20, 255)
    green1 = (60, 170, 80, 255)
    green2 = (30, 120, 60, 255)
    pink = (230, 90, 150, 255)
    yellow = (245, 225, 90, 255)

    cx, cy = size // 2, size // 2

    if stage == "seed":
        _disk(img, cx, cy + 2, max(1, size // 10), soil_brown)
        return img

    if stage == "sprout":
        _line(img, cx, size - 3, cx, cy, green2)
        _disk(img, cx - 2, cy - 1, max(1, size // 10), green1)
        _disk(img, cx + 2, cy - 1, max(1, size // 10), green1)
        return img

    if species == "fern":
        if stage in ("leafy", "mature"):
            h = size // 2 if stage == "leafy" else (size * 2) // 3
            _line(img, cx, size - 3, cx, size - 3 - h, green2)
            # fronds
            for i in range(1, 6):
                y = size - 3 - (i * h) // 6
                span = (i * size) // (10 if stage == "leafy" else 8)
                _line(img, cx, y, cx - span, y - 1, green1)
                _line(img, cx, y, cx + span, y - 1, green1)
            return img

    if species == "flower":
        if stage == "bud":
            _line(img, cx, size - 3, cx, cy + 2, green2)
            _disk(img, cx, cy, max(2, size // 8), pink)
            return img
        if stage == "bloom":
            _line(img, cx, size - 3, cx, cy + 2, green2)
            pr = max(2, size // 6)
            # petals (simple plus + diagonals)
            for dx, dy in [(0, -pr), (pr, 0), (0, pr), (-pr, 0), (pr, -pr), (-pr, -pr)]:
                _disk(img, cx + dx, cy + dy, pr, pink)
            _disk(img, cx, cy, max(2, pr - 1), yellow)
            return img

    # unknown fallback (red box)
    for x in range(size):
        _putpx(img, x, 0, (255, 0, 0, 255))
        _putpx(img, x, size - 1, (255, 0, 0, 255))
    for y in range(size):
        _putpx(img, 0, y, (255, 0, 0, 255))
        _putpx(img, size - 1, y, (255, 0, 0, 255))
    return img

def cmd_sprites_init(args: argparse.Namespace) -> None:
    Image, _, _ = _require_pil_and_term_image()
    size = args.size
    overwrite = args.overwrite

    for species, stages in SPECIES.items():
        for _, stage in stages:
            path = sprite_path(species, stage)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if (not overwrite) and os.path.exists(path):
                continue
            spr = make_sprite(Image, species, stage, size)
            spr.save(path, format="PNG")

    print(f"Sprites ready in: {SPRITES_DIR}")
    print("Replace any PNG with your own AI-generated pixel art later (keep transparency).")

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

    # work in RGBA so we can alpha-composite sprites cleanly
    canvas = Image.new("RGBA", (w * cell_px, h * cell_px), (0, 0, 0, 255))

    # resized sprite cache for this render
    resized: Dict[Tuple[str, str], "Image.Image"] = {}

    for y in range(h):
        for x in range(w):
            cell = st["cells"][idx(x, y, w)]
            ground = cell.get("ground", "soil")
            x0, y0 = x * cell_px, y * cell_px

            # ground tile
            bg = _colors_for_ground(ground)
            tile = Image.new("RGBA", (cell_px, cell_px), (bg[0], bg[1], bg[2], 255))
            canvas.alpha_composite(tile, (x0, y0))

            # plant sprite
            if cell.get("plant") is not None:
                species = cell["plant"]["species"]
                stage = plant_stage(cell["plant"], now)
                key = (species, stage)
                spr = resized.get(key)
                if spr is None:
                    base = load_sprite(Image, species, stage)
                    if base is None:
                        # missing sprite: just skip (or you could draw a marker)
                        spr = None
                    else:
                        spr = base.resize((cell_px, cell_px), resample=Image.NEAREST)
                    resized[key] = spr  # cache None too
                if spr is not None:
                    canvas.alpha_composite(spr, (x0, y0))

    if clear:
        print("\x1b[2J\x1b[H", end="")

    # AutoImage wants RGB nicely; flatten alpha onto black (or keep as-is if it handles RGBA)
    out_img = canvas.convert("RGB")
    print(AutoImage(out_img))

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

    psp = sp.add_parser("sprites-init")
    psp.add_argument("--size", type=int, default=16, help="Sprite base size in pixels (recommended: 16 or 24).")
    psp.add_argument("--overwrite", action="store_true", help="Overwrite existing PNGs.")
    psp.set_defaults(fn=cmd_sprites_init)

    pv = sp.add_parser("show")
    pv.add_argument("--kitty", action="store_true", help="Render as an image using Kitty/TGP.")
    pv.add_argument("--cell-px", type=int, default=32, help="Pixel size per cell for --kitty (use multiples of sprite size).")
    pv.add_argument("--no-clear", action="store_true", help="Don't clear screen before drawing in --kitty mode.")
    pv.set_defaults(fn=cmd_show)

    args = p.parse_args()
    args.fn(args)

if __name__ == "__main__":
    main()
