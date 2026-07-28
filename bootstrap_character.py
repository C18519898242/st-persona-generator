#!/usr/bin/env python3
"""从人物卡与 sample 参考图生成 profile.json、头像与全身像（第一阶段）。"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.error import URLError
from urllib.parse import quote

from PIL import Image, ImageOps, UnidentifiedImageError

import generate_with_gemini as gemini


class BootstrapError(RuntimeError):
    """Bootstrap 配置或生成失败。"""


SAMPLE_SUFFIXES = {".jpg", ".jpeg", ".png"}

COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")
POSITION_RE = re.compile(r"[A-Za-z0-9.%\s-]+")

DEFAULT_DISPLAY = {
    "frontScale": 1.04,
    "sideScale": 1.04,
    "backScale": 1.04,
    "expressionAspect": 0.7,
    "expressionPosition": "center 28%",
}

FIXED_VIEWS = [
    {"label": "正面", "file": "view_front.jpg", "className": "focus-front"},
    {"label": "侧面", "file": "view_side.jpg", "className": "focus-side"},
    {"label": "背面", "file": "view_back.jpg", "className": "focus-back"},
]
FIXED_EXPRESSIONS = [
    {"label": "平静", "file": "exp_calm.jpg"},
    {"label": "微笑", "file": "exp_smile.jpg"},
    {"label": "认真", "file": "exp_serious.jpg"},
    {"label": "惊讶", "file": "exp_surprise.jpg"},
    {"label": "思考", "file": "exp_think.jpg"},
    {"label": "羞涩", "file": "exp_shy.jpg"},
]
FIXED_ITEM_FILES = [
    "item_blouse.jpg",
    "item_skirt.jpg",
    "item_hose.jpg",
    "item_shoes.jpg",
]
DEFAULT_ITEM_LABELS = ["上装", "下装", "丝袜", "鞋子"]
ITEM_SLOT_HINTS = (
    "上装单件（如衬衫、T恤、外套、开衫，禁止整套造型名）",
    "下装单件（如短裙、长裤、半身裙，禁止整套造型名）",
    "袜类单件（如丝袜、连裤袜、船袜；无袜可写肉色丝袜或光腿用肉色丝）",
    "鞋类单件（如高跟鞋、凉鞋、皮鞋，禁止整套造型名）",
)
# Labels that look like outfit/role names rather than a single garment.
_BAD_ITEM_LABEL_RE = re.compile(
    r"(警官|便装|制服|战斗|姿态|造型|套装|全身|立绘|角色|人物|"
    r"场景|职业装|工作装|日常装|私服|夜场)"
)


@dataclass(frozen=True)
class ResolvedPaths:
    root: Path
    character: str
    character_dir: Path
    card_path: Path
    sample_dir: Path
    sample_images: tuple[Path, ...]


@dataclass(frozen=True)
class CardData:
    name: str
    raw_text: str
    basic_facts: tuple[tuple[str, str], ...]
    appearance: str
    work_outfit: str
    personality: str
    description: str


_SECTION_RE = re.compile(
    r"【\s*([^】]+?)\s*】",
)


def resolve_paths(root: Path, character: str) -> ResolvedPaths:
    character_dir = Path(root).resolve() / character
    if not character_dir.is_dir():
        raise BootstrapError(f"人物目录不存在：{character_dir}")

    plain = character_dir / "人物卡.txt"
    named = character_dir / f"人物卡_{character}.txt"
    if plain.is_file():
        card_path = plain
    elif named.is_file():
        card_path = named
    else:
        raise BootstrapError(
            f"找不到人物卡，期望以下之一：\n- {plain}\n- {named}"
        )

    sample_dir = character_dir / "sample"
    if not sample_dir.is_dir():
        raise BootstrapError(f"找不到 sample 目录：{sample_dir}")

    samples = sorted(
        (
            path
            for path in sample_dir.iterdir()
            if path.is_file() and path.suffix.lower() in SAMPLE_SUFFIXES
        ),
        key=lambda path: path.name.lower(),
    )
    if not samples:
        raise BootstrapError(
            f"sample 目录中没有 jpg/png 参考图：{sample_dir}"
        )

    return ResolvedPaths(
        root=Path(root).resolve(),
        character=character,
        character_dir=character_dir,
        card_path=card_path,
        sample_dir=sample_dir,
        sample_images=tuple(samples),
    )


def _split_sections(text: str) -> dict[str, str]:
    matches = list(_SECTION_RE.finditer(text))
    sections: dict[str, str] = {}
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        # Keep first occurrence; also index by first token before /
        sections[title] = body
        head = title.split("/", 1)[0].strip().lower()
        sections.setdefault(head, body)
    return sections


def _extract_work_outfit(appearance_or_desc: str) -> str:
    lines = appearance_or_desc.splitlines()
    for index, line in enumerate(lines):
        stripped = line.strip()
        if "工作" in stripped and ("：" in stripped or ":" in stripped):
            # same-line value after colon
            for sep in ("：", ":"):
                if sep in stripped:
                    after = stripped.split(sep, 1)[1].strip()
                    if after and not after.startswith("-"):
                        return after
            # following bullet lines until blank or next major bullet category
            collected: list[str] = []
            for follow in lines[index + 1 :]:
                f = follow.strip()
                if not f:
                    if collected:
                        break
                    continue
                if f.startswith("-") or f.startswith("·"):
                    # stop if looks like another category label only
                    body = f.lstrip("-· ").strip()
                    if body.startswith("私下") or body.startswith("日常"):
                        break
                    if body.startswith("工作"):
                        continue
                    collected.append(body)
                elif collected:
                    break
            if collected:
                return "；".join(collected)
            return stripped
    # fallback: first clothing-like sentence
    for line in lines:
        if any(key in line for key in ("白大褂", "外套", "衬衫", "着装")):
            return line.strip()
    return appearance_or_desc.strip()[:200]


def _extract_basic_facts(text: str) -> tuple[tuple[str, str], ...]:
    facts: list[tuple[str, str]] = []
    for line in text.splitlines():
        stripped = line.strip().lstrip("-· ").strip()
        if "：" in stripped:
            label, value = stripped.split("：", 1)
        elif ":" in stripped:
            label, value = stripped.split(":", 1)
        else:
            continue
        label, value = label.strip(), value.strip()
        if label and value and len(label) <= 12:
            facts.append((label, value))
    return tuple(facts)


def parse_character_card(text: str) -> CardData:
    sections = _split_sections(text)
    name_body = sections.get("Name / 角色名") or sections.get("name") or ""
    name = ""
    for line in name_body.splitlines():
        line = line.strip()
        if line and not line.startswith("═"):
            name = line
            break

    description = (
        sections.get("Description / 角色描述")
        or sections.get("description")
        or ""
    )
    personality = (
        sections.get("Personality / 性格")
        or sections.get("personality")
        or ""
    )
    # appearance may be nested heading inside description
    appearance = description
    for key, body in sections.items():
        if "外貌" in key:
            appearance = body
            break

    work_outfit = _extract_work_outfit(appearance)
    if not work_outfit:
        work_outfit = _extract_work_outfit(description)

    basic_source = description
    for key, body in sections.items():
        if "基本信息" in key:
            basic_source = body
            break
    basic_facts = _extract_basic_facts(basic_source)

    return CardData(
        name=name.strip(),
        raw_text=text,
        basic_facts=basic_facts,
        appearance=appearance.strip(),
        work_outfit=work_outfit.strip(),
        personality=personality.strip(),
        description=description.strip(),
    )


def build_profile_skeleton(card: CardData, *, fallback_name: str) -> dict[str, Any]:
    name = card.name.strip() or fallback_name.strip()
    facts: list[dict[str, str]] = [
        {"label": label, "value": value} for label, value in card.basic_facts
    ]
    if not facts:
        facts = [{"label": "姓名", "value": name}]
    return {
        "schemaVersion": 1,
        "name": name,
        "nameEn": "",
        "tagline": "",
        "seal": {"letters": "", "cn": "", "en": ""},
        "assetDir": "assets_简介",
        "theme": {
            "accent": "#5B8FA8",
            "accentSoft": "#A8C4D4",
            "palette": [{"name": "占位", "color": "#F6F1E8"}],
        },
        "facts": facts,
        "factNote": "",
        "bio": "",
        "traits": [],
        "tags": [],
        "images": {
            "views": [dict(item) for item in FIXED_VIEWS],
            "expressions": [dict(item) for item in FIXED_EXPRESSIONS],
            "items": [
                {"label": label, "file": filename}
                for label, filename in zip(DEFAULT_ITEM_LABELS, FIXED_ITEM_FILES)
            ],
            "details": [
                {"label": "面部与发型", "file": "exp_calm.jpg"},
                {
                    "label": "职业装侧影",
                    "file": "view_side.jpg",
                    "className": "focus-full",
                },
            ],
        },
        "display": dict(DEFAULT_DISPLAY),
        "_work_outfit": card.work_outfit,
        "_personality": card.personality,
        "_appearance": card.appearance,
    }


def _normalize_hex_color(value: Any) -> str | None:
    """Return #RRGGBB or None if value cannot be coerced."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if COLOR_RE.fullmatch(text):
        return text
    # tolerate missing leading #
    if re.fullmatch(r"[0-9A-Fa-f]{6}", text):
        return f"#{text}"
    return None


def normalize_palette(raw: Any) -> list[dict[str, str]] | None:
    """Coerce common Gemini palette shapes into [{name, color}, ...].

    Accepts:
    - [{name, color}, ...]
    - ["#RRGGBB", ...] or with optional names as plain strings mixed in
    - [{color/#/hex: ..., name/label: ...}, ...]
    Returns None if nothing usable (caller keeps skeleton palette).
    """
    if not isinstance(raw, list) or not raw:
        return None
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(raw[:6]):
        if isinstance(item, str):
            color = _normalize_hex_color(item)
            if color is None:
                # plain name without color — skip
                continue
            normalized.append({"name": f"色{index + 1}", "color": color})
            continue
        if not isinstance(item, dict):
            continue
        name = (
            item.get("name")
            or item.get("label")
            or item.get("title")
            or f"色{index + 1}"
        )
        color_raw = (
            item.get("color")
            or item.get("hex")
            or item.get("value")
            or item.get("#")
        )
        color = _normalize_hex_color(color_raw)
        if color is None:
            continue
        if not isinstance(name, str) or not name.strip():
            name = f"色{index + 1}"
        normalized.append({"name": str(name).strip(), "color": color})
    if not normalized:
        return None
    return normalized[:6]


def merge_profile(
    skeleton: dict[str, Any],
    patch: dict[str, Any],
) -> dict[str, Any]:
    merged = json.loads(json.dumps(skeleton, ensure_ascii=False))
    # strip internal keys from output later; keep during fill
    for key in (
        "nameEn",
        "tagline",
        "factNote",
        "bio",
        "traits",
        "tags",
    ):
        if key in patch:
            merged[key] = patch[key]
    if isinstance(patch.get("seal"), dict):
        for key in ("letters", "cn", "en"):
            if key in patch["seal"]:
                merged["seal"][key] = patch["seal"][key]
    if isinstance(patch.get("theme"), dict):
        theme = patch["theme"]
        for key in ("accent", "accentSoft"):
            if key in theme:
                color = _normalize_hex_color(theme[key])
                merged["theme"][key] = color if color is not None else theme[key]
        palette = normalize_palette(theme.get("palette"))
        if palette is not None:
            merged["theme"]["palette"] = palette
    # some models put palette at top level
    top_palette = normalize_palette(patch.get("palette"))
    if top_palette is not None and (
        not isinstance(patch.get("theme"), dict)
        or normalize_palette(patch["theme"].get("palette")) is None
    ):
        merged["theme"]["palette"] = top_palette
    if isinstance(patch.get("facts"), list) and patch["facts"]:
        # allow value polish only if list of {label,value}
        polished: list[dict[str, str]] = []
        for item in patch["facts"]:
            if isinstance(item, dict) and item.get("label") and item.get("value"):
                polished.append(
                    {"label": str(item["label"]), "value": str(item["value"])}
                )
        if polished:
            merged["facts"] = polished
    character_name = str(merged.get("name") or "").strip()
    if isinstance(patch.get("images"), dict):
        items = patch["images"].get("items")
        if isinstance(items, list):
            for index, filename in enumerate(FIXED_ITEM_FILES):
                if index < len(items) and isinstance(items[index], dict):
                    label = items[index].get("label")
                    if isinstance(label, str) and label.strip():
                        cleaned = normalize_item_label(
                            label.strip(),
                            slot_index=index,
                            character_name=character_name,
                        )
                        if cleaned is not None:
                            merged["images"]["items"][index]["label"] = cleaned
                merged["images"]["items"][index]["file"] = filename
    # Fill any remaining bad/default labels from work outfit / traits text.
    fill_item_labels_from_card_text(
        merged,
        work_outfit=str(skeleton.get("_work_outfit") or ""),
        appearance=str(skeleton.get("_appearance") or ""),
        traits=merged.get("traits") if isinstance(merged.get("traits"), list) else [],
    )
    # re-apply locks
    merged["schemaVersion"] = 1
    merged["assetDir"] = "assets_简介"
    merged["images"]["views"] = [dict(item) for item in FIXED_VIEWS]
    merged["images"]["expressions"] = [dict(item) for item in FIXED_EXPRESSIONS]
    merged["images"]["details"] = [
        {"label": "面部与发型", "file": "exp_calm.jpg"},
        {
            "label": "职业装侧影",
            "file": "view_side.jpg",
            "className": "focus-full",
        },
    ]
    for index, filename in enumerate(FIXED_ITEM_FILES):
        merged["images"]["items"][index]["file"] = filename
    merged["display"] = dict(DEFAULT_DISPLAY)
    return merged


def _require_str(mapping: dict[str, Any], key: str, where: str) -> str:
    if key not in mapping or not isinstance(mapping[key], str) or not mapping[key].strip():
        raise BootstrapError(f"{where}.{key} 必须是非空字符串")
    return mapping[key]


def validate_bootstrap_profile(config: dict[str, Any]) -> None:
    if config.get("schemaVersion") != 1:
        raise BootstrapError("schemaVersion 必须为 1")
    for key in ("name", "nameEn", "tagline", "assetDir", "factNote", "bio"):
        _require_str(config, key, "profile")
    seal = config.get("seal")
    if not isinstance(seal, dict):
        raise BootstrapError("seal 必须是对象")
    for key in ("letters", "cn", "en"):
        _require_str(seal, key, "seal")
    if len(seal["letters"]) > 5 or len(seal["cn"]) > 3 or len(seal["en"]) > 12:
        raise BootstrapError("seal 字段长度超出限制")
    theme = config.get("theme")
    if not isinstance(theme, dict):
        raise BootstrapError("theme 必须是对象")
    for key in ("accent", "accentSoft"):
        color = _require_str(theme, key, "theme")
        if not COLOR_RE.fullmatch(color):
            raise BootstrapError(f"theme.{key} 必须是 #RRGGBB")
    palette = theme.get("palette")
    if not isinstance(palette, list) or not palette or len(palette) > 6:
        raise BootstrapError("theme.palette 需要 1–6 项")
    for index, swatch in enumerate(palette):
        if not isinstance(swatch, dict):
            raise BootstrapError(
                f"palette[{index}] 无效：期望对象 {{name, color}}，"
                f"实际为 {type(swatch).__name__}: {swatch!r}"
            )
        _require_str(swatch, "name", f"palette[{index}]")
        color = _require_str(swatch, "color", f"palette[{index}]")
        if not COLOR_RE.fullmatch(color):
            raise BootstrapError(f"palette[{index}].color 必须是 #RRGGBB，实际为 {color!r}")
    facts = config.get("facts")
    if not isinstance(facts, list) or not facts:
        raise BootstrapError("facts 至少一项")
    for index, fact in enumerate(facts):
        if not isinstance(fact, dict):
            raise BootstrapError(f"facts[{index}] 无效")
        _require_str(fact, "label", f"facts[{index}]")
        _require_str(fact, "value", f"facts[{index}]")
    for key in ("traits", "tags"):
        values = config.get(key)
        if not isinstance(values, list) or not values:
            raise BootstrapError(f"{key} 至少一项")
        for index, value in enumerate(values):
            if not isinstance(value, str) or not value.strip():
                raise BootstrapError(f"{key}[{index}] 必须非空字符串")
    display = config.get("display")
    if not isinstance(display, dict):
        raise BootstrapError("display 必须是对象")
    for key in ("frontScale", "sideScale", "backScale"):
        number = display.get(key)
        if isinstance(number, bool) or not isinstance(number, (int, float)):
            raise BootstrapError(f"display.{key} 必须是数字")
        if not 0.8 <= float(number) <= 1.35:
            raise BootstrapError(f"display.{key} 超出范围")
    aspect = display.get("expressionAspect")
    if isinstance(aspect, bool) or not isinstance(aspect, (int, float)):
        raise BootstrapError("display.expressionAspect 必须是数字")
    if not 0.45 <= float(aspect) <= 1.4:
        raise BootstrapError("display.expressionAspect 超出范围")
    position = _require_str(display, "expressionPosition", "display")
    if not POSITION_RE.fullmatch(position):
        raise BootstrapError("display.expressionPosition 含非法字符")

    images = config.get("images")
    if not isinstance(images, dict):
        raise BootstrapError("images 必须是对象")
    expected = {
        "views": [name for name, _, _ in gemini.EXPECTED_ASSETS["views"]],
        "expressions": [name for name, _, _ in gemini.EXPECTED_ASSETS["expressions"]],
        "items": [name for name, _, _ in gemini.EXPECTED_ASSETS["items"]],
    }
    for group, expected_names in expected.items():
        entries = images.get(group)
        if not isinstance(entries, list):
            raise BootstrapError(f"images.{group} 必须是数组")
        actual = [
            entry.get("file") if isinstance(entry, dict) else None for entry in entries
        ]
        if actual != expected_names:
            raise BootstrapError(
                f"images.{group} 文件顺序必须为：{', '.join(expected_names)}"
            )
        for entry in entries:
            if not isinstance(entry.get("label"), str) or not entry["label"].strip():
                raise BootstrapError(f"images.{group} 存在空 label")
    details = images.get("details")
    if not isinstance(details, list) or len(details) < 1:
        raise BootstrapError("images.details 至少一项")


def profile_for_disk(config: dict[str, Any]) -> dict[str, Any]:
    """Drop internal underscore keys before writing."""
    return {key: value for key, value in config.items() if not key.startswith("_")}


def normalize_item_label(
    label: str,
    *,
    slot_index: int,
    character_name: str = "",
) -> str | None:
    """Return a single-garment label, or None if the model label is unusable."""
    text = label.strip()
    if not text:
        return None
    # Reject "角色名+造型" style labels.
    if character_name and character_name in text and len(text) <= len(character_name) + 8:
        return None
    if character_name and text.startswith(character_name):
        remainder = text[len(character_name) :].strip(" ·-_")
        if remainder and _BAD_ITEM_LABEL_RE.search(remainder):
            return None
        if remainder and len(remainder) <= 6 and _BAD_ITEM_LABEL_RE.search(text):
            return None
    if _BAD_ITEM_LABEL_RE.search(text):
        return None
    # Too vague defaults are kept only if not pure category words from skeleton.
    return text


def _looks_like_garment_phrase(text: str) -> bool:
    garment_keys = (
        "衫", "恤", "衣", "裙", "裤", "袜", "鞋", "靴", "高跟", "凉鞋",
        "开衫", "外套", "夹克", "大衣", "背心", "丝袜", "连裤", "衬衫",
        "T恤", "t恤", "罩衫", "卫衣", "羽绒服", "风衣",
    )
    return any(key in text for key in garment_keys)


def extract_garment_candidates(*texts: str) -> list[str]:
    """Pull short garment phrases from work outfit / traits prose."""
    candidates: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        # Split on common Chinese/English separators.
        parts = re.split(r"[，,、；;。/\n\|]+", text)
        for part in parts:
            piece = part.strip()
            piece = re.sub(r"^[\-\*·•\d\.\)\s]+", "", piece)
            piece = re.sub(r"^(内搭|外搭|下着|上穿|脚穿|穿着)\s*", "", piece)
            if len(piece) < 2 or len(piece) > 24:
                continue
            if not _looks_like_garment_phrase(piece):
                continue
            if piece in seen:
                continue
            seen.add(piece)
            candidates.append(piece)
    return candidates


def fill_item_labels_from_card_text(
    config: dict[str, Any],
    *,
    work_outfit: str,
    appearance: str,
    traits: list[Any],
) -> None:
    """Ensure items are four single garments, not outfit/role names."""
    items = config.get("images", {}).get("items")
    if not isinstance(items, list) or len(items) < 4:
        return
    character_name = str(config.get("name") or "")
    trait_texts = [str(t) for t in traits if isinstance(t, str)]
    candidates = extract_garment_candidates(work_outfit, appearance, *trait_texts)

    slot_patterns = (
        ("恤", "衫", "衣", "外套", "开衫", "夹克", "背心", "罩衫", "卫衣"),
        ("裙", "裤"),
        ("袜", "丝"),
        ("鞋", "靴", "高跟", "凉鞋", "拖鞋"),
    )

    def pick_for_slot(index: int) -> str | None:
        keys = slot_patterns[index]
        for cand in candidates:
            if any(key in cand for key in keys):
                return cand
        return None

    for index in range(4):
        entry = items[index]
        if not isinstance(entry, dict):
            continue
        current = str(entry.get("label") or "").strip()
        cleaned = normalize_item_label(
            current, slot_index=index, character_name=character_name
        )
        if cleaned is not None and _looks_like_garment_phrase(cleaned):
            entry["label"] = cleaned
            continue
        picked = pick_for_slot(index)
        if picked is not None:
            entry["label"] = picked
        elif cleaned is not None:
            entry["label"] = cleaned
        else:
            entry["label"] = DEFAULT_ITEM_LABELS[index]
        entry["file"] = FIXED_ITEM_FILES[index]


Transport = Callable[
    [str, dict[str, str], dict[str, Any], float],
    dict[str, Any],
]


def _extract_text(response: dict[str, Any]) -> str:
    candidates = response.get("candidates")
    if not isinstance(candidates, list):
        raise gemini.RetryableGenerationError("Gemini 没有返回文本")
    chunks: list[str] = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        content = candidate.get("content")
        if not isinstance(content, dict):
            continue
        parts = content.get("parts")
        if not isinstance(parts, list):
            continue
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                chunks.append(part["text"])
    text = "\n".join(chunks).strip()
    if not text:
        raise gemini.RetryableGenerationError("Gemini 返回空文本")
    return text


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        # try to locate first {...}
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            try:
                data = json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError as exc2:
                raise gemini.RetryableGenerationError(
                    "Gemini 文本不是有效 JSON"
                ) from exc2
        else:
            raise gemini.RetryableGenerationError(
                "Gemini 文本不是有效 JSON"
            ) from exc
    if not isinstance(data, dict):
        raise gemini.RetryableGenerationError("Gemini JSON 顶层必须是对象")
    return data


def build_profile_text_prompt(card: CardData, skeleton: dict[str, Any]) -> str:
    palette_example = (
        '{"name":"暖米白","color":"#F6F1E8"},'
        '{"name":"雾蓝","color":"#7FA3B8"}'
    )
    return (
        "你是人物设定资料助手。根据人物卡摘要，输出一个 JSON 对象，不要 Markdown。"
        "角色为虚构成年女性，完整着装，非露骨。"
        "字段：nameEn, tagline, seal{letters,cn,en}, theme{accent,accentSoft,palette},"
        "factNote, bio, traits(数组), tags(数组), images.items(长度4，每项含 label)。"
        "theme.palette 必须是对象数组，每项形如 {\"name\":\"中文名\",\"color\":\"#RRGGBB\"}，"
        f"例如 [{palette_example}]；禁止只写颜色字符串数组。"
        "theme.accent / accentSoft 也必须是 #RRGGBB。"
        "seal.letters≤5, cn≤3, en≤12。"
        "images.items 必须恰好 4 项，且每项 label 是【单件衣物名称】，顺序固定为："
        f"1){ITEM_SLOT_HINTS[0]}；2){ITEM_SLOT_HINTS[1]}；"
        f"3){ITEM_SLOT_HINTS[2]}；4){ITEM_SLOT_HINTS[3]}。"
        "正确示例：[{\"label\":\"白色短袖T恤\"},{\"label\":\"桔红色短裙\"},"
        "{\"label\":\"肉色丝袜\"},{\"label\":\"白色凉鞋\"}]。"
        "错误示例（禁止）：严慧雯警官、便装、制服、战斗姿态、整套造型、角色名+场合。"
        "不要把人物名写进 item label。"
        f"人物中文名：{skeleton['name']}。"
        f"工作装：{card.work_outfit}。"
        f"性格：{card.personality}。"
        f"外貌：{card.appearance}。"
        f"基本信息：{json.dumps(skeleton.get('facts', []), ensure_ascii=False)}。"
        "bio 用第三人称中文，traits 侧重视觉与默认工作装单件。"
    )


def request_profile_patch(
    *,
    card: CardData,
    skeleton: dict[str, Any],
    api_key: str,
    base_url: str,
    model: str,
    transport: Transport,
    sleeper: Callable[[float], None] = time.sleep,
    timeout: float = 180.0,
    max_attempts: int = 3,
) -> dict[str, Any]:
    """Request Gemini text patch, merge into skeleton, and validate.

    Retries on transport/JSON failures and on merge/validation failures
    (invalid model output), up to max_attempts.
    """
    encoded_model = quote(model, safe="-.()")
    url = f"{base_url.rstrip('/')}/models/{encoded_model}:generateContent"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": build_profile_text_prompt(card, skeleton)}],
            }
        ],
        "generationConfig": {
            "responseModalities": ["TEXT"],
            "temperature": 0.4,
        },
    }
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = transport(url, headers, payload, timeout)
            patch = _parse_json_object(_extract_text(response))
            merged = merge_profile(skeleton, patch)
            validate_bootstrap_profile(merged)
            return merged
        except gemini.HttpStatusError as exc:
            retryable = exc.status == 429 or 500 <= exc.status <= 599
            if not retryable or attempt == max_attempts:
                raise
            last_error = exc
        except (
            gemini.RetryableGenerationError,
            BootstrapError,
            URLError,
            TimeoutError,
            ConnectionError,
        ) as exc:
            if attempt == max_attempts:
                raise
            last_error = exc
        sleeper(float(attempt))
        print(
            f"重试 profile JSON：第 {attempt + 1}/{max_attempts} 次"
            f"（{type(last_error).__name__}）"
        )
    raise BootstrapError("profile JSON 生成失败")


def is_valid_profile_file(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    try:
        validate_bootstrap_profile(data)
    except BootstrapError:
        return False
    return True


def ensure_profile_json(
    paths: ResolvedPaths,
    card: CardData,
    *,
    api_key: str,
    base_url: str,
    model: str,
    overwrite: bool,
    dry_run: bool,
    transport: Transport = gemini.http_post_json,
    sleeper: Callable[[float], None] | None = None,
) -> Path:
    if sleeper is None:
        sleeper = time.sleep
    output = paths.character_dir / "profile.json"
    if not overwrite and is_valid_profile_file(output):
        print(f"跳过 profile.json：{output}")
        return output
    skeleton = build_profile_skeleton(card, fallback_name=paths.character)
    if dry_run:
        print(f"[dry-run] 将生成 profile.json → {output}")
        print(f"[dry-run] name={skeleton['name']}")
        return output
    if not api_key.strip():
        raise BootstrapError("缺少环境变量 GEMINI_API_KEY")
    print(f"生成 profile.json：{output}")
    merged = request_profile_patch(
        card=card,
        skeleton=skeleton,
        api_key=api_key,
        base_url=base_url,
        model=model,
        transport=transport,
        sleeper=sleeper,
    )
    disk = profile_for_disk(merged)
    payload = json.dumps(disk, ensure_ascii=False, indent=2) + "\n"
    gemini.atomic_write(output, payload.encode("utf-8"))
    if not is_valid_profile_file(output):
        raise BootstrapError(f"写入后 profile.json 校验失败：{output}")
    return output


PORTRAIT_SIZE = (896, 1280)
FULL_BODY_SIZE = (1024, 1536)
PORTRAIT_RATIO = "3:4"
FULL_BODY_RATIO = "2:3"


def normalize_image_png(
    image_bytes: bytes,
    target_size: tuple[int, int],
    *,
    headshot: bool = False,
) -> bytes:
    """无拉伸 fit 到目标尺寸并输出 PNG；头像启用头肩特写收紧。"""
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source.load()
            if headshot:
                prepared = gemini.prepare_headshot_rgb(source)
                centering = gemini.HEADSHOT_CENTERING
            else:
                prepared = source.convert("RGB")
                centering = (0.5, 0.5)
            normalized = ImageOps.fit(
                prepared,
                target_size,
                method=Image.Resampling.LANCZOS,
                centering=centering,
            )
            output = io.BytesIO()
            normalized.save(output, format="PNG", optimize=True)
            return output.getvalue()
    except (OSError, UnidentifiedImageError) as exc:
        raise gemini.RetryableGenerationError("Gemini 返回的图片无法解码") from exc


def is_valid_png(path: Path, target_size: tuple[int, int]) -> bool:
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            return image.format == "PNG" and image.size == target_size
    except (OSError, UnidentifiedImageError):
        return False


def find_existing_reference(
    character_dir: Path,
    name: str,
    kind: str,
    target_size: tuple[int, int],
) -> Path | None:
    preferred = character_dir / f"{name}_{kind}.png"
    legacy = character_dir / f"{name}_{kind}_1.png"
    for path in (preferred, legacy):
        if is_valid_png(path, target_size):
            return path
    return None


def encode_reference_resized(path: Path, max_side: int = 2048) -> dict[str, Any]:
    """Like gemini.encode_reference but downscales large images in memory."""
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    mime = mime_types.get(path.suffix.lower())
    if mime is None:
        raise BootstrapError(f"不支持的参考图格式：{path}")
    try:
        with Image.open(path) as image:
            image.load()
            rgb = image.convert("RGB")
            width, height = rgb.size
            longest = max(width, height)
            if longest > max_side:
                scale = max_side / float(longest)
                rgb = rgb.resize(
                    (max(1, int(width * scale)), max(1, int(height * scale))),
                    Image.Resampling.LANCZOS,
                )
            buf = io.BytesIO()
            if path.suffix.lower() == ".png":
                rgb.save(buf, format="PNG", optimize=True)
                mime = "image/png"
            else:
                rgb.save(buf, format="JPEG", quality=90, optimize=True)
                mime = "image/jpeg"
            raw = buf.getvalue()
    except OSError as exc:
        raise BootstrapError(f"无法读取参考图 {path}：{exc}") from exc

    return {
        "inlineData": {
            "mimeType": mime,
            "data": base64.b64encode(raw).decode("ascii"),
        }
    }


def _profile_image_summary(config: dict[str, Any]) -> str:
    traits = "；".join(str(item) for item in config.get("traits", []))
    return (
        f"人物：{config.get('name', '')}。"
        f"简介：{config.get('bio', '')}。"
        f"视觉特征：{traits}。"
        f"工作装：{config.get('_work_outfit', '')}。"
    )


# 参考图统一背景：纯摄影棚，禁止 sample 里的客厅/家具带进成片
STUDIO_BACKGROUND = (
    "背景必须是专业摄影棚纯净无缝背景纸/背景布，均匀暖米白或浅暖灰，"
    "柔和均匀人像棚灯，地面与背景融为一体、无明显接缝。"
    "严禁室内家居场景，严禁椅子、沙发、桌子、书架、绿植、窗、门、墙线装饰、道具、杂物。"
    "画面中只能有这一个人物，不要文字、标签、边框、拼图、水印、额外人物。"
)


def build_portrait_prompt(config: dict[str, Any]) -> str:
    """半身像提示词：必须以已生成的全身像为身份与着装锚点。"""
    return (
        "用途：专业人物设定资料。角色明确为成年人，完整着装，非露骨内容。"
        + _profile_image_summary(config)
        + "【参考图优先顺序】第一张是已生成的全身立绘（身份+服装锚点），"
        "其后如有 sample 仅作辅助；若冲突，一律以全身立绘为准。"
        "生成单张人物半身像参考图，表情自然平静。"
        "必须是全身立绘中的同一个人：脸型、五官、发型、发色、肤色、年龄感完全一致。"
        "上装必须与全身立绘一致（领型、颜色、外套有无、材质），禁止另起一套衣服或换装。"
        + gemini.HEADSHOT_FRAMING
        + STUDIO_BACKGROUND
        + f"目标比例 {PORTRAIT_RATIO}，交付尺寸 {PORTRAIT_SIZE[0]}×{PORTRAIT_SIZE[1]}。"
        "只输出一张图片。"
    )


def build_full_body_prompt(config: dict[str, Any]) -> str:
    # 优先用 images.items 四单品，保证与服装拆解一致；否则退回人物卡工作装摘要
    item_labels: list[str] = []
    images = config.get("images")
    if isinstance(images, dict):
        items = images.get("items")
        if isinstance(items, list):
            for entry in items:
                if isinstance(entry, dict):
                    label = entry.get("label")
                    if isinstance(label, str) and label.strip():
                        item_labels.append(label.strip())
    if item_labels:
        outfit = "、".join(item_labels)
        outfit_rule = (
            f"必须完整穿着以下单品构成的工作装：{outfit}。"
            "不得改成与单品列表冲突的套装（例如单品是半身裙时禁止西装长裤）。"
        )
    else:
        outfit = config.get("_work_outfit") or "默认职业工作装，完整着装"
        outfit_rule = f"穿着默认工作装：{outfit}。"
    return (
        "用途：专业人物设定资料。角色明确为成年人，完整着装，非露骨内容。"
        + _profile_image_summary(config)
        + "严格保持参考图中的同一人物身份；sample 仅作脸与体型参考，"
        "禁止把 sample 的室内家具、沙发、场景背景带进成片。"
        f"生成单张标准正面全身立绘，{outfit_rule}"
        "自然站立，双臂自然下垂，从头顶到鞋底完整可见，人物约占画面高度 88%，"
        "透视自然，不做动态姿势。"
        + STUDIO_BACKGROUND
        + f"目标比例 {FULL_BODY_RATIO}，交付尺寸 {FULL_BODY_SIZE[0]}×{FULL_BODY_SIZE[1]}。"
        "只输出一张图片。"
    )


def request_bootstrap_image(
    *,
    prompt: str,
    reference_paths: Sequence[Path],
    aspect_ratio: str,
    target_size: tuple[int, int],
    api_key: str,
    base_url: str,
    model: str,
    transport: Transport,
    sleeper: Callable[[float], None] = time.sleep,
    timeout: float = 180.0,
    max_attempts: int = 3,
) -> bytes:
    url = (
        f"{base_url.rstrip('/')}/models/"
        f"{quote(model, safe='-.()')}:generateContent"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    parts: list[dict[str, Any]] = [{"text": prompt}]
    for path in reference_paths:
        parts.append(encode_reference_resized(path))
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": aspect_ratio,
                "imageSize": "2K",
            },
        },
    }
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = transport(url, headers, payload, timeout)
            image_bytes, _ = gemini.extract_image(response)
            return normalize_image_png(
                image_bytes,
                target_size,
                headshot=(target_size == PORTRAIT_SIZE),
            )
        except gemini.HttpStatusError as exc:
            retryable = exc.status == 429 or 500 <= exc.status <= 599
            if not retryable or attempt == max_attempts:
                raise
            last_error = exc
        except (
            gemini.RetryableGenerationError,
            URLError,
            TimeoutError,
            ConnectionError,
        ) as exc:
            if attempt == max_attempts:
                raise
            last_error = exc
        sleeper(float(attempt))
        print(
            f"重试图片：第 {attempt + 1}/{max_attempts} 次"
            f"（{type(last_error).__name__}）"
        )
    raise BootstrapError("图片生成失败")


def ensure_reference_images(
    paths: ResolvedPaths,
    config: dict[str, Any],
    *,
    api_key: str,
    base_url: str,
    model: str,
    overwrite: bool,
    dry_run: bool,
    transport: Transport = gemini.http_post_json,
    sleeper: Callable[[float], None] | None = None,
) -> tuple[Path, Path]:
    """先全身像，再半身像（半身以全身为身份/着装锚点）。返回 (头像路径, 全身路径)。"""
    if sleeper is None:
        sleeper = time.sleep
    name = config["name"]
    portrait_out = paths.character_dir / f"{name}_头像.png"
    full_out = paths.character_dir / f"{name}_全身像.png"

    existing_portrait = None if overwrite else find_existing_reference(
        paths.character_dir, name, "头像", PORTRAIT_SIZE
    )
    existing_full = None if overwrite else find_existing_reference(
        paths.character_dir, name, "全身像", FULL_BODY_SIZE
    )

    if dry_run:
        print(
            f"[dry-run] 全身像 → {full_out} ({FULL_BODY_SIZE[0]}x{FULL_BODY_SIZE[1]})"
        )
        print(
            f"[dry-run] 头像(半身,锚全身) → {portrait_out} "
            f"({PORTRAIT_SIZE[0]}x{PORTRAIT_SIZE[1]})"
        )
        return portrait_out, full_out

    if not api_key.strip():
        raise BootstrapError("缺少环境变量 GEMINI_API_KEY")

    # 1) 全身像：sample 定身份 + items/工作装定衣服
    if existing_full is not None:
        print(f"跳过全身像：{existing_full}")
        full_path = existing_full
    else:
        print(f"生成全身像：{full_out}")
        raw = request_bootstrap_image(
            prompt=build_full_body_prompt(config),
            reference_paths=list(paths.sample_images),
            aspect_ratio=FULL_BODY_RATIO,
            target_size=FULL_BODY_SIZE,
            api_key=api_key,
            base_url=base_url,
            model=model,
            transport=transport,
            sleeper=sleeper,
        )
        gemini.atomic_write(full_out, raw)
        if not is_valid_png(full_out, FULL_BODY_SIZE):
            raise BootstrapError(f"全身像写入后校验失败：{full_out}")
        full_path = full_out

    # 2) 半身头像：必须以全身像为第一参考，保证同人同装
    if existing_portrait is not None:
        print(f"跳过头像：{existing_portrait}")
        portrait_path = existing_portrait
    else:
        if not full_path.is_file():
            raise BootstrapError(
                f"生成半身头像前需要有效全身像，未找到：{full_path}"
            )
        print(f"生成头像（锚定全身像）：{portrait_out}")
        # 全身像放第一张，其后 sample 仅辅助
        portrait_refs = [full_path, *list(paths.sample_images)]
        raw = request_bootstrap_image(
            prompt=build_portrait_prompt(config),
            reference_paths=portrait_refs,
            aspect_ratio=PORTRAIT_RATIO,
            target_size=PORTRAIT_SIZE,
            api_key=api_key,
            base_url=base_url,
            model=model,
            transport=transport,
            sleeper=sleeper,
        )
        gemini.atomic_write(portrait_out, raw)
        if not is_valid_png(portrait_out, PORTRAIT_SIZE):
            raise BootstrapError(f"头像写入后校验失败：{portrait_out}")
        portrait_path = portrait_out

    return portrait_path, full_path


@dataclass(frozen=True)
class BootstrapResult:
    profile_path: Path
    portrait_path: Path
    full_body_path: Path


def load_profile_config(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise BootstrapError(f"profile.json 顶层必须是对象：{path}")
    validate_bootstrap_profile(data)
    return data


def run_bootstrap(
    *,
    root: Path,
    character: str,
    api_key: str | None,
    base_url: str = gemini.DEFAULT_BASE_URL,
    model: str = gemini.DEFAULT_MODEL,
    overwrite: bool = False,
    dry_run: bool = False,
    transport: Transport = gemini.http_post_json,
    sleeper: Callable[[float], None] | None = None,
) -> BootstrapResult:
    paths = resolve_paths(root, character)
    card_text = paths.card_path.read_text(encoding="utf-8-sig")
    card = parse_character_card(card_text)
    key = api_key or ""

    profile_path = ensure_profile_json(
        paths,
        card,
        api_key=key,
        base_url=base_url,
        model=model,
        overwrite=overwrite,
        dry_run=dry_run,
        transport=transport,
        sleeper=sleeper,
    )
    if dry_run:
        skeleton = build_profile_skeleton(card, fallback_name=character)
        config = skeleton
    else:
        config = load_profile_config(profile_path)
    config = dict(config)
    config["_work_outfit"] = card.work_outfit
    config["_personality"] = card.personality
    config["_appearance"] = card.appearance

    portrait_path, full_body_path = ensure_reference_images(
        paths,
        config,
        api_key=key,
        base_url=base_url,
        model=model,
        overwrite=overwrite,
        dry_run=dry_run,
        transport=transport,
        sleeper=sleeper,
    )

    if not dry_run:
        # smoke: load_character + build_tasks
        loaded = gemini.load_character(paths.root, paths.character)
        tasks = gemini.build_tasks(loaded)
        print(f"下游可规划 {len(tasks)} 张标准素材。下一步：")
        print(
            f"  python generate_with_gemini.py --character {paths.character}"
        )

    return BootstrapResult(
        profile_path=profile_path,
        portrait_path=portrait_path,
        full_body_path=full_body_path,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="从人物卡与 sample 参考图生成 profile.json、头像与全身像"
    )
    parser.add_argument("--character", required=True, help="人物目录名")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="人物根目录（默认 GEMINI_DEFAULT_ROOT）",
    )
    parser.add_argument(
        "--model",
        default=gemini.DEFAULT_MODEL,
        help="Gemini 模型",
    )
    parser.add_argument(
        "--base-url",
        default=(
            os.environ.get("GEMINI_BASE_URL")
            or os.environ.get("GEMINI_BASE_RUL")
            or gemini.DEFAULT_BASE_URL
        ),
        help="Gemini API Base URL",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="覆盖已有有效 profile.json 与参考图",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示计划，不访问 API 或写入文件",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        gemini.load_env_file(gemini.DEFAULT_ENV_FILE)
    except (OSError, gemini.GeneratorError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    root = args.root if args.root is not None else gemini.get_default_root()
    try:
        result = run_bootstrap(
            root=root,
            character=args.character,
            api_key=os.environ.get("GEMINI_API_KEY"),
            base_url=args.base_url,
            model=args.model,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
    except (OSError, BootstrapError, gemini.GeneratorError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(f"profile: {result.profile_path}")
    print(f"头像: {result.portrait_path}")
    print(f"全身像: {result.full_body_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

