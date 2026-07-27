#!/usr/bin/env python3
from __future__ import annotations

import json
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


class ProfileBuildTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(bootstrap)
        self.card = bootstrap.parse_character_card(SAMPLE_CARD)

    def test_skeleton_has_fixed_image_files(self):
        skeleton = bootstrap.build_profile_skeleton(self.card, fallback_name="雨彤")

        self.assertEqual(skeleton["schemaVersion"], 1)
        self.assertEqual(skeleton["name"], "测试角色")
        self.assertEqual(skeleton["assetDir"], "assets_简介")
        files = [item["file"] for item in skeleton["images"]["views"]]
        self.assertEqual(
            files,
            ["view_front.jpg", "view_side.jpg", "view_back.jpg"],
        )
        exp = [item["file"] for item in skeleton["images"]["expressions"]]
        self.assertEqual(
            exp,
            [
                "exp_calm.jpg",
                "exp_smile.jpg",
                "exp_serious.jpg",
                "exp_surprise.jpg",
                "exp_think.jpg",
                "exp_shy.jpg",
            ],
        )
        items = [item["file"] for item in skeleton["images"]["items"]]
        self.assertEqual(
            items,
            [
                "item_blouse.jpg",
                "item_skirt.jpg",
                "item_hose.jpg",
                "item_shoes.jpg",
            ],
        )

    def test_merge_ignores_model_file_overrides(self):
        skeleton = bootstrap.build_profile_skeleton(self.card, fallback_name="雨彤")
        patch = {
            "nameEn": "Test Role",
            "tagline": "利落会来事",
            "seal": {"letters": "CS", "cn": "测", "en": "TEST"},
            "theme": {
                "accent": "#5B8FA8",
                "accentSoft": "#A8C4D4",
                "palette": [{"name": "雾蓝", "color": "#7FA3B8"}],
            },
            "factNote": "补充",
            "bio": "简介正文成年女性。",
            "traits": ["黑直发", "白大褂"],
            "tags": ["利落"],
            "images": {
                "views": [{"label": "X", "file": "hack.jpg"}],
                "items": [
                    {"label": "雾蓝衬衫", "file": "nope.jpg"},
                    {"label": "半身裙", "file": "nope.jpg"},
                    {"label": "丝袜", "file": "nope.jpg"},
                    {"label": "高跟鞋", "file": "nope.jpg"},
                ],
            },
            "display": {"frontScale": 9.0},
            "schemaVersion": 99,
            "assetDir": "evil",
        }
        merged = bootstrap.merge_profile(skeleton, patch)
        bootstrap.validate_bootstrap_profile(merged)

        self.assertEqual(merged["schemaVersion"], 1)
        self.assertEqual(merged["assetDir"], "assets_简介")
        self.assertEqual(merged["images"]["views"][0]["file"], "view_front.jpg")
        self.assertEqual(merged["images"]["items"][0]["label"], "雾蓝衬衫")
        self.assertEqual(merged["images"]["items"][0]["file"], "item_blouse.jpg")
        self.assertEqual(merged["display"]["frontScale"], 1.04)

    def test_validate_rejects_bad_color(self):
        skeleton = bootstrap.build_profile_skeleton(self.card, fallback_name="雨彤")
        skeleton["nameEn"] = "X"
        skeleton["tagline"] = "t"
        skeleton["seal"] = {"letters": "A", "cn": "测", "en": "A"}
        skeleton["theme"] = {
            "accent": "red",
            "accentSoft": "#FFFFFF",
            "palette": [{"name": "白", "color": "#FFFFFF"}],
        }
        skeleton["factNote"] = "n"
        skeleton["bio"] = "b"
        skeleton["traits"] = ["t"]
        skeleton["tags"] = ["g"]
        with self.assertRaises(bootstrap.BootstrapError):
            bootstrap.validate_bootstrap_profile(skeleton)


class ProfileGenerationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(bootstrap)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.character_dir = self.root / "雨彤"
        self.character_dir.mkdir()
        (self.character_dir / "人物卡.txt").write_text(SAMPLE_CARD, encoding="utf-8")
        write_png(self.character_dir / "sample" / "ref.png")
        self.paths = bootstrap.resolve_paths(self.root, "雨彤")
        self.card = bootstrap.parse_character_card(
            self.paths.card_path.read_text(encoding="utf-8-sig")
        )
        self.valid_patch = {
            "nameEn": "Test Role",
            "tagline": "利落会来事的助理",
            "seal": {"letters": "CS", "cn": "测", "en": "TEST"},
            "theme": {
                "accent": "#5B8FA8",
                "accentSoft": "#A8C4D4",
                "palette": [
                    {"name": "暖米白", "color": "#F6F1E8"},
                    {"name": "雾蓝", "color": "#7FA3B8"},
                ],
            },
            "factNote": "客气里藏着机灵。",
            "bio": "测试角色是成年女性诊所助理，气质利落。",
            "traits": ["黑直中长发", "白色工作外套", "雾蓝衬衫"],
            "tags": ["利落", "俏", "助理感"],
            "images": {
                "items": [
                    {"label": "雾蓝衬衫"},
                    {"label": "炭灰半身裙"},
                    {"label": "肉色丝袜"},
                    {"label": "银色高跟凉鞋"},
                ]
            },
        }

    def test_ensure_profile_writes_json_via_transport(self):
        calls: list[dict] = []

        def transport(url, headers, payload, timeout):
            calls.append(payload)
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        self.valid_patch, ensure_ascii=False
                                    )
                                }
                            ]
                        }
                    }
                ]
            }

        path = bootstrap.ensure_profile_json(
            self.paths,
            self.card,
            api_key="test-key",
            base_url="https://example.test/v1beta",
            model="gemini-test",
            overwrite=False,
            dry_run=False,
            transport=transport,
        )
        self.assertTrue(path.is_file())
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["nameEn"], "Test Role")
        self.assertEqual(data["images"]["items"][0]["file"], "item_blouse.jpg")
        self.assertEqual(len(calls), 1)
        # second call skips
        bootstrap.ensure_profile_json(
            self.paths,
            self.card,
            api_key="test-key",
            base_url="https://example.test/v1beta",
            model="gemini-test",
            overwrite=False,
            dry_run=False,
            transport=transport,
        )
        self.assertEqual(len(calls), 1)

    def test_dry_run_does_not_write(self):
        def transport(*args, **kwargs):
            raise AssertionError("dry-run must not call API")

        path = bootstrap.ensure_profile_json(
            self.paths,
            self.card,
            api_key="test-key",
            base_url="https://example.test/v1beta",
            model="gemini-test",
            overwrite=False,
            dry_run=True,
            transport=transport,
        )
        self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
