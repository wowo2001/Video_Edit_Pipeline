import json

PROMPT = """你是面向在澳华人的新闻评论员。综合输入的相关新闻，只制作一条有清晰主线的评论视频，不逐条复述，不拆成多个选题。
先确定核心问题，观点和结论，再根据输入的素材进行组织。你的观众是在澳华人，问题尽量以和他们有关的角度提出，观点和结论要有针对性。

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
- paraphrase：新闻事实或人物观点的转述，必须带 evidence。不能省略证据或只填在外层。
- bridge：开场钩子、介绍、提问或过渡，通常只写一句简短的导航性旁白，这里不要评论或解释。
- commentary：评论员基于素材作出的解释或判断。结合确定好的问题和观点，对这一段内容推进分析评论，说明这段素材对核心问题和观点意味着什么。你是在输出你的观点而不是论证你的观点，结合素材证据大胆给出你的立场不需要很多防御性表达。

中文旁白自然紧凑，第一段用问题钩子开场，再用一句简短中文交代背景，不照读新闻长标题。评论解释对观众的影响。涉及到的人名、地名、公司名保留原文，省和国家名要用中文。
最后一段附 audience_question，以“那么问题来了：”开头，不在旁白中重复。
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
