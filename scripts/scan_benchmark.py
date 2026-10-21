#!/usr/bin/env python3
"""Recognition accuracy on synthetic photos of the scan fixture cards.

    cd backend && uv run python ../scripts/scan_benchmark.py [--engine rapidocr] [--per-card 5]

Needs a synced database; candidate images are taken from (and downloaded into) the image cache.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from mtgdm.config import load_settings  # noqa: E402
from mtgdm.db import connect  # noqa: E402
from mtgdm.scan.match import Matcher  # noqa: E402
from mtgdm.scan.ocr.base import default_engine_name, get_engine  # noqa: E402
from mtgdm.scan.pipeline import scan_image  # noqa: E402
from mtgdm.scan.synth import synth_photo  # noqa: E402
from mtgdm.scryfall import ScryfallClient  # noqa: E402
from mtgdm.scryfall.images import ImageCache  # noqa: E402

CARDS = ROOT / "backend" / "tests" / "fixtures" / "scans" / "cards"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", default=default_engine_name())
    parser.add_argument("--per-card", type=int, default=5)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--clean", action="store_true", help="straight card images instead of synthetic photos")
    parser.add_argument("--pages", type=int, default=0, help="synthetic A4 scans with up to 9 cards instead of photos")
    parser.add_argument("--background", choices=["white", "black"], default="white",
                        help="page background: white (lid closed) or black (lid open, white-bordered cards)")
    args = parser.parse_args()

    settings = load_settings()
    conn = connect(settings.db_path)
    matcher = Matcher(conn)
    engine = get_engine(args.engine)
    manifest = json.loads((CARDS / "manifest.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(args.seed)

    with ScryfallClient() as client:
        cache = ImageCache(settings.images_dir, client)

        def load_image(card_id: str):
            try:
                return cv2.imread(str(cache.get(conn, card_id, "normal")))
            except Exception:  # offline or no image: image re-ranking is skipped for this card
                return None

        if args.pages:
            return bench_pages(args, conn, matcher, engine, manifest, rng, load_image)

        names = printings = total = 0
        seconds = 0.0
        misses = []
        for card in manifest:
            original = cv2.imread(str(CARDS / f"{card['id']}.jpg"))
            for _ in range(1 if args.clean else args.per_card):
                photo = original if args.clean else synth_photo(original, rng).image
                started = time.monotonic()
                result = scan_image(photo, matcher, engine, load_image=load_image)[0]
                seconds += time.monotonic() - started
                top = result.candidates[0] if result.candidates else None
                total += 1
                name_ok = bool(top) and conn.execute(
                    "SELECT oracle_id FROM cards WHERE id = ?", (top.card_id,)).fetchone()[0] == card["oracle_id"]
                printing_ok = bool(top) and top.card_id == card["id"]
                names += name_ok
                printings += printing_ok
                if not printing_ok:
                    misses.append(f"{card['name']} ({card['set']} {card['collector_number']}) -> "
                                  + (f"{top.name} ({top.set_code} {top.collector_number}) {top.score:.2f} {top.reasons}"
                                     if top else "nothing")
                                  + f" | read name={result.text.name!r} num={result.text.collector_number}"
                                    f" set={result.text.set_code}")
    print(f"engine={args.engine} photos={total}  names {names}/{total} = {names / total:.0%}  "
          f"printings {printings}/{total} = {printings / total:.0%}  {seconds / total:.2f} s/photo")
    for line in misses[:25]:
        print("  miss:", line)
    return 0


def bench_pages(args, conn, matcher, engine, manifest, rng, load_image) -> int:
    from mtgdm.scan.synth import synth_page

    images = [cv2.imread(str(CARDS / f"{c['id']}.jpg")) for c in manifest]
    total = found = names = printings = extra = 0
    seconds = 0.0
    for _ in range(args.pages):
        page = synth_page(images, rng, background=args.background, fill=0.85, white_border=args.background == "black")
        started = time.monotonic()
        results = scan_image(page.image, matcher, engine, load_image=load_image, kind="page")
        seconds += time.monotonic() - started
        unused = list(range(len(results)))
        for index, truth in page.cards:
            total += 1
            center = truth.mean(axis=0)
            width = np.linalg.norm(truth[0] - truth[1])
            near = [i for i in unused if np.linalg.norm(results[i].corners.mean(axis=0) - center) < 0.4 * width]
            if not near:
                continue
            unused.remove(near[0])
            found += 1
            top = results[near[0]].candidates[0] if results[near[0]].candidates else None
            if top:
                names += top.name == manifest[index]["name"]
                printings += top.card_id == manifest[index]["id"]
        extra += len(unused)
    print(f"engine={args.engine} pages={args.pages} background={args.background} cards={total}  "
          f"found {found}/{total} = {found / total:.0%}  names {names / total:.0%}  printings {printings / total:.0%}  "
          f"extra {extra}  {seconds / args.pages:.1f} s/page")
    return 0


if __name__ == "__main__":
    sys.exit(main())
