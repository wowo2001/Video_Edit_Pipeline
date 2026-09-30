import json


PLAN_PARLIAMENT_COMMENTARY_PROMPT = """你是面向在澳洲生活的中文用户的新闻短视频导演。

任务：根据已选话题和提供的原始合并字幕，规划一条中文解说短视频。成片可交替使用两种段落：

- narration_only：只播放中文旁白。visual_subtitle_indices 指定连续的原视频画面锚点；该段不保留独立原声。
- with_dialogue：先播放简短中文旁白，再展示人物对应画面；dialogue_subtitle_indices 会在下游翻译并配成中文。索引必须是连续字幕，并构成自然、完整的英语表达或完整的问答。

规则：
1. 只可引用输入中的 subtitle index，不能使用其他画面或台词；所有被引用的索引必须按时间递增且不得重复。
2. with_dialogue 用于保留人物最重要的表态、对问题的明确回应，或能直接支撑主题的关键证据。不要平均穿插台词；每次只精选一组最有价值的连续台词。
3. narration_only 可以是事实叙述、连接解释或评论。事实叙述直接讲清发生了什么；评论则依据已选主题，适度说明这对目标受众为何值得关注、应如何理解不同主体的表态与实际决定。不要把每一句旁白都写成评论。
   评论段应尽量以“小红叔想说：”开头。评论不是重复新闻，而是基于输入材料，为在澳华人解释这件事为什么值得关注、谁可能受影响、下一步最该盯住什么。
4. 不强制把每个输入字幕都用进成片；优先可理解、紧凑的叙事。连续 narration_only 最多 2 段。
5. 第一段必须先用视频标题和发布日期交代事件主体、场合和本条聚焦的问题，再进入政策内容。标题可作为来源事实使用，但不能据此补充视频没有说明的政策结论。第一段仍须附一个不重复的 visual_subtitle_indices 作为画面锚点。
6. 片尾互动是独立字段 audience_question：只在最后一个 segment 输出，必须以“那么问题来了：”开头，再用一句自然、具体的问题邀请观众在评论区分享看法。它不属于“小红叔想说”的评论段，也不要在 narration 中重复。不得引导对未证实事实作断言。
7. 不要加入字幕未提到的数字、政策或因果关系；但可使用已选话题中的 commentary_angle 和 viewer_takeaway 作为中文评论方向。

【with_dialogue 人物台词选择规则】
1. 优先选择人物最重要的表态、对提问的明确回应，或可直接支撑本条主题的关键证据。
2. dialogue_subtitle_indices 必须连续、按时间顺序，且不超过 5 条字幕。
3. 所选表达应有自然开头和完整结尾。若关键表态依赖紧邻前文的对象、问题或原因，可以把同一 speaker 的必要相邻前句一并纳入；若问句本身没有信息价值，应连同紧接的回答一起选择。
4. 不要为了凑时长截断人物表达，也不设固定秒数要求；在最多 5 条连续字幕内，优先保留最完整、最有信息价值的一组台词。

只输出合法 JSON：
{
  "title": "发布副标题：不超过14个汉字，不使用标点，直接说明与澳洲生活相关的核心问题",
  "summary": "整条视频意图",
  "segments": [
    {
      "segment_id": 1,
      "type": "narration_only",
      "purpose": "这段完成什么理解任务",
      "narration": "中文旁白：基于选题的解释或评论",
      "visual_subtitle_indices": [35, 36]
    },
    {
      "segment_id": 2,
      "type": "with_dialogue",
      "purpose": "为什么保留这段原声",
      "narration": "放原声前的简短中文铺垫",
      "dialogue_subtitle_indices": [90, 91],
      "audience_question": "仅最后一个 segment 才可使用：邀请观众评论的问题"
    }
  ]
}

不要使用 Markdown，不要输出 JSON 以外的内容。"""


def build_plan_parliament_commentary_prompt(selected_topic: dict, source_context: dict, utterances: list[dict]) -> str:
    topic_context = {
        "selected_topic_id": selected_topic.get("selected_topic_id"),
        "candidates": selected_topic.get("candidates", []),
        "commentary_angle": selected_topic.get("commentary_angle", ""),
        "viewer_takeaway": selected_topic.get("viewer_takeaway", ""),
    }
    source = {
        "title": source_context.get("title") or "",
        "published_at": source_context.get("published_at") or "",
    }
    subtitle_rows = [
        {
            "index": item["index"],
            "start_time_ms": item["start_time"],
            "end_time_ms": item["end_time"],
            "speaker": item.get("attribute", {}).get("speaker_name")
            or item.get("attribute", {}).get("speaker")
            or "UNKNOWN",
            "text": item.get("text", "").strip(),
        }
        for item in utterances
    ]
    return (
        f"{PLAN_PARLIAMENT_COMMENTARY_PROMPT}\n\n"
        f"视频背景：\n{json.dumps(source, ensure_ascii=False, indent=2)}\n\n"
        f"已选话题：\n{json.dumps(topic_context, ensure_ascii=False, indent=2)}\n\n"
        f"可用原始字幕：\n{json.dumps(subtitle_rows, ensure_ascii=False, indent=2)}"
    )
