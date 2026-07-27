#!/usr/bin/env python3
"""从人物卡与 sample 参考图生成 profile.json、头像与全身像（第一阶段）。"""

from __future__ import annotations

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
