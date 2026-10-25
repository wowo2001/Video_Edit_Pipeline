import json

PROMPT = """你是面向在澳华人的新闻评论视频导演。综合全部相关新闻，只制作一条有清晰主线的评论视频，不要逐条复述新闻，也不要拆成多个选题。
先确定核心问题和观点，再安排事实背景、证据、解释、评论和结尾互动。材料有分歧时保留差异，不要把相关性说成因果关系。只使用输入事实，注明不同时间或口径，不编造信息。
每个段落引用一个 source_id 和该视频的一组连续 subtitle_indices，作为画面或人物发言证据；可以跨视频自由安排段落顺序，不必使用所有视频。不要重复引用相同字幕。所有 subtitle_indices 和 paragraph_indices（包括段落与 evidence）只输出首尾索引[start,end]，两端均包含，例如第7至10句写[7,10]，单句写[7,7]；不要展开中间编号。不连续的证据拆成多个 evidence 项。
type 为 narration_only（中文解说，索引是画面锚点）或 with_dialogue（简短中文铺垫后接人物发言，后续翻译为中文配音）。with_dialogue 最多引用5句，必须属于同一非 UNKNOWN speaker，语义完整，不拼接不同人的话。
旁白必须输出 narration_parts 数组，每项包含 kind 和 text，按实际播放顺序细分，不能把不同功能混写在一项：
- paraphrase：新闻事实或人物观点的转述，必须附 evidence 数组，每项为 source_id 和 subtitle_indices，准确指向支撑该转述的字幕。证据引用允许重复，和段落画面锚点不是一回事。
- bridge：小红叔的开场钩子、人物介绍、提问或过渡串联，不夹带未经标注的事实转述。
- commentary：小红叔的解释、判断、观点或对观众的提醒，明确区别于人物原话。
with_dialogue 的人物发言由该段 subtitle_indices 指定，单独出现，不写入 narration_parts。不要在铺垫中提前复述随后的人物发言。
不要把所有证据都改写成旁白：不同来源中直接支撑主线的重要表态，优先保留为人物发言；不设固定数量，不为凑数引用。
不要输出 narration 字段，程序会按顺序拼接 narration_parts.text 供配音。
中文旁白应自然紧凑，第一段用问题钩子开场，再用一句简短中文交代背景，不照读新闻长标题。评论解释对观众的影响，可用“小红叔想说：”引入。人名、地名、公司名保留原文。
最后一段附 audience_question，以“那么问题来了：”开头，邀请观众讨论，不在旁白中重复。
若输入 advertisement 非空，在前半段的一段旁白自然植入一次，并给该段标记 advertisement: true。
只输出JSON：
{"title":"中文成片标题","summary":"这条评论的核心主线","segments":[{"source_id":"source_01","type":"narration_only","purpose":"本段在主线中的作用","narration_parts":[{"kind":"bridge","text":"开场问题"},{"kind":"paraphrase","text":"新闻事实转述","evidence":[{"source_id":"source_01","subtitle_indices":[0,1]}]}],"subtitle_indices":[0,1]}]}
输入：
"""


MIXED_RULES = """
混合素材规则：source_type 是 video 或 article；publisher 是媒体来源。
上述字幕规则适用于视频。文章改用 paragraph_indices 引用 article_paragraphs 的 index，从0开始。
每段和 evidence 均按 source_id 的素材类型使用 subtitle_indices 或 paragraph_indices，不混用。
文章没有时间戳或说话人，不受视频同一说话人及最多5句的规则限制。
文章 narration_only：中文解说，画中画显示来源 Logo。
文章 with_dialogue：简短中文铺垫，之后引用原文翻译成中文配音，画面逐字显示英文原文，不是英文朗读。
引用精炼完整，只输出连续段落的首尾索引[start,end]（包含中间的小标题），程序取回原文，不要改写或输出引用正文。
保留 paraphrase、bridge、commentary 区分，不把作者观点当作事实。
注意不同来源的日期和数据口径，历史视频不能当作同期证据。
人物姓名若只有中低置信度推测，使用角色称呼。
"""


def build_prompt(catalog, angle='', advertisement=''):
    sources = []
    for source in catalog:
        kind = source.get('source_type', 'video')
        entry = {'source_id': source['source_id'], 'source_type': kind,
                 'publisher': source.get('publisher', ''), 'url': source['url'],
                 'context': source['context'],
                 'sections': [{k: p[k] for k in ('start_index', 'end_index', 'topic', 'summary') if k in p}
                              for p in source['paragraphs']]}
        if kind == 'article':
            entry['article_paragraphs'] = source['article_paragraphs']
        else:
            entry['utterances'] = [{'index': i, 'text': row['text'],
                'start_time': row['start_time'], 'end_time': row['end_time'],
                **{k: row.get('attribute', {}).get(k) for k in
                   ('speaker', 'speaker_name', 'speaker_confidence')}}
                for i, row in enumerate(source['utterances'])]
        sources.append(entry)
    return PROMPT + MIXED_RULES + json.dumps(
        {'angle': angle, 'advertisement': advertisement, 'sources': sources}, ensure_ascii=False)
