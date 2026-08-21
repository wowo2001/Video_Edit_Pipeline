SPLIT_SCENE_SEGMENT_PROMPT = """【解说主题】{theme}
【当前场景】{summary}
【原始对白】{subtitles}
【解说要求】{task}

你是一名短视频影视解说分镜导演。按照解说要求，把当前场景拆成若干 segment。每个 segment 由解说旁白和原剧台词组成，只完成当前场景的任务，不复述完整剧情。segment 数量应服从任务；每段只承担一个明确作用；与主题和任务无关的内容舍弃。

subtitle_ids 必须引用已有字幕编号，严格连续递增，保持原顺序，不修改编号、不返回对白文本。剧情跳跃时，narration 可以用 1-2 句补足必要背景。

只输出 JSON：
{{"segments": [{{"segment_id": 1, "purpose": "...", "narration": "...", "subtitle_ids": [1, 2]}}]}}
"""
