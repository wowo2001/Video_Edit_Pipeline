# YouTube 上传模块

独立模块 `services.youtube_upload`，已接入新闻流水线上传阶段。现有 Google Drive 授权不变。API Key 不能替代频道 OAuth 授权。

## 首次准备

1. 在 Google Cloud 项目启用 YouTube Data API v3，配置 OAuth 同意屏幕（测试模式下添加登录账号为测试用户）。
2. 创建 **Desktop app / 桌面应用** OAuth 客户端，下载 JSON 到 `auth/youtube_client.json`。
3. 运行下面的授权命令，在浏览器选择目标 YouTube 频道。模块使用 `youtube.upload` 和 `youtube.readonly` 权限，token 单独保存到 `auth/youtube_token.json`，不覆盖 Drive token。

```sh
venv/bin/python -m services.youtube_upload --channels
```

返回频道 ID 和名称。将频道 ID 填入参数文件；上传前模块核对授权频道，防止发错频道。多频道使用不同 token 文件，通过 `--token-path` 指定。

## 上传

复制 `docs/youtube_upload.example.json` 到 `work/youtube_upload.json`，填好真实路径、标题和频道 ID：

```sh
venv/bin/python -m services.youtube_upload --config work/youtube_upload.json
```

JSON 中路径相对执行命令时的工作目录，建议从项目根目录执行。不要把凭据内容粘贴到对话或提交到 Git；授权文件默认保存在已忽略的 `auth/` 下。

| 参数 | 必填 | 默认 / 含义 |
|---|---|---|
| video_path | 是 | 本地成片文件 |
| title | 是 | 标题，最多 100 字符 |
| channel_id | 是 | 授权命令返回的频道 ID，用于核对目标频道 |
| client_secrets | 首次需准备文件 | auth/youtube_client.json |
| token_path | 否 | auth/youtube_token.json，首次自动生成 |
| description | 否 | 简介，默认空，最多 5000 UTF-8 字节 |
| thumbnail_path | 否 | PNG/JPEG 封面，处理成功后上传；账号须有自定义封面权限 |
| privacy | 否 | private（私密）；也可 unlisted（不公开）、public（公开） |
| tags | 否 | 字符串数组 |
| category_id | 否 | 25（新闻与政治）；以频道所在地区支持的类别为准 |
| language | 否 | zh |
| made_for_kids | 否 | false；按实际内容声明 |
| contains_synthetic_media | 否 | 不设置；示例为 true，按实际合成/修改内容声明 |
| publish_at | 否 | 带时区的未来 ISO 时间，例如 2026-12-01T18:00:00+11:00；必须 privacy=private |
| notify_subscribers | 否 | false |
| processing_timeout | 否 | 600 秒，上传封面前等待视频处理的期限 |
| receipt_path | 否 | 视频同目录同名 .youtube.json，保存请求摘要及视频 ID |

横屏和竖屏分别调用一次，每个视频使用自己的封面和上传记录。Shorts 没有独立上传开关，由 YouTube 按视频尺寸、时长等规则归类。

## 重试与返回

返回 `video_id`、`url`、上传状态，以及成功设置封面后的记录。视频上传后立即保存 ID，再处理封面。同样参数重跑会复用 ID，不重复创建视频。封面失败或等待超时，可用原命令继续。没有传封面时，成功返回只代表上传完成，不代表 YouTube 已处理完毕。

分块上传对临时错误最多重试 5 次。进程中断后不恢复上传会话；若记录处于 uploading 且没有视频 ID，自动停止，需先到 YouTube Studio 核实上传结果，避免重复上传。确认未上传才删除该记录重试；已有视频应保留并恢复其正确 ID。不要并发上传同一视频或共用同一 receipt_path。

修改视频、标题或发布参数后，旧记录会阻止再次上传。模块不提供修改既有视频元数据的功能；确实需要新副本时明确指定新的 receipt_path。

官方接口：
- https://developers.google.com/youtube/data/reference/rest/v3/videos/insert
- https://developers.google.com/youtube/data/reference/rest/v3/thumbnails/set
- https://developers.google.com/identity/protocols/oauth2/native-app

## 新闻评论的发布映射

新闻评论使用 `experiments.news_commentary.youtube.build_upload_config(root, orientation)` 生成参数，`orientation` 为 `portrait` 或 `landscape`。该函数只返回参数；流水线上传阶段调用 `upload_news_videos` 完成横竖屏公开发布及封面设置。

- `privacy=public`、`publish_at=None`：上传并经 YouTube 处理后公开，不安排定时发布。
- `tags` 由脚本规划 AI 在 `commentary_plan.json` 顶层生成；旧任务缺少标签时明确报错，不用固定标签代替。
- 视频、封面、标题和来源链接取自该任务的产物；频道固定为已授权的「土澳小红叔」。
- 通用上传模块仍保留私密默认值，新闻映射明确覆盖为公开。其他发布声明按实际内容传入。

新闻任务勾选上传后，`all --upload` 会依次上传 Google Drive、公开发布 YouTube。`--step upload` 同时执行两者；YouTube 失败后使用 `--step upload-youtube` 单独重试，避免重复上传 Drive。两种画幅各自保存 `youtube_portrait.json` / `youtube_landscape.json`；链接和状态写入 `media.json → main.youtube`。新闻使用 AI 配音，发布时设置 `contains_synthetic_media=true`，默认不通知订阅者。

YouTube 上传前使用 ffprobe 检查最终竖屏成片实际时长（含封面）：超过 180 秒跳过竖屏视频及封面，并记录 skipped；180 秒以内（含）正常上传。横屏照常发布，Google Drive 仍保存两个版本。
