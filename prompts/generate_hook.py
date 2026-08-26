GENERATE_HOOK_PROMPT = """主题：{theme}

你是一名短视频影视解说开场导演。从完整视频 segment 中选择最适合作为开头 hook 的片段。优先选择 type 为 with_dialogue、具有语义完整原声高光的 segment；只有没有合适 with_dialogue 时，才选择 narration_only。

hook 不是选择剧情最高潮，而是选择最适合第一次吸引观众的片段。优先选择与主题高度相关、能快速制造核心疑问、人物命运反转或强烈冲突的内容；避免需要大量背景才能理解的内容。hook 旁白不要复述完整剧情、解释所有背景或揭露最终答案，要结合主题制造悬念。

输入剧情：
{scenes}

只输出 JSON：
{{"scene_id": 8, "segment_id": 2, "hook_narration": "..."}}
"""
