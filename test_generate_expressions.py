#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import tempfile
import unittest
import base64
import zipfile
from pathlib import Path

from PIL import Image

try:
    import generate_expressions as expressions
except ModuleNotFoundError:
    expressions = None


EXPECTED_LABELS = (
    "admiration", "amusement", "anger", "annoyance", "approval",
    "caring", "confusion", "curiosity", "desire", "disappointment",
    "disapproval", "disgust", "embarrassment", "excitement", "fear",
    "gratitude", "grief", "joy", "love", "nervousness", "optimism",
    "pride", "realization", "relief", "remorse", "sadness",
    "surprise", "neutral",
)

EXPECTED_EXPRESSION_DESCRIPTIONS = {
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


def write_png(
    path: Path,
    size: tuple[int, int] = (896, 1280),
    mode: str = "RGBA",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    color = (120, 100, 90, 0) if mode == "RGBA" else (120, 100, 90)
    Image.new(mode, size, color).save(path, format="PNG")


def png_bytes(
    size: tuple[int, int] = (1200, 1600),
    mode: str = "RGBA",
) -> bytes:
    output = io.BytesIO()
    color = (20, 40, 60, 0) if mode == "RGBA" else (20, 40, 60)
    Image.new(mode, size, color).save(output, format="PNG")
    return output.getvalue()


def image_response(raw: bytes) -> dict:
    return {
        "candidates": [{
            "content": {
                "parts": [{
                    "inlineData": {
                        "mimeType": "image/png",
                        "data": base64.b64encode(raw).decode("ascii"),
                    }
                }]
            }
        }]
    }


class LabelContractTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(expressions, "generate_expressions module is missing")

    def test_standard_labels_are_complete_unique_and_stable(self):
        self.assertEqual(expressions.EXPRESSION_LABELS, EXPECTED_LABELS)
        self.assertEqual(len(set(expressions.EXPRESSION_LABELS)), 28)


class DescriptionContractTests(unittest.TestCase):
    def test_expression_descriptions_match_fixed_contract(self):
        self.assertEqual(
            expressions.EXPRESSION_DESCRIPTIONS,
            EXPECTED_EXPRESSION_DESCRIPTIONS,
        )
        self.assertEqual(
            tuple(expressions.EXPRESSION_DESCRIPTIONS),
            EXPECTED_LABELS,
        )


class PathAndValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.character = "吴莹莹"
        self.character_dir = self.root / self.character
        self.character_dir.mkdir()
        (self.character_dir / "profile.json").write_text(
            json.dumps({"name": self.character}, ensure_ascii=False),
            encoding="utf-8",
        )
        write_png(self.character_dir / f"{self.character}_头像.png", (864, 1152))
        write_png(self.character_dir / f"{self.character}_全身像.png", (1086, 1448))

    def test_resolve_expression_paths_finds_inputs_and_outputs(self):
        paths = expressions.resolve_expression_paths(self.root, self.character)

        self.assertEqual(paths.profile_path, self.character_dir / "profile.json")
        self.assertEqual(paths.portrait_path.name, "吴莹莹_头像.png")
        self.assertEqual(paths.full_body_path.name, "吴莹莹_全身像.png")
        self.assertEqual(paths.output_dir, self.character_dir / "expressions")
        self.assertEqual(
            paths.zip_path,
            self.character_dir / "吴莹莹_expressions.zip",
        )

    def test_resolve_accepts_legacy_numbered_reference_names(self):
        (self.character_dir / "吴莹莹_头像.png").unlink()
        (self.character_dir / "吴莹莹_全身像.png").unlink()
        write_png(self.character_dir / "吴莹莹_头像_1.png")
        write_png(self.character_dir / "吴莹莹_全身像_1.png")

        paths = expressions.resolve_expression_paths(self.root, self.character)

        self.assertEqual(paths.portrait_path.name, "吴莹莹_头像_1.png")
        self.assertEqual(paths.full_body_path.name, "吴莹莹_全身像_1.png")

    def test_resolve_fails_before_generation_when_input_is_missing(self):
        (self.character_dir / "profile.json").unlink()
        with self.assertRaisesRegex(expressions.ExpressionError, "profile.json"):
            expressions.resolve_expression_paths(self.root, self.character)

    def test_valid_expression_png_requires_exact_size_and_alpha(self):
        valid = self.character_dir / "valid.png"
        wrong_size = self.character_dir / "wrong-size.png"
        no_alpha = self.character_dir / "rgb.png"
        write_png(valid)
        write_png(wrong_size, (512, 512))
        write_png(no_alpha, mode="RGB")

        self.assertTrue(expressions.is_valid_expression_png(valid))
        self.assertFalse(expressions.is_valid_expression_png(wrong_size))
        self.assertFalse(expressions.is_valid_expression_png(no_alpha))


class PromptAndRequestTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "name": "Test Person",
            "bio": "Adult psychologist",
            "traits": ["black medium-length hair", "white camisole"],
        }

    def test_neutral_prompt_locks_identity_framing_and_transparency(self):
        prompt = expressions.build_expression_prompt(self.profile, "neutral")

        self.assertIn(expressions.EXPRESSION_DESCRIPTIONS["neutral"], prompt)
        self.assertIn("第一张参考图", prompt)
        self.assertIn("第二张参考图", prompt)
        self.assertIn("上半身半身像", prompt)
        self.assertIn("透明背景", prompt)
        self.assertIn("896×1280", prompt)

    def test_non_neutral_prompt_assigns_neutral_reference_and_only_changes_face(self):
        prompt = expressions.build_expression_prompt(self.profile, "anger")

        self.assertIn(expressions.EXPRESSION_DESCRIPTIONS["anger"], prompt)
        self.assertIn("第三张参考图", prompt)
        self.assertIn("neutral.png", prompt)
        self.assertIn("只改变面部表情", prompt)

    def test_normalize_expression_png_preserves_alpha_and_exact_size(self):
        result = expressions.normalize_expression_png(png_bytes())
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (896, 1280))
            self.assertIn("A", image.getbands())

    def test_request_expression_image_builds_native_gemini_payload(self):
        calls = []

        def transport(url, headers, payload, timeout):
            calls.append((url, headers, payload, timeout))
            return image_response(png_bytes())

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            portrait = root / "portrait.png"
            full_body = root / "full.png"
            write_png(portrait)
            write_png(full_body)
            result = expressions.request_expression_image(
                prompt="test prompt",
                reference_paths=(portrait, full_body),
                api_key="secret",
                base_url="https://example.test/v1beta",
                model="gemini-test",
                transport=transport,
                sleeper=lambda _: None,
            )

        self.assertEqual(len(calls), 1)
        url, headers, payload, timeout = calls[0]
        self.assertTrue(url.endswith("/models/gemini-test:generateContent"))
        self.assertEqual(headers["Authorization"], "Bearer secret")
        self.assertEqual(payload["generationConfig"]["responseModalities"], ["IMAGE"])
        self.assertEqual(
            payload["generationConfig"]["imageConfig"]["aspectRatio"],
            "3:4",
        )
        self.assertEqual(len(payload["contents"][0]["parts"]), 3)
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(image.size, (896, 1280))
            self.assertIn("A", image.getbands())


class GenerationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.character = "workflow-character"
        self.character_dir = self.root / self.character
        self.character_dir.mkdir()
        (self.character_dir / "profile.json").write_text(
            json.dumps(
                {
                    "name": self.character,
                    "bio": "鎴愬勾濂虫€?",
                    "traits": ["榛戝彂"],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        write_png(self.character_dir / f"{self.character}_头像.png", (864, 1152))
        write_png(self.character_dir / f"{self.character}_全身像.png", (1086, 1448))
        self.paths = expressions.resolve_expression_paths(self.root, self.character)

    def test_generates_neutral_first_and_uses_it_for_other_labels(self):
        calls = []

        def generator(**kwargs):
            calls.append(kwargs)
            return png_bytes()

        result = expressions.generate_expression_images(
            self.paths,
            api_key="key",
            base_url="https://example.test/v1beta",
            model="gemini-test",
            image_generator=generator,
        )

        self.assertEqual(calls[0]["label"], "neutral")
        self.assertEqual(len(calls[0]["reference_paths"]), 2)
        self.assertEqual(len(calls[1]["reference_paths"]), 3)
        self.assertEqual(
            calls[1]["reference_paths"][-1],
            self.paths.output_dir / "neutral.png",
        )
        self.assertEqual(len(result.generated), 28)
        self.assertEqual(result.failed, ())

    def test_skips_valid_files_but_overwrite_regenerates_them(self):
        existing = self.paths.output_dir / "neutral.png"
        write_png(existing)
        calls = []

        def generator(**kwargs):
            calls.append(kwargs["label"])
            return png_bytes()

        result = expressions.generate_expression_images(
            self.paths,
            api_key="key",
            base_url="https://example.test/v1beta",
            model="gemini-test",
            image_generator=generator,
        )
        self.assertIn("neutral", result.skipped)
        self.assertNotIn("neutral", calls)

        calls.clear()
        expressions.generate_expression_images(
            self.paths,
            api_key="key",
            base_url="https://example.test/v1beta",
            model="gemini-test",
            overwrite=True,
            image_generator=generator,
        )
        self.assertIn("neutral", calls)

    def test_invalid_existing_file_is_regenerated(self):
        write_png(self.paths.output_dir / "neutral.png", (64, 64))
        calls = []

        def generator(**kwargs):
            calls.append(kwargs["label"])
            return png_bytes()

        expressions.generate_expression_images(
            self.paths,
            api_key="key",
            base_url="https://example.test/v1beta",
            model="gemini-test",
            image_generator=generator,
        )
        self.assertIn("neutral", calls)

    def test_one_failure_is_recorded_and_later_labels_continue(self):
        calls = []

        def generator(**kwargs):
            label = kwargs["label"]
            calls.append(label)
            if label == "anger":
                raise expressions.ExpressionError("planned failure")
            return png_bytes()

        result = expressions.generate_expression_images(
            self.paths,
            api_key="key",
            base_url="https://example.test/v1beta",
            model="gemini-test",
            image_generator=generator,
        )

        self.assertEqual(result.failed, ("anger",))
        self.assertIn("surprise", calls)
        self.assertFalse((self.paths.output_dir / "anger.png").exists())


class ZipPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        character = "zip-character"
        character_dir = root / character
        character_dir.mkdir()
        (character_dir / "profile.json").write_text(
            json.dumps({"name": character}),
            encoding="utf-8",
        )
        write_png(character_dir / f"{character}_头像.png")
        write_png(character_dir / f"{character}_全身像.png")
        self.paths = expressions.resolve_expression_paths(root, character)

    def test_incomplete_outputs_do_not_create_zip(self):
        write_png(self.paths.output_dir / "neutral.png")

        with self.assertRaisesRegex(expressions.ExpressionError, r"\u7f3a\u5c11"):
            expressions.create_expression_zip(self.paths)

        self.assertFalse(self.paths.zip_path.exists())

    def test_complete_zip_has_exactly_28_root_entries(self):
        for label in expressions.EXPRESSION_LABELS:
            write_png(self.paths.output_dir / f"{label}.png")

        output = expressions.create_expression_zip(self.paths)

        with zipfile.ZipFile(output) as archive:
            self.assertEqual(
                archive.namelist(),
                [f"{label}.png" for label in expressions.EXPRESSION_LABELS],
            )
            self.assertTrue(all("/" not in name for name in archive.namelist()))


class CliTests(unittest.TestCase):
    def test_parser_exposes_required_options(self):
        args = expressions.build_parser().parse_args([
            "--character", "cli-character",
            "--root", "C:/persona",
            "--model", "gemini-test",
            "--overwrite",
            "--no-zip",
        ])

        self.assertEqual(args.character, "cli-character")
        self.assertEqual(args.root, Path("C:/persona"))
        self.assertEqual(args.model, "gemini-test")
        self.assertTrue(args.overwrite)
        self.assertTrue(args.no_zip)

    def test_main_returns_nonzero_when_required_input_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            code = expressions.main([
                "--character", "missing-character",
                "--root", temp,
            ])

        self.assertEqual(code, 1)
