#!/usr/bin/env python3
"""从人物卡与 sample 参考图生成 profile.json、头像与全身像（第一阶段）。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


class BootstrapError(RuntimeError):
    """Bootstrap 配置或生成失败。"""


SAMPLE_SUFFIXES = {".jpg", ".jpeg", ".png"}


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
