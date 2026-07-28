import json
import re
import tempfile
import unittest
from pathlib import Path

import generate_profiles


class ProfileGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.template = self.root / "_人物模板" / "profile_template.html"
        self.template.parent.mkdir()
        self.template.write_text(
            "<title>{{TITLE}}</title><style>{{THEME_CSS}}</style>"
            "<h1>{{NAME}}</h1><p>{{TAGLINE}}</p>{{FACTS_HTML}}{{VIEWS_HTML}}",
            encoding="utf-8",
        )

    def make_character(self, name="测试人物", *, missing_image=False):
        character_dir = self.root / name
        assets_dir = character_dir / "assets_简介"
        assets_dir.mkdir(parents=True)
        image_names = ["front.jpg", "side.jpg", "back.jpg"]
        for image_name in image_names:
            if not (missing_image and image_name == "back.jpg"):
                (assets_dir / image_name).write_bytes(b"image")

        config = {
            "schemaVersion": 1,
            "name": name,
            "nameEn": "Test Person",
            "tagline": "温柔 <可靠>",
            "seal": {"letters": "TP", "cn": "测", "en": "TEST"},
            "assetDir": "assets_简介",
            "theme": {
                "accent": "#6F98AD",
                "accentSoft": "#A8C4D4",
                "palette": [
                    {"name": "雾蓝", "color": "#6F98AD"},
                    {"name": "炭灰", "color": "#303030"},
                ],
            },
            "facts": [{"label": "姓名", "value": name}],
            "factNote": "说明",
            "bio": "人物简介",
            "traits": ["特征一"],
            "tags": ["温柔"],
            "images": {
                "views": [
                    {"label": "正面", "file": "front.jpg", "className": "focus-front"},
                    {"label": "侧面", "file": "side.jpg"},
                    {"label": "背面", "file": "back.jpg", "className": "focus-back"},
                ],
                "expressions": [],
                "items": [],
                "details": [],
            },
            "display": {
                "frontScale": 1.08,
                "sideScale": 1.0,
                "backScale": 1.06,
                "expressionAspect": 0.76,
                "expressionPosition": "center 22%",
            },
        }
        config_path = character_dir / "profile.json"
        config_path.write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return config_path

    def test_discovers_only_character_configs(self):
        first = self.make_character("甲")
        second = self.make_character("乙")
        (self.root / "说明").mkdir()

        discovered = generate_profiles.discover_profile_configs(self.root)

        self.assertEqual(discovered, sorted([first, second], key=lambda path: path.parent.name))

    def test_render_escapes_text_and_resolves_placeholders(self):
        config_path = self.make_character("小夏")
        raw = json.loads(config_path.read_text(encoding="utf-8"))
        raw["name"] = "小<夏>"
        raw["facts"][0]["value"] = "小<夏>"
        config_path.write_text(
            json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        config = generate_profiles.load_and_validate_config(config_path)

        rendered = generate_profiles.render_profile(config, self.template)

        self.assertIn("小&lt;夏&gt;", rendered)
        self.assertIn("温柔 &lt;可靠&gt;", rendered)
        self.assertIn("--front-scale: 1.08", rendered)
        self.assertNotIn("{{", rendered)

    def test_validation_reports_missing_image(self):
        config_path = self.make_character(missing_image=True)

        with self.assertRaisesRegex(
            generate_profiles.ProfileConfigError, "back.jpg"
        ):
            generate_profiles.load_and_validate_config(config_path)

    def test_generate_creates_backup_once_and_writes_output(self):
        config_path = self.make_character()
        assets_dir = config_path.parent / "assets_简介"
        output_path = assets_dir / "profile.html"
        output_path.write_text("旧页面", encoding="utf-8")

        first_result = generate_profiles.generate_one(config_path, self.template)
        backup_path = assets_dir / "profile.before-template.html"
        self.assertEqual(first_result, output_path)
        self.assertEqual(backup_path.read_text(encoding="utf-8"), "旧页面")
        self.assertIn("测试人物", output_path.read_text(encoding="utf-8"))

        output_path.write_text("后来页面", encoding="utf-8")
        generate_profiles.generate_one(config_path, self.template)
        self.assertEqual(backup_path.read_text(encoding="utf-8"), "旧页面")

    def test_check_mode_does_not_write_output(self):
        config_path = self.make_character()
        output_path = config_path.parent / "assets_简介" / "profile.html"

        results = generate_profiles.run(
            root=self.root,
            template_path=self.template,
            check_only=True,
        )

        self.assertEqual(results, [output_path])
        self.assertFalse(output_path.exists())


class SharedTemplateRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.template = generate_profiles.DEFAULT_TEMPLATE.read_text(encoding="utf-8")
        cls.root = generate_profiles.DEFAULT_ROOT

    def test_asset_panels_clip_portrait_images_to_their_row(self):
        self.assertRegex(
            self.template,
            re.compile(
                r"\.assets-row\s*>\s*\.panel\s*\{[^}]*overflow:\s*hidden",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template,
            re.compile(
                r"\.asset-grid\s*\{[^}]*min-height:\s*200px",
                re.DOTALL,
            ),
        )

    def test_sheet_height_grows_with_content(self):
        self.assertRegex(
            self.template,
            re.compile(
                r"\.sheet\s*\{[^}]*height:\s*auto"
                r"[^}]*min-height:\s*var\(--sheet-height\)",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template,
            re.compile(
                r"figcaption\s*\{[^}]*overflow-wrap:\s*anywhere",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template,
            re.compile(
                r"\.image-card\s*\{[^}]*grid-template-rows:\s*minmax\(0,\s*1fr\)\s+auto",
                re.DOTALL,
            ),
        )

    def test_main_profile_panels_cannot_expand_past_their_grid_row(self):
        self.assertRegex(
            self.template,
            re.compile(
                r"\.profile-main\s*\{[^}]*min-height:\s*0",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template,
            re.compile(
                r"\.profile-main\s*>\s*\.panel\s*\{"
                r"[^}]*min-height:\s*0"
                r"[^}]*overflow:\s*hidden",
                re.DOTALL,
            ),
        )

    def test_summary_panels_cannot_expand_into_the_footer(self):
        self.assertRegex(
            self.template,
            re.compile(
                r"\.summary-row\s*\{[^}]*min-height:\s*0",
                re.DOTALL,
            ),
        )
        self.assertRegex(
            self.template,
            re.compile(
                r"\.summary-row\s*>\s*\.panel\s*\{"
                r"[^}]*min-height:\s*0"
                r"[^}]*overflow:\s*hidden",
                re.DOTALL,
            ),
        )

    def test_second_detail_uses_the_original_side_view(self):
        for character in ("夏语冰", "吴莹莹"):
            config_path = self.root / character / "profile.json"
            config = json.loads(config_path.read_text(encoding="utf-8"))
            with self.subTest(character=character):
                self.assertEqual(
                    config["images"]["details"][1]["file"],
                    "view_side.jpg",
                )
                self.assertEqual(
                    config["images"]["details"][1]["className"],
                    "focus-full",
                )


if __name__ == "__main__":
    unittest.main()
