#!/usr/bin/env python3
"""从人物卡与 sample 参考图生成 profile.json、头像与全身像（第一阶段）。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

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
    "expressionPosition": "center 22%",
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
                merged["theme"][key] = theme[key]
        if isinstance(theme.get("palette"), list) and theme["palette"]:
            merged["theme"]["palette"] = theme["palette"]
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
    if isinstance(patch.get("images"), dict):
        items = patch["images"].get("items")
        if isinstance(items, list):
            for index, filename in enumerate(FIXED_ITEM_FILES):
                if index < len(items) and isinstance(items[index], dict):
                    label = items[index].get("label")
                    if isinstance(label, str) and label.strip():
                        merged["images"]["items"][index]["label"] = label.strip()
                merged["images"]["items"][index]["file"] = filename
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
            raise BootstrapError(f"palette[{index}] 无效")
        _require_str(swatch, "name", f"palette[{index}]")
        color = _require_str(swatch, "color", f"palette[{index}]")
        if not COLOR_RE.fullmatch(color):
            raise BootstrapError(f"palette[{index}].color 必须是 #RRGGBB")
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
