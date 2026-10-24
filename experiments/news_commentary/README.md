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

阶段可选 `--step prepare|plan|produce|final|upload`，默认 `all`：

- prepare：每条独立下载 → 火山英文识别（与 conference 相同，en-US）→ 语法短句整合 → 说话人/性别识别 → 段落总结。
- plan：GPT 阅读全部段落摘要和字幕，输出一条主线及跨来源证据引用。
- produce：每段绑定自己的源视频，复用 conference 翻译、TTS、片段剪辑，再按规划顺序合成。
- final：复用完整比例新闻窗、头像动画、程序字幕换行、封面和最终音量设置。
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
