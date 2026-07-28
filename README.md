# 通用人物简介页模板

这套工具用于把每个人物的文字资料和图片资源生成统一版式的 `profile.html`。

日常新增或修改人物时，主要编辑人物目录中的 `profile.json` 和 `assets_简介` 图片。除非需要调整所有人物的公共版式，否则不要直接修改生成后的 `profile.html`。

## 目录结构

```text
root/
├── _人物模板/
│   ├── README.md
│   ├── .env.example
│   ├── profile_template.html
│   ├── generate_profiles.py
│   ├── generate_with_gemini.py
│   ├── profile_schema.json
│   ├── test_generate_profiles.py
│   └── test_generate_with_gemini.py
└── 新人物/
    ├── profile.json
    └── assets_简介/
        ├── view_front.jpg
        ├── view_side.jpg
        ├── view_back.jpg
        ├── exp_calm.jpg
        ├── 其余五张 exp_*.jpg
        ├── 四张 item_*.jpg
        └── profile.html
```

新人物只需要 13 张源图片：三视图 3 张、表情图 6 张、服装拆解图 4 张。面部细节复用 `exp_calm.jpg`，职业装侧影复用 `view_side.jpg`，不需要额外生成 `detail_face.jpg` 或 `clothes.jpg`。

各文件职责：

| 文件 | 用途 | 是否经常修改 |
|---|---|---|
| `profile_template.html` | 所有人物共用的 HTML 和 CSS 版式 | 否 |
| `generate_profiles.py` | 扫描配置、检查图片并生成页面 | 否 |
| `generate_with_gemini.py` | 调用 Gemini 生成 13 张标准图片并生成页面 | 否 |
| `profile_schema.json` | `profile.json` 的字段格式说明 | 否 |
| `人物名/profile.json` | 当前人物的文字、配色、图片映射和裁切参数 | 是 |
| `人物名/assets_简介/*.jpg` | 当前人物使用的图片资源 | 是 |
| `人物名/assets_简介/profile.html` | 自动生成的最终页面 | 不要手改 |
| `profile.before-template.html` | 第一次覆盖旧页面时保存的备份 | 不要删除，除非确认不再需要 |

## 页面规格

- 设计画布：`1400 × 1860 px`
- 页面比例：约 `0.753`
- 浏览器显示：页面会按窗口宽度等比缩小，设计画布本身不会改变
- 页面主要区域：
  - 页眉与人物名称
  - 基本信息
  - 正面、侧面、背面三视图
  - 六张表情图
  - 四张服装拆解图
  - 两张局部细节图
  - 人物色板
  - 人物简介、视觉特征和标签

## 新人物图片标准 V2

以下尺寸是新人物图片的最终交付标准，不是模糊的建议值。向 AI 请求图片时应同时写明像素尺寸和宽高比；如果所用 AI 只能控制比例，必须按标准比例出图，并在交付前导出为表中的最终像素尺寸。

夏语冰和吴莹莹属于已经验收的旧版资源，不需要重画或调整。后面的“当前两个人物实际尺寸”只用于说明现状，不能作为新人物标准。

| 图片类别 | 最终尺寸 | 标准比例 | 数量 | 模板显示方式 |
|---|---:|---:|---:|---|
| 正面、侧面、背面 | `1024 × 1536` | `2:3` | 3 | `cover` |
| 表情图 | `896 × 1280` | `7:10` | 6 | `cover` |
| 服装拆解图 | `1024 × 2048` | `1:2` | 4 | `contain` |
| 面部与发型细节 | 复用 `exp_calm.jpg` | `7:10` | 0 张新增图片 | `cover` |
| 职业装侧影 | 复用 `view_side.jpg` | `2:3` | 0 张新增图片 | `contain` |

### 三视图构图要求

三张图最好使用相同画布、相同背景、相同人物比例和相同地面高度。

- 人物从头到脚必须完整。
- 头顶建议保留画面高度约 `5%` 的安全距离。
- 鞋底下方建议保留约 `4%–7%` 的安全距离。
- 人物主体高度必须占画面高度的 `86%–91%`。
- 正面、侧面、背面的人物头顶和脚底尽量处在同一水平线。
- 避免在原图顶部或底部增加白条、文字或装饰边框。
- 背景应尽量简洁，推荐暖米白或浅灰色。

如果原图带有多余边框，可以在 `display.frontScale`、`sideScale`、`backScale` 中轻微放大。通常不要超过 `1.12`，否则容易裁掉头发或鞋。

### 表情图构图要求

表情图与 bootstrap 参考图都是**统一的胸上半身像**（头+双肩+胸部，下沿在胸部稍下），不是大头特写，也不是拍到腰的大半身。统一使用 `896 × 1280`、`7:10` 竖版画布。

- 构图参考：完整头发、头部、双肩与胸部；下沿约在**胸部下方一点点**（可见上衣胸前，不到腰）。
- 头部（含发型）约占画面高度 `38%–48%`；双眼中心约在 `30%` 一带；脸部水平居中。
- **六张表情必须是同一个人**：同一镜头距离、机位高度、发型、服装、背景和光线；只改表情。
- 禁止大头特写、手部遮挡五官、夸张漫画表情、大幅转头，禁止换装/换发型，禁止腰线以下入画。
- 第一张 `exp_calm.jpg` 使用自然平静表情，必须清楚显示五官、发型和耳饰，因为它同时用于“面部与发型”细节。
- 六张表情**只**锚定人物头像做「表情编辑」，不挂全身像、不挂已生成的 `exp_calm`。
- 表情落盘时不做二次强裁；bootstrap 参考图仅在偏长时轻度收紧。

如果脸部位置偏高或偏低，通过 `display.expressionPosition` 调整，例如：

```json
"expressionPosition": "center 22%"
```

第二个百分比越小，图片显示区域越靠上；越大则越靠下。

如果想让表情框更长，减小 `display.expressionAspect`：

```json
"expressionAspect": 0.70
```

常见范围：

| 数值 | 效果 |
|---:|---|
| `0.60` | 很长的竖框 |
| `0.70` | 当前推荐值 |
| `0.76` | 稍短一些 |
| `1.00` | 正方形 |

### 服装拆解图要求

服装拆解图统一使用 `1024 × 2048`、`1:2` 竖版画布。该比例接近页面中四个服装展示框的实际比例，使用 `contain` 时不会再产生大块无效留白。

- 每张图只能展示一种服装类别。
- 上衣和裙装主体高度必须占画布 `78%–86%`。
- 丝袜纵向展开，主体高度必须占画布 `82%–90%`。
- 一双鞋上下错位或斜向纵向排列，整体高度必须占画布 `65%–78%`。
- 主体水平居中，四边至少保留 `7%` 安全距离。
- 四张图必须使用相同背景、光线、渲染风格和大小逻辑。
- 禁止出现人物、人体部位、衣架、模特、文字、边框、拼图和无关配件。
- 图片内部不要放名称；名称由 `profile.json` 中的 `label` 生成。

### 局部细节图要求

新人物不需要额外生成局部细节图，固定复用已有资源：

1. `exp_calm.jpg`：复用第一张平静表情图，显示面部、发型和耳饰。
2. `view_side.jpg`：复用三视图中的侧面全身图，显示职业装轮廓。

第二张侧面图使用 `className: "focus-full"`，模板会采用 `contain`，确保完整人物不会被裁掉。

现有夏语冰和吴莹莹目录中的 `detail_face.jpg`、`clothes.jpg` 可以继续保留；新人物不需要创建这两个文件。

## 标准图片命名

建议所有人物都使用同一套文件名，这样复制配置时只需要修改文字。

### 三视图

| 文件名 | 用途 |
|---|---|
| `view_front.jpg` | 正面全身 |
| `view_side.jpg` | 侧面全身，同时用于第二张局部细节 |
| `view_back.jpg` | 背面全身 |

### 表情图

| 文件名 | 默认标签 |
|---|---|
| `exp_calm.jpg` | 平静，同时用于第一张局部细节 |
| `exp_smile.jpg` | 微笑 |
| `exp_serious.jpg` | 认真 |
| `exp_surprise.jpg` | 惊讶 |
| `exp_think.jpg` | 思考 |
| `exp_shy.jpg` | 羞涩 |

表情名称并非强制。其他人物可以使用 `exp_angry.jpg`、`exp_sad.jpg` 等，只要同步修改 `profile.json`。

### 服装拆解

| 文件名 | 默认用途 |
|---|---|
| `item_blouse.jpg` | 上衣或衬衫 |
| `item_skirt.jpg` | 裙装或下装 |
| `item_hose.jpg` | 丝袜或袜子 |
| `item_shoes.jpg` | 鞋 |

### 局部细节

| 复用文件 | 用途 |
|---|---|
| `exp_calm.jpg` | 面部、发型、耳饰等 |
| `view_side.jpg` | 职业装侧面轮廓 |

## 当前两个人物的实际图片尺寸

这些是现有文件的真实尺寸，仅用于排查旧资源问题。它们已经通过人工验收，但并不符合统一的 V2 尺寸；新增人物必须使用前述 V2 最终交付尺寸。

| 文件名 | 夏语冰 | 吴莹莹 | 页面用途 |
|---|---:|---:|---|
| `view_front.jpg` | `864 × 1152` | `864 × 1152` | 正面三视图 |
| `view_side.jpg` | `864 × 1152` | `864 × 1152` | 侧面三视图、职业装侧影 |
| `view_back.jpg` | `864 × 1152` | `864 × 1152` | 背面三视图 |
| `exp_calm.jpg` | `832 × 1248` | `704 × 1472` | 平静 |
| `exp_smile.jpg` | `832 × 1248` | `704 × 1472` | 微笑 |
| `exp_serious.jpg` | `832 × 1248` | `704 × 1472` | 认真 |
| `exp_surprise.jpg` | `832 × 1248` | `704 × 1472` | 惊讶 |
| `exp_think.jpg` | `832 × 1248` | `704 × 1472` | 思考 |
| `exp_shy.jpg` | `832 × 1248` | `704 × 1472` | 羞涩 |
| `item_blouse.jpg` | `352 × 530` | `535 × 500` | 上衣拆解 |
| `item_skirt.jpg` | `331 × 648` | `395 × 559` | 下装拆解 |
| `item_hose.jpg` | `281 × 619` | `260 × 442` | 丝袜拆解 |
| `item_shoes.jpg` | `373 × 530` | `352 × 442` | 鞋类拆解 |
| `detail_face.jpg` | `832 × 1248` | `704 × 1472` | 面部与发型 |
| `clothes.jpg` | `704 × 1472` | `704 × 1472` | 备用素材，当前未使用 |

吴莹莹目录中的 `_preview_detail.jpg`、`_preview_expr.jpg` 以及各目录中的 `_tmp_full.png` 属于预览或调试文件，不参与页面生成。

## AI 标准出图提示词

以下提示词可以直接复制。使用时替换方括号中的内容，并把已有角色图作为人物身份、发型和服装参考图上传给 AI。

如果 AI 不支持指定精确像素，就指定标准宽高比生成，再以不拉伸、不改变构图的方式导出为最终尺寸。不能把错误比例的图片直接拉伸到目标尺寸。

### 提示词 1：单张三视图

正面、侧面、背面必须分别生成，不要让 AI 在一张图里制作三视图拼图。三次生成应使用相同提示词，只替换 `[视角]`。

```text
用途：人物设定页单张全身三视图资源。
人物参考：[人物姓名与完整外观描述]。
服装参考：[服装、鞋袜、发型和配饰的完整描述]。
本张视角：[正面 / 标准左侧面 / 正背面]，自然站立，双臂自然下垂。

最终画布必须为 1024 × 1536 px，宽高比 2:3，竖版单人全身图。
人物必须从头顶到鞋底完整可见，人物高度占画面 86%–91%。
头顶保留约 5% 空间，鞋底下方保留 4%–7% 空间。
人物水平居中，镜头高度、人物比例、地面线和背景必须与另外两张视图一致。
背景为干净、均匀的暖米白摄影棚背景，柔和正面光，无明显投影。

严格保持参考人物的脸型、年龄、身材比例、发型、服装结构、材质、颜色、鞋袜和配饰。
禁止透视夸张，禁止动态姿势，禁止裁掉头发或鞋，禁止额外人物、家具、文字、标签、边框、拼图和水印。
只输出一张当前视角的完整人物图。
```

三张图验收时必须并排检查：

- 头顶处在同一水平线。
- 鞋底和地面线处在同一水平线。
- 人物肩宽、头身比和整体高度一致。
- 服装长度、腰线、袖口和鞋跟高度一致。

### 提示词 2：单张表情图（标准头像）

六张表情分别生成，只替换 `[目标表情]`。第一张 `exp_calm.jpg` 的目标表情必须为“自然平静”。生成管线优先用人物头像作参考；非平静表情在平静图已存在时会额外锁定 `exp_calm.jpg`，保证六张同一人。

```text
用途：人物设定页统一标准头像与表情资源。
人物参考：[人物姓名与外观描述]，严格保持参考人物身份一致。
目标表情：[自然平静 / 微笑 / 认真 / 惊讶 / 思考 / 羞涩]。

最终画布必须为 896 × 1280 px，宽高比 7:10，竖版胸上半身像。
画面包含完整头发、头部、双肩与胸部，下沿约在胸部下方一点点；上衣胸前可见。
头部约占画高 38%–48%，双眼中心约 30%，禁止大头特写，禁止拍到腰线。
脸部水平居中，头顶保留安全距离，肩部不能被不自然截断。
六张必须是同一个人、同一镜头距离、同一机位高度、同一发型服装背景光线和色彩。
背景为干净、均匀的暖米白，柔和人像光。

只改变目标表情与极细微的眉眼嘴角。
严格保持脸型、年龄、五官比例、发型、耳饰和服装不变。
禁止改变人物身份，禁止夸张漫画表情，禁止手部遮挡主要五官，禁止文字、边框、拼图和水印。
只输出一张半身表情图。
```

`exp_calm.jpg` 同时用于页面的“面部与发型”细节，因此这一张尤其需要：

- 五官清楚，不能闭眼。
- 发型轮廓完整。
- 耳饰等标志性配件清晰可见。
- 表情自然平静，不要做夸张动作。
- 半身构图可作为另外五张表情的镜头模板。

### 提示词 3：上衣或裙装拆解图

分别生成 `item_blouse.jpg` 和 `item_skirt.jpg`，每张只放一件服装。

```text
用途：人物设定页服装拆解单品图。
服装参考：[准确描述上衣或裙装的版型、长度、颜色、材质、领口、袖口、腰线和细节]。
本张只展示：[上衣 / 裙装]。

最终画布必须为 1024 × 2048 px，宽高比 1:2，竖版单品展示。
服装主体高度占画布 78%–86%，水平居中。
四边至少保留 7% 安全距离，服装任何部分都不能超出画面。
正面平整展示，完整表现轮廓、剪裁、接缝、褶皱和材质。
背景为完全均匀的暖米白，与同一人物其他服装拆解图一致。
使用柔和均匀的产品摄影光线，不要强烈投影。

严格保持参考服装的颜色、长度、剪裁、材质和装饰。
一张图只能出现这一件服装。
禁止人物、人体、模特、衣架、衣柜、鞋袜、首饰、其他衣物、文字、标签、边框、拼图和水印。
```

### 提示词 4：丝袜或袜子拆解图

```text
用途：人物设定页袜类拆解单品图。
袜类参考：[颜色、透明度、长度、材质、袜口、脚尖和接缝描述]。

最终画布必须为 1024 × 2048 px，宽高比 1:2，竖版单品展示。
一双袜子自然并列或轻微错位纵向展开，必须完整显示袜口到脚尖。
袜类主体高度占画布 82%–90%，水平居中。
四边至少保留 7% 安全距离。
清楚表现透明度、弹性、织物纹理、袜口和脚尖结构。
背景为完全均匀的暖米白，与其他服装拆解图一致。

只展示这一双袜子。
禁止腿、脚、人体、模特、衣架、鞋、其他衣物、文字、标签、边框、拼图和水印。
```

### 提示词 5：鞋类拆解图

```text
用途：人物设定页鞋类拆解单品图。
鞋类参考：[鞋型、颜色、材质、鞋头、鞋跟高度、鞋底和装饰描述]。

最终画布必须为 1024 × 2048 px，宽高比 1:2，竖版一双鞋展示。
必须完整显示一双鞋，两只鞋采用上下错位或斜向纵向排列，不能横向挤在画面底部。
整双鞋的纵向组合高度占画布 65%–78%，水平居中。
四边至少保留 7% 安全距离。
采用清晰的三分之四产品视角，准确表现鞋头、鞋面、鞋跟和鞋底结构。
背景为完全均匀的暖米白，与其他服装拆解图一致。

只展示这一双鞋。
禁止脚、腿、人体、模特、鞋盒、其他服装、文字、标签、边框、拼图和水印。
```

### 新人物图片交付检查

生成完成后，在写 `profile.json` 前逐项检查：

- 三视图是否全部为 `1024 × 1536`、`2:3`。
- 六张表情是否全部为 `896 × 1280`、`7:10`。
- 四张服装拆解是否全部为 `1024 × 2048`、`1:2`。
- 三视图的人物高度、头顶、鞋底和地面线是否一致。
- 六张表情的人物身份、镜头距离、服装和背景是否一致。
- 四张服装拆解是否大小逻辑一致，没有人物、拼图或文字。
- `exp_calm.jpg` 是否足以同时承担面部与发型细节。
- `view_side.jpg` 是否足以同时承担职业装侧影。

## `profile.json` 完整说明

配置文件必须使用 UTF-8 编码。JSON 不允许注释、末尾多余逗号或使用单引号。

下面是一份可复制的完整示例：

```json
{
  "$schema": "../_人物模板/profile_schema.json",
  "schemaVersion": 1,
  "name": "人物姓名",
  "nameEn": "Character Name",
  "tagline": "用于页眉的一句话人物气质描述。",
  "seal": {
    "letters": "CN",
    "cn": "印",
    "en": "ROLE"
  },
  "assetDir": "assets_简介",
  "theme": {
    "accent": "#6F98AD",
    "accentSoft": "#A8C4D4",
    "palette": [
      {"name": "主色", "color": "#6F98AD"},
      {"name": "浅色", "color": "#A8C4D4"},
      {"name": "深色", "color": "#34373D"},
      {"name": "纸色", "color": "#F6F1E8"}
    ]
  },
  "facts": [
    {"label": "姓名", "value": "人物姓名"},
    {"label": "年龄", "value": "25 岁"},
    {"label": "身高", "value": "约 168 cm"},
    {"label": "职业", "value": "人物职业"},
    {"label": "气质", "value": "温柔、专业"}
  ],
  "factNote": "基本信息下方的补充说明。",
  "bio": "人物简介正文。",
  "traits": [
    "第一条视觉特征",
    "第二条视觉特征",
    "第三条视觉特征"
  ],
  "tags": ["温柔", "知性", "专业", "亲近"],
  "images": {
    "views": [
      {"label": "正面", "file": "view_front.jpg", "className": "focus-front"},
      {"label": "侧面", "file": "view_side.jpg", "className": "focus-side"},
      {"label": "背面", "file": "view_back.jpg", "className": "focus-back"}
    ],
    "expressions": [
      {"label": "平静", "file": "exp_calm.jpg"},
      {"label": "微笑", "file": "exp_smile.jpg"},
      {"label": "认真", "file": "exp_serious.jpg"},
      {"label": "惊讶", "file": "exp_surprise.jpg"},
      {"label": "思考", "file": "exp_think.jpg"},
      {"label": "羞涩", "file": "exp_shy.jpg"}
    ],
    "items": [
      {"label": "上衣", "file": "item_blouse.jpg"},
      {"label": "下装", "file": "item_skirt.jpg"},
      {"label": "袜子", "file": "item_hose.jpg"},
      {"label": "鞋", "file": "item_shoes.jpg"}
    ],
    "details": [
      {"label": "面部与发型", "file": "exp_calm.jpg"},
      {
        "label": "职业装侧影",
        "file": "view_side.jpg",
        "className": "focus-full"
      }
    ]
  },
  "display": {
    "frontScale": 1.06,
    "sideScale": 1.0,
    "backScale": 1.05,
    "expressionAspect": 0.7,
    "expressionPosition": "center 22%"
  }
}
```

### 顶层字段

| 字段 | 类型 | 说明 |
|---|---|---|
| `$schema` | 字符串 | 让编辑器识别配置格式和提供字段提示 |
| `schemaVersion` | 整数 | 当前固定为 `1` |
| `name` | 字符串 | 中文姓名 |
| `nameEn` | 字符串 | 英文名或拼音 |
| `tagline` | 字符串 | 页眉的一句话描述 |
| `seal` | 对象 | 页眉和页脚圆章文字 |
| `assetDir` | 字符串 | 相对人物目录的图片目录，通常为 `assets_简介` |
| `theme` | 对象 | 页面强调色和人物色板 |
| `facts` | 数组 | 左侧基本信息，数组顺序就是页面显示顺序 |
| `factNote` | 字符串 | 基本信息下方的补充说明 |
| `bio` | 字符串 | 角色简介正文 |
| `traits` | 字符串数组 | 视觉特征列表 |
| `tags` | 字符串数组 | 关键词标签 |
| `images` | 对象 | 所有页面图片的文件映射 |
| `display` | 对象 | 缩放、表情框比例和裁切位置 |

### `seal`

| 字段 | 示例 | 说明 |
|---|---|---|
| `letters` | `XYB` | 页眉圆章中的姓名缩写，建议 2–4 个字符 |
| `cn` | `数` | 页脚圆章中央汉字，建议 1 个字 |
| `en` | `MATH` | 页脚圆章英文小字 |

### `theme`

颜色必须使用六位十六进制格式：

```json
"accent": "#4A6FA5"
```

不要使用 `blue`、`rgb(...)` 或三位缩写 `#FFF`。

- `accent`：标题竖线、印章、边框的主色。
- `accentSoft`：弱强调色。
- `palette`：页面色板。推荐 4–6 个颜色。

### `facts`

`facts` 是有顺序的数组，可以增加、减少或重新排列：

```json
"facts": [
  {"label": "姓名", "value": "夏语冰"},
  {"label": "职业", "value": "大学数学系副教授"}
]
```

建议控制在 6–9 项。项目过多或单项文字过长，可能挤压下方补充说明。

### `images`

每张图片至少需要：

```json
{"label": "正面", "file": "view_front.jpg"}
```

- `label`：图片下方文字，同时作为无障碍 `alt` 文本。
- `file`：相对于 `assets_简介` 的文件名。
- `className`：可选显示方式。

内置 `className`：

| 类名 | 用途 |
|---|---|
| `focus-front` | 正面三视图，使用 `frontScale` |
| `focus-side` | 侧面三视图，使用 `sideScale` |
| `focus-back` | 背面三视图，使用 `backScale` |
| `focus-full` | 局部细节中的全身图，使用 `contain` 完整显示 |

三视图必须正好三张。当前标准版式最多适合六张表情、四张服装拆解和两张局部细节。

### `display`

| 字段 | 允许范围 | 说明 |
|---|---:|---|
| `frontScale` | `0.8–1.35` | 正面图缩放 |
| `sideScale` | `0.8–1.35` | 侧面图缩放 |
| `backScale` | `0.8–1.35` | 背面图缩放 |
| `expressionAspect` | `0.45–1.4` | 表情框宽高比；越小越长 |
| `expressionPosition` | CSS 位置字符串 | 表情图在裁切框内的位置 |

常用调整：

```json
"frontScale": 1.08
```

正面图放大 `8%`，适合去掉原图上下白边。

```json
"expressionPosition": "center 18%"
```

表情图显示区域上移。

```json
"expressionPosition": "center 30%"
```

表情图显示区域下移。

## 使用方法

打开 PowerShell：

```powershell
cd "C:\src\g\persona\被催眠的表妹和老婆\_人物模板"
```

## 第一阶段：从人物卡 bootstrap

当只有人物卡和模特参考图时，先运行：

```bash
python bootstrap_character.py --character 雨彤
```

准备目录（`GEMINI_DEFAULT_ROOT` 下）：

```text
雨彤/
├── 人物卡.txt          # 或 人物卡_雨彤.txt
└── sample/             # 一张或多张模特参考图 jpg/png
```

生成：

- `profile.json`
- `{name}_头像.png`（896×1280）
- `{name}_全身像.png`（1024×1536）

人工检查后进入第二阶段：

```bash
python generate_with_gemini.py --character 雨彤
```

## 生成 SillyTavern 表情图片包

角色目录已经包含 `profile.json`、`角色名_头像.png` 和 `角色名_全身像.png` 后，运行：

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
`neutral.png`，其余图片使用头像、全身像和 neutral 图共同锁定人物身份、服装和构图。

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

### 使用 Gemini 生成 13 张图片和人物页面

`generate_with_gemini.py` 会读取人物目录中的 `profile.json`、头像和全身像，
使用 Gemini 原生 API 依次生成 13 张标准图片，最后调用
`generate_profiles.py` 生成 `assets_简介/profile.html`。

#### 1. 安装依赖

```powershell
python -m pip install Pillow
```

#### 2. 配置 `.env`

复制 `.env.example` 为 `.env`，然后填写：

```env
GEMINI_API_KEY=你的 API Key
GEMINI_BASE_RUL=https://gemini.xyz365.tech/v1beta
GEMINI_DEFAULT_ROOT=C:\path\to\root
```

- `GEMINI_API_KEY`：必填，Gemini API 密钥。
- `GEMINI_BASE_RUL`：Gemini 原生 API Base URL。脚本也兼容标准拼写
  `GEMINI_BASE_URL`。
- `GEMINI_DEFAULT_ROOT`：人物根目录，也就是包含 `_人物模板` 和各个人物目录的
  `root`。
- `.env` 已被 Git 忽略，不要把真实密钥提交到仓库。
- 命令行传入的 `--root` 和 `--base-url` 会覆盖 `.env` 中的对应配置。

#### 3. 准备人物目录

```text
root/
├── _人物模板/
└── 新人物/
    ├── profile.json
    ├── 新人物_头像.png
    └── 新人物_全身像.png
```

参考图优先使用无序号的新命名：

- `人物名_头像.png`
- `人物名_全身像.png`

为兼容已有素材，脚本也能读取 `人物名_头像_1.png` 和
`人物名_全身像_1.png`。

`profile.json` 必须先按下文的完整说明填写，并保证 `images` 中三视图、
六张表情图和四张服装拆解图的顺序及文件名符合标准。

#### 4. 预览生成计划

预览不会访问 API，也不会写入图片：

```powershell
python generate_with_gemini.py --character "新人物" --dry-run
```

#### 5. 正式生成

```powershell
python generate_with_gemini.py --character "新人物"
```

生成结果位于：

```text
root/新人物/assets_简介/
├── view_front.jpg
├── view_side.jpg
├── view_back.jpg
├── exp_calm.jpg
├── exp_smile.jpg
├── exp_serious.jpg
├── exp_surprise.jpg
├── exp_think.jpg
├── exp_shy.jpg
├── item_blouse.jpg
├── item_skirt.jpg
├── item_hose.jpg
├── item_shoes.jpg
└── profile.html
```

脚本具有断点续跑功能：已存在、能够解码且尺寸正确的 JPEG 会自动跳过。
生成中断后，重新执行同一条命令即可继续。

如需强制重新生成全部 13 张图片：

```powershell
python generate_with_gemini.py --character "新人物" --overwrite
```

临时指定其他人物根目录、模型或 API 地址：

```powershell
python generate_with_gemini.py `
  --root "C:\path\to\root" `
  --character "新人物" `
  --model "gemini-3.1-flash-image" `
  --base-url "https://gemini.xyz365.tech/v1beta"
```

查看全部参数：

```powershell
python generate_with_gemini.py --help
```

### 只检查，不写文件

```powershell
python generate_profiles.py --check
```

检查内容包括：

- `profile.json` 是否是有效 JSON。
- 必填字段是否存在。
- 颜色格式和数值范围是否正确。
- 图片是否真实存在。
- 图片路径是否仍在 `assets_简介` 内。
- HTML 模板占位符是否全部成功替换。

### 生成全部人物

```powershell
python generate_profiles.py
```

生成器会扫描 `_人物模板` 同级目录下所有包含 `profile.json` 的人物文件夹。

### 只生成一个人物

```powershell
python generate_profiles.py --character "夏语冰"
```

也可以重复指定：

```powershell
python generate_profiles.py --character "夏语冰" --character "吴莹莹"
```

### 运行测试

```powershell
python -m unittest -v test_generate_profiles.py
```

## 新增人物步骤

假设新增人物名为“新人物”：

1. 在项目根目录建立 `新人物` 文件夹。
2. 在其中建立 `assets_简介` 文件夹。
3. 复制一份现有人物的 `profile.json` 到 `新人物/profile.json`。
4. 修改姓名、文案、配色、标签和图片标签。
5. 按 V2 标准准备 13 张图片并放入 `新人物/assets_简介`。
6. 确认三视图、表情图和服装拆解图的尺寸与比例符合“新人物图片标准 V2”。
7. 把第一张局部细节设置为 `exp_calm.jpg`，第二张设置为带 `focus-full` 的 `view_side.jpg`。
8. 确认 JSON 中的图片文件名与磁盘文件完全一致。
9. 先运行：

   ```powershell
   python generate_profiles.py --character "新人物" --check
   ```

10. 检查通过后生成：

   ```powershell
   python generate_profiles.py --character "新人物"
   ```

11. 打开 `新人物/assets_简介/profile.html` 查看。

## 修改现有人物

### 只修改文字

编辑对应的 `profile.json`，再重新运行生成器。

### 更换图片

有两种方式：

- 保持原文件名，直接替换 `assets_简介` 中的图片。
- 使用新文件名，并同步修改 `profile.json` 中的 `file`。

替换后运行：

```powershell
python generate_profiles.py --check
python generate_profiles.py
```

### 修改所有人物的公共版式

编辑 `_人物模板/profile_template.html`，然后重新生成全部人物。

不要把仅适合某个人物的裁切值直接写进公共模板。人物专属缩放和表情位置应写入该人物的 `display`。

## 备份与覆盖规则

首次生成时，如果 `assets_简介/profile.html` 已经存在，生成器会复制为：

```text
profile.before-template.html
```

该备份只创建一次，之后重新生成不会覆盖它。

页面写入采用临时文件原子替换。即使生成中途异常，也不会留下只写了一半的 HTML。

## 常见问题

### 修改 JSON 后页面没有变化

`profile.json` 不会被浏览器直接读取，必须重新运行生成器：

```powershell
python generate_profiles.py --character "人物名"
```

然后在浏览器中刷新。必要时使用 `Ctrl+F5` 强制刷新。

### 提示找不到图片

检查：

- 图片是否放在正确人物的 `assets_简介`。
- 文件扩展名是否一致，例如 `.jpg` 和 `.png`。
- JSON 文件名是否有空格或错别字。
- Windows 隐藏扩展名是否导致实际文件名变成 `xxx.jpg.jpg`。

### 三视图有白边

轻微增加对应缩放：

```json
"frontScale": 1.08,
"sideScale": 1.03,
"backScale": 1.06
```

每次建议只增加 `0.01–0.03`，避免裁掉头发和鞋。

### 三视图人物被裁掉

减小对应 `Scale`，最低通常不必低于 `0.95`。如果仍然裁切，应修改原图片构图，而不是继续缩小人物。

### 表情图太短或太长

调整：

```json
"expressionAspect": 0.70
```

数值越小越长，越大越接近正方形。

### 表情图只显示头顶或胸口

调整：

```json
"expressionPosition": "center 22%"
```

建议每次改变 `3%–5%` 后重新生成查看。

### 图片覆盖下面的角色简介

当前模板已经对资源区设置固定网格行和 `overflow: hidden`。如果再次出现：

1. 确认页面是使用最新模板重新生成的。
2. 不要直接编辑旧 `profile.html`。
3. 运行测试确认模板约束仍然存在。

### 第二张局部图显示成服装拼图

标准配置应为：

```json
{
  "label": "职业装侧影",
  "file": "view_side.jpg",
  "className": "focus-full"
}
```

不要在这个位置填写 `clothes.jpg`。

## 维护原则

- 人物内容放在 `profile.json`。
- 人物图片放在自己的 `assets_简介`。
- 人物专属裁切放在 `display`。
- 公共布局才修改 `profile_template.html`。
- `profile.html` 是生成结果，不作为数据源。
- 修改模板后必须重新生成所有人物。
- 提交或交付前先运行 `--check` 和单元测试。
