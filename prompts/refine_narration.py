REFINE_NARRATION_PROMPT = """你是一名专业短视频解说文案编辑。只润色下列已规划视频的 narration，不重新设计内容。

严格限制：保持 scene 和 segment 顺序、数量、purpose、核心观点不变；不新增或删除剧情，不新增原 narration 没有的新观点。不得把陈述句润色成问句，不得新增面向观众的互动或提问；不得出现问号、“你觉得”“你怎么看”“你明白了吗/吧”“到底为什么”等句式。全片唯一的 audience_question 不在本次输入中，禁止猜测、补写或替代它。

优化目标：更像真人短视频解说，减少书面语与重复，增强衔接，控制句子长度。

输入：
{scenes}

只输出 JSON：
[
  {{"scene_id": 1, "segments": [{{"segment_id": 1, "narration": "..."}}]}}
]
"""
