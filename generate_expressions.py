#!/usr/bin/env python3
"""Generate a SillyTavern-compatible expression sprite pack."""

from __future__ import annotations

import argparse
import base64
from dataclasses import dataclass
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
from typing import Any, Callable, Sequence
from urllib.error import URLError
from urllib.parse import quote
import zipfile

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
NormalizedPngGenerator = Callable[..., bytes]


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


@dataclass(frozen=True)
class ExpressionRunResult:
    generated: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[str, ...]


@dataclass(frozen=True)
class ExpressionPackResult:
    paths: ExpressionPaths
    images: ExpressionRunResult
    zip_path: Path | None


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


def create_expression_zip(paths: ExpressionPaths) -> Path:
    missing = [
        label
        for label in EXPRESSION_LABELS
        if not is_valid_expression_png(paths.output_dir / f"{label}.png")
    ]
    if missing:
        raise ExpressionError("缺少有效表情图片：" + ", ".join(missing))
    paths.zip_path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{paths.character}_expressions-",
        suffix=".zip",
        dir=paths.zip_path.parent,
    )
    os.close(fd)
    temporary_path = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for label in EXPRESSION_LABELS:
                archive.write(
                    paths.output_dir / f"{label}.png",
                    arcname=f"{label}.png",
                )
        os.replace(temporary_path, paths.zip_path)
    finally:
        temporary_path.unlink(missing_ok=True)
    return paths.zip_path


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


def encode_expression_reference(
    path: Path,
    max_side: int = 2048,
) -> dict[str, Any]:
    """Encode one reference locally, retaining PNG transparency."""
    suffix = path.suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg"}:
        raise ExpressionError(f"Unsupported reference image format: {path}")
    try:
        with Image.open(path) as source:
            source.load()
            image = (
                source.convert("RGBA")
                if suffix == ".png"
                else source.convert("RGB")
            )
            width, height = image.size
            longest = max(width, height)
            if longest > max_side:
                scale = max_side / float(longest)
                image = image.resize(
                    (
                        max(1, int(width * scale)),
                        max(1, int(height * scale)),
                    ),
                    Image.Resampling.LANCZOS,
                )
            output = io.BytesIO()
            if suffix == ".png":
                image.save(output, format="PNG", optimize=True)
                mime_type = "image/png"
            else:
                image.save(
                    output,
                    format="JPEG",
                    quality=90,
                    optimize=True,
                )
                mime_type = "image/jpeg"
    except (OSError, UnidentifiedImageError) as exc:
        raise ExpressionError(f"Unable to read reference image: {path}") from exc
    return {
        "inlineData": {
            "mimeType": mime_type,
            "data": base64.b64encode(output.getvalue()).decode("ascii"),
        }
    }


def _is_normalized_expression_png(image_bytes: bytes) -> bool:
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            image.load()
            return (
                image.format == "PNG"
                and image.size == EXPRESSION_SIZE
                and "A" in image.getbands()
            )
    except (OSError, UnidentifiedImageError):
        return False


def generate_expression_images(
    paths: ExpressionPaths,
    *,
    api_key: str,
    base_url: str,
    model: str,
    overwrite: bool = False,
    image_generator: NormalizedPngGenerator | None = None,
) -> ExpressionRunResult:
    """Generate labels; generators return normalized RGBA PNG bytes."""
    if not api_key.strip():
        raise ExpressionError("Missing GEMINI_API_KEY")
    profile = json.loads(paths.profile_path.read_text(encoding="utf-8-sig"))
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    generator = image_generator or _generate_one_expression
    generated: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    order = ("neutral",) + tuple(
        label for label in EXPRESSION_LABELS if label != "neutral"
    )
    for label in order:
        output_path = paths.output_dir / f"{label}.png"
        if not overwrite and is_valid_expression_png(output_path):
            skipped.append(label)
            continue
        references = [paths.portrait_path, paths.full_body_path]
        neutral_path = paths.output_dir / "neutral.png"
        if label != "neutral":
            if not is_valid_expression_png(neutral_path):
                failed.append(label)
                continue
            references.append(neutral_path)
        try:
            normalized_png = generator(
                label=label,
                profile=profile,
                reference_paths=tuple(references),
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            if not _is_normalized_expression_png(normalized_png):
                raise ExpressionError(
                    "Image generator did not return a normalized "
                    f"{EXPRESSION_SIZE[0]}x{EXPRESSION_SIZE[1]} RGBA PNG"
                )
            gemini.atomic_write(output_path, normalized_png)
            if not is_valid_expression_png(output_path):
                raise ExpressionError(f"Written image did not validate: {output_path}")
            generated.append(label)
        except (
            OSError,
            ExpressionError,
            bootstrap.BootstrapError,
            gemini.GeneratorError,
            URLError,
            TimeoutError,
            ConnectionError,
        ) as exc:
            print(f"Expression generation failed for {label}: {exc}", file=sys.stderr)
            failed.append(label)
    return ExpressionRunResult(
        generated=tuple(generated),
        skipped=tuple(skipped),
        failed=tuple(failed),
    )


def _generate_one_expression(
    *,
    label: str,
    profile: dict,
    reference_paths: Sequence[Path],
    api_key: str,
    base_url: str,
    model: str,
) -> bytes:
    return request_expression_image(
        prompt=build_expression_prompt(profile, label),
        reference_paths=reference_paths,
        api_key=api_key,
        base_url=base_url,
        model=model,
    )


def run_expression_pack(
    *,
    root: Path,
    character: str,
    api_key: str | None,
    base_url: str,
    model: str,
    overwrite: bool = False,
    create_zip: bool = True,
    image_generator: NormalizedPngGenerator | None = None,
) -> ExpressionPackResult:
    paths = resolve_expression_paths(root, character)
    images = generate_expression_images(
        paths,
        api_key=api_key or "",
        base_url=base_url,
        model=model,
        overwrite=overwrite,
        image_generator=image_generator,
    )
    zip_path = None
    if create_zip and not images.failed:
        zip_path = create_expression_zip(paths)
    return ExpressionPackResult(paths=paths, images=images, zip_path=zip_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate a SillyTavern-standard character expression pack.",
    )
    parser.add_argument("--character", required=True, help="Character directory name")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Character root directory (defaults to GEMINI_DEFAULT_ROOT)",
    )
    parser.add_argument(
        "--model",
        default=gemini.DEFAULT_MODEL,
        help="Gemini image model",
    )
    parser.add_argument(
        "--base-url",
        default=(
            os.environ.get("GEMINI_BASE_URL")
            or os.environ.get("GEMINI_BASE_RUL")
            or gemini.DEFAULT_BASE_URL
        ),
        help="Gemini API base URL",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate already-valid expression images",
    )
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="Do not create the ZIP expression pack",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        gemini.load_env_file(gemini.DEFAULT_ENV_FILE)
    except (OSError, gemini.GeneratorError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    args = build_parser().parse_args(argv)
    root = args.root if args.root is not None else gemini.get_default_root()
    try:
        result = run_expression_pack(
            root=root,
            character=args.character,
            api_key=os.environ.get("GEMINI_API_KEY"),
            base_url=args.base_url,
            model=args.model,
            overwrite=args.overwrite,
            create_zip=not args.no_zip,
        )
    except (
        OSError,
        ExpressionError,
        gemini.GeneratorError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Generated: {len(result.images.generated)}")
    print(f"Skipped: {len(result.images.skipped)}")
    print(f"Failed: {len(result.images.failed)}")
    if result.images.failed:
        print("Failed labels: " + ", ".join(result.images.failed), file=sys.stderr)
        return 1
    print(f"Image directory: {result.paths.output_dir}")
    if result.zip_path is not None:
        print(f"ZIP: {result.zip_path}")
    return 0


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
        encode_expression_reference(path)
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

if __name__ == "__main__":
    raise SystemExit(main())
