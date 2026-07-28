#!/usr/bin/env python3
"""Generate a SillyTavern-compatible expression sprite pack."""

from __future__ import annotations

from dataclasses import dataclass
import io
import json
from pathlib import Path
import time
from typing import Any, Callable, Sequence
from urllib.error import URLError
from urllib.parse import quote

from PIL import Image, ImageOps, UnidentifiedImageError

import bootstrap_character as bootstrap
import generate_with_gemini as gemini


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

EXPRESSION_DESCRIPTIONS = {
    "admiration": "欣赏与赞叹：眉眼柔和、目光明亮、轻微微笑",
    "amusement": "被逗乐：眼角微弯、自然笑容",
    "anger": "明确生气：眉头下压、目光锐利、嘴唇收紧",
    "annoyance": "轻微烦躁：眉头略皱、目光不耐、嘴角轻压",
    "approval": "认可赞同：温和注视、轻微点头感、克制微笑",
    "caring": "关心体贴：眉眼柔和、专注温暖的目光",
    "confusion": "困惑不解：一侧眉毛微抬、轻微皱眉",
    "curiosity": "好奇探究：双眼略睁、眉毛轻抬、专注注视",
    "desire": "向往期待：目光专注柔和、嘴唇微启",
    "disappointment": "失望：眉眼下垂、嘴角轻微向下",
    "disapproval": "不赞同：眉头微皱、嘴唇收紧、审视目光",
    "disgust": "厌恶：鼻梁轻皱、上唇略抬、眉头收紧",
    "embarrassment": "尴尬羞窘：目光轻微回避、克制不自然的微笑",
    "excitement": "兴奋：眼睛明亮睁大、眉毛抬起、开心笑容",
    "fear": "害怕：眉毛抬起并靠拢、眼睛睁大、嘴唇微张",
    "gratitude": "感激：温暖目光、柔和真诚的微笑",
    "grief": "悲痛：眉头内收上扬、眼神沉痛、嘴角下垂",
    "joy": "喜悦：自然灿烂笑容、眼角弯曲",
    "love": "爱意：温柔专注的目光、柔和微笑",
    "nervousness": "紧张：眉毛略抬、嘴唇轻抿、目光稍显不安",
    "optimism": "乐观：神情明朗、自信温和的微笑",
    "pride": "自豪：眉眼自信、嘴角轻扬、神情从容",
    "realization": "恍然大悟：眉毛抬起、眼睛略睁、嘴唇微张",
    "relief": "如释重负：眉眼放松、轻轻呼气后的微笑",
    "remorse": "懊悔：眉头内收、目光下垂、嘴角轻压",
    "sadness": "悲伤：眉眼下垂、嘴角向下、神情低落",
    "surprise": "惊讶：眉毛明显抬起、眼睛睁大、嘴巴微张",
    "neutral": "自然平静：面部放松、目视镜头、嘴唇自然闭合",
}

Transport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


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


def _profile_summary(profile: dict) -> str:
    traits = "、".join(str(item) for item in profile.get("traits", []))
    return (
        f"人物：{profile.get('name', '')}。"
        f"简介：{profile.get('bio', '')}。"
        f"视觉特征：{traits}。"
    )


def build_expression_prompt(profile: dict, label: str) -> str:
    try:
        description = EXPRESSION_DESCRIPTIONS[label]
    except KeyError as exc:
        raise ExpressionError(f"未知表情标签：{label}") from exc
    neutral_reference = (
        "第三张参考图是已经生成的 neutral.png，用于严格锁定镜头、"
        "人物位置、姿势、服装、光线和画面比例。"
        if label != "neutral"
        else ""
    )
    return (
        "用途：SillyTavern 成人角色表情立绘，内容健康、完整着装。"
        + _profile_summary(profile)
        + "第一张参考图只用于严格锁定同一人物的脸型、五官、年龄感和发型。"
        "第二张参考图只用于严格锁定身材比例、服装、材质、颜色和配饰。"
        + neutral_reference
        + f"目标表情为 {label}：{description}。"
        "只改变面部表情；不得改变人物身份、发型、服装、姿势、"
        "镜头距离、人物大小、光线和画面构图。"
        "统一正面上半身半身像，完整头发、头部、双肩与上衣主体入镜，"
        "不要大头特写，不要全身立绘。"
        "背景必须真正透明（透明背景），人物边缘干净，不要纯色背景、渐变背景、"
        "棋盘格、场景、家具、文字、水印、边框或额外人物。"
        "交付单张 896×1280 PNG，只输出图片。"
    )


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


def normalize_expression_png(image_bytes: bytes) -> bytes:
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source.load()
            rgba = source.convert("RGBA")
            normalized = ImageOps.fit(
                rgba,
                EXPRESSION_SIZE,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.4),
            )
            output = io.BytesIO()
            normalized.save(output, format="PNG", optimize=True)
            return output.getvalue()
    except (OSError, UnidentifiedImageError) as exc:
        raise gemini.RetryableGenerationError(
            "Gemini 返回的表情图片无法解码"
        ) from exc


def request_expression_image(
    *,
    prompt: str,
    reference_paths: Sequence[Path],
    api_key: str,
    base_url: str,
    model: str,
    transport: Transport = gemini.http_post_json,
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
    parts = [{"text": prompt}]
    parts.extend(
        bootstrap.encode_reference_resized(path)
        for path in reference_paths
    )
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": EXPRESSION_ASPECT_RATIO,
                "imageSize": "2K",
            },
        },
    }
    for attempt in range(1, max_attempts + 1):
        try:
            response = transport(url, headers, payload, timeout)
            image_bytes, _ = gemini.extract_image(response)
            return normalize_expression_png(image_bytes)
        except gemini.HttpStatusError as exc:
            retryable = exc.status == 429 or 500 <= exc.status <= 599
            if not retryable or attempt == max_attempts:
                raise
        except (
            gemini.RetryableGenerationError,
            URLError,
            TimeoutError,
            ConnectionError,
        ):
            if attempt == max_attempts:
                raise
        sleeper(float(attempt))
    raise ExpressionError("表情图片生成失败")
