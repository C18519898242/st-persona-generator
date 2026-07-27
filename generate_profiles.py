#!/usr/bin/env python3
"""从人物目录中的 profile.json 生成统一版式的人物简介页。"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any


TEMPLATE_DIR = Path(__file__).resolve().parent
DEFAULT_ROOT = TEMPLATE_DIR.parent
DEFAULT_TEMPLATE = TEMPLATE_DIR / "profile_template.html"
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z][A-Z0-9_]*)\}\}")
COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}")
CLASS_RE = re.compile(r"[A-Za-z0-9_-]*")
POSITION_RE = re.compile(r"[A-Za-z0-9.%\s-]+")


class ProfileConfigError(ValueError):
    """人物配置无效。"""


def discover_profile_configs(root: Path) -> list[Path]:
    """返回根目录下所有人物的 profile.json，按目录名稳定排序。"""
    root = Path(root)
    return sorted(
        (
            path / "profile.json"
            for path in root.iterdir()
            if path.is_dir()
            and not path.name.startswith("_")
            and (path / "profile.json").is_file()
        ),
        key=lambda path: path.parent.name,
    )


def _require(
    mapping: dict[str, Any],
    key: str,
    expected_type: type | tuple[type, ...],
    where: str,
) -> Any:
    if key not in mapping:
        raise ProfileConfigError(f"{where} 缺少必填字段 {key!r}")
    value = mapping[key]
    if not isinstance(value, expected_type):
        if isinstance(expected_type, tuple):
            type_name = " 或 ".join(item.__name__ for item in expected_type)
        else:
            type_name = expected_type.__name__
        raise ProfileConfigError(
            f"{where}.{key} 应为 {type_name}，实际为 {type(value).__name__}"
        )
    if expected_type == str and not value.strip():
        raise ProfileConfigError(f"{where}.{key} 不能为空")
    return value


def _validate_color(value: str, where: str) -> None:
    if not COLOR_RE.fullmatch(value):
        raise ProfileConfigError(f"{where} 必须是 #RRGGBB 颜色，实际为 {value!r}")


def _validate_number(
    value: Any, where: str, minimum: float, maximum: float
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProfileConfigError(f"{where} 必须是数字")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ProfileConfigError(f"{where} 必须在 {minimum} 到 {maximum} 之间")
    return number


def _validate_image_list(
    images: dict[str, Any],
    key: str,
    assets_dir: Path,
) -> None:
    entries = _require(images, key, list, "images")
    for index, entry in enumerate(entries):
        where = f"images.{key}[{index}]"
        if not isinstance(entry, dict):
            raise ProfileConfigError(f"{where} 必须是对象")
        _require(entry, "label", str, where)
        filename = _require(entry, "file", str, where)
        class_name = entry.get("className", "")
        if not isinstance(class_name, str) or not CLASS_RE.fullmatch(class_name):
            raise ProfileConfigError(f"{where}.className 只能包含字母、数字、- 和 _")

        relative_path = Path(filename)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ProfileConfigError(f"{where}.file 必须位于 assets_简介 内部")
        image_path = (assets_dir / relative_path).resolve()
        if not image_path.is_relative_to(assets_dir.resolve()):
            raise ProfileConfigError(f"{where}.file 超出图片目录")
        if not image_path.is_file():
            raise ProfileConfigError(f"找不到图片：{image_path}")


def load_and_validate_config(config_path: Path) -> dict[str, Any]:
    """读取并校验一份人物配置，返回附带路径信息的配置。"""
    config_path = Path(config_path).resolve()
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileConfigError(
            f"{config_path} 不是有效 JSON：第 {exc.lineno} 行第 {exc.colno} 列"
        ) from exc
    if not isinstance(config, dict):
        raise ProfileConfigError(f"{config_path} 顶层必须是对象")

    schema_version = _require(config, "schemaVersion", int, "profile")
    if schema_version != 1:
        raise ProfileConfigError(f"仅支持 schemaVersion 1，实际为 {schema_version}")

    for key in ("name", "nameEn", "tagline", "assetDir", "factNote", "bio"):
        _require(config, key, str, "profile")
    for key in ("facts", "traits", "tags"):
        _require(config, key, list, "profile")

    seal = _require(config, "seal", dict, "profile")
    for key in ("letters", "cn", "en"):
        _require(seal, key, str, "seal")

    theme = _require(config, "theme", dict, "profile")
    for key in ("accent", "accentSoft"):
        color = _require(theme, key, str, "theme")
        _validate_color(color, f"theme.{key}")
    palette = _require(theme, "palette", list, "theme")
    if not palette:
        raise ProfileConfigError("theme.palette 至少需要一个颜色")
    for index, swatch in enumerate(palette):
        where = f"theme.palette[{index}]"
        if not isinstance(swatch, dict):
            raise ProfileConfigError(f"{where} 必须是对象")
        _require(swatch, "name", str, where)
        color = _require(swatch, "color", str, where)
        _validate_color(color, f"{where}.color")

    facts = config["facts"]
    if not facts:
        raise ProfileConfigError("facts 至少需要一项")
    for index, fact in enumerate(facts):
        where = f"facts[{index}]"
        if not isinstance(fact, dict):
            raise ProfileConfigError(f"{where} 必须是对象")
        _require(fact, "label", str, where)
        _require(fact, "value", str, where)
    for key in ("traits", "tags"):
        for index, value in enumerate(config[key]):
            if not isinstance(value, str) or not value.strip():
                raise ProfileConfigError(f"{key}[{index}] 必须是非空字符串")

    display = _require(config, "display", dict, "profile")
    for key in ("frontScale", "sideScale", "backScale"):
        _validate_number(
            _require(display, key, (int, float), "display"),
            f"display.{key}",
            0.8,
            1.35,
        )
    _validate_number(
        _require(display, "expressionAspect", (int, float), "display"),
        "display.expressionAspect",
        0.45,
        1.4,
    )
    expression_position = _require(display, "expressionPosition", str, "display")
    if not POSITION_RE.fullmatch(expression_position):
        raise ProfileConfigError("display.expressionPosition 含有不安全字符")

    asset_dir_name = config["assetDir"]
    relative_assets = Path(asset_dir_name)
    if relative_assets.is_absolute() or ".." in relative_assets.parts:
        raise ProfileConfigError("assetDir 必须是人物目录内的相对路径")
    assets_dir = (config_path.parent / relative_assets).resolve()
    if not assets_dir.is_dir():
        raise ProfileConfigError(f"找不到图片目录：{assets_dir}")

    images = _require(config, "images", dict, "profile")
    for key in ("views", "expressions", "items", "details"):
        _validate_image_list(images, key, assets_dir)
    if len(images["views"]) != 3:
        raise ProfileConfigError("images.views 必须正好包含正面、侧面、背面三张图")

    validated = dict(config)
    validated["_config_path"] = config_path
    validated["_assets_path"] = assets_dir
    return validated


def _esc(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _image_figure(entry: dict[str, Any], frame_class: str) -> str:
    class_name = entry.get("className", "")
    image_class = f' class="{_esc(class_name)}"' if class_name else ""
    return (
        '<figure class="image-card">'
        f'<div class="media-frame {frame_class}">'
        f'<img src="{_esc(entry["file"])}" alt="{_esc(entry["label"])}"{image_class}>'
        "</div>"
        f"<figcaption>{_esc(entry['label'])}</figcaption>"
        "</figure>"
    )


def _theme_css(config: dict[str, Any]) -> str:
    theme = config["theme"]
    display = config["display"]
    return (
        f"--accent: {theme['accent']}; "
        f"--accent-soft: {theme['accentSoft']}; "
        f"--front-scale: {display['frontScale']}; "
        f"--side-scale: {display['sideScale']}; "
        f"--back-scale: {display['backScale']}; "
        f"--expression-aspect: {display['expressionAspect']}; "
        f"--expression-position: {display['expressionPosition']};"
    )


def _render_values(config: dict[str, Any]) -> dict[str, str]:
    images = config["images"]
    facts_html = "".join(
        f'<div class="fact"><dt>{_esc(item["label"])}</dt>'
        f'<dd>{_esc(item["value"])}</dd></div>'
        for item in config["facts"]
    )
    traits_html = "".join(f"<li>{_esc(item)}</li>" for item in config["traits"])
    tags_html = "".join(f"<span>{_esc(item)}</span>" for item in config["tags"])
    palette_html = "".join(
        '<div class="swatch">'
        f'<i style="background:{_esc(item["color"])}"></i>'
        f'<b>{_esc(item["name"])}</b><small>{_esc(item["color"].upper())}</small>'
        "</div>"
        for item in config["theme"]["palette"]
    )
    return {
        "TITLE": _esc(f"{config['name']} · 人物设定档案"),
        "THEME_CSS": _theme_css(config),
        "NAME": _esc(config["name"]),
        "NAME_EN": _esc(config["nameEn"]),
        "TAGLINE": _esc(config["tagline"]),
        "SEAL_LETTERS": _esc(config["seal"]["letters"]),
        "SEAL_CN": _esc(config["seal"]["cn"]),
        "SEAL_EN": _esc(config["seal"]["en"]),
        "FACTS_HTML": facts_html,
        "FACT_NOTE": _esc(config["factNote"]),
        "BIO": _esc(config["bio"]),
        "TRAITS_HTML": traits_html,
        "TAGS_HTML": tags_html,
        "PALETTE_HTML": palette_html,
        "VIEWS_HTML": "".join(
            _image_figure(entry, "media-frame--turnaround")
            for entry in images["views"]
        ),
        "EXPRESSIONS_HTML": "".join(
            _image_figure(entry, "media-frame--expression")
            for entry in images["expressions"]
        ),
        "ITEMS_HTML": "".join(
            _image_figure(entry, "media-frame--item") for entry in images["items"]
        ),
        "DETAILS_HTML": "".join(
            _image_figure(entry, "media-frame--detail")
            for entry in images["details"]
        ),
    }


def render_profile(config: dict[str, Any], template_path: Path = DEFAULT_TEMPLATE) -> str:
    """将已校验配置渲染为完整 HTML。"""
    template = Path(template_path).read_text(encoding="utf-8")
    values = _render_values(config)

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise ProfileConfigError(f"模板含未知占位符：{{{{{key}}}}}")
        return values[key]

    rendered = PLACEHOLDER_RE.sub(replace, template)
    unresolved = PLACEHOLDER_RE.findall(rendered)
    if unresolved:
        raise ProfileConfigError(f"模板仍有未解析占位符：{', '.join(unresolved)}")
    return rendered


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def generate_one(
    config_path: Path,
    template_path: Path = DEFAULT_TEMPLATE,
    *,
    check_only: bool = False,
) -> Path:
    """校验并生成单个人物页面，返回目标路径。"""
    config = load_and_validate_config(config_path)
    rendered = render_profile(config, template_path)
    output_path = config["_assets_path"] / "profile.html"
    if check_only:
        return output_path

    backup_path = config["_assets_path"] / "profile.before-template.html"
    if output_path.exists() and not backup_path.exists():
        shutil.copy2(output_path, backup_path)
    _atomic_write(output_path, rendered)
    return output_path


def run(
    *,
    root: Path = DEFAULT_ROOT,
    template_path: Path = DEFAULT_TEMPLATE,
    characters: list[str] | None = None,
    check_only: bool = False,
) -> list[Path]:
    """批量校验或生成人物页面。"""
    configs = discover_profile_configs(Path(root))
    if characters:
        requested = set(characters)
        configs = [path for path in configs if path.parent.name in requested]
        found = {path.parent.name for path in configs}
        missing = sorted(requested - found)
        if missing:
            raise ProfileConfigError(f"找不到人物配置：{', '.join(missing)}")
    if not configs:
        raise ProfileConfigError(f"在 {Path(root)} 下没有找到 profile.json")
    return [
        generate_one(path, template_path, check_only=check_only) for path in configs
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="从 profile.json 生成统一版式的人物简介页"
    )
    parser.add_argument(
        "--character",
        action="append",
        dest="characters",
        help="只处理指定人物，可重复使用",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="只校验配置和渲染结果，不写入 HTML",
    )
    args = parser.parse_args()

    try:
        outputs = run(characters=args.characters, check_only=args.check)
    except (OSError, ProfileConfigError) as exc:
        parser.exit(1, f"错误：{exc}\n")

    action = "校验通过" if args.check else "已生成"
    for output in outputs:
        print(f"{action}：{output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
