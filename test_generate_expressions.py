#!/usr/bin/env python3
from __future__ import annotations

import io
import json
import tempfile
import unittest
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


def write_png(
    path: Path,
    size: tuple[int, int] = (896, 1280),
    mode: str = "RGBA",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    color = (120, 100, 90, 0) if mode == "RGBA" else (120, 100, 90)
    Image.new(mode, size, color).save(path, format="PNG")


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
