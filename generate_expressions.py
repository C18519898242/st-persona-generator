#!/usr/bin/env python3
"""Generate a SillyTavern-compatible expression sprite pack."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from PIL import Image, UnidentifiedImageError


class ExpressionError(RuntimeError):
    """Expression pack input or generation failed."""


EXPRESSION_SIZE = (896, 1280)
EXPRESSION_ASPECT_RATIO = "3:4"
EXPRESSION_LABELS = (
    "admiration", "amusement", "anger", "annoyance", "approval",
    "caring", "confusion", "curiosity", "desire", "disappointment",
    "disapproval", "disgust", "embarrassment", "excitement", "fear",
    "gratitude", "grief", "joy", "love", "nervousness", "optimism",
    "pride", "realization", "relief", "remorse", "sadness",
    "surprise", "neutral",
)


@dataclass(frozen=True)
class ExpressionPaths:
    root: Path
    character: str
    character_dir: Path
    profile_path: Path
    portrait_path: Path
    full_body_path: Path
    output_dir: Path
    zip_path: Path


def _find_reference(character_dir: Path, character: str, kind: str) -> Path:
    for name in (f"{character}_{kind}.png", f"{character}_{kind}_1.png"):
        path = character_dir / name
        if path.is_file():
            try:
                with Image.open(path) as image:
                    image.verify()
                return path
            except (OSError, UnidentifiedImageError):
                continue
    raise ExpressionError(f"找不到有效参考图：{character}_{kind}.png")


def resolve_expression_paths(root: Path, character: str) -> ExpressionPaths:
    root = Path(root).expanduser().resolve()
    character_dir = root / character
    if not character_dir.is_dir():
        raise ExpressionError(f"人物目录不存在：{character_dir}")
    profile_path = character_dir / "profile.json"
    if not profile_path.is_file():
        raise ExpressionError(f"找不到 profile.json：{profile_path}")
    try:
        profile = json.loads(profile_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ExpressionError(f"无法读取 profile.json：{profile_path}") from exc
    if not isinstance(profile, dict):
        raise ExpressionError(f"profile.json 顶层必须是对象：{profile_path}")
    portrait_path = _find_reference(character_dir, character, "头像")
    full_body_path = _find_reference(character_dir, character, "全身像")
    return ExpressionPaths(
        root=root,
        character=character,
        character_dir=character_dir,
        profile_path=profile_path,
        portrait_path=portrait_path,
        full_body_path=full_body_path,
        output_dir=character_dir / "expressions",
        zip_path=character_dir / f"{character}_expressions.zip",
    )


def is_valid_expression_png(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            return (
                image.format == "PNG"
                and image.size == EXPRESSION_SIZE
                and "A" in image.getbands()
            )
    except (OSError, UnidentifiedImageError):
        return False
