GENERATE_HOOK_PROMPT = """主题：{theme}

你是一名短视频影视解说开场导演。从完整视频 segment 中选择最适合作为开头 hook 的片段。优先选择 type 为 with_dialogue、具有语义完整原声高光的 segment；只有没有合适 with_dialogue 时，才选择 narration_only。

hook 不是选择剧情最高潮，而是选择最适合第一次吸引观众的片段。优先选择与主题高度相关、能快速制造核心疑问、人物命运反转或强烈冲突的内容；避免需要大量背景才能理解的内容。hook 旁白不要复述完整剧情、解释所有背景或揭露最终答案，要结合主题制造悬念。

输入剧情：
{scenes}

ID 选择规则（必须遵守）：
1. `scene_id` 必须逐字使用输入剧情中某个 scene 的 `scene_id`，不得编造、改写、使用示例数字或使用 subtitle_id。
2. `segment_id` 必须是该 `scene_id` 的 `segments` 数组中实际存在的 `segment_id`；两个 ID 必须构成输入中真实存在的一组。
3. 输出前静默核对：在输入中找到 `scene_id`，再确认该 scene 中存在同一个 `segment_id`。若找不到，必须改选输入中存在的组合。
4. 下方 JSON 仅展示字段结构；其中的占位符不是可选 ID，绝对不可原样输出。
5. `scene_id` 和 `segment_id` 必须输出为 JSON 整数，不得加双引号。例如应输出 `"scene_id": 489`，不得输出 `"scene_id": "489"`。

只输出 JSON：
{{"scene_id": <输入中的整数scene_id>, "segment_id": <该scene实际存在的整数segment_id>, "hook_narration": "..."}}
"""
