#!/usr/bin/env python3
import argparse, json, os, time
from typing import Dict, Any, List, Tuple

STATE_PATH = os.path.expanduser("~/.local/state/terminal-garden/garden.json")

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
                # Simple mapping to single-glyph for MVP
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

# ---------- kitty/TGP render via Pillow + term-image ----------
def _require_pil_and_term_image():
    try:
        from PIL import Image, ImageDraw
    except Exception as e:
        raise SystemExit("Missing Pillow. Install: python3 -m pip install --user pillow") from e
    try:
        # term-image v0.7.x
        from term_image.image import AutoImage
    except Exception as e:
        raise SystemExit("Missing term-image. Install: python3 -m pip install --user term-image") from e
    return Image, ImageDraw, AutoImage

def _colors_for_ground(ground: str) -> Tuple[int, int, int]:
    # keep it simple + readable
    if ground == "stone":
        return (90, 90, 95)
    if ground == "path":
        return (150, 150, 150)
    return (88, 60, 35)  # soil

def _draw_plant(draw, x0: int, y0: int, cell_px: int, species: str, stage: str):
    cx = x0 + cell_px // 2
    cy = y0 + cell_px // 2
    r  = max(2, cell_px // 10)

    # palette-ish colors
    green = (50, 150, 70)
    darkg = (30, 110, 50)
    pink  = (220, 90, 140)
    yellow= (240, 220, 80)

    if stage == "seed":
        draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=(40, 30, 20))
        return

    if stage == "sprout":
        draw.line((cx, cy+r, cx, cy-r), fill=green, width=max(1, cell_px//16))
        draw.ellipse((cx-r, cy-r*2, cx+r, cy), fill=green)
        return

    if species == "fern":
        if stage in ("leafy", "mature"):
            # simple frond strokes
            for i in range(-2, 3):
                draw.line((cx, cy, cx + i*(cell_px//6), cy - cell_px//3), fill=green, width=max(1, cell_px//18))
                draw.line((cx, cy, cx + i*(cell_px//7), cy - cell_px//5), fill=darkg, width=max(1, cell_px//22))
            return

    if species == "flower":
        if stage == "bud":
            draw.ellipse((cx-r*2, cy-r*2, cx+r*2, cy+r*2), fill=green)
            draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=pink)
            return
        if stage == "bloom":
            # 5 petals + center
            pr = cell_px // 4
            for dx, dy in [(0,-pr),(pr,0),(0,pr),(-pr,0),(pr//2,-pr//2)]:
                draw.ellipse((cx+dx-r*2, cy+dy-r*2, cx+dx+r*2, cy+dy+r*2), fill=pink)
            draw.ellipse((cx-r*2, cy-r*2, cx+r*2, cy+r*2), fill=yellow)
            return

    # fallback
    draw.rectangle((x0+2, y0+2, x0+cell_px-2, y0+cell_px-2), outline=(255, 0, 0), width=2)

def render_kitty(st: Dict[str, Any], cell_px: int = 32, clear: bool = True) -> None:
    Image, ImageDraw, AutoImage = _require_pil_and_term_image()

    w, h = st["width"], st["height"]
    now = int(time.time())

    img_w = w * cell_px
    img_h = h * cell_px
    im = Image.new("RGB", (img_w, img_h), (0, 0, 0))
    draw = ImageDraw.Draw(im)

    # background + grid
    for y in range(h):
        for x in range(w):
            cell = st["cells"][idx(x, y, w)]
            ground = cell.get("ground", "soil")
            x0, y0 = x * cell_px, y * cell_px
            bg = _colors_for_ground(ground)
            draw.rectangle((x0, y0, x0 + cell_px, y0 + cell_px), fill=bg)

            # subtle grid line
            draw.rectangle((x0, y0, x0 + cell_px, y0 + cell_px), outline=(0, 0, 0), width=1)

            if cell.get("plant") is not None:
                species = cell["plant"]["species"]
                stage = plant_stage(cell["plant"], now)
                _draw_plant(draw, x0, y0, cell_px, species, stage)

    if clear:
        # clear screen + home
        print("\x1b[2J\x1b[H", end="")

    # AutoImage uses the best available protocol (Kitty on Ghostty).
    # Print renders it at the current cursor position.
    ti = AutoImage(im)
    print(ti)

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
    pv.add_argument("--kitty", action="store_true", help="Render as an image using Kitty/TGP (Ghostty supported).")
    pv.add_argument("--cell-px", type=int, default=32, help="Pixel size per cell for --kitty.")
    pv.add_argument("--no-clear", action="store_true", help="Don't clear screen before drawing in --kitty mode.")
    pv.set_defaults(fn=cmd_show)

    args = p.parse_args()
    args.fn(args)

if __name__ == "__main__":
    main()
