import json


PARLIAMENT_SPEAKER_PROMPT = """你是澳大利亚议会及政府新闻发布会的说话人识别助手。

任务：根据视频元数据和已经按声纹聚类、并按语法合并后的英文字幕，识别每个 SPEAKER_XX 的人物姓名和现场角色。

判断原则：
- 视频标题、频道、发布日期只作为背景和候选线索，不能单独当作身份结论；必须与台词中的自称、互相称呼、发言内容和问答关系交叉验证。
- 同一 SPEAKER_XX 是声纹簇。综合它的全部台词判断，不要只根据一条短句。
- 无法确认姓名的提问者可标为 Journalist；无法判断角色则标为 Unknown。不要编造姓名。
- UNKNOWN 是未可靠聚类的字幕标签，不要为它输出条目。
- 所有出现过的 SPEAKER_XX 必须输出一项。

严格输出合法 JSON 对象，key 为原 SPEAKER_XX，value 必须包含：
{
  "name": "英文姓名，不能确认时为 null",
  "role": "例如 Treasurer / Finance Minister / Journalist / Unknown",
  "confidence": "high / medium / low",
  "evidence": "不超过一句英文证据摘要"
}

不要使用 Markdown，也不要输出 JSON 以外的内容。"""


def build_recognise_parliament_speaker_prompt(source_context: dict, speaker_lines: list[str]) -> str:
    metadata = {
        "title": source_context.get("title") or "",
        "channel": source_context.get("channel") or "",
        "published_at": source_context.get("published_at") or "",
        "youtube_id": source_context.get("youtube_id") or "",
    }
    return (
        f"{PARLIAMENT_SPEAKER_PROMPT}\n\n"
        f"视频元数据：\n{json.dumps(metadata, ensure_ascii=False, indent=2)}\n\n"
        "聚类后的完整合并字幕（按时间顺序）：\n"
        + "\n".join(speaker_lines)
    )
