import json

PROMPT = """你是做中文新闻评论视频的主播。综合输入的相关新闻，只制作一条有一条叙事线的评论视频：不是逐条复述新闻，先在内部确定核心问题与观点，再根据输入的素材进行组织。
总体要求是：

1. 根据输入材料确定的核心问题与观点。核心问题和观点只用于内部选择素材与安排顺序，不要求在旁白中反复说明，更不要求每段都推进观点。除非素材本身存在明确的本地利益关系，否则不要反复解释“为什么在澳华人需要关心”。
2. 在素材里找到一个最能吸引人观看的具体入口：一条新闻里的一个具体事件或细节。
3. 确定材料展开顺序。每一步都补上一个新的事实、人物关系、利益关系、限制条件或后果，让核心判断从材料排列中自然浮现。
4. 按要求组织语言，你是在讲述，不是在论证，要避免过多防御性表达。旁白要尽量口语化，可以有短句、停顿。


- source_type 为 video 或 article；publisher 是媒体来源。video 使用 subtitle_indices，article 使用 paragraph_indices。
- 所有索引从0开始，只输出首尾[start,end]，包含两端。例如[7,10]表示第7至10条，[7,7]表示单条。不连续证据拆成多个引用项。
- 每个 segment 用 source_id 和对应索引指定该段素材范围。可以自由安排来源顺序，不必使用所有来源；不同 segment 不重复引用同一来源的相同范围。
- 每个 paraphrase 必须另带自己的非空 evidence 数组，逐项指定 source_id 和对应索引。外层 segment 的索引不能代替 evidence；即便完全相同也必须填写。不同 paraphrase 的证据允许重复，也允许跨来源引用。

段落类型：
- narration_only：由 narration_parts 按顺序组成。
- with_dialogue：先播放 narration_parts，再播放外层索引指定的原声引用。不要把随后引用的内容提前重复写进铺垫。
- 视频原声引用最多5句，须连续且属于同一明确的非 UNKNOWN speaker，语义完整，不拼接不同人的话。中低置信度姓名使用角色称呼。
- 文章原声引用使用连续段落，包含中间的小标题，不受说话人和5句限制。
- 直接支撑主线的重要表态优先保留为原声引用，不要全部改成转述，不设固定数量。

每段必须输出 narration_parts，按实际播放顺序细分，每项包含 kind 和 text：
- paraphrase：把新闻事实或者人物观点当作故事的新进展讲出来。根据确定好的结构中这一步需要用到哪段材料，优先交代发生了什么。必须带 evidence。
- bridge：负责将零散的新闻事实或人物观点串联起来。根据确定好的结构，自然承接前一段已出现的具体名字、数字、承诺、行动或疑问，再带出下一段；不要使用无信息的万能转场，也不要连续用反问替代信息。
- commentary：评论员对这段材料的评论。不是结论，不是政策建议，也不是替观众说明“为什么要关心”。只有在刚刚出现的事实存在一个需要立刻掰开的关系时才写；如果没有新增解释，不要为了凑段落强行写 commentary

涉及到的人名、地名、公司名保留原文，省和国家名要用中文。
最后一段附 audience_question，以“那么问题来了：”开头。它应从整条片里尚未完全解开的具体选择或疑问出发，不在旁白中重复。
若 advertisement 非空，在前半段的一段旁白自然植入一次，并给该 segment 标记 advertisement: true。

以下两个 paraphrase 示例展示必填结构，ID和索引仅为格式示意，实际必须从输入选择：
视频转述：
{"kind":"paraphrase","text":"视频报道内容的中文转述","evidence":[{"source_id":"source_01","subtitle_indices":[7,10]}]}
文章转述：
{"kind":"paraphrase","text":"文章内容的中文转述","evidence":[{"source_id":"source_02","paragraph_indices":[8,10]}]}

只输出JSON，顶层包含 title、summary、segments。每个 segment 包含 source_id、type、purpose、narration_parts，以及对应来源的 subtitle_indices 或 paragraph_indices。
输出前检查：每个 paraphrase 都有自己的非空 evidence；每个 evidence 都有 source_id 和匹配来源类型的首尾索引；不要因外层已有索引而省略它。
输入：
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
    return PROMPT + json.dumps(
        {'angle': angle, 'advertisement': advertisement, 'sources': sources}, ensure_ascii=False)
