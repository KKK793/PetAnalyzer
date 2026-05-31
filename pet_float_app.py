import json
import math
import os
import re
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import psutil
import win32gui
import win32process
from rapidocr import RapidOCR
from windows_capture import WindowsCapture


if getattr(sys, "frozen", False):
    APP_DIR = Path(sys.executable).resolve().parent
else:
    APP_DIR = Path(__file__).resolve().parent
DATA_PATH = APP_DIR / "data" / "pet_plans.json"
PROCESS_NAME = os.environ.get("PET_GAME_PROCESS", "NRC-Win64-Shipping")
NEXT_FRAME_WAIT_SECONDS = 0.08

STATS = ["生命", "魔攻", "物攻", "魔防", "物防", "速度"]
SCREEN_STAT_ORDER = ["生命", "物攻", "魔攻", "物防", "魔防", "速度"]
BASE_IV_VALUES = (7, 8, 9, 10)
IV_MULTIPLIERS = (1, 2, 3, 4, 5, 6)
VALID_IV_DISPLAY_VALUES = {base * multiplier for base in BASE_IV_VALUES for multiplier in IV_MULTIPLIERS}
AMBIGUOUS_NATURE_TRAIT_PAIRS = {
    ("警惕", "预警"),
}
NATURES = [
    {"name": "固执", "plus": "物攻", "minus": "魔攻"},
    {"name": "大胆", "plus": "物攻", "minus": "物防"},
    {"name": "调皮", "plus": "物攻", "minus": "魔防"},
    {"name": "勇敢", "plus": "物攻", "minus": "速度"},
    {"name": "逞强", "plus": "物攻", "minus": "生命"},
    {"name": "稳重", "plus": "物防", "minus": "物攻"},
    {"name": "天真", "plus": "物防", "minus": "魔攻"},
    {"name": "悠闲", "plus": "物防", "minus": "速度"},
    {"name": "懒散", "plus": "物防", "minus": "魔防"},
    {"name": "坦率", "plus": "物防", "minus": "生命"},
    {"name": "警惕", "plus": "魔防", "minus": "物攻"},
    {"name": "害羞", "plus": "魔防", "minus": "魔攻"},
    {"name": "温顺", "plus": "魔防", "minus": "物防"},
    {"name": "慎重", "plus": "魔防", "minus": "速度"},
    {"name": "焦虑", "plus": "魔防", "minus": "生命"},
    {"name": "胆小", "plus": "速度", "minus": "物攻"},
    {"name": "开朗", "plus": "速度", "minus": "魔攻"},
    {"name": "急躁", "plus": "速度", "minus": "物防"},
    {"name": "莽撞", "plus": "速度", "minus": "魔防"},
    {"name": "热情", "plus": "速度", "minus": "生命"},
    {"name": "沉默", "plus": "生命", "minus": "物攻"},
    {"name": "平和", "plus": "生命", "minus": "魔攻"},
    {"name": "忧郁", "plus": "生命", "minus": "物防"},
    {"name": "粗心", "plus": "生命", "minus": "魔防"},
    {"name": "踏实", "plus": "生命", "minus": "速度"},
    {"name": "聪明", "plus": "魔攻", "minus": "物攻"},
    {"name": "专注", "plus": "魔攻", "minus": "物防"},
    {"name": "偏执", "plus": "魔攻", "minus": "魔防"},
    {"name": "冷静", "plus": "魔攻", "minus": "速度"},
    {"name": "理性", "plus": "魔攻", "minus": "生命"},
]
NATURE_BY_NAME = {item["name"]: item for item in NATURES}


def resource_path(relative: str) -> Path:
    return APP_DIR / relative


def normalize_text(value) -> str:
    text = str(value or "")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[【】\[\]（）()：:]", "", text)
    return text.replace("资貭", "资质")


def compact_text(value) -> str:
    return re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", normalize_text(value))


def clean_process_name(value: str) -> str:
    return Path(value or "").stem.lower()


def median(values):
    values = sorted(v for v in values if isinstance(v, (int, float)) and math.isfinite(v))
    return values[len(values) // 2] if values else 0


def edit_distance(a: str, b: str) -> int:
    aa, bb = list(a), list(b)
    prev = list(range(len(bb) + 1))
    curr = [0] * (len(bb) + 1)
    for i, ca in enumerate(aa, 1):
        curr[0] = i
        for j, cb in enumerate(bb, 1):
            curr[j] = prev[j - 1] if ca == cb else min(prev[j - 1], prev[j], curr[j - 1]) + 1
        prev, curr = curr, prev
    return prev[len(bb)]


def common_count(a: str, b: str) -> int:
    chars = list(a)
    count = 0
    for char in b:
        if char in chars:
            chars.remove(char)
            count += 1
    return count


def similarity(text: str, name: str) -> float:
    if not text or not name:
        return 0.0
    if name in text:
        return 1.0
    best = common_count(text, name) / max(1, len(name)) * 0.82
    chars = list(text)
    for size in range(max(1, len(name) - 1), min(len(chars), len(name) + 1) + 1):
        for start in range(0, len(chars) - size + 1):
            part = "".join(chars[start:start + size])
            score = 1 - edit_distance(part, name) / max(len(part), len(name))
            best = max(best, score)
    return best


class PetData:
    def __init__(self, path: Path):
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
        self.version = raw.get("version", "")
        self.update_date = raw.get("update_date", "")
        self.pets = raw.get("pets", [])
        self.names = sorted({pet.get("名字", "") for pet in self.pets if pet.get("名字")}, key=len, reverse=True)
        self.traits = sorted({normalize_text(pet.get("特性", "")) for pet in self.pets if pet.get("特性")}, key=len, reverse=True)
        self.by_id = {}
        self.by_name = {}
        self.by_trait = {}
        self.nature_name_set = {item["name"] for item in NATURES}
        self.short_trait_tail = {}
        for pet in self.pets:
            self.by_id.setdefault(pet.get("编号"), []).append(pet)
            name_key = normalize_text(pet.get("名字", ""))
            trait_key = normalize_text(pet.get("特性", ""))
            if name_key:
                self.by_name.setdefault(name_key, []).append(pet)
            if trait_key:
                self.by_trait.setdefault(trait_key, []).append(pet)
        self._stat_group_cache = {}
        self._nature_cache = {}
        self._variant_cache = {}
        self._trait_pet_cache = {}
        for trait in self.traits:
            compact = compact_text(trait)
            if 2 <= len(compact) <= 3 and trait not in self.nature_name_set:
                self.short_trait_tail.setdefault(compact[-1], set()).add(trait)

    def find_pet(self, name: str):
        target = normalize_text(name)
        entries = self.by_name.get(target, [])
        return entries[0] if entries else None

    def unique_pets(self, pets):
        result = []
        seen = set()
        for pet in pets:
            key = normalize_text(pet.get("名字", "")) or f"id:{pet.get('编号')}"
            if key in seen:
                continue
            seen.add(key)
            result.append(pet)
        return result

    def find_pets_by_trait(self, trait: str):
        target = normalize_text(trait)
        if not target:
            return []
        exact = self.find_pets_by_trait_exact(trait)
        if exact:
            return exact
        matched = self.match_trait(trait)
        if matched and normalize_text(matched) != target:
            return self.find_pets_by_trait_exact(matched)
        matches = []
        for pet in self.pets:
            pet_trait = normalize_text(pet.get("特性", ""))
            if pet_trait and (target in pet_trait or pet_trait in target):
                matches.append(pet)
        return matches

    def find_pets_by_trait_exact(self, trait: str):
        target = normalize_text(trait)
        if not target:
            return []
        return self.by_trait.get(target, [])

    def match_trait(self, text: str):
        target = normalize_text(text)
        if not target:
            return ""
        for trait in self.traits:
            if normalize_text(trait) == target:
                return trait
        candidates = []
        for trait in self.traits:
            normalized = normalize_text(trait)
            if not normalized:
                continue
            if normalized in target or (len(target) >= 2 and target in normalized):
                candidates.append((trait in self.nature_name_set, -len(normalized), trait))
        if not candidates:
            compact = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", target)
            best_trait, best_score = "", 0.0
            for trait in self.traits:
                normalized = normalize_text(trait)
                if not normalized:
                    continue
                score = similarity(compact, normalized)
                if trait in self.nature_name_set:
                    score -= 0.08
                if score > best_score:
                    best_trait, best_score = trait, score
            if best_trait:
                threshold = 0.64 if len(normalize_text(best_trait)) <= 3 else 0.70
                if best_score >= threshold:
                    return best_trait
            compact = compact_text(target)
            if 2 <= len(compact) <= 3:
                for trait in self.traits:
                    if trait in self.nature_name_set:
                        continue
                    compact_trait = compact_text(trait)
                    if not (2 <= len(compact_trait) <= 3):
                        continue
                    if abs(len(compact) - len(compact_trait)) > 1:
                        continue
                    if edit_distance(compact, compact_trait) <= 1 and common_count(compact, compact_trait) >= max(1, len(compact_trait) - 1):
                        return trait
            for char, traits in self.short_trait_tail.items():
                if char == "啪" and len(compact) >= 1 and (char in compact or "拍" in compact) and len(traits) == 1:
                    return next(iter(traits))
            return ""
        candidates.sort()
        return candidates[0][2]

    def guess_name(self, text: str):
        candidates = self.name_candidates(text, limit=1)
        if not candidates:
            compact = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", normalize_text(text))
            return "", 0.0 if not compact else max((similarity(compact, normalize_text(name)) for name in self.names), default=0.0)
        name, score = candidates[0]
        threshold = 0.92 if len(name) <= 2 else 0.72 if len(name) == 3 else 0.62
        return (name, score) if score >= threshold else ("", score)

    def name_candidates(self, text: str, limit=6):
        compact = re.sub(r"[^\u4e00-\u9fa5A-Za-z0-9]", "", normalize_text(text))
        if not compact:
            return []
        candidates = {}
        for name in self.names:
            normalized = normalize_text(name)
            if normalized in compact:
                candidates[name] = max(candidates.get(name, 0.0), 1.0)
        for name in self.names:
            normalized = normalize_text(name)
            score = similarity(compact, normalized)
            if score < 0.50:
                continue
            if len(normalized) <= 2 and score < 0.92:
                continue
            if len(normalized) == 3 and score < 0.60:
                continue
            if len(normalized) >= 4 and score < 0.55:
                continue
            candidates[name] = max(candidates.get(name, 0.0), score)
        return sorted(candidates.items(), key=lambda item: (-item[1], len(item[0]), item[0]))[:limit]

    def parse_natures(self, value):
        key = str(value or "")
        if key not in self._nature_cache:
            self._nature_cache[key] = [item.strip() for item in re.split(r"[、,，/|;\s]+", key) if item.strip()]
        return self._nature_cache[key]

    def parse_stat_groups(self, value):
        key = str(value or "")
        if key in self._stat_group_cache:
            return self._stat_group_cache[key]
        groups = []
        for group in re.split(r"[、,，|;\s]+", key):
            stats = [item.strip() for item in re.split(r"[\/／]+", group) if item.strip() in STATS]
            if stats:
                groups.append(stats)
        self._stat_group_cache[key] = groups
        return groups

    def parse_reference_ids(self, value):
        if isinstance(value, int):
            return [value]
        if not isinstance(value, str):
            return []
        text = value.strip()
        if not re.fullmatch(r"\d+(?:\s*[\/／、,，|;]\s*\d+)*", text):
            return []
        return [int(item) for item in re.findall(r"\d+", text)]

    def variants_for_refs(self, refs, seen):
        variants = []
        for ref in refs:
            for target in self.by_id.get(ref, []):
                variants.extend(self.resolve_variants(target, set(seen)))
        return variants

    def resolve_variants(self, pet, seen=None):
        seen = seen or set()
        if not pet:
            return []
        key = f"{pet.get('编号')}:{pet.get('名字')}:{pet.get('推荐个体值')}:{pet.get('推荐性格')}"
        if key in seen:
            return []
        seen.add(key)
        stat_value = pet.get("推荐个体值")
        nature_value = pet.get("推荐性格")
        stat_refs = self.parse_reference_ids(stat_value)
        nature_refs = self.parse_reference_ids(nature_value)
        if stat_refs and nature_refs and stat_refs == nature_refs:
            return self.variants_for_refs(stat_refs, seen)
        if stat_refs or nature_refs:
            stat_variants = (
                self.variants_for_refs(stat_refs, seen)
                if stat_refs
                else [{"statGroups": self.parse_stat_groups(stat_value), "statText": stat_value or ""}]
            )
            nature_variants = (
                self.variants_for_refs(nature_refs, seen)
                if nature_refs
                else [{"natures": self.parse_natures(nature_value), "natureText": nature_value or ""}]
            )
            return [
                {"statGroups": sv.get("statGroups", []), "statText": sv.get("statText", ""),
                 "natures": nv.get("natures", []), "natureText": nv.get("natureText", "")}
                for sv in stat_variants for nv in nature_variants
            ]
        return [{
            "statGroups": self.parse_stat_groups(stat_value),
            "statText": stat_value if isinstance(stat_value, str) else "",
            "natures": self.parse_natures(nature_value),
            "natureText": nature_value if isinstance(nature_value, str) else "",
        }]

    def recommendation_variants(self, name: str):
        name_key = normalize_text(name)
        if name_key in self._variant_cache:
            return self._variant_cache[name_key]
        entries = self.by_name.get(name_key, [])
        seen = set()
        variants = []
        for pet in entries:
            for variant in self.resolve_variants(pet):
                key = f"{variant.get('statText')}|{variant.get('natureText')}"
                if key not in seen:
                    seen.add(key)
                    variants.append(variant)
        self._variant_cache[name_key] = variants
        return variants


class CaptureSession:
    def __init__(self, process_name: str):
        self.process_name = clean_process_name(process_name)
        self.window = None
        self.capture = None
        self.control = None
        self.lock = threading.Lock()
        self.frame_ready = threading.Event()
        self.latest_frame = None
        self.closed = False

    def find_window(self):
        pids = set()
        for process in psutil.process_iter(["pid", "name"]):
            try:
                if clean_process_name(process.info["name"]) == self.process_name:
                    pids.add(int(process.info["pid"]))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        if not pids:
            raise RuntimeError(f"未找到进程：{PROCESS_NAME}.exe")
        windows = []

        def callback(hwnd, _):
            if not win32gui.IsWindow(hwnd):
                return True
            try:
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid not in pids:
                    return True
                left, top, right, bottom = win32gui.GetWindowRect(hwnd)
                width, height = right - left, bottom - top
                if width >= 200 and height >= 200:
                    windows.append({
                        "hwnd": int(hwnd), "pid": int(pid), "title": win32gui.GetWindowText(hwnd),
                        "width": width, "height": height, "area": width * height,
                        "visible": bool(win32gui.IsWindowVisible(hwnd)),
                    })
            except Exception:
                pass
            return True

        win32gui.EnumWindows(callback, None)
        if not windows:
            raise RuntimeError("找到游戏进程，但没有可捕获窗口")
        windows.sort(key=lambda item: (item["visible"], item["area"]), reverse=True)
        return windows[0]

    def start(self):
        if self.control is not None and not self.closed:
            return
        self.window = self.find_window()
        self.frame_ready.clear()
        self.closed = False
        capture = WindowsCapture(
            cursor_capture=False,
            draw_border=False,
            secondary_window=True,
            minimum_update_interval=60,
            dirty_region=False,
            window_hwnd=self.window["hwnd"],
        )

        @capture.event
        def on_frame_arrived(frame, _control):
            with self.lock:
                self.latest_frame = frame.frame_buffer.copy()
            self.frame_ready.set()

        @capture.event
        def on_closed():
            self.closed = True
            self.frame_ready.set()

        self.capture = capture
        self.control = capture.start_free_threaded()
        if not self.frame_ready.wait(6):
            raise RuntimeError("后台捕获初始化超时")

    def frame(self):
        self.start()
        with self.lock:
            has_frame = self.latest_frame is not None
        if has_frame:
            self.frame_ready.clear()
            self.frame_ready.wait(NEXT_FRAME_WAIT_SECONDS)
        elif not self.frame_ready.wait(2):
            raise RuntimeError("没有可用游戏画面")
        with self.lock:
            if self.latest_frame is None:
                raise RuntimeError("没有可用游戏画面")
            frame = self.latest_frame.copy()
        return cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR) if frame.shape[2] == 4 else frame

    def stop(self):
        if self.control is not None:
            try:
                self.control.stop()
                self.control.wait()
            except Exception:
                pass
        self.control = None
        self.capture = None


def pixel_rgb(image, x, y):
    b, g, r = image[y, x][:3]
    return int(r), int(g), int(b)


def is_bright_ui(r, g, b):
    return r > 205 and g > 190 and b > 155


def is_yellow(r, g, b):
    return r > 185 and g > 125 and b < 135 and r > b * 1.45 and g > b * 1.12


def is_green(r, g, b):
    return g > 125 and r < 125 and b < 120 and g > r * 1.35 and g > b * 1.2


def is_red(r, g, b):
    return r > 135 and g < 130 and b < 130 and r > g * 1.25 and r > b * 1.15


def merge_bands(bands, max_gap):
    merged = []
    for band in bands:
        if not merged or band["start"] - merged[-1]["end"] > max_gap:
            merged.append(dict(band))
        else:
            merged[-1]["end"] = band["end"]
            merged[-1]["weight"] += band["weight"]
    return merged


def choose_rows(centers):
    if len(centers) < 6:
        return []
    if len(centers) == 6:
        return centers
    best = None

    def visit(start, chosen):
        nonlocal best
        if len(chosen) == 6:
            gaps = [chosen[i] - chosen[i - 1] for i in range(1, 6)]
            avg = sum(gaps) / len(gaps)
            score = sum(abs(g - avg) for g in gaps) / max(1, avg)
            if best is None or score < best[0]:
                best = (score, list(chosen))
            return
        for i in range(start, len(centers)):
            visit(i + 1, chosen + [centers[i]])

    visit(0, [])
    return best[1] if best else centers[:6]


def detect_rows_in_region(image, x0, x1, y0, y1):
    h, w = image.shape[:2]
    threshold = max(10, int((x1 - x0) * 0.025))
    counts = []
    region = image[y0:y1, x0:x1]
    for row in region:
        rgb = row[:, ::-1]
        mask = (rgb[:, 0] > 205) & (rgb[:, 1] > 190) & (rgb[:, 2] > 155)
        counts.append(int(mask.sum()))
    bands, band = [], None
    for idx, count in enumerate(counts):
        y = y0 + idx
        if count >= threshold:
            band = band or {"start": y, "end": y, "weight": 0}
            band["end"] = y
            band["weight"] += count
        elif band:
            bands.append(band)
            band = None
    if band:
        bands.append(band)
    merged = merge_bands(bands, max(8, int(h * 0.014)))
    filtered = []
    min_band_height = max(5, int(h * 0.006))
    for band in merged:
        height = band["end"] - band["start"] + 1
        if min_band_height <= height <= h * 0.055 and band["weight"] >= threshold * height * 1.2:
            filtered.append((band["start"] + band["end"]) / 2)
    rows = choose_rows(filtered)
    score = len(filtered) * 100000 + sum(band["weight"] for band in merged)
    return rows, score


def detect_stat_panel(image):
    h, w = image.shape[:2]
    candidates = [
        (0.00, 0.75, 0.18, 0.84),
        (0.10, 0.52, 0.14, 0.78),
        (0.20, 0.72, 0.18, 0.84),
        (0.26, 0.66, 0.22, 0.80),
        (0.32, 0.70, 0.22, 0.80),
    ]
    best = None
    for rx0, rx1, ry0, ry1 in candidates:
        x0, x1 = int(w * rx0), int(w * rx1)
        y0, y1 = int(h * ry0), int(h * ry1)
        rows, score = detect_rows_in_region(image, x0, x1, y0, y1)
        if len(rows) == 6:
            score += 1000000
        if best is None or score > best["score"]:
            best = {"rows": rows, "score": score, "x0": x0, "x1": x1, "y0": y0, "y1": y1}
    rows = best["rows"] if best else []
    gaps = [rows[i] - rows[i - 1] for i in range(1, len(rows))]
    row_step = median(gaps)
    if len(rows) != 6 or row_step < h * 0.03 or row_step > h * 0.08:
        y_start, spacing = h * 0.415, h * 0.046
        rows = [y_start + i * spacing for i in range(6)]
        row_step = spacing
        best = {"x0": 0, "x1": w, "y0": 0, "y1": h, "score": 0}
    if not best:
        best = {"x0": 0, "x1": w, "y0": 0, "y1": h, "score": 0}
    return {
        "rows": rows,
        "row_step": row_step or h * 0.046,
        "x0": best["x0"],
        "x1": best["x1"],
        "y0": best["y0"],
        "y1": best["y1"],
    }


def detect_rows(image):
    panel = detect_stat_panel(image)
    return panel["rows"], panel["row_step"]


def connected_components(mask, min_pixels):
    h, w = mask.shape
    visited = np.zeros(mask.shape, dtype=np.uint8)
    comps = []
    for y in range(h):
        for x in range(w):
            if visited[y, x] or not mask[y, x]:
                continue
            stack = [(x, y)]
            visited[y, x] = 1
            xs, ys = [], []
            while stack:
                cx, cy = stack.pop()
                xs.append(cx)
                ys.append(cy)
                for nx, ny in ((cx - 1, cy), (cx + 1, cy), (cx, cy - 1), (cx, cy + 1)):
                    if 0 <= nx < w and 0 <= ny < h and not visited[ny, nx] and mask[ny, nx]:
                        visited[ny, nx] = 1
                        stack.append((nx, ny))
            if len(xs) >= min_pixels:
                comps.append({"count": len(xs), "cx": (min(xs) + max(xs)) / 2, "cy": (min(ys) + max(ys)) / 2,
                              "w": max(xs) - min(xs) + 1, "h": max(ys) - min(ys) + 1})
    return comps


def arrow_candidates_from_mask(mask, x0, y0, rows, row_step):
    if mask.size == 0:
        return []
    num_labels, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    candidates = []
    min_width = max(3, int(row_step * 0.16))
    max_width = row_step * 0.58
    min_height = max(4, int(row_step * 0.22))
    max_height = row_step * 0.62
    min_pixels = max(18, int(row_step * 0.95))
    max_row_delta = row_step * 0.42
    for label in range(1, num_labels):
        count = int(stats[label, cv2.CC_STAT_AREA])
        if count < min_pixels:
            continue
        width = int(stats[label, cv2.CC_STAT_WIDTH])
        height = int(stats[label, cv2.CC_STAT_HEIGHT])
        if not (min_width <= width <= max_width and min_height <= height <= max_height):
            continue
        cx, cy = centroids[label]
        yy = y0 + float(cy)
        index = min(range(6), key=lambda i: abs(rows[i] - yy))
        if abs(rows[index] - yy) > max_row_delta:
            continue
        candidates.append({
            "x": x0 + float(cx),
            "y": yy,
            "count": count,
            "index": index,
        })
    return candidates


def choose_arrow_pair(plus_candidates, minus_candidates, row_step):
    max_x_gap = max(14, row_step * 1.25)
    best = None
    for plus in plus_candidates:
        for minus in minus_candidates:
            x_gap = abs(plus["x"] - minus["x"])
            if x_gap > max_x_gap:
                continue
            score = (x_gap, -(plus["count"] + minus["count"]))
            if best is None or score < best[0]:
                best = (score, plus, minus)
    if not best:
        return None
    return best[1], best[2]


def relative_rect_to_bounds(image, rect):
    if not rect or len(rect) != 4:
        return None
    h, w = image.shape[:2]
    try:
        x, y, rw, rh = [float(value) for value in rect]
    except (TypeError, ValueError):
        return None
    if rw <= 0 or rh <= 0:
        return None
    x0 = max(0, min(w - 1, int(round(x * w))))
    y0 = max(0, min(h - 1, int(round(y * h))))
    x1 = max(0, min(w, int(round((x + rw) * w))))
    y1 = max(0, min(h, int(round((y + rh) * h))))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return x0, y0, x1, y1


def manual_arrow_candidates(image, rect, color, rows, row_step):
    bounds = relative_rect_to_bounds(image, rect)
    if not bounds:
        return []
    x0, y0, x1, y1 = bounds
    region = image[y0:y1, x0:x1]
    if region.size == 0:
        return []
    rgb = region[:, :, ::-1]
    if color == "green":
        mask = (
            (rgb[:, :, 1] > 125)
            & (rgb[:, :, 0] < 125)
            & (rgb[:, :, 2] < 120)
            & (rgb[:, :, 1] > rgb[:, :, 0] * 1.35)
        )
    else:
        mask = (
            (rgb[:, :, 0] > 135)
            & (rgb[:, :, 1] < 130)
            & (rgb[:, :, 2] < 130)
            & (rgb[:, :, 0] > rgb[:, :, 1] * 1.25)
        )
    return arrow_candidates_from_mask(mask, x0, y0, rows, row_step)


def detect_manual_arrows(image, rows, row_step, manual_regions=None):
    manual_regions = manual_regions or {}
    nature_rect = manual_regions.get("nature")
    plus_rect = nature_rect or manual_regions.get("nature_plus")
    minus_rect = nature_rect or manual_regions.get("nature_minus")
    plus_candidates = manual_arrow_candidates(image, plus_rect, "green", rows, row_step)
    minus_candidates = manual_arrow_candidates(image, minus_rect, "red", rows, row_step)
    if not plus_candidates or not minus_candidates:
        return {"plus": "", "minus": ""}
    pair = choose_arrow_pair(plus_candidates, minus_candidates, row_step)
    if pair:
        plus, minus = pair
    else:
        plus = max(plus_candidates, key=lambda item: item["count"])
        minus = max(minus_candidates, key=lambda item: item["count"])
    return {
        "plus": SCREEN_STAT_ORDER[plus["index"]],
        "minus": SCREEN_STAT_ORDER[minus["index"]],
    }


def detect_arrows(image, rows, row_step, panel=None, manual_regions=None):
    manual_regions = manual_regions or {}
    if manual_regions.get("nature") or manual_regions.get("nature_plus") or manual_regions.get("nature_minus"):
        return detect_manual_arrows(image, rows, row_step, manual_regions)
    return {"plus": "", "minus": ""}


def manual_stats_panel(image, manual_regions=None):
    manual_regions = manual_regions or {}
    bounds = relative_rect_to_bounds(image, manual_regions.get("nature"))
    if not bounds:
        return None
    x0, y0, x1, y1 = bounds
    height = y1 - y0
    if height < 60:
        return None
    rows, _score = detect_rows_in_region(image, x0, x1, y0, y1)
    if len(rows) == 6:
        gaps = [rows[index] - rows[index - 1] for index in range(1, 6)]
        row_step = median(gaps) or (height / 6)
    else:
        row_step = height / 6
        rows = [y0 + row_step * (index + 0.5) for index in range(6)]
    return {
        "rows": rows,
        "row_step": row_step,
        "x0": x0,
        "x1": x1,
        "y0": y0,
        "y1": y1,
        "manual": True,
    }


def yellow_runs(image, row_y, row_step, panel=None):
    h, w = image.shape[:2]
    if panel:
        if panel.get("manual"):
            x0 = max(0, int(panel["x0"]))
            x1 = min(w, int(panel["x1"]))
        else:
            pad = max(20, int((panel["x1"] - panel["x0"]) * 0.10))
            x0 = max(0, int(panel["x0"] - pad))
            x1 = min(w, max(int(panel["x1"] + pad), int(w * 0.72)))
    else:
        x0, x1 = 0, w
    y0 = max(0, int(row_y - row_step * 0.30))
    ww = max(1, x1 - x0)
    hh = min(h - y0, max(10, int(row_step * 0.85)))
    region = image[y0:y0 + hh, x0:x0 + ww]
    rgb = region[:, :, ::-1]
    mask = (rgb[:, :, 0] > 185) & (rgb[:, :, 1] > 125) & (rgb[:, :, 2] < 135) & (rgb[:, :, 0] > rgb[:, :, 2] * 1.45)
    cols = []
    for x in range(mask.shape[1]):
        ys = np.where(mask[:, x])[0]
        if len(ys):
            cols.append({"x": x0 + x, "minY": y0 + int(ys.min()), "maxY": y0 + int(ys.max()), "pixels": int(len(ys))})
    runs, run = [], None
    for col in cols:
        if run is None or col["x"] > run["end"] + 1:
            if run:
                runs.append(run)
            run = {"start": col["x"], "end": col["x"], "minY": col["minY"], "maxY": col["maxY"], "pixels": col["pixels"]}
        else:
            run["end"] = col["x"]
            run["minY"] = min(run["minY"], col["minY"])
            run["maxY"] = max(run["maxY"], col["maxY"])
            run["pixels"] += col["pixels"]
    if run:
        runs.append(run)
    for run in runs:
        run["width"] = run["end"] - run["start"] + 1
        run["height"] = run["maxY"] - run["minY"] + 1
    return [r for r in runs if r["width"] >= 3 and r["height"] >= 6 and r["pixels"] >= 12]


def run_yellow_mask(image, run):
    crop = image[run["minY"]:run["maxY"] + 1, run["start"]:run["end"] + 1]
    rgb = crop[:, :, ::-1]
    return ((rgb[:, :, 0] > 185) & (rgb[:, :, 1] > 125) & (rgb[:, :, 2] < 135)).astype(np.uint8)


def digit_features(mask):
    small = cv2.resize(mask * 255, (24, 32), interpolation=cv2.INTER_AREA) > 80

    def occ(x0, x1, y0, y1):
        box = small[int(y0 * 32):int(y1 * 32), int(x0 * 24):int(x1 * 24)]
        return float(box.mean()) if box.size else 0.0

    return {
        "top": occ(0.18, 0.82, 0.00, 0.18),
        "mid": occ(0.15, 0.85, 0.40, 0.60),
        "bot": occ(0.18, 0.82, 0.80, 1.00),
        "ul": occ(0.00, 0.35, 0.16, 0.45),
        "ur": occ(0.65, 1.00, 0.16, 0.45),
        "ll": occ(0.00, 0.35, 0.55, 0.84),
        "lr": occ(0.65, 1.00, 0.55, 0.84),
        "center": occ(0.38, 0.62, 0.20, 0.80),
    }


def plus_score(image, run):
    features = digit_features(run_yellow_mask(image, run))
    if features["mid"] < 0.78 or features["center"] < 0.78:
        return 0.0
    if features["top"] > 0.70 and features["bot"] > 0.70:
        return 0.0
    return features["mid"] + features["center"] - (features["top"] + features["bot"]) * 0.35


def classify_digit(image, run):
    features = digit_features(run_yellow_mask(image, run))
    active = {key: features[key] > 0.62 for key in ("top", "mid", "bot", "ul", "ur", "ll", "lr")}
    pattern = {key for key, value in active.items() if value}
    templates = {
        0: {"top", "bot", "ul", "ur", "ll", "lr"},
        2: {"top", "mid", "bot", "ur", "ll"},
        3: {"top", "mid", "bot", "ur", "lr"},
        5: {"top", "mid", "bot", "ul", "lr"},
        6: {"top", "mid", "bot", "ul", "ll", "lr"},
        7: {"top", "ur", "lr"},
        8: {"top", "mid", "bot", "ul", "ur", "ll", "lr"},
        9: {"top", "mid", "bot", "ul", "ur", "lr"},
    }
    if features["center"] > 0.78 and features["mid"] < 0.65 and features["ul"] < 0.35 and features["ur"] < 0.35:
        return 1
    if run["width"] <= 4 and run["height"] <= 7 and features["top"] > 0.85 and features["bot"] > 0.85 and features["ul"] < 0.25 and features["ll"] < 0.25 and features["mid"] < 0.55:
        return 1
    if features["bot"] < 0.56 and features["lr"] > 0.62 and (features["ul"] > 0.58 or features["mid"] > 0.62):
        return 4
    if features["top"] > 0.82 and features["bot"] > 0.82 and features["ll"] > 0.58 and features["ur"] > 0.50 and features["lr"] < 0.22 and features["ul"] < 0.35:
        return 2
    if features["top"] > 0.72 and features["ur"] > 0.78 and features["ul"] < 0.35 and features["ll"] < 0.12 and features["mid"] < 0.58 and features["bot"] < 0.68:
        return 7
    if features["top"] > 0.42 and features["ur"] > 0.82 and features["ul"] < 0.35 and features["ll"] < 0.15 and features["mid"] < 0.60 and features["bot"] < 0.65:
        return 7
    if features["top"] > 0.85 and features["ur"] > 0.45 and features["ul"] < 0.25 and features["ll"] < 0.15 and features["mid"] < 0.68 and features["bot"] < 0.72:
        return 7
    if features["top"] > 0.62 and features["ur"] > 0.55 and features["lr"] > 0.45 and features["ll"] < 0.45 and features["bot"] < 0.58:
        return 7
    if (
        run["width"] <= 5 and run["height"] <= 7
        and features["top"] > 0.85 and features["mid"] > 0.65 and features["bot"] > 0.75
        and features["ul"] > 0.65 and features["ll"] > 0.50 and features["lr"] > 0.75
        and features["ur"] > 0.35
    ):
        return 8
    if features["center"] < 0.18 and features["top"] > 0.75 and features["bot"] > 0.75:
        return 0
    if features["ul"] < 0.45 and features["ll"] < 0.45 and features["mid"] > 0.70 and features["ur"] > 0.62 and features["lr"] > 0.62:
        return 3
    if features["ul"] > 0.45 and features["ll"] < 0.50 and features["mid"] > 0.70 and features["ur"] > 0.62 and features["lr"] > 0.62:
        return 9
    if features["ur"] < 0.60 and features["mid"] > 0.70 and features["ll"] > 0.62 and features["lr"] > 0.62:
        return 6

    best_digit, best_score = None, -1
    for digit, expected in templates.items():
        score = len(pattern & expected) - len(pattern ^ expected) * 0.55
        if score > best_score:
            best_digit, best_score = digit, score
    return best_digit if best_score >= 2.6 else None


def parse_iv_display_value(digits):
    if not digits:
        return 0
    if len(digits) >= 2 and digits[0] is not None and digits[1] is not None:
        value = digits[0] * 10 + digits[1]
        return value if value in VALID_IV_DISPLAY_VALUES else 0
    if len(digits) == 1 and digits[0] in VALID_IV_DISPLAY_VALUES:
        return digits[0]
    return 0


def detect_iv_displays(image, rows, row_step, panel=None, manual_regions=None):
    manual_regions = manual_regions or {}
    if not manual_regions.get("nature"):
        return {stat: 0 for stat in SCREEN_STAT_ORDER}
    values = {}
    plus_min_width = max(4, int(row_step * 0.14))
    plus_max_width = max(34, int(row_step * 0.19))
    digit_min_width = max(3, int(row_step * 0.018))
    digit_min_height = max(5, int(row_step * 0.10))
    if panel:
        digit_column_start = panel["x0"] + (panel["x1"] - panel["x0"]) * 0.66
    else:
        digit_column_start = 0
    for stat, row_y in zip(SCREEN_STAT_ORDER, rows):
        runs = yellow_runs(image, row_y, row_step, panel)
        plus_candidates = [
            (i, plus_score(image, r))
            for i, r in enumerate(runs)
            if plus_min_width <= r["width"] <= plus_max_width and r["height"] >= max(5, int(row_step * 0.12))
        ]
        plus_candidates = [item for item in plus_candidates if item[1] > 0]
        value = 0
        for plus_index, _score in sorted(plus_candidates, key=lambda item: runs[item[0]]["start"]):
            plus_run = runs[plus_index]
            digit_runs = [
                r for r in runs[plus_index + 1:]
                if r["width"] >= digit_min_width
                and r["height"] >= digit_min_height
                and r["start"] - plus_run["end"] <= max(120, int(row_step * 1.35))
            ]
            digits = [classify_digit(image, r) for r in digit_runs[:2]]
            parsed = parse_iv_display_value(digits)
            if parsed:
                value = parsed
                break
        if not value:
            digit_runs = [
                r for r in runs
                if r["start"] >= digit_column_start
                and r["width"] >= digit_min_width
                and r["height"] >= digit_min_height
            ]
            digits = [classify_digit(image, r) for r in sorted(digit_runs, key=lambda item: item["start"])[:2]]
            parsed = parse_iv_display_value(digits)
            if parsed:
                value = parsed
        values[stat] = value
    return values


def infer_iv_multiplier(displays):
    positives = [value for value in displays.values() if isinstance(value, int) and value > 0]
    if not positives:
        return 1
    candidates = []
    for multiplier in range(1, 7):
        bases = []
        for value in positives:
            if value % multiplier != 0:
                break
            base = value // multiplier
            if base not in BASE_IV_VALUES:
                break
            bases.append(base)
        else:
            candidates.append((abs(max(bases) - 10), -multiplier, multiplier))
    return min(candidates)[2] if candidates else 1


def normalize_iv_displays(displays, multiplier):
    normalized = {}
    for stat, value in displays.items():
        if not value or value % multiplier != 0:
            normalized[stat] = 0
            continue
        base = value // multiplier
        normalized[stat] = base if base in BASE_IV_VALUES else 0
    return normalized


def crop_manual_ocr_line(image, rect, target_height=48):
    bounds = relative_rect_to_bounds(image, rect)
    if not bounds:
        return None
    x0, y0, x1, y1 = bounds
    crop = image[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    scale = target_height / max(1, crop.shape[0])
    interpolation = cv2.INTER_CUBIC if scale >= 1 else cv2.INTER_AREA
    return cv2.resize(crop, None, fx=scale, fy=scale, interpolation=interpolation)


def trait_pet_name(pet_data, trait, plus, preferred_name=""):
    cache_key = (normalize_text(trait), plus or "", normalize_text(preferred_name))
    if cache_key in pet_data._trait_pet_cache:
        return pet_data._trait_pet_cache[cache_key]

    if normalize_text(trait) in pet_data.nature_name_set and not normalize_text(preferred_name):
        result = ("", 0.0, "")
        pet_data._trait_pet_cache[cache_key] = result
        return result

    matches = pet_data.unique_pets(pet_data.find_pets_by_trait(trait))
    if not matches:
        result = ("", 0.0, "")
        pet_data._trait_pet_cache[cache_key] = result
        return result
    preferred_key = normalize_text(preferred_name)
    if preferred_key:
        for pet in matches:
            if normalize_text(pet.get("名字", "")) == preferred_key:
                result = (pet.get("名字", ""), 1.0, pet.get("特性", ""))
                pet_data._trait_pet_cache[cache_key] = result
                return result
    result = (matches[0].get("名字", ""), 1.0, matches[0].get("特性", ""))
    pet_data._trait_pet_cache[cache_key] = result
    return result


def ocr_result(ocr: RapidOCR, image, detect=True):
    # RapidOCR keeps use_det/use_cls/use_rec on the instance after every call.
    # Pass all three flags explicitly so the fast single-line path cannot leak
    # into later detector-based OCR calls.
    return ocr(image, use_det=detect, use_cls=False, use_rec=True)


def ocr_text(ocr: RapidOCR, image, detect=True) -> str:
    result = ocr_result(ocr, image, detect)
    return "".join(result.txts or [])


def nature_by_stats(plus, minus):
    return next((n for n in NATURES if n["plus"] == plus and n["minus"] == minus), None)


def expand_groups(groups):
    sets = [[]]
    for group in groups:
        sets = [base + [stat] for base in sets for stat in group]
    return [s for s in sets if len(set(s)) == len(s)]


def compute_iv_plan(targets, ivs, multiplier=1):
    fit, ability = 0, 0
    final = {}
    missing = []
    for stat in targets:
        value = ivs.get(stat)
        if value and value > 0:
            final[stat] = value
        else:
            missing.append(stat)
    donors = sorted(
        [{"stat": stat, "iv": value} for stat, value in ivs.items() if stat not in targets and value and value > 0],
        key=lambda item: item["iv"], reverse=True
    )
    steps = []
    for stat in missing:
        fit += 1
        donor = donors.pop(0) if donors else None
        if donor:
            final[stat] = donor["iv"]
            shown = donor["iv"] * multiplier
            steps.append(f"适格钥匙：{donor['stat']}+{shown} -> {stat}+{shown}")
        else:
            final[stat] = 8
            steps.append(f"适格钥匙：新增 {stat}+{8 * multiplier}")
    for stat in targets:
        add = max(0, 10 - int(final.get(stat, 0)))
        ability += add
        if add:
            steps.append(f"能力钥匙：{stat} 补 {add} 个到 +{10 * multiplier}")
    return {"fit": fit, "ability": ability, "steps": steps, "targets": targets, "total": fit + ability}


def best_plan(pet_data, pet_name, plus, minus, ivs, multiplier=1):
    pet = pet_data.find_pet(pet_name)
    if not pet:
        return None, "未匹配到推荐表精灵"
    variants = []
    for variant in pet_data.recommendation_variants(pet_name):
        target_natures = []
        for name in variant["natures"]:
            nature = NATURE_BY_NAME.get(name)
            if nature and nature["plus"] == plus:
                target_natures.append(nature)
        if variant["natures"] and not target_natures:
            continue
        target_nature = next((n for n in target_natures if n["minus"] == minus), target_natures[0] if target_natures else None)
        mirror = 0 if not target_nature or target_nature["minus"] == minus else 1
        combos = expand_groups(variant["statGroups"])
        iv_plan = min((compute_iv_plan(combo, ivs, multiplier) for combo in combos), key=lambda p: (p["total"], p["fit"], p["ability"])) if combos else {"fit": 0, "ability": 0, "steps": [], "targets": [], "total": 0}
        variants.append({"variant": variant, "nature": target_nature, "mirror": mirror, "iv": iv_plan, "total": mirror + iv_plan["total"]})
    if not variants:
        return None, f"没有 {plus or '?'} 增益对应方案"
    variants.sort(key=lambda p: (p["total"], p["iv"]["fit"], p["iv"]["ability"]))
    return variants[0], ""


@dataclass
class Recognition:
    pet: str
    pet_score: float
    plus: str
    minus: str
    ivs: dict
    iv_displays: dict
    iv_multiplier: int
    ocr_raw: str
    trait: str
    elapsed_ms: int
    plan: object
    plan_error: str


class Recognizer:
    def __init__(self, pet_data: PetData, compute_best_plan=True):
        self.pet_data = pet_data
        self.compute_best_plan = compute_best_plan
        self.capture = CaptureSession(PROCESS_NAME)
        self.ocr = RapidOCR()
        self.panel_cache = {}
        self.manual_regions_by_shape = {}

    def set_manual_regions(self, regions):
        self.manual_regions_by_shape = regions or {}

    def manual_regions_for_image(self, image):
        h, w = image.shape[:2]
        return self.manual_regions_by_shape.get(f"{w}x{h}", {})

    def warm_up(self):
        line = np.full((48, 180, 3), 255, dtype=np.uint8)
        page = np.full((120, 260, 3), 255, dtype=np.uint8)
        cv2.putText(line, "test", (8, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 0), 2, cv2.LINE_AA)
        cv2.putText(page, "test", (18, 74), cv2.FONT_HERSHEY_SIMPLEX, 1.4, (0, 0, 0), 3, cv2.LINE_AA)
        for image, detect in ((line, False), (page, True)):
            try:
                ocr_result(self.ocr, image, detect=detect)
            except Exception:
                pass

    def recognize_pet_name(self, image):
        name, score, raw, _candidates = self.recognize_pet_name_candidates(image)
        return name, score, raw

    def recognize_pet_name_candidates(self, image):
        manual_regions = self.manual_regions_for_image(image)
        best_name, best_score, best_raw = "", 0.0, ""
        candidates_by_name = {}
        manual_crop = crop_manual_ocr_line(image, manual_regions.get("name"), target_height=64)
        if manual_crop is not None:
            raw = ocr_text(self.ocr, manual_crop, detect=False)
            candidates = self.pet_data.name_candidates(raw)
            name, score = self.pet_data.guess_name(raw)
            if raw:
                best_raw = raw
            for candidate_name, candidate_score in candidates:
                candidates_by_name[candidate_name] = max(candidates_by_name.get(candidate_name, 0.0), candidate_score)
            if score > best_score:
                best_name, best_score, best_raw = name, score, raw
        name_candidates = sorted(candidates_by_name.items(), key=lambda item: (-item[1], len(item[0]), item[0]))[:8]
        return best_name, best_score, best_raw, name_candidates

    def unique_trait_for_pet(self, name):
        traits = {
            pet.get("特性", "")
            for pet in self.pet_data.by_name.get(normalize_text(name), [])
            if pet.get("特性")
        }
        return next(iter(traits)) if len(traits) == 1 else ""

    def unique_pet_for_trait(self, trait):
        matches = self.pet_data.unique_pets(self.pet_data.find_pets_by_trait_exact(trait))
        if len(matches) != 1:
            return ""
        return matches[0].get("名字", "")

    def pet_has_trait(self, name, trait):
        target = normalize_text(trait)
        if not target:
            return False
        return any(
            normalize_text(pet.get("特性", "")) == target
            for pet in self.pet_data.by_name.get(normalize_text(name), [])
        )

    def resolve_pet_by_name_and_trait(self, trait, name_candidates=None):
        matches = self.pet_data.unique_pets(self.pet_data.find_pets_by_trait_exact(trait))
        if not matches:
            matches = self.pet_data.unique_pets(self.pet_data.find_pets_by_trait(trait))
        if not matches:
            return "", 0.0, ""
        name_candidates = name_candidates or []
        by_name = {normalize_text(pet.get("名字", "")): pet for pet in matches}
        for candidate_name, candidate_score in name_candidates:
            pet = by_name.get(normalize_text(candidate_name))
            if pet:
                return pet.get("名字", ""), max(0.93, candidate_score), pet.get("特性", "")
        if len(matches) == 1:
            pet = matches[0]
            return pet.get("名字", ""), 1.0, pet.get("特性", "")
        pet = matches[0]
        return pet.get("名字", ""), 0.88, pet.get("特性", "")

    def trait_conflicts_current_nature(self, trait, plus, minus="", raw=""):
        nature = nature_by_stats(plus, minus) if plus and minus else None
        if not nature:
            return normalize_text(trait) in self.pet_data.nature_name_set
        trait_key = normalize_text(trait)
        nature_key = normalize_text(nature["name"])
        raw_key = normalize_text(raw)
        if not trait_key:
            return False
        if trait_key == nature_key:
            return True
        if (nature_key, trait_key) in AMBIGUOUS_NATURE_TRAIT_PAIRS and nature_key in raw_key and trait_key not in raw_key:
            return True
        return False

    def resolve_trait_result(self, raw, trait, plus, minus="", name="", name_score=0.0, name_raw="", name_candidates=None, trusted_trait=False):
        name_candidates = list(name_candidates or [])
        if name and not any(normalize_text(candidate_name) == normalize_text(name) for candidate_name, _score in name_candidates):
            name_candidates.insert(0, (name, name_score))
        if not trusted_trait and self.trait_conflicts_current_nature(trait, plus, minus, raw):
            if name:
                expected_trait = self.unique_trait_for_pet(name)
                return raw or name_raw, expected_trait or "", name, name_score, expected_trait
            return raw, "", "", 0.0, ""
        pet, score, matched_trait = self.resolve_pet_by_name_and_trait(trait, name_candidates)
        if pet:
            return raw, matched_trait or trait, pet, score, matched_trait
        pet, score, matched_trait = trait_pet_name(self.pet_data, trait, plus, name if name_score >= 0.92 else "")
        return raw, matched_trait or trait, pet, score, matched_trait

    def recognize_trait(self, image, plus, minus=""):
        manual_regions = self.manual_regions_for_image(image)
        name, name_score, name_raw, name_candidates = self.recognize_pet_name_candidates(image)
        manual_trait_crop = crop_manual_ocr_line(image, manual_regions.get("trait"), target_height=54)
        if manual_trait_crop is not None:
            manual_raw = ocr_text(self.ocr, manual_trait_crop, detect=False)
            manual_trait = self.pet_data.match_trait(manual_raw)
            if manual_trait:
                return self.resolve_trait_result(
                    manual_raw,
                    manual_trait,
                    plus,
                    minus,
                    name,
                    name_score,
                    name_raw,
                    name_candidates,
                    trusted_trait=True,
                )
            return manual_raw, manual_raw, "", 0.0, ""
        return "", "", "", 0.0, ""

    def read_panel_stats(self, image, panel):
        manual_regions = self.manual_regions_for_image(image)
        manual_panel = manual_stats_panel(image, manual_regions)
        if manual_panel:
            panel = manual_panel
        rows, row_step = panel["rows"], panel["row_step"]
        arrows = detect_arrows(image, rows, row_step, panel, manual_regions)
        iv_displays = detect_iv_displays(image, rows, row_step, panel, manual_regions)
        return rows, row_step, arrows, iv_displays

    def panel_result_valid(self, arrows, iv_displays):
        return bool(arrows.get("plus") and arrows.get("minus") and any(iv_displays.values()))

    def recognize(self) -> Recognition:
        started = time.perf_counter()
        image = self.capture.frame()
        image_shape = image.shape[:2]
        panel = self.panel_cache.get(image_shape)
        if panel:
            rows, row_step, arrows, iv_displays = self.read_panel_stats(image, panel)
            if not self.panel_result_valid(arrows, iv_displays):
                panel = None
        if not panel:
            panel = detect_stat_panel(image)
            rows, row_step, arrows, iv_displays = self.read_panel_stats(image, panel)
            if self.panel_result_valid(arrows, iv_displays):
                self.panel_cache[image_shape] = panel
        iv_multiplier = infer_iv_multiplier(iv_displays)
        ivs = normalize_iv_displays(iv_displays, iv_multiplier)

        # OCR trait text
        trait_raw, trait, pet, score, _matched_trait = self.recognize_trait(
            image,
            arrows.get("plus", ""),
            arrows.get("minus", ""),
        )

        # Name, trait, and nature now come only from user-calibrated regions;
        # keep the raw manual trait OCR text for display/debug context.
        raw = trait_raw

        plan = None
        plan_error = ""
        if self.compute_best_plan:
            plan, plan_error = best_plan(self.pet_data, pet, arrows.get("plus", ""), arrows.get("minus", ""), ivs, iv_multiplier)
        elif not pet:
            plan_error = "未匹配到推荐表精灵"
        return Recognition(
            pet=pet,
            pet_score=score,
            plus=arrows.get("plus", ""),
            minus=arrows.get("minus", ""),
            ivs=ivs,
            iv_displays=iv_displays,
            iv_multiplier=iv_multiplier,
            ocr_raw=raw,
            trait=trait,
            elapsed_ms=int((time.perf_counter() - started) * 1000),
            plan=plan,
            plan_error=plan_error,
        )

if __name__ == "__main__":
    print("PetAnalyzer desktop entry is desktop_float.py")
