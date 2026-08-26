# 项目架构说明

这个项目把长视频自动加工成短视频解说。代码的原则是：**服务只提供原子能力，流水线负责业务编排，所有运行时媒体路径由 JSON 记录，不能靠目录扫描或字符串猜路径。**

## 目录职责

| 目录 / 文件 | 职责 |
| --- | --- |
| `main.py` | 主流程的启动入口，读取任务并创建项目工作目录。 |
| `search.py` | 检索式剪辑流程入口：从 `question.json` 逐条创建工作目录，从数据库选择场景、下载素材、生成解说并导出。 |
| `core/` | 通用基础能力：路径、命令、JSON、ffmpeg、音频分离、转写/说话人识别等。不能放具体业务流程。 |
| `pipeline/` | 可复用的流程动作，例如下载、裁剪、混音、字幕处理、场景拼装。这里的函数只处理传入的数据和路径。 |
| `services/` | 外部服务的封装：大模型、火山语音、PostgreSQL、S3、Google Drive。服务不读取业务 JSON，也不决定工作目录。 |
| `prompts/` | 每种 LLM 任务的独立 prompt 文件。`chatgpt.py` 只导入和填充它们。 |
| `work/<任务名>/` | 单次任务的工作目录；任务之间互不清理、互不影响。 |

## 路径与运行时数据

`core/path.py` 的 `ProjectPaths` 是路径的唯一入口。新增文件路径先加到这里，再由调用方使用；不要在业务函数中随手拼接工作目录。

每个任务使用一个 `work/<任务名>/media.json`。它记录**运行时生成或使用的媒体路径**，而不是 LLM 的业务内容。

主流程入库时，`story.json` 的 `总故事` 会写入 PostgreSQL 的 `source_story`；每条 `scene` 通过 `story_id` 关联该次素材入库的总故事。旧的 `story` 表保留给原有按人物/集数检索的用途，不与主流程混用。

```json
{
  "sources": [
    {"url": "原始链接", "video_path": "下载后的分段视频"}
  ],
  "main": {
    "source_video_path": "主视频",
    "vocals_audio_path": "人声音频",
    "hook": {
      "narration_audio_path": "...",
      "video_path": "...",
      "final_video_path": "..."
    },
    "clips": {
      "1": {
        "narration_audio_path": "...",
        "video_path": "...",
        "final_video_path": "..."
      }
    }
  },
  "search": {
    "scenes": {},
    "hook": {}
  }
}
```

规则：

- `script.json`、故事 JSON、场景 JSON 保存业务语义，例如文案、字幕编号、场景选择、时长。
- `media.json` 保存文件路径和媒体处理阶段的产物。
- 后续步骤必须从 `media.json` 读取上一步产生的路径。
- 禁止用 `glob`、`clip_*.mp4` 等方式重新猜测文件；需要的路径必须在 JSON 中记录。

## 主流水线

`pipeline/pipeline.py` 的 `AutoVideoPipeline.run()` 按下列顺序工作：

1. 下载多个来源视频，并写入 `media.json.sources`；合并为主视频。
2. 逐个导出音频并分离人声，再把人声合并。
3. 语音识别、说话人分类、角色识别与故事拆分。
4. 生成解说脚本并把字幕时间线回填到脚本。
5. 流水线读取脚本，逐段调用 TTS，回写时长到脚本，并把 MP3 路径写入 `media.json.main`。
6. 根据脚本裁剪 hook 和 clip，混音，拼接成视频。
7. 加速后先导出未混背景音乐的字幕识别音频；随后可选背景音乐混音，并依次进行遮罩、字幕、文字/GIF 等后处理。背景音乐绝不进入字幕识别音频。
8. 上传素材并写入场景、人物和字幕数据库。

`services/volcengine.py` 只负责：`generate_tts(text, audio_path)`、语音识别和与火山 API 通信。它不能解析主脚本或 search 的 JSON。

## Search 流程

`search.py` 是另一条业务流程，但沿用相同边界：

它和主流程一样接受任务列表。将任务写入项目根目录的 `question.json`，每项会在
`work/<序号>_<标题>/` 下独立执行，避免各任务的媒体和中间 JSON 相互覆盖：

```json
[
  {
    "问题": "雍正为什么要重用李卫？",
    "解说角度": "用人策略",
    "场景": [101, 102, 103],
    "标题": "雍正重用李卫的真相",
    "剧名": "雍正王朝",
    "背景音乐": "xiang_tian_zai_jie_500_nian",
    "背景音乐音量": 0.15
  }
]
```

也支持对应的英文键：`question`、`strategy`、`scene_ids`、`subtitle`、`drama_title`。

背景音乐为可选项；`背景音乐`（或 `background_music`）填写 `assets/background_music.json` 中的 `id` 或 `name`，`背景音乐音量`（或 `background_music_volume`）可覆盖素材登记的默认音量，取值为 `0` 到 `1`。音乐会在视频变速后循环混入，保留原声且不会改变视频时长；其输出路径和实际音量记录于 `media.json`。

1. 从 PostgreSQL 取指定场景和字幕。
2. LLM 选择场景、拆分 segment、生成 hook 和润色旁白。
3. 下载并标准化场景源视频。
4. search 流程自己从场景 JSON 读取旁白，逐段调用通用 TTS，并回写时长。
5. 所有 search 媒体路径写入 `media.json.search`。
6. 后续裁剪、混音、拼接仅读取 `media.json.search`。

search 的 segment 有两种画面语法：

- `type` 只描述是否展示原声，避免与旁白的复述/分析功能混淆。`narration_only` 表示不展示原声：可以复述剧情，也可以分析人物动机或权谋含义；`visual_subtitle_ids` 只负责定位对应画面，TTS 生成后程序从第一条定位字幕开始向后截取与旁白实际时长相等的连续画面，在整段画面上压低原声并叠加旁白。
- `with_dialogue` 表示展示原声：仅用于原声本身能证明旁白判断、制造关键反差、完成反转或提供不可替代表演张力的段落；`subtitle_ids` 是要保留的完整原声，程序从原声前向前预留旁白时长，形成“旁白 → 原声”。片尾互动问题可直接接在任一类型之后：with_dialogue 为“旁白 → 原声 → 问题”，narration_only 为“旁白 → 问题”。

类型判断与字幕定位由现有分段 LLM 调用一次完成，不额外增加模型调用。时长匹配、片尾容量和裁剪边界由程序根据 TTS 与源视频的真实时长确定。

search 的场景源视频会缓存到 `work/search_download_cache/`，按 S3 URL 复用下载与标准化结果；每个任务的 `media.json.search` 仍记录它实际使用的缓存路径。

主流程和 search 不共享“专用包装函数”。例如，不应存在 `cut_hook_video_temp`、`generate_tts_temp` 这种按某个 JSON 结构命名的 service 方法；应由流程层读取 JSON，再调用通用的 `cut_video`、`generate_tts`、`mix_narration_audio`。

## 服务边界

### `services/chatgpt.py` 与 `services/ali.py`

`ChatGPT` 是统一的大模型客户端，`Ali` 只是选择阿里 provider 的轻包装。模型选择由 provider 配置决定。每个大模型方法对应一个 `prompts/` 中的独立 prompt 文件。

新增 LLM 能力时：

1. 在 `prompts/<任务名>.py` 新建 prompt。
2. 在 `ChatGPT` 新增只负责“组织输入、调用模型、解析输出”的方法。
3. 在实际流程中调用，路径仍写入 `media.json`。

### `services/postgresql.py`

只封装当前数据库表的原子读写：场景、人物、字幕和场景检索。不要在这里加入 LLM、视频或 JSON 编排逻辑。

### `services/post_cut_service.py`

负责把主流程已经得到的场景/字幕业务数据写入数据库；不负责下载、转写或生成媒体。

## 通用代码的放置规则

- 纯文件/JSON/时间转换：`core/utils.py`。
- ffmpeg 的单一媒体动作：`core/ffmpeg.py` 或 `pipeline/video.py`。
- 业务字幕转换：`pipeline/subtitles.py`。
- 业务场景组合与字幕回填：`pipeline/scenes.py`。
- 下载行为：`pipeline/download.py`。
- 外部 API：`services/`。

如果一个函数需要知道 `hook`、`clips`、`segments`、`scene_id` 等业务结构，它通常应该在 `pipeline.py`、`search.py` 或对应的 `pipeline/` 业务模块，而不是 `core/` 或 `services/`。

## 后续实施约定

以后新增功能时，我会：

1. 先确认它属于主流程、search，还是通用能力。
2. 选择最小正确的模块，而不是复制现有函数。
3. 需要新增媒体文件时，先设计 `media.json` 字段。
4. 不修改第三方依赖目录 `.venv/`；依赖问题只报告或在你明确授权后通过包管理器处理。
5. 修改后运行与改动相匹配的编译、导入或流程检查，并报告结果。
