# SillyTavern Expression Pack Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Python CLI that generates all 28 standard SillyTavern character-expression sprites from an existing character profile, portrait, and full-body reference, then packages them as an upload-ready ZIP.

**Architecture:** Create one focused `generate_expressions.py` module that reuses stable Gemini transport, image extraction, atomic writing, and reference encoding helpers from the existing generator modules. Keep path resolution, prompt construction, image validation, generation orchestration, and ZIP packaging as independently testable pure or dependency-injected functions; tests use `unittest` and fake transports without network access.

**Tech Stack:** Python 3, standard library (`argparse`, `json`, `zipfile`, `pathlib`), Pillow, existing native Gemini API helpers, `unittest`.

## Global Constraints

- Generate exactly the 28 standard labels listed in the approved design, with lowercase English PNG filenames.
- Write images to `<root>/<character>/expressions/`.
- Normalize every generated image to exactly `896 × 1280` PNG with an alpha channel.
- Use a uniform upper-body portrait composition and request a transparent background.
- Generate `neutral.png` first; every other expression references the portrait, full-body image, and `neutral.png`.
- Skip existing valid images unless `--overwrite` is supplied.
- Create `<character>_expressions.zip` only when all 28 output images are valid; ZIP entries must be at the archive root.
- Never print API keys or inline base64 data.
- Do not change the behavior of `bootstrap_character.py`, `generate_profiles.py`, or `generate_with_gemini.py`.
- All production behavior is implemented with a failing test first.

---

## File Structure

- Create `generate_expressions.py`: constants, paths, prompts, Gemini image request, orchestration, ZIP packaging, and CLI.
- Create `test_generate_expressions.py`: unit and CLI tests using temporary directories and fake Gemini responses.
- Modify `README.md`: document prerequisites, command usage, output layout, resume behavior, and SillyTavern import.

### Task 1: Standard labels, input resolution, and PNG validation

**Files:**
- Create: `generate_expressions.py`
- Create: `test_generate_expressions.py`

**Interfaces:**
- Produces: `EXPRESSION_LABELS: tuple[str, ...]`
- Produces: `EXPRESSION_SIZE: tuple[int, int]`
- Produces: `ExpressionError`
- Produces: `ExpressionPaths`
- Produces: `resolve_expression_paths(root: Path, character: str) -> ExpressionPaths`
- Produces: `is_valid_expression_png(path: Path) -> bool`
- Consumes later: all subsequent tasks use these constants, paths, and validation.

- [ ] **Step 1: Write failing tests for the label contract**

Add:

```python
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
```

- [ ] **Step 2: Run the label test and verify RED**

Run:

```powershell
python -m unittest test_generate_expressions.LabelContractTests -v
```

Expected: ERROR because `generate_expressions` does not exist.

- [ ] **Step 3: Add the minimal module constants**

Create `generate_expressions.py` with:

```python
#!/usr/bin/env python3
"""Generate a SillyTavern-compatible expression sprite pack."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


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
```

- [ ] **Step 4: Run the label test and verify GREEN**

Run:

```powershell
python -m unittest test_generate_expressions.LabelContractTests -v
```

Expected: PASS.

- [ ] **Step 5: Write failing tests for paths and image validation**

Append:

```python
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
```

- [ ] **Step 6: Run the path tests and verify RED**

Run:

```powershell
python -m unittest test_generate_expressions.PathAndValidationTests -v
```

Expected: FAIL because `ExpressionPaths`, `resolve_expression_paths`, and `is_valid_expression_png` are missing.

- [ ] **Step 7: Implement path resolution and validation**

Add imports and functions:

```python
import json

from PIL import Image, UnidentifiedImageError


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
```

- [ ] **Step 8: Run Task 1 tests and commit**

Run:

```powershell
python -m unittest test_generate_expressions.LabelContractTests test_generate_expressions.PathAndValidationTests -v
git diff --check
```

Expected: all Task 1 tests PASS; `git diff --check` prints nothing.

Commit:

```powershell
git add generate_expressions.py test_generate_expressions.py
git commit -m "feat: define expression pack inputs"
```

### Task 2: Prompts, RGBA normalization, and Gemini request

**Files:**
- Modify: `generate_expressions.py`
- Modify: `test_generate_expressions.py`

**Interfaces:**
- Consumes: `ExpressionPaths`, `EXPRESSION_SIZE`, `EXPRESSION_ASPECT_RATIO`
- Produces: `EXPRESSION_DESCRIPTIONS: dict[str, str]`
- Produces: `build_expression_prompt(profile: dict, label: str) -> str`
- Produces: `normalize_expression_png(image_bytes: bytes) -> bytes`
- Produces: `request_expression_image(...) -> bytes`
- Consumed later by: the generation workflow in Task 3.

- [ ] **Step 1: Write failing prompt and normalization tests**

Add imports `base64` and `unittest.mock.patch`, then append:

```python
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


class PromptAndRequestTests(unittest.TestCase):
    def setUp(self):
        self.profile = {
            "name": "吴莹莹",
            "bio": "成年女性心理医生",
            "traits": ["黑色中长发", "白色吊带与米白开衫"],
        }

    def test_neutral_prompt_locks_identity_framing_and_transparency(self):
        prompt = expressions.build_expression_prompt(self.profile, "neutral")

        self.assertIn("自然平静", prompt)
        self.assertIn("第一张参考图", prompt)
        self.assertIn("第二张参考图", prompt)
        self.assertIn("上半身半身像", prompt)
        self.assertIn("透明背景", prompt)
        self.assertIn("896×1280", prompt)

    def test_non_neutral_prompt_assigns_neutral_reference_and_only_changes_face(self):
        prompt = expressions.build_expression_prompt(self.profile, "anger")

        self.assertIn("明确生气", prompt)
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
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```powershell
python -m unittest test_generate_expressions.PromptAndRequestTests -v
```

Expected: FAIL because prompt, normalization, and request functions are missing.

- [ ] **Step 3: Implement expression descriptions and prompts**

Add all 28 fixed visual definitions:

```python
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
        "背景必须真正透明，人物边缘干净，不要纯色背景、渐变背景、"
        "棋盘格、场景、家具、文字、水印、边框或额外人物。"
        "交付单张 896×1280 PNG，只输出图片。"
    )
```

- [ ] **Step 4: Implement RGBA normalization and Gemini request**

Add imports and request code:

```python
import io
import time
from typing import Any, Callable, Sequence
from urllib.error import URLError
from urllib.parse import quote

from PIL import ImageOps

import bootstrap_character as bootstrap
import generate_with_gemini as gemini

Transport = Callable[
    [str, dict[str, str], dict[str, Any], float],
    dict[str, Any],
]


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
        bootstrap.encode_reference_resized(path)
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
```

- [ ] **Step 5: Run Task 2 and regression tests**

Run:

```powershell
python -m unittest test_generate_expressions.PromptAndRequestTests -v
python -m unittest test_bootstrap_character test_generate_with_gemini -v
```

Expected: all tests PASS.

- [ ] **Step 6: Commit**

```powershell
git add generate_expressions.py test_generate_expressions.py
git commit -m "feat: generate consistent expression images"
```

### Task 3: Resumable 28-image orchestration

**Files:**
- Modify: `generate_expressions.py`
- Modify: `test_generate_expressions.py`

**Interfaces:**
- Consumes: Task 1 paths/validation and Task 2 prompts/request.
- Produces: `ExpressionRunResult`
- Produces: `generate_expression_images(...) -> ExpressionRunResult`
- Consumed later by: ZIP packaging and CLI.

- [ ] **Step 1: Write failing workflow tests**

Append:

```python
class GenerationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.character = "吴莹莹"
        self.character_dir = self.root / self.character
        self.character_dir.mkdir()
        (self.character_dir / "profile.json").write_text(
            json.dumps(
                {"name": self.character, "bio": "成年女性", "traits": ["黑发"]},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        write_png(self.character_dir / "吴莹莹_头像.png", (864, 1152))
        write_png(self.character_dir / "吴莹莹_全身像.png", (1086, 1448))
        self.paths = expressions.resolve_expression_paths(
            self.root,
            self.character,
        )

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
```

- [ ] **Step 2: Run workflow tests and verify RED**

Run:

```powershell
python -m unittest test_generate_expressions.GenerationWorkflowTests -v
```

Expected: FAIL because `ExpressionRunResult` and `generate_expression_images` are missing.

- [ ] **Step 3: Implement resumable orchestration**

Add:

```python
@dataclass(frozen=True)
class ExpressionRunResult:
    generated: tuple[str, ...]
    skipped: tuple[str, ...]
    failed: tuple[str, ...]


def generate_expression_images(
    paths: ExpressionPaths,
    *,
    api_key: str,
    base_url: str,
    model: str,
    overwrite: bool = False,
    image_generator: Callable[..., bytes] | None = None,
) -> ExpressionRunResult:
    if not api_key.strip():
        raise ExpressionError("缺少环境变量 GEMINI_API_KEY")
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
            raw = generator(
                label=label,
                profile=profile,
                reference_paths=tuple(references),
                api_key=api_key,
                base_url=base_url,
                model=model,
            )
            normalized = normalize_expression_png(raw)
            gemini.atomic_write(output_path, normalized)
            if not is_valid_expression_png(output_path):
                raise ExpressionError(f"写入后校验失败：{output_path}")
            generated.append(label)
        except (
            OSError,
            ExpressionError,
            gemini.GeneratorError,
            URLError,
            TimeoutError,
            ConnectionError,
        ) as exc:
            print(f"表情生成失败 {label}：{exc}", file=sys.stderr)
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
```

Adjust the fake `generator` functions in the tests to return decoded source PNG bytes; `generate_expression_images` owns normalization and atomic writing. Add `import sys` to production imports.

- [ ] **Step 4: Run workflow and full expression tests**

Run:

```powershell
python -m unittest test_generate_expressions -v
```

Expected: all expression tests PASS.

- [ ] **Step 5: Commit**

```powershell
git add generate_expressions.py test_generate_expressions.py
git commit -m "feat: add resumable expression generation"
```

### Task 4: ZIP packaging and CLI

**Files:**
- Modify: `generate_expressions.py`
- Modify: `test_generate_expressions.py`

**Interfaces:**
- Consumes: `generate_expression_images` and `is_valid_expression_png`.
- Produces: `create_expression_zip(paths: ExpressionPaths) -> Path`
- Produces: `run_expression_pack(...) -> ExpressionPackResult`
- Produces: `build_parser() -> argparse.ArgumentParser`
- Produces: `main(argv: Sequence[str] | None = None) -> int`

- [ ] **Step 1: Write failing ZIP tests**

Add `zipfile` import and append:

```python
class ZipPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        character_dir = root / "吴莹莹"
        character_dir.mkdir()
        (character_dir / "profile.json").write_text(
            '{"name":"吴莹莹"}',
            encoding="utf-8",
        )
        write_png(character_dir / "吴莹莹_头像.png")
        write_png(character_dir / "吴莹莹_全身像.png")
        self.paths = expressions.resolve_expression_paths(root, "吴莹莹")

    def test_incomplete_outputs_do_not_create_zip(self):
        write_png(self.paths.output_dir / "neutral.png")
        with self.assertRaisesRegex(expressions.ExpressionError, "缺少"):
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
```

- [ ] **Step 2: Run ZIP tests and verify RED**

Run:

```powershell
python -m unittest test_generate_expressions.ZipPackagingTests -v
```

Expected: FAIL because `create_expression_zip` is missing.

- [ ] **Step 3: Implement atomic ZIP packaging**

Add:

```python
import os
import tempfile
import zipfile


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
```

- [ ] **Step 4: Write failing CLI tests**

Append:

```python
class CliTests(unittest.TestCase):
    def test_parser_exposes_required_options(self):
        args = expressions.build_parser().parse_args([
            "--character", "吴莹莹",
            "--root", "C:/persona",
            "--model", "gemini-test",
            "--overwrite",
            "--no-zip",
        ])
        self.assertEqual(args.character, "吴莹莹")
        self.assertEqual(args.root, Path("C:/persona"))
        self.assertEqual(args.model, "gemini-test")
        self.assertTrue(args.overwrite)
        self.assertTrue(args.no_zip)

    def test_main_returns_nonzero_when_required_input_is_missing(self):
        with tempfile.TemporaryDirectory() as temp:
            code = expressions.main([
                "--character", "不存在",
                "--root", temp,
            ])
        self.assertEqual(code, 1)
```

- [ ] **Step 5: Run CLI tests and verify RED**

Run:

```powershell
python -m unittest test_generate_expressions.CliTests -v
```

Expected: FAIL because parser and `main` are missing.

- [ ] **Step 6: Implement run result and CLI**

Add:

```python
import argparse


@dataclass(frozen=True)
class ExpressionPackResult:
    paths: ExpressionPaths
    images: ExpressionRunResult
    zip_path: Path | None


def run_expression_pack(
    *,
    root: Path,
    character: str,
    api_key: str | None,
    base_url: str,
    model: str,
    overwrite: bool = False,
    create_zip: bool = True,
    image_generator: Callable[..., bytes] | None = None,
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
        description="生成 SillyTavern 标准角色表情图片包",
    )
    parser.add_argument("--character", required=True, help="人物目录名")
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="人物根目录（默认 GEMINI_DEFAULT_ROOT）",
    )
    parser.add_argument(
        "--model",
        default=gemini.DEFAULT_MODEL,
        help="Gemini 图片模型",
    )
    parser.add_argument(
        "--base-url",
        default=(
            os.environ.get("GEMINI_BASE_URL")
            or os.environ.get("GEMINI_BASE_RUL")
            or gemini.DEFAULT_BASE_URL
        ),
        help="Gemini API Base URL",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="重新生成已有有效图片",
    )
    parser.add_argument(
        "--no-zip",
        action="store_true",
        help="不创建 ZIP 表情包",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        gemini.load_env_file(gemini.DEFAULT_ENV_FILE)
    except (OSError, gemini.GeneratorError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
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
    except (OSError, ExpressionError, gemini.GeneratorError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    print(f"生成：{len(result.images.generated)}")
    print(f"跳过：{len(result.images.skipped)}")
    print(f"失败：{len(result.images.failed)}")
    if result.images.failed:
        print("失败标签：" + ", ".join(result.images.failed), file=sys.stderr)
        return 1
    print(f"图片目录：{result.paths.output_dir}")
    if result.zip_path is not None:
        print(f"ZIP：{result.zip_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run Task 4 and all expression tests**

Run:

```powershell
python -m unittest test_generate_expressions -v
python generate_expressions.py --help
git diff --check
```

Expected: tests PASS; help lists `--character`, `--root`, `--model`, `--base-url`, `--overwrite`, and `--no-zip`; diff check prints nothing.

- [ ] **Step 8: Commit**

```powershell
git add generate_expressions.py test_generate_expressions.py
git commit -m "feat: package SillyTavern expressions"
```

### Task 5: Documentation and full verification

**Files:**
- Modify: `README.md`
- Test: `test_generate_expressions.py`

**Interfaces:**
- Consumes: final CLI and output contract.
- Produces: user-facing workflow for generating and importing the ZIP.

- [ ] **Step 1: Add a failing README contract test**

Append:

```python
class ReadmeTests(unittest.TestCase):
    def test_readme_documents_expression_pack_command_and_import(self):
        readme = (
            Path(__file__).resolve().parent / "README.md"
        ).read_text(encoding="utf-8")
        self.assertIn("generate_expressions.py", readme)
        self.assertIn("--character \"吴莹莹\"", readme)
        self.assertIn("吴莹莹_expressions.zip", readme)
        self.assertIn("上传表情图片包", readme)
        self.assertIn("896 × 1280", readme)
```

- [ ] **Step 2: Run the README test and verify RED**

Run:

```powershell
python -m unittest test_generate_expressions.ReadmeTests -v
```

Expected: FAIL because the new script usage is not documented.

- [ ] **Step 3: Add the README usage section**

Add a section after the existing bootstrap usage:

```markdown
## 生成 SillyTavern 表情图片包

角色目录已经包含 `profile.json`、`角色名_头像.png` 和
`角色名_全身像.png` 后，运行：

```powershell
python generate_expressions.py --character "吴莹莹"
```

脚本生成 SillyTavern 全部 28 个标准表情。图片保存在：

```text
吴莹莹/
├── expressions/
│   ├── neutral.png
│   ├── joy.png
│   ├── anger.png
│   └── ...
└── 吴莹莹_expressions.zip
```

表情图统一为 `896 × 1280` 上半身透明 PNG。脚本先生成
`neutral.png`，其余图片使用头像、全身像和 neutral 图共同锁定
人物身份、服装和构图。

再次运行会跳过已有有效图片并继续缺失项目。要全部重做：

```powershell
python generate_expressions.py --character "吴莹莹" --overwrite
```

只生成图片、不创建 ZIP：

```powershell
python generate_expressions.py --character "吴莹莹" --no-zip
```

生成完成后，在 SillyTavern 的“角色表情”设置中点击
“上传表情图片包（ZIP）”，选择 `吴莹莹_expressions.zip`。
```

- [ ] **Step 4: Run README and full regression tests**

Run:

```powershell
python -m unittest test_generate_expressions -v
python -m unittest discover -p "test_*.py" -v
python -m compileall -q generate_expressions.py
git diff --check
```

Expected: all tests PASS, compile command exits 0, diff check prints nothing.

- [ ] **Step 5: Perform a no-network input smoke check with 吴莹莹**

Run:

```powershell
python -c "from pathlib import Path; import generate_expressions as g; p=g.resolve_expression_paths(Path(r'C:\src\g\persona\被催眠的表妹和老婆'), '吴莹莹'); print(p.portrait_path.name); print(p.full_body_path.name); print(p.output_dir)"
```

Expected:

```text
吴莹莹_头像.png
吴莹莹_全身像.png
C:\src\g\persona\被催眠的表妹和老婆\吴莹莹\expressions
```

Do not run the real 28-image API generation unless the user explicitly authorizes the cost.

- [ ] **Step 6: Commit documentation**

```powershell
git add README.md test_generate_expressions.py
git commit -m "docs: explain SillyTavern expression generation"
```

- [ ] **Step 7: Final repository verification**

Run:

```powershell
git status --short
git log -6 --oneline
```

Expected: working tree clean; recent history contains the four implementation commits plus the design and plan commits.
