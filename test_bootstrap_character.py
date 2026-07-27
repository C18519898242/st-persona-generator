#!/usr/bin/env python3
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image

try:
    import bootstrap_character as bootstrap
except ModuleNotFoundError:
    bootstrap = None


def write_png(path: Path, size: tuple[int, int] = (64, 64)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, "#C49A8A").save(path, format="PNG")


SAMPLE_CARD = """════════════════════════════════════
【Name / 角色名】
测试角色

【Description / 角色描述】
【基本信息】
- 姓名：测试角色
- 年龄：约 24 岁
- 职业：诊所助理

【外貌】
黑直中长发。
常见着装：
- 工作：白色长款工作外套，内搭雾蓝衬衫，炭灰半身裙，肉色丝袜，银色高跟凉鞋

════════════════════════════════════
【Personality / 性格】
利落、俏、会来事。
"""


class PathResolutionTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(bootstrap, "bootstrap_character 模块尚未实现")
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.character = "雨彤"
        self.character_dir = self.root / self.character
        self.character_dir.mkdir()

    def test_resolve_prefers_plain_card_name(self):
        (self.character_dir / "人物卡.txt").write_text(SAMPLE_CARD, encoding="utf-8")
        (self.character_dir / "人物卡_雨彤.txt").write_text("其他", encoding="utf-8")
        sample = self.character_dir / "sample"
        write_png(sample / "b.png")
        write_png(sample / "a.jpg")

        paths = bootstrap.resolve_paths(self.root, self.character)

        self.assertEqual(paths.card_path.name, "人物卡.txt")
        self.assertEqual(
            [p.name for p in paths.sample_images],
            ["a.jpg", "b.png"],
        )

    def test_resolve_falls_back_to_character_named_card(self):
        (self.character_dir / "人物卡_雨彤.txt").write_text(SAMPLE_CARD, encoding="utf-8")
        write_png(self.character_dir / "sample" / "ref.png")

        paths = bootstrap.resolve_paths(self.root, self.character)

        self.assertEqual(paths.card_path.name, "人物卡_雨彤.txt")

    def test_resolve_errors_when_character_dir_missing(self):
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.resolve_paths(self.root, "不存在")

    def test_resolve_errors_when_no_card(self):
        write_png(self.character_dir / "sample" / "ref.png")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "人物卡"):
            bootstrap.resolve_paths(self.root, self.character)

    def test_resolve_errors_when_sample_empty(self):
        (self.character_dir / "人物卡.txt").write_text(SAMPLE_CARD, encoding="utf-8")
        (self.character_dir / "sample").mkdir()
        with self.assertRaisesRegex(bootstrap.BootstrapError, "sample"):
            bootstrap.resolve_paths(self.root, self.character)


class CardParseTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(bootstrap)

    def test_parse_extracts_name_work_outfit_and_basics(self):
        card = bootstrap.parse_character_card(SAMPLE_CARD)

        self.assertEqual(card.name, "测试角色")
        self.assertIn("工作外套", card.work_outfit)
        self.assertIn("姓名", " ".join(f"{k}{v}" for k, v in card.basic_facts))
        self.assertTrue(any("24" in v for _, v in card.basic_facts))
        self.assertIn("利落", card.personality)

    def test_parse_empty_name_allowed(self):
        card = bootstrap.parse_character_card("【Personality / 性格】\n开朗\n")
        self.assertEqual(card.name, "")
        self.assertIn("开朗", card.personality)


if __name__ == "__main__":
    unittest.main()
