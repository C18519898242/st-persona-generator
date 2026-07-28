#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import tempfile
import unittest
import base64
from pathlib import Path
from unittest.mock import patch

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
