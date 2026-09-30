import json


SEGMENT_PARLIAMENT_CONTENT_PROMPT = """你是澳大利亚议会新闻视频的内容分段助手。

任务：把已经按时间顺序排列的合并字幕，划分为若干个连续的内容段。每段是一个相对完整、连贯的讨论单元；它可以是开场声明、政策说明、记者提问与回答、多轮追问或收尾，不必强行符合问答结构。

分段规则：
1. 只能在字幕条目之间切分，不能修改、拆开、遗漏或重排任何条目。
2. 所有条目必须恰好覆盖一次：第一段 start_index 为 0，最后一段 end_index 为最后一个索引；后一段必须从前一段 end_index + 1 开始。
3. 仅在议题、讨论对象或发言阶段明显改变时分段；不要因说话人切换本身而切段。
4. 每段提供简短中性的英文 topic 和中文 summary。summary 只概述该段实际说了什么，不加入评论、事实补充或受众影响推断。

只输出合法 JSON：
{
  "segments": [
    {
      "start_index": 0,
      "end_index": 12,
      "topic": "Final budget outcome",
      "summary": "财政部长公布最终预算结果，并说明赤字改善。"
    }
  ]
}

不要使用 Markdown，不要输出 JSON 以外的内容。"""


def build_segment_parliament_content_prompt(source_context: dict, utterances: list[dict]) -> str:
    metadata = {
        "title": source_context.get("title") or "",
        "channel": source_context.get("channel") or "",
        "published_at": source_context.get("published_at") or "",
    }
    compact_utterances = [
        {
            "index": index,
            "speaker": item.get("attribute", {}).get("speaker_name")
            or item.get("attribute", {}).get("speaker")
            or "UNKNOWN",
            "text": item.get("text", "").strip(),
        }
        for index, item in enumerate(utterances)
    ]
    return (
        f"{SEGMENT_PARLIAMENT_CONTENT_PROMPT}\n\n"
        f"视频元数据：\n{json.dumps(metadata, ensure_ascii=False, indent=2)}\n\n"
        f"合并字幕：\n{json.dumps(compact_utterances, ensure_ascii=False)}"
    )
