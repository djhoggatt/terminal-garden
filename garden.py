#!/usr/bin/env python3
import argparse, json, os, time
from dataclasses import dataclass
from typing import Optional, Dict, Any, List

STATE_PATH = os.path.expanduser("~/.local/state/terminal-garden/garden.json")

SPECIES = {
    "fern": [
        (0,    "·"),   # just planted
        (60,   "˘"),   # sprout
        (5*60, "☘"),   # leafy
        (20*60,"♣"),   # mature
    ],
    "flower": [
        (0,    "·"),
        (60,   "˘"),
        (8*60, "✿"),
        (25*60,"❀"),
    ],
}

GROUND_GLYPH = {"soil": "  ", "stone": "⬚ ", "path": "··"}

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

def plant_glyph(plant: Dict[str, Any], now: int) -> str:
    species = plant["species"]
    planted_at = plant["planted_at"]
    age = max(0, now - planted_at)
    stages = SPECIES.get(species, [(0, "?")])

    g = stages[0][1]
    for t, glyph in stages:
        if age >= t:
            g = glyph
    return g

def render(st: Dict[str, Any]) -> str:
    w, h = st["width"], st["height"]
    now = int(time.time())
    out: List[str] = []
    out.append(f"Terminal Garden  ({w}x{h})  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(now))}")
    out.append("+" + "-" * (w * 2) + "+")
    for y in range(h):
        row = ["|"]
        for x in range(w):
            cell = st["cells"][idx(x, y, w)]
            g = GROUND_GLYPH.get(cell.get("ground", "soil"), "  ")
            if cell.get("plant") is not None:
                pg = plant_glyph(cell["plant"], now)
                row.append(pg + " ")
            else:
                row.append(g)
        row.append("|")
        out.append("".join(row))
    out.append("+" + "-" * (w * 2) + "+")
    return "\n".join(out)

def cmd_init(args: argparse.Namespace) -> None:
    w, h = args.width, args.height
    st = {
        "width": w,
        "height": h,
        "cells": [{"ground": "soil", "plant": None} for _ in range(w * h)],
    }
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

def cmd_show(_: argparse.Namespace) -> None:
    st = load_state()
    print(render(st))

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
    pv.set_defaults(fn=cmd_show)

    args = p.parse_args()
    args.fn(args)

if __name__ == "__main__":
    main()
