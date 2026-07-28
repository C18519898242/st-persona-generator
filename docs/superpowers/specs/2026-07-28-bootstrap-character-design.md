# Bootstrap Character：人物卡 + 模特参考图 → profile.json + 头像/全身像

**日期：** 2026-07-28  
**状态：** 已定稿（待实现）  
**仓库：** `st-persona-generator`

## 1. 背景与目标

现有流水线假设人物目录中**已经具备**：

- `profile.json`
- `{name}_头像.png` 或 `{name}_头像_1.png`
- `{name}_全身像.png` 或 `{name}_全身像_1.png`

然后由 `generate_with_gemini.py` 生成 13 张标准素材，再由 `generate_profiles.py` 渲染 `profile.html`。

缺口在**更上游**：用户持有 SillyTavern 风格人物卡与一张/多张模特参考图，需要自动得到可审阅的中间产物，再进入现有第二阶段。

### 1.1 目标（第一阶段 / Stage B 的前半）

新增 Python 脚本，调用 Gemini，完成：

| 输入 | 输出 |
|------|------|
| 人物卡（固定路径） | `profile.json`（可被下游消费） |
| `sample/` 下 1+ 张模特参考图 | `{name}_头像.png`、`{name}_全身像.png` |

用户**人工审阅**后，再单独运行现有：

```bash
python generate_with_gemini.py --character <目录名>
```

### 1.2 非目标（YAGNI）

- 不生成 13 张标准素材，不渲染 `profile.html`
- 不提供 Web UI / 一键合并第二阶段
- 不抽取独立 `gemini_client` 包（避免本期重构）
- 不自动重命名已有 `_1` 旧参考图
- 不支持多套服装批量出图；全身像仅默认**工作装**
- 人物目录不存在时不自动创建空角色目录

## 2. 用户流程

```text
.env: GEMINI_DEFAULT_ROOT, GEMINI_API_KEY
        ↓
{root}/雨彤/人物卡.txt  +  sample/*.{jpg,png}
        ↓  python bootstrap_character.py --character 雨彤
profile.json  +  {name}_头像.png  +  {name}_全身像.png
        ↓  人工审阅
python generate_with_gemini.py --character 雨彤
        ↓
assets_简介/（13 张 JPEG）+ profile.html
```

## 3. 目录与命名约定

相对 `GEMINI_DEFAULT_ROOT`（与 `generate_with_gemini.get_default_root()` 一致；未配置时回退为模板目录的父目录）。

```text
{root}/
└── 雨彤/                              # --character 值 = 目录名
    ├── 人物卡.txt                     # 优先
    ├── 人物卡_雨彤.txt                # 回退（仅当 人物卡.txt 不存在）
    ├── sample/                        # 模特参考图，至少 1 张
    │   ├── a.jpg
    │   └── b.png
    ├── profile.json                   # 输出
    ├── <name>_头像.png                # 输出；name 来自 profile.json
    └── <name>_全身像.png              # 输出
```

### 3.1 人物卡定位

1. `{character_dir}/人物卡.txt`
2. 否则 `{character_dir}/人物卡_{character}.txt`
3. 都没有 → 报错并打印期望路径

### 3.2 参考图定位

- 扫描 `{character_dir}/sample/` 下扩展名 `.jpg` / `.jpeg` / `.png`（大小写不敏感）
- 按**文件名**稳定排序
- 0 张 → 报错
- 编码进请求前可将单张最长边限制为 ≤ 2048（仅内存缩放，**不修改** `sample/` 原文件）

### 3.3 输出命名

- 优先新命名：`{name}_头像.png`、`{name}_全身像.png`（匹配 `load_character` 的 preferred 路径）
- `name` 取自 `profile.json` 的 `name` 字段（解析自人物卡 Name 区块；为空则回退为 `--character` 目录名）

## 4. CLI

脚本路径：`bootstrap_character.py`（与 `generate_with_gemini.py` 并列）。

| 参数 | 必填 | 说明 |
|------|------|------|
| `--character` | 是 | 人物目录名 |
| `--root` | 否 | 覆盖默认根目录 |
| `--overwrite` | 否 | 覆盖已有有效 `profile.json` 与两张参考图 |
| `--dry-run` | 否 | 只解析与规划，不调 API、不写文件 |
| `--model` | 否 | 图片模型，默认与现网 `DEFAULT_MODEL` 一致 |
| `--base-url` | 否 | 默认与 `generate_with_gemini` 相同解析顺序 |

鉴权：环境变量 `GEMINI_API_KEY`；通过现有 `load_env_file(DEFAULT_ENV_FILE)` 加载 `.env`。

日常调用示例：

```bash
python bootstrap_character.py --character 雨彤
```

## 5. 跳过与覆盖策略

无 `--overwrite` 时：

| 产物 | 跳过条件 |
|------|----------|
| `profile.json` | 文件存在且通过 **bootstrap 结构校验**（见 §7；不要求 13 张图） |
| 头像 / 全身像 | 目标路径存在且像素尺寸精确匹配；**或**仅存在合法尺寸的旧名 `{name}_头像_1.png` / `{name}_全身像_1.png`（视为已有参考，跳过生成，不强制改名） |
| 存在但尺寸错误 | 视为无效，重新生成 |

有 `--overwrite`：强制重做 JSON 与两张图（仍写新命名路径）。

部分失败时：已成功写入的文件保留；进程以退出码 `1` 结束；再次运行时跳过策略使任务可重入。

## 6. `profile.json` 生成

### 6.1 策略：规则抽取 + Gemini 补全

**本地解析人物卡**（`【Section】` / 分隔线区块）→ `CardData`：

| 区块 | 用途 |
|------|------|
| Name / 角色名 | 默认 `name` |
| Description 内基本信息 / 外貌 / 工作着装等 | `facts` 草稿、工作装文案、体态 |
| Personality | 供 tagline / factNote / tags |
| Scenario / First Message 等 | 可选上下文摘要，不强制写入必填字段 |
| 合规与年龄表述 | 仅用于 prompt 约束（虚构成年） |

- 不执行 `{{char}}` / `{{user}}` 宏
- 从「常见着装 / 工作：」类句子提取**默认工作装**描述
- 缺块不崩溃，以空串 + 默认/Gemini 补齐

### 6.2 本地固定（模型不可覆盖）

以下字段由脚本写入，合并时以本地为准：

- `schemaVersion`: `1`
- `assetDir`: `"assets_简介"`
- `images.views`：三文件名与顺序固定为 `view_front.jpg` / `view_side.jpg` / `view_back.jpg`，label 与 className 与现网示例一致（正面/侧面/背面 + focus-\*）
- `images.expressions`：六文件名顺序固定为  
  `exp_calm.jpg` … `exp_shy.jpg`（与 `EXPECTED_ASSETS` 完全一致），默认中文 label：平静/微笑/认真/惊讶/思考/羞涩
- `images.items`：四文件名固定为  
  `item_blouse.jpg` / `item_skirt.jpg` / `item_hose.jpg` / `item_shoes.jpg`  
  （**仅 label 可由 Gemini 填写**，语义对应上装/下装/袜/鞋）
- `images.details`：  
  - 面部与发型 → `exp_calm.jpg`  
  - 职业装侧影 → `view_side.jpg` + `className: focus-full`
- `display` 默认：

```json
{
  "frontScale": 1.04,
  "sideScale": 1.04,
  "backScale": 1.04,
  "expressionAspect": 0.7,
  "expressionPosition": "center 22%"
}
```

可选：`$schema` 若能稳定算出指向模板内 `profile_schema.json` 的相对路径则写入，否则省略。

### 6.3 规则尽量填充

| 字段 | 来源 |
|------|------|
| `name` | 卡 Name，否则 `--character` |
| `facts[]` | 从基本信息抽取姓名/年龄/职业/气质/体态等；保证至少一项 |

### 6.4 Gemini 文本补全

一次 `generateContent` 文本请求，要求**只输出 JSON 对象**，字段包括：

- `nameEn`
- `tagline`
- `seal`: `letters`（≤5）、`cn`（≤3）、`en`（≤12）
- `theme.accent` / `accentSoft` / `palette`（1–6 项，颜色 `#RRGGBB`）
- `factNote`、`bio`、`traits[]`、`tags[]`
- `images.items[*].label`（四项中文名）
- 可选：润色 `facts[].value`（不得破坏 label 列表结构）

约束写入 prompt：虚构成年、完整着装、非露骨；`bio`/`traits` 与默认工作装一致。

失败（非 JSON / 校验失败）有限重试（最多 3 次），与图片侧策略类似。

### 6.5 合并顺序

1. 构建本地骨架  
2. 应用 Gemini 补丁（忽略任何试图改写固定 file/display/schemaVersion/assetDir 的键）  
3. `validate_bootstrap_profile(config)`  
4. 原子写入 `profile.json`（UTF-8，`ensure_ascii=False`，缩进 2）

## 7. 校验边界（兼容下游）

### 7.1 Bootstrap 校验（写入 `profile.json` 前）

对齐 `generate_profiles` 中**不依赖图片文件存在**的约束，例如：

- 必填字符串：`name`、`nameEn`、`tagline`、`assetDir`、`factNote`、`bio`
- `seal` / `theme` 颜色 `#RRGGBB`、palette 非空
- `facts` / `traits` / `tags` 结构
- `display` 数值范围与 `expressionPosition` 字符集
- `images` 四组存在，且 **file 名与顺序**满足 `generate_with_gemini.EXPECTED_ASSETS` / `build_tasks`

**不**要求 `assets_简介` 目录存在，**不**要求 13 张图存在。

### 7.2 与下游通过条件

| 时机 | `load_character` + `build_tasks` | `generate_profiles.load_and_validate_config` |
|------|----------------------------------|-----------------------------------------------|
| bootstrap 刚结束 | 应通过 | 预期失败（缺 13 图）— 正常 |
| `generate_with_gemini` 成功后 | 应通过 | 应通过 |

可选：bootstrap 成功结束时打印 13 任务摘要（等价 dry-run 列表）及下一步命令提示。

## 8. 头像与全身像生成

### 8.1 尺寸与格式

| 产物 | 尺寸 | 请求比例 | 磁盘格式 |
|------|------|----------|----------|
| 头像 | 896×1280 | 请求 `aspectRatio` 与 `EXPECTED_ASSETS` 表情图一致（`3:4`）；落盘前 **fit 到精确 896×1280** | PNG RGB |
| 全身像 | 1024×1536 | 请求 `2:3`；落盘前 **fit 到精确 1024×1536** | PNG RGB |

规范化：居中 `ImageOps.fit`、LANCZOS、无拉伸；提供 `normalize_image_png`（算法对齐 `normalize_image`，输出 PNG 而非 JPEG）。写盘使用现有 `atomic_write`。

### 8.2 顺序

1. 确保 `profile.json`（生成或跳过加载）  
2. 生成/跳过全身像（参考 = 全部 `sample/*`；着装优先 `images.items`）  
3. 生成/跳过头像半身像（参考 = **全身像优先** + `sample/*`；同人同装，禁止另起服装）  
4. 打印结果与下一步

### 8.3 Prompt 要点

**共用：** 专业设定资料；成年；完整着装；非露骨；身份与参考图一致；干净背景；无文字/水印/拼图/额外人物；附 profile 摘要与工作装描述。

**全身像（先）：** 单人正面全身立绘；头到鞋完整；人物约占画高 86–91%；着装优先 profile 四单品 / 人物卡工作装；自然站姿。

**头像半身（后）：** 以全身像为身份与上装锚点；胸上半身像；完整头发/头/双肩/胸部；下沿约在胸部下方一点点；头部约占画高 38–48%；眼位约 30%；平静表情；**上装必须与全身像一致**；落盘前仅轻度裁掉过长下方。

请求：`responseModalities: ["IMAGE"]`，`imageConfig.aspectRatio` + `imageSize: "2K"`；429/5xx/无效图最多 3 次重试。复用 `http_post_json`、`extract_image` 等。

## 9. 模块结构

### 9.1 新文件

- `bootstrap_character.py` — CLI 与编排  
- `test_bootstrap_character.py` — 单测  

### 9.2 复用（import `generate_with_gemini`）

优先复用：`load_env_file`、`get_default_root`、`http_post_json`、`extract_image`、`atomic_write`、`GeneratorError` / `HttpStatusError` / `RetryableGenerationError`、`DEFAULT_BASE_URL` / `DEFAULT_MODEL` / `DEFAULT_ENV_FILE`、`encode_reference`（或等价逻辑）。

若图片请求封装重复过多，在 bootstrap 内做薄封装 `call_gemini_image`；**不**为本期大拆 `generate_with_gemini.py`。

### 9.3 逻辑骨架

```text
main
 └─ run_bootstrap(character, root, ...)
      ├─ resolve_paths()
      ├─ parse_character_card() → CardData
      ├─ ensure_profile_json()   # 跳过 | 骨架 + Gemini 文本 + 校验 + 写
      ├─ collect_sample_images()
      ├─ ensure_portrait()
      └─ ensure_full_body()
```

### 9.4 错误与退出码

| 情况 | 行为 |
|------|------|
| 人物目录不存在 | 报错退出（不自动创建） |
| 无人物卡 / sample 空 | 报错 + 期望路径 |
| 非 dry-run 且无 API Key | 报错 |
| 文本/图片重试耗尽 | 退出码 1，保留已写文件 |
| 成功 | 退出码 0 |

## 10. 测试计划

Mock transport，不打真 API：

1. **人物卡解析**：精简样例卡 → `name`、工作装相关文本、基本信息键可抽出  
2. **路径**：`人物卡.txt` 优先于 `人物卡_{character}.txt`；sample 过滤与排序  
3. **JSON 合并**：模型不得覆盖固定 `images.*.file` 顺序；颜色与 display 合法  
4. **跳过逻辑**：已有合法产物时不调用 transport；`--overwrite` 会调用  
5. **下游兼容冒烟**：写入 bootstrap 产物后，`load_character` + `build_tasks` 得 13 项且不抛错  

可选手工：真 API 跑 dry-run + 实生成，再 `generate_with_gemini --dry-run`。

## 11. README（实现期可选）

在 `README.md` 增加简短「第一阶段：从人物卡 bootstrap」小节：目录约定、命令、与第二阶段衔接。非阻塞实现核心代码。

## 12. 实现顺序建议

1. 路径解析 + 人物卡解析 + 单测  
2. 骨架 / 合并 / `validate_bootstrap_profile` + 单测  
3. Gemini 文本请求 + dry-run  
4. 头像/全身像请求 + PNG 规范化 + 跳过逻辑 + 单测  
5. CLI `main` 串联 + 兼容冒烟测试  
6. （可选）README 片段  

## 13. 决策记录

| 决策 | 选择 |
|------|------|
| 阶段划分 | 两段式：bootstrap 后人工审阅，再跑现有 13 图 + HTML |
| 脚本位置 | `st-persona-generator/bootstrap_character.py`，不合并第二阶段入口 |
| JSON 策略 | 规则骨架 + Gemini 补文案/配色 |
| 全身像服装 | 人物卡默认工作装 |
| CLI | 主参数仅 `--character`；root 来自 `GEMINI_DEFAULT_ROOT` |
| 参考图 | `{character}/sample/` |
| 人物卡 | `人物卡.txt` 优先，否则 `人物卡_{character}.txt` |
| 覆盖 | 默认跳过有效产物；`--overwrite` 全量重做 |
| 复用 | import 现有 Gemini 基建，不大重构 |
