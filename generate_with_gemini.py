#!/usr/bin/env python3
"""使用 Gemini 原生 API 生成人物模板图片并渲染 HTML。"""

from __future__ import annotations

import argparse
import base64
import binascii
import io
import json
import os
import socket
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence, TypeAlias
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from PIL import Image, ImageOps, UnidentifiedImageError

import generate_profiles


TEMPLATE_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = TEMPLATE_DIR.parent
DEFAULT_BASE_URL = "https://gemini.xyz365.tech/v1beta"
DEFAULT_MODEL = "gemini-3.1-flash-image"
DEFAULT_ENV_FILE = TEMPLATE_DIR / ".env"

EXPECTED_ASSETS = {
    "views": (
        ("view_front.jpg", (1024, 1536), "2:3"),
        ("view_side.jpg", (1024, 1536), "2:3"),
        ("view_back.jpg", (1024, 1536), "2:3"),
    ),
    "expressions": (
        ("exp_calm.jpg", (896, 1280), "3:4"),
        ("exp_smile.jpg", (896, 1280), "3:4"),
        ("exp_serious.jpg", (896, 1280), "3:4"),
        ("exp_surprise.jpg", (896, 1280), "3:4"),
        ("exp_think.jpg", (896, 1280), "3:4"),
        ("exp_shy.jpg", (896, 1280), "3:4"),
    ),
    "items": (
        ("item_blouse.jpg", (1024, 2048), "9:16"),
        ("item_skirt.jpg", (1024, 2048), "9:16"),
        ("item_hose.jpg", (1024, 2048), "9:16"),
        ("item_shoes.jpg", (1024, 2048), "9:16"),
    ),
}


def load_env_file(path: Path) -> None:
    """读取简单 KEY=VALUE 格式的 .env，且不覆盖已有环境变量。"""
    env_path = Path(path)
    if not env_path.is_file():
        return
    for line_number, raw_line in enumerate(
        env_path.read_text(encoding="utf-8-sig").splitlines(),
        start=1,
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise GeneratorError(
                f"{env_path} 第 {line_number} 行不是 KEY=VALUE 格式"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        if (
            not key
            or key[0].isdigit()
            or not key.replace("_", "").isalnum()
        ):
            raise GeneratorError(
                f"{env_path} 第 {line_number} 行变量名无效：{key}"
            )
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {'"', "'"}
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def get_default_root() -> Path:
    """返回环境变量配置的人物根目录，未配置时使用模板目录的父目录。"""
    configured = os.environ.get("GEMINI_DEFAULT_ROOT")
    if configured:
        return Path(configured).expanduser().resolve()
    return DEFAULT_ROOT


class GeneratorError(RuntimeError):
    """人物图片生成失败。"""


class HttpStatusError(GeneratorError):
    """服务端返回非成功 HTTP 状态。"""

    def __init__(self, status: int, message: str):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status


class RetryableGenerationError(GeneratorError):
    """一次生成返回了可重试的无效结果。"""


@dataclass(frozen=True)
class AssetTask:
    filename: str
    label: str
    kind: str
    target_size: tuple[int, int]
    aspect_ratio: str


@dataclass(frozen=True)
class CharacterInput:
    character_dir: Path
    config_path: Path
    config: dict[str, Any]
    portrait_path: Path
    full_body_path: Path
    assets_dir: Path


Transport: TypeAlias = Callable[
    [str, dict[str, str], dict[str, Any], float],
    dict[str, Any],
]


def _require_file(path: Path, description: str) -> None:
    if not path.is_file():
        raise GeneratorError(f"找不到{description}：{path}")


def _find_reference_image(
    character_dir: Path,
    name: str,
    image_kind: str,
) -> Path:
    """优先使用无序号命名，并兼容已有的 `_1` 文件。"""
    preferred = character_dir / f"{name}_{image_kind}.png"
    if preferred.is_file():
        return preferred
    legacy = character_dir / f"{name}_{image_kind}_1.png"
    if legacy.is_file():
        return legacy
    raise GeneratorError(f"找不到{image_kind}参考图：{preferred}")


def load_character(root: Path, character: str) -> CharacterInput:
    """读取人物配置并发现头像、全身像参考图。"""
    character_dir = Path(root).resolve() / character
    config_path = character_dir / "profile.json"
    _require_file(config_path, "人物配置")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GeneratorError(f"无法读取人物配置 {config_path}：{exc}") from exc
    if not isinstance(config, dict):
        raise GeneratorError(f"人物配置顶层必须是对象：{config_path}")
    name = config.get("name")
    if not isinstance(name, str) or not name.strip():
        raise GeneratorError(f"人物配置缺少非空 name：{config_path}")

    portrait_path = _find_reference_image(character_dir, name, "头像")
    full_body_path = _find_reference_image(character_dir, name, "全身像")
    return CharacterInput(
        character_dir=character_dir,
        config_path=config_path,
        config=config,
        portrait_path=portrait_path,
        full_body_path=full_body_path,
        assets_dir=character_dir / "assets_简介",
    )


def build_tasks(character: CharacterInput) -> list[AssetTask]:
    """从人物配置构建顺序稳定的 13 个标准素材任务。"""
    images = character.config.get("images")
    if not isinstance(images, dict):
        raise GeneratorError("profile.json 缺少 images 对象")

    tasks: list[AssetTask] = []
    kind_for_group = {
        "views": "view",
        "expressions": "expression",
        "items": "item",
    }
    for group, expected in EXPECTED_ASSETS.items():
        entries = images.get(group)
        if not isinstance(entries, list):
            raise GeneratorError(f"profile.json 的 images.{group} 必须是数组")
        expected_names = [filename for filename, _, _ in expected]
        actual_names = [
            entry.get("file") if isinstance(entry, dict) else None
            for entry in entries
        ]
        if actual_names != expected_names:
            raise GeneratorError(
                f"images.{group} 文件必须按标准顺序配置为："
                + ", ".join(expected_names)
            )
        for entry, (filename, size, ratio) in zip(entries, expected):
            label = entry.get("label")
            if not isinstance(label, str) or not label.strip():
                raise GeneratorError(f"{filename} 缺少非空 label")
            tasks.append(
                AssetTask(
                    filename=filename,
                    label=label,
                    kind=kind_for_group[group],
                    target_size=size,
                    aspect_ratio=ratio,
                )
            )
    return tasks


def _profile_summary(character: CharacterInput) -> str:
    config = character.config
    traits = "；".join(str(item) for item in config.get("traits", []))
    facts = "；".join(
        f"{item.get('label', '')}：{item.get('value', '')}"
        for item in config.get("facts", [])
        if isinstance(item, dict)
    )
    palette = "；".join(
        f"{item.get('name', '')} {item.get('color', '')}"
        for item in config.get("theme", {}).get("palette", [])
        if isinstance(item, dict)
    )
    return (
        f"人物：{config['name']}。人物简介：{config.get('bio', '')}。"
        f"视觉特征：{traits}。基本资料：{facts}。配色：{palette}。"
    )


def build_prompt(character: CharacterInput, task: AssetTask) -> str:
    """为一个标准素材任务生成确定性的中文提示词。"""
    shared = (
        "用途：专业人物设定资料。角色明确为成年人，完整着装，非露骨内容。"
        + _profile_summary(character)
        + "严格保持两张参考图中的同一人物身份、成年年龄感、脸型、五官、"
        "黑色直发与齐刘海、体型比例、服装结构和主色一致。"
        "背景使用干净统一的暖米白摄影棚，柔和均匀人像光。"
        "不要文字、标签、边框、拼图、水印、额外人物或无关物品。"
    )
    if task.kind == "view":
        view_instruction = {
            "view_front.jpg": "标准正面",
            "view_side.jpg": "标准左侧面",
            "view_back.jpg": "标准背面",
        }[task.filename]
        specific = (
            f"生成单张{view_instruction}全身立绘，自然站立，双臂自然下垂。"
            "从头顶到鞋底完整可见，头发和鞋不能被裁切；人物占画面高度约 88%，"
            "透视自然，不改变服装，不做动态姿势。"
        )
        if task.filename == "view_back.jpg":
            specific += (
                "画面中只能出现一个人物，只显示这个人物的完整背面，"
                "人物面朝远离镜头的方向；不得同时展示正面人物，"
                "不得做正背面对照或并排拼图。"
            )
    elif task.kind == "expression":
        specific = (
            f"生成单张半身肖像，目标表情为“{task.label}”。"
            "只改变目标表情和与表情直接相关的细微头部动作，"
            "保持镜头距离、脸、发型、服装、背景和光线一致。"
            "包含完整头发、头部、双肩和少量上半身。"
        )
    elif task.kind == "item":
        specific = (
            f"生成单张服装拆解产品图，只展示“{task.label}”。"
            "禁止出现人物或人体、模特、衣架、其他衣物或配件。"
            "衣物必须平铺或悬空独立展示，不得被任何人穿着；"
            "不得出现手、脚、腿、人体轮廓或人体阴影。"
            "这不是隐形模特摄影：衣物内部、后方、上方和下方都必须为空，"
            "背景从顶部到底部只能包含商品和纯色背景，"
            "任何人类身体部位都会使结果无效。"
            "物品完整、纵向居中，准确保持参考图中的颜色、材质、剪裁和结构。"
        )
    else:
        raise GeneratorError(f"未知素材类型：{task.kind}")
    width, height = task.target_size
    return (
        f"{shared}{specific}"
        f"目标构图比例为 {task.aspect_ratio}，后续交付尺寸为 {width}×{height} 像素。"
        "只输出一张图片。"
    )


def encode_reference(path: Path) -> dict[str, Any]:
    """把本地参考图编码为 Gemini 原生 inlineData part。"""
    mime_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
    }
    mime_type = mime_types.get(path.suffix.lower())
    if mime_type is None:
        raise GeneratorError(f"不支持的参考图格式：{path}")
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise GeneratorError(f"无法读取参考图 {path}：{exc}") from exc
    if not raw:
        raise GeneratorError(f"参考图为空：{path}")
    return {
        "inlineData": {
            "mimeType": mime_type,
            "data": base64.b64encode(raw).decode("ascii"),
        }
    }


def build_request(
    character: CharacterInput,
    task: AssetTask,
) -> dict[str, Any]:
    """构建 Gemini generateContent 原生图片请求。"""
    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": build_prompt(character, task)},
                    encode_reference(character.portrait_path),
                    encode_reference(character.full_body_path),
                ],
            }
        ],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {
                "aspectRatio": task.aspect_ratio,
                "imageSize": "2K",
            },
        },
    }


def _safe_error_message(raw: bytes) -> str:
    text = raw.decode("utf-8", errors="replace").strip()
    if not text:
        return "服务端未提供错误信息"
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return text[:500]
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict) and isinstance(error.get("message"), str):
            return error["message"][:500]
    return text[:500]


def http_post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    """使用标准库发送 JSON POST，并返回 JSON 对象。"""
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request_headers = {"Content-Type": "application/json", **headers}
    request = Request(
        url,
        data=body,
        headers=request_headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        try:
            error_body = exc.read()
        except OSError:
            error_body = b""
        raise HttpStatusError(
            int(exc.code),
            _safe_error_message(error_body),
        ) from exc
    try:
        decoded = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RetryableGenerationError("服务端响应不是有效 JSON") from exc
    if not isinstance(decoded, dict):
        raise RetryableGenerationError("服务端 JSON 响应顶层不是对象")
    return decoded


def extract_image(response: dict[str, Any]) -> tuple[bytes, str]:
    """从 Gemini 原生响应中提取第一张 PNG/JPEG 图片。"""
    candidates = response.get("candidates")
    if not isinstance(candidates, list):
        raise RetryableGenerationError("Gemini 没有返回图片")
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
            if not isinstance(part, dict):
                continue
            inline = part.get("inlineData", part.get("inline_data"))
            if not isinstance(inline, dict):
                continue
            mime_type = inline.get("mimeType", inline.get("mime_type"))
            data = inline.get("data")
            if mime_type not in {"image/png", "image/jpeg"}:
                continue
            if not isinstance(data, str):
                continue
            try:
                image_bytes = base64.b64decode(data, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RetryableGenerationError(
                    "Gemini 返回的图片 Base64 无效"
                ) from exc
            if not image_bytes:
                raise RetryableGenerationError("Gemini 返回了空图片")
            try:
                with Image.open(io.BytesIO(image_bytes)) as image:
                    image.verify()
            except (OSError, UnidentifiedImageError) as exc:
                raise RetryableGenerationError(
                    "Gemini 返回的数据不是可解码图片"
                ) from exc
            return image_bytes, mime_type
    raise RetryableGenerationError("Gemini 没有返回图片")


def request_image(
    character: CharacterInput,
    task: AssetTask,
    *,
    api_key: str,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    transport: Transport = http_post_json,
    sleeper: Callable[[float], None] = time.sleep,
    timeout: float = 180.0,
    max_attempts: int = 3,
) -> tuple[bytes, str]:
    """请求一张图片，对限流、服务异常和无效图片响应做有限重试。"""
    encoded_model = quote(model, safe="-.()")
    url = (
        f"{base_url.rstrip('/')}/models/"
        f"{encoded_model}:generateContent"
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = build_request(character, task)
    for attempt in range(1, max_attempts + 1):
        try:
            response = transport(url, headers, payload, timeout)
            return extract_image(response)
        except HttpStatusError as exc:
            retryable = exc.status == 429 or 500 <= exc.status <= 599
            if not retryable or attempt == max_attempts:
                raise
            error: Exception = exc
        except (
            RetryableGenerationError,
            URLError,
            TimeoutError,
            socket.timeout,
            ConnectionError,
        ) as exc:
            if attempt == max_attempts:
                raise
            error = exc
        sleeper(float(attempt))
        print(
            f"重试 {task.filename}：第 {attempt + 1}/{max_attempts} 次"
            f"（{type(error).__name__}）"
        )
    raise AssertionError("不可达的重试状态")


def normalize_image(
    image_bytes: bytes,
    target_size: tuple[int, int],
) -> bytes:
    """无拉伸地居中裁切并输出高质量 RGB JPEG。"""
    try:
        with Image.open(io.BytesIO(image_bytes)) as source:
            source.load()
            normalized = ImageOps.fit(
                source.convert("RGB"),
                target_size,
                method=Image.Resampling.LANCZOS,
                centering=(0.5, 0.5),
            )
            output = io.BytesIO()
            normalized.save(
                output,
                format="JPEG",
                quality=94,
                optimize=True,
            )
            return output.getvalue()
    except (OSError, UnidentifiedImageError) as exc:
        raise RetryableGenerationError("Gemini 返回的图片无法解码") from exc


def is_valid_output(
    path: Path,
    target_size: tuple[int, int],
) -> bool:
    """检查输出是否为可完整解码且尺寸准确的 JPEG。"""
    if not path.is_file():
        return False
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            return image.format == "JPEG" and image.size == target_size
    except (OSError, UnidentifiedImageError):
        return False


def atomic_write(path: Path, data: bytes) -> None:
    """在目标目录内写临时文件并原子替换正式文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def run_generation(
    *,
    root: Path,
    character_name: str,
    api_key: str | None,
    base_url: str = DEFAULT_BASE_URL,
    model: str = DEFAULT_MODEL,
    overwrite: bool = False,
    dry_run: bool = False,
    transport: Transport = http_post_json,
    sleeper: Callable[[float], None] = time.sleep,
    html_generator: Callable[[Path], Path] | None = None,
) -> Path | None:
    """生成指定人物的 13 张标准图片，并在完整后渲染 HTML。"""
    character = load_character(Path(root), character_name)
    tasks = build_tasks(character)
    if dry_run:
        print(f"人物：{character.config['name']}")
        print(f"模型：{model}")
        for index, task in enumerate(tasks, start=1):
            width, height = task.target_size
            print(
                f"{index:02d}/13 {task.filename} "
                f"[{task.kind}] {task.aspect_ratio} -> {width}x{height}"
            )
        return None
    if not isinstance(api_key, str) or not api_key.strip():
        raise GeneratorError("缺少环境变量 GEMINI_API_KEY")

    character.assets_dir.mkdir(parents=True, exist_ok=True)
    for index, task in enumerate(tasks, start=1):
        output_path = character.assets_dir / task.filename
        if not overwrite and is_valid_output(
            output_path,
            task.target_size,
        ):
            print(f"{index:02d}/13 跳过：{task.filename}")
            continue
        print(f"{index:02d}/13 生成：{task.filename}")
        image_bytes, _ = request_image(
            character,
            task,
            api_key=api_key,
            base_url=base_url,
            model=model,
            transport=transport,
            sleeper=sleeper,
        )
        normalized = normalize_image(image_bytes, task.target_size)
        atomic_write(output_path, normalized)
        if not is_valid_output(output_path, task.target_size):
            raise GeneratorError(f"图片写入后校验失败：{output_path}")

    invalid = [
        task.filename
        for task in tasks
        if not is_valid_output(
            character.assets_dir / task.filename,
            task.target_size,
        )
    ]
    if invalid:
        raise GeneratorError(
            "以下图片尚未有效生成，不能生成 HTML："
            + ", ".join(invalid)
        )
    render = html_generator or generate_profiles.generate_one
    return render(character.config_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="使用 Gemini 生成人物模板的 13 张图片和 HTML"
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=get_default_root(),
        help="人物根目录",
    )
    parser.add_argument(
        "--character",
        required=True,
        help="人物目录名",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help="Gemini 图片模型",
    )
    parser.add_argument(
        "--base-url",
        default=(
            os.environ.get("GEMINI_BASE_URL")
            or os.environ.get("GEMINI_BASE_RUL")
            or DEFAULT_BASE_URL
        ),
        help="Gemini 原生 API Base URL",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="重新生成已经有效的图片",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只显示计划，不访问 API 或写入文件",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        load_env_file(DEFAULT_ENV_FILE)
    except (OSError, GeneratorError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        output = run_generation(
            root=args.root,
            character_name=args.character,
            api_key=os.environ.get("GEMINI_API_KEY"),
            base_url=args.base_url,
            model=args.model,
            overwrite=args.overwrite,
            dry_run=args.dry_run,
        )
    except (OSError, GeneratorError, generate_profiles.ProfileConfigError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    if output is not None:
        print(f"已生成 HTML：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
