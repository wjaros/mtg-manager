"""Match recognized card text (and the card image) to printings.

    a. set code + collector number from the bottom line: exact printing (OCR look-alikes tolerated)
    b. fuzzy name match (English names, printed names of other languages)
    c. choose the printing: collector number, artist, copyright year, then image similarity
    d. result: top candidates with a confidence
"""

import json
import logging
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field

import cv2
import numpy as np
from rapidfuzz import fuzz, process, utils

from mtgdm.cards.search import EXTRA_LAYOUTS
from mtgdm.i18n import tr
from mtgdm.scan.reader import CardText

log = logging.getLogger(__name__)

NAME_MIN_SCORE = 70          # fuzzy name score (0..100) to consider a card at all
MAX_NAME_CANDIDATES = 3
MAX_IMAGE_COMPARISONS = 16   # printings compared by image when the text can't decide
# Art box of a straightened card (relative): least affected by frame and border differences.
ART_BOX = (0.08, 0.11, 0.92, 0.55)

_SET_LOOKALIKES = {"0": "O", "O": "0", "1": "I", "I": "1", "5": "S", "S": "5", "8": "B", "B": "8", "2": "Z", "Z": "2"}

# Loads the image of a printing (BGR, any size) or returns None when it is not available.
ImageLoader = Callable[[str], np.ndarray | None]


@dataclass
class Candidate:
    card_id: str
    name: str
    set_code: str
    collector_number: str
    score: float                      # 0..1
    reasons: list[str] = field(default_factory=list)


class Matcher:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn
        self._names: list[str] = []
        self._oracles: list[str] = []
        # Tokens, emblems and art-series cards ("Lightning Bolt // Lightning Bolt") share names with
        # real cards; they are not what people scan into a collection.
        extras = ", ".join(f"'{layout}'" for layout in EXTRA_LAYOUTS)
        rows = conn.execute(
            f"SELECT o.oracle_id, o.name FROM oracle_cards o JOIN cards c ON c.id = o.default_card_id"
            f" WHERE COALESCE(c.layout, '') NOT IN ({extras})"
        ).fetchall()
        for oracle_id, name in rows:
            self._add_name(name, oracle_id)
            if " // " in name:
                for face in name.split(" // "):
                    self._add_name(face, oracle_id)
        for oracle_id, printed in conn.execute(
            "SELECT DISTINCT oracle_id, printed_name FROM cards WHERE printed_name IS NOT NULL AND oracle_id IS NOT NULL"
        ):
            self._add_name(printed, oracle_id)
        self._set_codes = {r[0] for r in conn.execute("SELECT code FROM sets")}

    def _add_name(self, name: str, oracle_id: str) -> None:
        self._names.append(name)
        self._oracles.append(oracle_id)

    # --- public -------------------------------------------------------------------

    def match(self, text: CardText, card_image: np.ndarray | None = None,
              load_image: ImageLoader | None = None) -> list[Candidate]:
        """Candidates best first (at most 3)."""
        candidates: dict[str, Candidate] = {}

        for row in self._by_collector_info(text):
            name_sim = self._name_similarity(text.name, row["name"])
            score = 0.9
            reasons = [f"set {row['set_code'].upper()} #{row['collector_number']}"]
            if name_sim is not None and name_sim >= 85:
                score, reasons = 0.98, reasons + [tr("reason_name")]
            elif name_sim is not None and name_sim < 60:
                score, reasons = 0.45, reasons + [tr("reason_name_mismatch")]
            self._keep(candidates, Candidate(row["id"], row["name"], row["set_code"], row["collector_number"],
                                             score, reasons))

        for oracle_id, name_score in self._names_like(text.name):
            for row, bonus, why in self._rank_printings(oracle_id, text):
                score = min(0.95, name_score / 100 * 0.8 + bonus)
                self._keep(candidates, Candidate(row["id"], row["name"], row["set_code"], row["collector_number"],
                                                 score, [tr("reason_name_score", score=f"{name_score:.0f}"), *why]))

        ranked = sorted(candidates.values(), key=lambda c: c.score, reverse=True)
        if card_image is not None and load_image is not None and ranked:
            ranked = self._rerank_by_image(ranked, card_image, load_image)
        return ranked[:3]

    # --- text -----------------------------------------------------------------------

    def _by_collector_info(self, text: CardText) -> list[sqlite3.Row]:
        if not text.collector_number:
            return []
        numbers = {text.collector_number, text.collector_number + "a"}
        if text.set_code:
            sets = [s for s in _lookalikes(text.set_code.upper()) if s.lower() in self._set_codes]
            sets = [s.lower() for s in sets]
            arena = [r[0] for r in self.conn.execute(
                "SELECT code FROM sets WHERE arena_code = ?", (text.set_code.lower(),))]
            for code in sets + [a for a in arena if a not in sets]:
                rows = self.conn.execute(
                    f"SELECT id, name, set_code, collector_number FROM cards WHERE set_code = ? AND collector_number IN"
                    f" ({', '.join('?' * len(numbers))}) ORDER BY collector_number",
                    (code, *numbers),
                ).fetchall()
                if rows:
                    return rows[:1]
            return []
        # Older frames print the number without a set code: needs the name to narrow it down.
        if not text.name:
            return []
        oracle_ids = [o for o, _ in self._names_like(text.name)]
        if not oracle_ids:
            return []
        return self.conn.execute(
            f"SELECT id, name, set_code, collector_number FROM cards WHERE oracle_id IN ({', '.join('?' * len(oracle_ids))})"
            f" AND collector_number IN ({', '.join('?' * len(numbers))})"
            + (" AND CAST(substr(released_at, 1, 4) AS INTEGER) <= ?" if text.year else "")
            + " ORDER BY released_at DESC LIMIT 3",
            (*oracle_ids, *numbers, *([text.year] if text.year else [])),
        ).fetchall()

    def _names_like(self, name: str | None) -> list[tuple[str, float]]:
        if not name or len(name) < 3:
            return []
        hits = process.extract(name, self._names, scorer=fuzz.WRatio, processor=utils.default_process,
                               limit=MAX_NAME_CANDIDATES * 3, score_cutoff=NAME_MIN_SCORE)
        best: dict[str, float] = {}
        for _, score, index in hits:
            oracle = self._oracles[index]
            best[oracle] = max(best.get(oracle, 0), score)
        return sorted(best.items(), key=lambda x: x[1], reverse=True)[:MAX_NAME_CANDIDATES]

    def _name_similarity(self, read: str | None, actual: str) -> float | None:
        if not read:
            return None
        faces = [actual, *actual.split(" // ")] if " // " in actual else [actual]
        return max(fuzz.WRatio(read, f, processor=utils.default_process) for f in faces)

    def _rank_printings(self, oracle_id: str, text: CardText) -> list[tuple[sqlite3.Row, float, list[str]]]:
        rows = self.conn.execute(
            """
            SELECT c.id, c.name, c.set_code, c.collector_number, c.artist, c.released_at, c.lang, c.games, c.promo
            FROM cards c WHERE c.oracle_id = ?
            """,
            (oracle_id,),
        ).fetchall()
        ranked = []
        for row in rows:
            bonus, why = 0.0, []
            if text.collector_number and row["collector_number"].lstrip("0") == text.collector_number:
                bonus += 0.08
                why.append(tr("reason_number"))
            if text.set_code and row["set_code"] == text.set_code:
                bonus += 0.08
                why.append("set")
            if text.artist and row["artist"] and fuzz.WRatio(text.artist, row["artist"], processor=utils.default_process) >= 80:
                bonus += 0.04
                why.append(tr("reason_artist"))
            year = int(row["released_at"][:4]) if row["released_at"] else None
            if text.year and year:
                if year == text.year:
                    bonus += 0.04
                    why.append(tr("reason_year"))
                elif year > text.year:
                    bonus -= 0.1  # printed later than the copyright says: not this printing
            if text.language and row["lang"] != text.language and not (text.language == "en" and row["lang"] == "en"):
                bonus -= 0.03
            if "paper" not in json.loads(row["games"] or "[]"):
                bonus -= 0.05  # a photographed card is a paper card
            ranked.append((row, bonus, why, row["released_at"] or ""))
        ranked.sort(key=lambda r: (r[1], r[3]), reverse=True)
        return [(r[0], r[1], r[2]) for r in ranked[:MAX_IMAGE_COMPARISONS]]

    def _same_illustration(self, card_id: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT c.id, c.name, c.set_code, c.collector_number FROM cards c JOIN card_details d ON d.id = c.id
            WHERE json_extract(d.raw, '$.illustration_id') = (
                SELECT json_extract(raw, '$.illustration_id') FROM card_details WHERE id = ?)
              AND c.id != ?
            LIMIT ?
            """,
            (card_id, card_id, MAX_IMAGE_COMPARISONS),
        ).fetchall()

    @staticmethod
    def _keep(candidates: dict[str, Candidate], cand: Candidate) -> None:
        current = candidates.get(cand.card_id)
        if current is None or cand.score > current.score:
            candidates[cand.card_id] = cand

    # --- image ----------------------------------------------------------------------

    def _rerank_by_image(self, ranked: list[Candidate], card_image: np.ndarray,
                         load_image: ImageLoader) -> list[Candidate]:
        """Compare the art with candidate printings: decides between printings of the same card
        (different art) and backs up weak text matches."""
        target_art, target_frame = art_hash(card_image), card_hash(card_image)
        best_text = ranked[0].score
        # Set + collector number with an agreeing name is exact: the image only double-checks it.
        exact = best_text >= 0.98 and ranked[0].reasons[0].startswith("set ")
        pool = [c for c in ranked if c.score >= best_text - 0.25][:MAX_IMAGE_COMPARISONS]
        frames: dict[str, int] = {}
        images: dict[str, np.ndarray] = {}
        for cand in pool:
            image = load_image(cand.card_id)
            if image is not None:
                images[cand.card_id] = cv2.resize(image, (card_image.shape[1], card_image.shape[0]),
                                                  interpolation=cv2.INTER_AREA)
        distances = {card_id: hamming(target_art, art_hash(image)) for card_id, image in images.items()}
        # Nothing in the pool looks like the scan (a badly framed crop, or the right card was not
        # compared): the image can't tell, so it must not push the compared candidates below the
        # ones that were never compared.
        informative = bool(distances) and min(distances.values()) <= 26
        for cand in pool:
            if cand.card_id not in images:
                continue
            image = images[cand.card_id]
            distance = distances[cand.card_id]
            # 0-10 bits: same image; 30+: unrelated. Map to an adjustment of +0.12 .. -0.15.
            adjust = 0.12 if distance <= 10 else (0.04 if distance <= 18 else (-0.05 if distance <= 26 else -0.15))
            if not informative:
                adjust = 0.0
            if exact and cand is ranked[0]:
                adjust = max(adjust, -0.05)  # glare can spoil the art hash; the printed number can't lie
            cand.score = max(0.0, min(0.99, cand.score + adjust))
            cand.reasons.append(tr("reason_image", distance=distance))
            if distance <= 18:
                frames[cand.card_id] = hamming(target_frame, card_hash(image))
        if exact:
            return sorted(ranked, key=lambda c: c.score, reverse=True)
        # Reprints often reuse the art: every printing with the matching illustration joins the
        # comparison (it may be missing from the text-based pool), and the closest frame wins.
        if frames:
            best_art = min(frames, key=frames.get)
            for row in self._same_illustration(best_art):
                if row["id"] in frames:
                    continue
                image = load_image(row["id"])
                if image is None:
                    continue
                image = cv2.resize(image, (card_image.shape[1], card_image.shape[0]), interpolation=cv2.INTER_AREA)
                if hamming(target_art, art_hash(image)) > 18:
                    continue
                score = next(c.score for c in pool if c.card_id == best_art)
                cand = Candidate(row["id"], row["name"], row["set_code"], row["collector_number"], score - 0.01,
                                 [tr("reason_same_art")])
                pool.append(cand)
                ranked.append(cand)
                frames[row["id"]] = hamming(target_frame, card_hash(image))
        if len(frames) >= 2:
            # Everything as close as the best frame (same frame generation) gets the bonus;
            # identical frames (M10 vs M11) stay tied and are left to the copyright year / number.
            best = min(frames.values())
            if sorted(frames.values())[-1] - best >= 15:
                for cand in pool:
                    if cand.card_id in frames and frames[cand.card_id] <= best + 10:
                        cand.score = min(0.99, cand.score + 0.06)
                        cand.reasons.append(tr("reason_frame"))
        return sorted(ranked, key=lambda c: c.score, reverse=True)


def art_hash(card_bgr: np.ndarray) -> np.ndarray:
    """64-bit perceptual hash (DCT) of the art box of a straightened card image."""
    h, w = card_bgr.shape[:2]
    x0, y0, x1, y1 = ART_BOX
    art = card_bgr[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
    gray = cv2.cvtColor(art, cv2.COLOR_BGR2GRAY) if art.ndim == 3 else art
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(small)[:8, :8]
    return (dct > np.median(dct[1:].ravel())).ravel()


def card_hash(card_bgr: np.ndarray) -> np.ndarray:
    """Hash of the frame only: name bar and bottom bar, where frame generations (1993, 2003,
    2015...) differ most. Reprints reuse the art, so the art alone can't tell them apart."""
    gray = cv2.cvtColor(card_bgr, cv2.COLOR_BGR2GRAY) if card_bgr.ndim == 3 else card_bgr
    h = gray.shape[0]
    bands = np.vstack([gray[: int(0.11 * h)], gray[int(0.86 * h):]])
    small = cv2.resize(bands, (32, 16), interpolation=cv2.INTER_AREA)
    return (small > np.median(small)).ravel()


def hamming(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(a != b))


def _lookalikes(code: str) -> list[str]:
    """'C0M' -> ['C0M', 'COM'] (each look-alike character swapped, original first)."""
    variants = [code]
    for i, ch in enumerate(code):
        if ch in _SET_LOOKALIKES:
            variants += [v[:i] + _SET_LOOKALIKES[ch] + v[i + 1:] for v in list(variants)]
    return list(dict.fromkeys(variants))
