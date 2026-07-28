import base64
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

try:
    import generate_with_gemini as generator
except ModuleNotFoundError:
    generator = None


def make_png(path: Path, size: tuple[int, int]) -> None:
    Image.new("RGB", size, "#C49A8A").save(path, format="PNG")


def make_png_bytes(size: tuple[int, int]) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, "#C49A8A").save(output, format="PNG")
    return output.getvalue()


def make_split_color_png_bytes(size: tuple[int, int]) -> bytes:
    image = Image.new("RGB", size, "red")
    midpoint = size[0] // 2
    for x in range(midpoint, size[0]):
        for y in range(size[1]):
            image.putpixel((x, y), (0, 0, 255))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def image_response(raw: bytes, *, snake_case: bool = False) -> dict:
    inline_key = "inline_data" if snake_case else "inlineData"
    mime_key = "mime_type" if snake_case else "mimeType"
    return {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            inline_key: {
                                mime_key: "image/png",
                                "data": base64.b64encode(raw).decode("ascii"),
                            }
                        }
                    ]
                }
            }
        ]
    }


class CharacterPlanningTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(generator, "generate_with_gemini 模块尚未实现")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)
        self.character_dir = self.root / "测试人物"
        self.character_dir.mkdir()
        config = {
            "name": "测试人物",
            "bio": "二十五岁的成年女性，黑色直发。",
            "traits": ["黑色直发", "米色开衫"],
            "facts": [{"label": "年龄", "value": "25 岁"}],
            "theme": {"palette": [{"name": "米色", "color": "#E8DCC8"}]},
            "images": {
                "views": [
                    {"label": "正面", "file": "view_front.jpg"},
                    {"label": "侧面", "file": "view_side.jpg"},
                    {"label": "背面", "file": "view_back.jpg"},
                ],
                "expressions": [
                    {"label": "平静", "file": "exp_calm.jpg"},
                    {"label": "微笑", "file": "exp_smile.jpg"},
                    {"label": "认真", "file": "exp_serious.jpg"},
                    {"label": "惊讶", "file": "exp_surprise.jpg"},
                    {"label": "思考", "file": "exp_think.jpg"},
                    {"label": "羞涩", "file": "exp_shy.jpg"},
                ],
                "items": [
                    {"label": "米色开衫", "file": "item_blouse.jpg"},
                    {"label": "短裙", "file": "item_skirt.jpg"},
                    {"label": "丝袜", "file": "item_hose.jpg"},
                    {"label": "高跟鞋", "file": "item_shoes.jpg"},
                ],
            },
        }
        (self.character_dir / "profile.json").write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
        )
        make_png(self.character_dir / "测试人物_头像.png", (128, 128))
        make_png(self.character_dir / "测试人物_全身像.png", (128, 192))

    def test_load_character_finds_config_and_two_references(self):
        character = generator.load_character(self.root, "测试人物")

        self.assertEqual(character.portrait_path.name, "测试人物_头像.png")
        self.assertEqual(character.full_body_path.name, "测试人物_全身像.png")
        self.assertEqual(character.assets_dir, self.character_dir / "assets_简介")

    def test_load_character_reports_exact_missing_reference_path(self):
        portrait = self.character_dir / "测试人物_头像.png"
        portrait.unlink()

        with self.assertRaisesRegex(
            generator.GeneratorError,
            str(portrait).replace("\\", r"\\"),
        ):
            generator.load_character(self.root, "测试人物")

    def test_load_character_falls_back_to_legacy_numbered_references(self):
        portrait = self.character_dir / "测试人物_头像.png"
        full_body = self.character_dir / "测试人物_全身像.png"
        portrait.rename(self.character_dir / "测试人物_头像_1.png")
        full_body.rename(self.character_dir / "测试人物_全身像_1.png")

        character = generator.load_character(self.root, "测试人物")

        self.assertEqual(character.portrait_path.name, "测试人物_头像_1.png")
        self.assertEqual(
            character.full_body_path.name,
            "测试人物_全身像_1.png",
        )

    def test_build_tasks_has_exact_names_sizes_and_ratios(self):
        character = generator.load_character(self.root, "测试人物")

        tasks = generator.build_tasks(character)

        self.assertEqual(len(tasks), 13)
        self.assertEqual(
            [
                (task.filename, task.target_size, task.aspect_ratio)
                for task in tasks
            ],
            [
                ("view_front.jpg", (1024, 1536), "2:3"),
                ("view_side.jpg", (1024, 1536), "2:3"),
                ("view_back.jpg", (1024, 1536), "2:3"),
                ("exp_calm.jpg", (896, 1280), "3:4"),
                ("exp_smile.jpg", (896, 1280), "3:4"),
                ("exp_serious.jpg", (896, 1280), "3:4"),
                ("exp_surprise.jpg", (896, 1280), "3:4"),
                ("exp_think.jpg", (896, 1280), "3:4"),
                ("exp_shy.jpg", (896, 1280), "3:4"),
                ("item_blouse.jpg", (1024, 2048), "9:16"),
                ("item_skirt.jpg", (1024, 2048), "9:16"),
                ("item_hose.jpg", (1024, 2048), "9:16"),
                ("item_shoes.jpg", (1024, 2048), "9:16"),
            ],
        )

    def test_prompt_marks_adult_and_specializes_each_kind(self):
        character = generator.load_character(self.root, "测试人物")
        prompts = {}
        for task in generator.build_tasks(character):
            prompts.setdefault(
                task.kind,
                generator.build_prompt(character, task),
            )

        for kind, prompt in prompts.items():
            self.assertIn("成年人", prompt)
            self.assertIn("完整着装", prompt)
            self.assertIn("不要文字", prompt)
            if kind != "expression":
                self.assertIn("禁止换人", prompt)
        self.assertIn("从头顶到鞋底完整可见", prompts["view"])
        self.assertIn("表情编辑", prompts["expression"])
        self.assertIn("仅以参考头像图像为准", prompts["expression"])
        self.assertNotIn("人物简介", prompts["expression"])
        self.assertIn("标准头像特写", prompts["expression"])
        self.assertIn("锁骨或胸口中上部", prompts["expression"])
        self.assertIn("双肩与上衣领口必须可见", prompts["expression"])
        self.assertIn("禁止比参考头像更近的大脸特写", prompts["expression"])
        self.assertIn("禁止换人换脸", prompts["expression"])
        self.assertIn("禁止手部遮挡主要五官", prompts["expression"])
        self.assertIn("严禁出现人物、人体", prompts["item"])

    def test_back_view_forbids_front_back_comparison(self):
        character = generator.load_character(self.root, "测试人物")
        task = next(
            task
            for task in generator.build_tasks(character)
            if task.filename == "view_back.jpg"
        )

        prompt = generator.build_prompt(character, task)

        self.assertIn("只显示这个人物的完整背面", prompt)
        self.assertIn("不得做正背面对照或并排拼图", prompt)

    def test_item_prompt_forbids_hidden_or_partial_people(self):
        character = generator.load_character(self.root, "测试人物")
        task = next(
            task
            for task in generator.build_tasks(character)
            if task.filename == "item_blouse.jpg"
        )

        prompt = generator.build_prompt(character, task)

        self.assertIn("上装单件", prompt)
        self.assertIn("电商产品图", prompt)
        self.assertIn("严禁整套穿搭拼贴", prompt)
        self.assertIn("这不是穿在身上的效果图", prompt)
        self.assertIn("只允许出现这一件商品", prompt)


class GeminiClientTests(unittest.TestCase):
    def setUp(self):
        CharacterPlanningTests.setUp(self)
        self.character = generator.load_character(self.root, "测试人物")
        self.task = generator.build_tasks(self.character)[0]
        self.raw_image = make_png_bytes((64, 96))

    def test_build_request_uses_native_inline_data_and_image_only_output(self):
        request = generator.build_request(self.character, self.task)
        parts = request["contents"][0]["parts"]

        self.assertEqual(
            parts[0]["text"],
            generator.build_prompt(self.character, self.task),
        )
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[1]["inlineData"]["mimeType"], "image/png")
        self.assertEqual(
            base64.b64decode(parts[1]["inlineData"]["data"]),
            self.character.portrait_path.read_bytes(),
        )
        self.assertEqual(
            base64.b64decode(parts[2]["inlineData"]["data"]),
            self.character.full_body_path.read_bytes(),
        )
        self.assertEqual(
            request["generationConfig"]["responseModalities"],
            ["IMAGE"],
        )
        self.assertEqual(
            request["generationConfig"]["imageConfig"],
            {"aspectRatio": "2:3", "imageSize": "2K"},
        )
        self.assertNotIn(
            "responseFormat",
            request["generationConfig"],
        )

    def test_expression_request_uses_portrait_only_never_calm_or_full_body(self):
        calm_path = self.character.assets_dir / "exp_calm.jpg"
        calm_path.parent.mkdir(parents=True, exist_ok=True)
        Image.new("RGB", (64, 96), "#C49A8A").save(calm_path, format="JPEG")
        for filename in ("exp_calm.jpg", "exp_smile.jpg"):
            expression = next(
                task
                for task in generator.build_tasks(self.character)
                if task.filename == filename
            )
            parts = generator.build_request(self.character, expression)[
                "contents"
            ][0]["parts"]
            self.assertEqual(len(parts), 2, filename)
            self.assertEqual(
                base64.b64decode(parts[1]["inlineData"]["data"]),
                self.character.portrait_path.read_bytes(),
            )

    def test_extract_image_reads_camel_case_inline_data(self):
        self.assertEqual(
            generator.extract_image(image_response(self.raw_image)),
            (self.raw_image, "image/png"),
        )

    def test_extract_image_reads_snake_case_inline_data(self):
        self.assertEqual(
            generator.extract_image(
                image_response(self.raw_image, snake_case=True)
            ),
            (self.raw_image, "image/png"),
        )

    def test_extract_image_rejects_response_without_image(self):
        with self.assertRaisesRegex(
            generator.RetryableGenerationError,
            "没有返回图片",
        ):
            generator.extract_image(
                {
                    "candidates": [
                        {"content": {"parts": [{"text": "no image"}]}}
                    ]
                }
            )

    def test_extract_image_rejects_invalid_base64(self):
        response = image_response(self.raw_image)
        response["candidates"][0]["content"]["parts"][0]["inlineData"][
            "data"
        ] = "not valid base64!"

        with self.assertRaisesRegex(
            generator.RetryableGenerationError,
            "Base64",
        ):
            generator.extract_image(response)

    def test_request_image_builds_url_and_bearer_header(self):
        calls = []

        def transport(url, headers, payload, timeout):
            calls.append((url, headers, payload, timeout))
            return image_response(self.raw_image)

        result = generator.request_image(
            self.character,
            self.task,
            api_key="secret",
            base_url="https://example.test/v1beta/",
            model="gemini-3.1-flash-image",
            transport=transport,
            sleeper=lambda _: None,
        )

        self.assertEqual(result, (self.raw_image, "image/png"))
        self.assertEqual(
            calls[0][0],
            "https://example.test/v1beta/models/"
            "gemini-3.1-flash-image:generateContent",
        )
        self.assertEqual(calls[0][1]["Authorization"], "Bearer secret")
        self.assertEqual(
            calls[0][2],
            generator.build_request(self.character, self.task),
        )

    def test_request_image_retries_429_and_5xx(self):
        attempts = []
        sleeps = []

        def transport(url, headers, payload, timeout):
            attempts.append(url)
            if len(attempts) == 1:
                raise generator.HttpStatusError(429, "busy")
            if len(attempts) == 2:
                raise generator.HttpStatusError(503, "unavailable")
            return image_response(self.raw_image)

        result = generator.request_image(
            self.character,
            self.task,
            api_key="secret",
            transport=transport,
            sleeper=sleeps.append,
        )

        self.assertEqual(result, (self.raw_image, "image/png"))
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeps, [1.0, 2.0])

    def test_request_image_retries_decodable_base64_that_is_not_an_image(self):
        attempts = []
        sleeps = []

        def transport(url, headers, payload, timeout):
            attempts.append(url)
            raw = b"not an image" if len(attempts) == 1 else self.raw_image
            return image_response(raw)

        result = generator.request_image(
            self.character,
            self.task,
            api_key="secret",
            transport=transport,
            sleeper=sleeps.append,
        )

        self.assertEqual(result, (self.raw_image, "image/png"))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(sleeps, [1.0])

    def test_request_image_does_not_retry_401_or_expose_secret(self):
        attempts = []

        def transport(url, headers, payload, timeout):
            attempts.append(url)
            raise generator.HttpStatusError(401, "invalid key")

        with self.assertRaises(generator.HttpStatusError) as raised:
            generator.request_image(
                self.character,
                self.task,
                api_key="top-secret",
                transport=transport,
                sleeper=lambda _: self.fail("401 不应重试"),
            )

        self.assertEqual(len(attempts), 1)
        self.assertNotIn("top-secret", str(raised.exception))


class ImageProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.root = Path(self.temp_dir.name)

    def test_normalize_image_center_crops_and_outputs_rgb_jpeg(self):
        source = make_split_color_png_bytes((300, 100))

        output = generator.normalize_image(source, (100, 100))

        with Image.open(io.BytesIO(output)) as image:
            image.load()
            self.assertEqual(image.size, (100, 100))
            self.assertEqual(image.mode, "RGB")
            self.assertEqual(image.format, "JPEG")
            left = image.getpixel((10, 50))
            right = image.getpixel((90, 50))
            self.assertGreater(left[0], left[2])
            self.assertGreater(right[2], right[0])

    def test_normalize_headshot_keeps_upper_region(self):
        """偏长半身图在 headshot 模式下应收紧，上方内容占比更高。"""
        image = Image.new("RGB", (100, 200), "blue")
        for y in range(0, 100):
            for x in range(100):
                image.putpixel((x, y), (255, 0, 0))  # 上半红=脸肩
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        source = buffer.getvalue()

        plain = generator.normalize_image(source, (50, 100), headshot=False)
        headshot = generator.normalize_image(source, (50, 100), headshot=True)

        def red_fraction(raw: bytes) -> float:
            with Image.open(io.BytesIO(raw)) as img:
                img.load()
                pixels = list(img.getdata())
            return sum(1 for p in pixels if p[0] > 200) / len(pixels)

        with Image.open(io.BytesIO(headshot)) as head_img:
            self.assertEqual(head_img.size, (50, 100))
        self.assertGreater(red_fraction(headshot), red_fraction(plain))

    def test_is_valid_output_requires_exact_size_and_complete_jpeg(self):
        valid = self.root / "valid.jpg"
        valid.write_bytes(
            generator.normalize_image(
                make_png_bytes((60, 90)),
                (40, 80),
            )
        )

        self.assertTrue(generator.is_valid_output(valid, (40, 80)))
        self.assertFalse(generator.is_valid_output(valid, (41, 80)))
        valid.write_bytes(b"broken")
        self.assertFalse(generator.is_valid_output(valid, (40, 80)))

    def test_atomic_write_replaces_file_without_leaving_temp_file(self):
        output = self.root / "image.jpg"
        output.write_bytes(b"old")

        generator.atomic_write(output, b"new")

        self.assertEqual(output.read_bytes(), b"new")
        self.assertEqual(list(self.root.glob("*.tmp")), [])


class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        CharacterPlanningTests.setUp(self)
        self.character = generator.load_character(self.root, "测试人物")
        self.raw_image = make_png_bytes((128, 192))
        self.transport_calls = []
        self.html_calls = []

    def transport(self, url, headers, payload, timeout):
        self.transport_calls.append((url, headers, payload, timeout))
        return image_response(self.raw_image)

    def html_generator(self, config_path):
        self.html_calls.append(Path(config_path))
        output = self.character.assets_dir / "profile.html"
        output.write_text("<html>ok</html>", encoding="utf-8")
        return output

    def test_full_run_generates_13_images_then_html(self):
        result = generator.run_generation(
            root=self.root,
            character_name="测试人物",
            api_key="secret",
            transport=self.transport,
            sleeper=lambda _: None,
            html_generator=self.html_generator,
        )

        self.assertEqual(len(self.transport_calls), 13)
        self.assertEqual(self.html_calls, [self.character.config_path])
        self.assertEqual(result, self.character.assets_dir / "profile.html")
        for task in generator.build_tasks(self.character):
            path = self.character.assets_dir / task.filename
            self.assertTrue(
                generator.is_valid_output(path, task.target_size),
                task.filename,
            )

    def test_valid_existing_image_skips_unless_overwrite(self):
        first = generator.build_tasks(self.character)[0]
        self.character.assets_dir.mkdir()
        (self.character.assets_dir / first.filename).write_bytes(
            generator.normalize_image(self.raw_image, first.target_size)
        )

        generator.run_generation(
            root=self.root,
            character_name="测试人物",
            api_key="secret",
            transport=self.transport,
            sleeper=lambda _: None,
            html_generator=self.html_generator,
        )
        self.assertEqual(len(self.transport_calls), 12)

        self.transport_calls.clear()
        generator.run_generation(
            root=self.root,
            character_name="测试人物",
            api_key="secret",
            overwrite=True,
            transport=self.transport,
            sleeper=lambda _: None,
            html_generator=self.html_generator,
        )
        self.assertEqual(len(self.transport_calls), 13)

    def test_corrupt_existing_image_is_regenerated(self):
        first = generator.build_tasks(self.character)[0]
        self.character.assets_dir.mkdir()
        output = self.character.assets_dir / first.filename
        output.write_bytes(b"broken")

        generator.run_generation(
            root=self.root,
            character_name="测试人物",
            api_key="secret",
            transport=self.transport,
            sleeper=lambda _: None,
            html_generator=self.html_generator,
        )

        self.assertTrue(
            generator.is_valid_output(output, first.target_size)
        )
        self.assertEqual(len(self.transport_calls), 13)

    def test_failure_keeps_completed_image_and_does_not_generate_html(self):
        def fails_on_second(url, headers, payload, timeout):
            self.transport_calls.append((url, headers, payload, timeout))
            if len(self.transport_calls) == 2:
                raise generator.HttpStatusError(401, "unauthorized")
            return image_response(self.raw_image)

        with self.assertRaises(generator.HttpStatusError):
            generator.run_generation(
                root=self.root,
                character_name="测试人物",
                api_key="secret",
                transport=fails_on_second,
                sleeper=lambda _: None,
                html_generator=self.html_generator,
            )

        first = generator.build_tasks(self.character)[0]
        self.assertTrue(
            generator.is_valid_output(
                self.character.assets_dir / first.filename,
                first.target_size,
            )
        )
        self.assertEqual(self.html_calls, [])

    def test_dry_run_does_not_require_key_call_network_or_write(self):
        result = generator.run_generation(
            root=self.root,
            character_name="测试人物",
            api_key=None,
            dry_run=True,
            transport=lambda *args: self.fail("dry-run 不应访问网络"),
            sleeper=lambda _: None,
            html_generator=lambda *args: self.fail(
                "dry-run 不应生成 HTML"
            ),
        )

        self.assertIsNone(result)
        self.assertFalse(self.character.assets_dir.exists())

    def test_live_run_requires_api_key_before_network(self):
        with self.assertRaisesRegex(
            generator.GeneratorError,
            "GEMINI_API_KEY",
        ):
            generator.run_generation(
                root=self.root,
                character_name="测试人物",
                api_key=None,
                transport=lambda *args: self.fail(
                    "缺少密钥时不应访问网络"
                ),
                sleeper=lambda _: None,
                html_generator=self.html_generator,
            )


class CliTests(unittest.TestCase):
    def setUp(self):
        CharacterPlanningTests.setUp(self)
        env_patch = mock.patch.object(
            generator,
            "DEFAULT_ENV_FILE",
            self.root / ".env",
        )
        env_patch.start()
        self.addCleanup(env_patch.stop)

    def test_parser_requires_character_and_has_expected_defaults(self):
        parser = generator.build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args([])

        args = parser.parse_args(["--character", "测试人物"])
        self.assertEqual(args.model, "gemini-3.1-flash-image")
        self.assertEqual(
            args.base_url,
            "https://gemini.xyz365.tech/v1beta",
        )
        self.assertFalse(args.overwrite)
        self.assertFalse(args.dry_run)

    def test_main_dry_run_succeeds_without_api_key(self):
        stdout = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stdout(stdout):
                result = generator.main(
                    [
                        "--root",
                        str(self.root),
                        "--character",
                        "测试人物",
                        "--dry-run",
                    ]
                )

        self.assertEqual(result, 0)
        self.assertIn("13/13", stdout.getvalue())

    def test_main_live_mode_reports_missing_api_key(self):
        stderr = io.StringIO()
        with mock.patch.dict(os.environ, {}, clear=True):
            with contextlib.redirect_stderr(stderr):
                result = generator.main(
                    [
                        "--root",
                        str(self.root),
                        "--character",
                        "测试人物",
                    ]
                )

        self.assertEqual(result, 1)
        self.assertIn("GEMINI_API_KEY", stderr.getvalue())

    def test_main_forwards_overwrite_and_prints_html_path(self):
        output = self.character_dir / "assets_简介" / "profile.html"
        stdout = io.StringIO()
        with mock.patch.object(
            generator,
            "run_generation",
            return_value=output,
        ) as run:
            with mock.patch.dict(
                os.environ,
                {"GEMINI_API_KEY": "secret"},
                clear=True,
            ):
                with contextlib.redirect_stdout(stdout):
                    result = generator.main(
                        [
                            "--root",
                            str(self.root),
                            "--character",
                            "测试人物",
                            "--overwrite",
                        ]
                    )

        self.assertEqual(result, 0)
        self.assertTrue(run.call_args.kwargs["overwrite"])
        self.assertEqual(run.call_args.kwargs["api_key"], "secret")
        self.assertIn(str(output), stdout.getvalue())

    def test_main_loads_dotenv_and_supports_base_rul_alias(self):
        env_file = self.root / ".env"
        env_file.write_text(
            "GEMINI_API_KEY=dotenv-secret\n"
            "GEMINI_BASE_RUL=https://example.test/v1beta\n",
            encoding="utf-8",
        )
        output = self.character_dir / "assets_简介" / "profile.html"

        with mock.patch.object(
            generator,
            "DEFAULT_ENV_FILE",
            env_file,
            create=True,
        ):
            with mock.patch.object(
                generator,
                "run_generation",
                return_value=output,
            ) as run:
                with mock.patch.dict(os.environ, {}, clear=True):
                    result = generator.main(
                        [
                            "--root",
                            str(self.root),
                            "--character",
                            "测试人物",
                        ]
                    )

        self.assertEqual(result, 0)
        self.assertEqual(
            run.call_args.kwargs["api_key"],
            "dotenv-secret",
        )
        self.assertEqual(
            run.call_args.kwargs["base_url"],
            "https://example.test/v1beta",
        )

    def test_main_loads_default_root_from_dotenv(self):
        env_file = self.root / ".env"
        configured_root = self.root / "人物仓库"
        env_file.write_text(
            "GEMINI_API_KEY=dotenv-secret\n"
            f"GEMINI_DEFAULT_ROOT={configured_root}\n",
            encoding="utf-8",
        )

        with mock.patch.object(
            generator,
            "run_generation",
            return_value=None,
        ) as run:
            with mock.patch.dict(os.environ, {}, clear=True):
                result = generator.main(["--character", "测试人物"])

        self.assertEqual(result, 0)
        self.assertEqual(
            run.call_args.kwargs["root"],
            configured_root.resolve(),
        )


if __name__ == "__main__":
    unittest.main()
