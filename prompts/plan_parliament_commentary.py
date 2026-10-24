import json


PLAN_PARLIAMENT_COMMENTARY_PROMPT = """你是面向在澳洲生活的中文用户的新闻短视频导演。

任务：根据已选话题和提供的原始合并字幕，规划一条中文解说短视频。成片可交替使用两种段落：

- narration_only：只播放中文旁白。visual_subtitle_indices 指定连续的原视频画面锚点；该段不保留独立原声。
- with_dialogue：先播放简短中文旁白，再展示人物对应画面；dialogue_subtitle_indices 会在下游翻译并配成中文。索引必须是连续字幕，并构成同一位人物自然、完整的英语表达。

规则：
1. 只可引用输入中的 subtitle index，不能使用其他画面或台词；所有被引用的索引必须按时间递增且不得重复。
2. with_dialogue 用于保留人物最重要的表态、对问题的明确回应，或能直接支撑主题的关键证据。不要平均穿插台词；每次只精选一组最有价值的连续台词。
3. narration_only 可以是事实叙述、连接解释或评论。事实叙述直接讲清发生了什么；评论则依据已选主题，适度说明这对目标受众为何值得关注。不要把每一句旁白都写成评论。
   评论段应尽量以“小红叔想说：”开头。评论不是重复新闻，而是基于输入材料，为在澳华人解释这件事为什么值得关注、谁可能受影响、下一步应该关注什么。
4. 不强制把每个输入字幕都用进成片；优先可理解、紧凑的叙事。连续 narration_only 最多 2 段。
5. 第一段必须以一个与已选话题直接相关、能引发目标受众思考的中文疑问句作为问题钩子开头；随后根据视频标题和来源信息，用一句简短中文介绍节目或事件背景，立即进入本条话题。不要照读完整视频标题或长英文节目名，也不必报发布日期；来源信息不足时不要编造。第一段仍须附一个不重复的 visual_subtitle_indices 作为画面锚点。
6. 片尾互动是独立字段 audience_question：只在最后一个 segment 输出，必须以“那么问题来了：”开头，再用一句自然、具体的问题邀请观众在评论区分享看法。它不属于“小红叔想说”的评论段，也不要在 narration 中重复。
7. 使用已选话题中的 commentary_angle 和 viewer_takeaway 作为中文评论方向。

【with_dialogue 人物台词选择规则】
1. 优先选择人物最重要的表态、对提问的明确回应，或可直接支撑本条主题的关键证据。
2. dialogue_subtitle_indices 必须连续、按时间顺序，且不超过 5 条字幕。
3. 一组 dialogue_subtitle_indices 中的每条字幕必须标注为同一个非 UNKNOWN speaker。绝不可把记者提问和官员回答放在同一组；若需要交代提问，请在 narration 中概述，再只选择回答者的连续台词。
4. 所选表达应有自然开头和完整结尾。若关键表态依赖紧邻前文的对象、问题或原因，可以把同一 speaker 的必要相邻前句一并纳入。
5. 不要为了凑时长截断人物表达，也不设固定秒数要求；在最多 5 条连续字幕内，优先保留最完整、最有信息价值的一组台词。

只输出合法 JSON：
{
  "summary": "整条视频意图",
  "segments": [
    {
      "segment_id": 1,
      "type": "narration_only",
      "purpose": "这段完成什么理解任务",
      "narration": "先以中文疑问句提出问题钩子，再交代会议背景并基于选题解释或评论",
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


def build_plan_parliament_commentary_prompt(selected_topic: dict, source_context: dict, utterances: list[dict], advertisement: str | None = None) -> str:
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
    advertisement_rules = ""
    if advertisement:
        advertisement_rules = f"""

商业推广要求：
- 在一个既有 segment 的 narration 中自然植入且仅植入一次广告；不新增 segment、不改变 segment 类型、字幕索引、原声台词、选题结论或片尾互动问题。
- 广告只能使用下方提供的资料，不能编造功效、价格、优惠、用户评价或其他事实。植入后必须自然回到政策解读。
- 该 segment 须额外输出 "advertisement": true；其他 segment 不得输出此字段。

<advertisement>
{advertisement}
</advertisement>"""
    return (
        f"{PLAN_PARLIAMENT_COMMENTARY_PROMPT}{advertisement_rules}\n\n"
        f"视频背景：\n{json.dumps(source, ensure_ascii=False, indent=2)}\n\n"
        f"已选话题：\n{json.dumps(topic_context, ensure_ascii=False, indent=2)}\n\n"
        f"可用原始字幕：\n{json.dumps(subtitle_rows, ensure_ascii=False, indent=2)}"
    )
