# 多新闻评论实验

输入多条相关新闻，综合成一条主线、一条成片；不会调用 conference 的多选题拆分。
正式流水线和共用模块不作修改。

## 运行

在项目根目录运行，先复制 `tasks.example.json` 并填写真实新闻链接。

```sh
PATH="$PWD/venv/bin:$PATH" venv/bin/python -m experiments.news_commentary.pipeline \
  --tasks experiments/news_commentary/tasks.json \
  --workspace work/news_commentary/trial_01
```

默认制作但不上传。需要制作后上传时加 `--upload`。

阶段可选 `--step download|transcribe|merge|speakers|section|prepare|plan|audio|paraphrase|produce|final|upload`，默认 `all`：

- download：仅下载素材。视频沿用 conference 下载；AFR 使用环境变量账号登录，保存 `article.txt` 和 `article.json`。`downloaded_sources.json` 记录类型和本地路径。已完成的下载会复用。
- transcribe：仅对已下载的视频调用火山英文识别（en-US）；AFR 原文不变，跳过识别。成功后重跑复用结果。
- merge：复用 conference 按语法整合视频英文短句，保留原始字幕和时间范围；AFR 原文不变。仅执行该步，不继续分段。
- speakers：复用 conference 说话人聚类、性别判断和人物识别；AFR 跳过，各子步骤成功后可复用。
- section：视频复用 conference 分段；AFR 按原文段落分 section，输出英文 topic、中文 summary、原文 text 和从0开始的段落索引到 content_segments.json。原始模型结果保存在 article_sections_raw.json，花费沿用 llm_cost_report.json。
- prepare：每条独立下载 → 火山英文识别（与 conference 相同，en-US）→ 语法短句整合 → 说话人/性别识别 → 段落总结。
- plan：从各素材的分段结果重建 source_catalog.json，GPT 同时读取文章原文、视频字幕及摘要，输出主线和跨来源证据。视频使用 subtitle_indices，文章使用 paragraph_indices；文章引用原文由程序取回，标记为 publisher_logo 或 article_typewriter。此阶段不翻译、不配音、不渲染。
- audio：仅翻译视频人物引用并生成全部中文 TTS（含文章解说及结尾互动），不渲染；完整成功的段落按输入复用。文章原文引用的配音入口待接入。
- produce：按分段音频串联转述素材、人物发言及串联画面，使用累计帧边界避免漂移；不重做翻译和配音。先运行 audio、paraphrase。
- final：读取 layout_config.json 的 none/small/large 规则，合成头像动画，再按分段时间生成字幕、烧录、加入1秒封面和最终音量设置。
- upload：上传最终成片到 title 指定的 Drive 文件夹。

`prepare` 已成功的单源步骤用标记跳过；其他阶段显式执行会重做，可能再次调用收费服务。
修改输入请换工作区，避免混用已有结果。改规划后从 produce 重做；只改布局从 final 重做。

## 产物与证据

- `sources/source_XX/`：每条新闻原视频、识别原文、整合字幕、人物信息和 `content_segments.json`。
- `source_catalog.json`：来源 URL、标题日期、段落摘要和字幕时间戳，索引在每条来源内从 0 开始。
- `commentary_plan_raw.json`：模型原始结果；验证失败时可据此检查。
- `commentary_plan.json`：主线、段落安排、source_id、源内字幕索引及后续配音信息。
- `render_segments/`：每段独立工作区，防止跨素材边界取错画面。
- `commentary_preview_horizontal.mp4`：合成横版；`commentary_news.mp4`：带封面的最终成片。

人物原声沿用 conference 含义：保留发言画面，翻译为中文配音。各源人物分开识别，不自动假定跨视频出现的人是同一位。
规划可改变来源和段落顺序，但每段证据必须连续，人物发言必须来自同一位明确说话人。不会为凑材料强制使用每条新闻。

AFR 当前已接入 download 阶段，并在 transcribe 阶段跳过识别；文章分段可单独运行 section；混合素材可单步运行 plan；完整 prepare 尚待接入；现可逐步运行 produce 和 final 渲染混合素材。输入 source_type 可设为 article/video，省略时根据 URL 判断。

素材类型使用 source_type: article 或 video；文章来源使用 publisher（例如 AFR）。目前文章下载支持 AFR。

旁白 TTS 按 narration_parts 分别生成，按文本及声音缓存；每项记录 audio_path、start_ms、end_ms、duration_ms（相对该段旁白）。整段兼容音频为 narration_parts.wav，PCM 拼接避免 MP3 边界偏移。人物与互动配音复用已有结果。

- paraphrase：按各 narration_part 的 evidence 生成转述视频，保存到 paraphrase_videos 并写回 paraphrase_video。视频只取引用范围并变速适配配音；文章按原文生成打字画面。复用已有分段音频，不调用 LLM/TTS。支持输入指纹缓存。多份 evidence 按原文字数分配画面时长，非逐词对齐。
