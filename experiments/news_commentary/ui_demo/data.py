"""Source adapters and commentary grouping for the local news page."""
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from config import YOUTUBE_API_KEY
from experiments.news_commentary.ui_demo.topics import load_topics
from services.youtube_news import YouTubeNews
from services.afr_news import fetch_afr_news, article_candidates
from services.chatgpt import ChatGPT
from core.utils import safe_json_parse
from core.llm_cost import record_llm_usage

COST = Path('work/news_comment_ui/llm_cost_report.json')
PROMPT = '''你是中文观点视频的选题编辑。你长期关注经济变化如何影响普通人的工作、收入、资产和生活选择，以及收益归谁、成本由谁承担。

根据输入的标题和来源，寻找能够共同支撑一个具体评论问题的材料组合。
分组的核心是：这些报道放在一起，能帮助观众理解什么单看其中一条不容易看清的处境或变化？
同一组可以跨越房产、就业、消费、政策等类别，不要求标题出现相同关键词；也不要仅因属于同一类别就放在一起。

每组先提出一个值得进一步核实的候选判断，再选择对这个问题有实际贡献的报道。
优先组合能够互相补充的材料：具体事件与更广泛的变化、政策承诺与实际结果、不同主体受到的影响、相互矛盾的表态或数据。
组内每条报道都应增加新的信息、解释角度或对照。不要为了覆盖新闻，把关联较弱的报道塞进一组。
只根据标题和已有信息判断关联；不能确认的联系保持为问题，不编造事实或因果，不强行归结为经济下行。最终判断留给阅读完整材料后的文案规划。

同一新闻可以出现在多个组中，不要求互斥；同组内不重复，不输出完全相同的组。
无法合理关联的新闻单独成组，不强行拼凑，不限制组数或每组数量。
每组给出简短中文问题标题；reason 简要说明候选角度，以及各条材料分别贡献什么。
使用输入 ID 引用，所有新闻至少出现一次。只输出 JSON：
{"groups":[{"title":"评论问题","reason":"关联和切入点","news_ids":["ID1","ID2"]}]}
'''

def fetch_news(body, log=lambda message: None):
    result,errors={},[]
    direct_ids=set()
    for source in body['sources']:
        try:
            url=source['url'].strip();name=source['label'] or url
            days=int(source.get('days',3))
            if not 1 <= days <= 30: raise ValueError('时间范围必须为1至30天')
            log(f'开始抓取：{name}，最近 {days} 天')
            if source['module']=='youtube':
                parsed=urlparse(url); playlist=parse_qs(parsed.query).get('list',[None])[0]
                if parsed.hostname not in ('youtube.com','www.youtube.com','m.youtube.com','youtu.be'):
                    raise ValueError('请输入 YouTube 频道或播放列表 URL')
                if not playlist and parsed.path.startswith('/show/VL'):playlist=parsed.path[len('/show/VL'):]
                client=YouTubeNews(YOUTUBE_API_KEY)
                config={'name':name,'channel_ref':url,'playlist_id':playlist,'live_streams_only':parsed.path.endswith(('/streams','/live'))}
                rows=client.recent_videos(config,days);client.add_video_durations(rows)
                for row in rows:row['source_type']='video'
            elif source['module']=='guardian':
                from services.guardian import fetch_guardian_news
                rows=fetch_guardian_news(url,days,log=log)
            elif source['module']=='cis':
                from services.cis import fetch_cis_news
                rows=fetch_cis_news(url,days,log=log)
            elif source['module']=='fair_work':
                from services.fair_work import fetch_fair_work_news
                rows=fetch_fair_work_news(url,days,log=log)
            elif source['module']=='home_affairs_minister':
                from services.home_affairs_minister import fetch_home_affairs_news
                rows=fetch_home_affairs_news(url,days,log=log)
            elif source['module']=='nsw_gov':
                from services.nsw_gov import fetch_nsw_news
                rows=fetch_nsw_news(url,days,log=log)
                output=Path('work/news_comment_ui/nsw_articles');output.mkdir(parents=True,exist_ok=True)
                for row in rows:
                    (output/(row['video_id']+'.json')).write_text(
                        json.dumps(row, ensure_ascii=False, indent=2), encoding='utf-8')
            elif source['module']=='afr':
                if urlparse(url).hostname not in ('afr.com','www.afr.com'):raise ValueError('AFR 模组需要 AFR 栏目网址')
                rows=article_candidates(fetch_afr_news(url),days,topic=body['topic'],source_name=name)
            elif source['module']=='the_australian':
                raise ValueError('澳大利亚人报模组尚未接入')
            else:
                raise ValueError(f"未知来源模组：{source['module']}，请检查来源配置并重启后台服务")
            log(f'抓取成功：{name}，{len(rows)} 条')
            for row in rows:
                item=dict(id=row['video_id'],title=row['title'],url=row['url'],source=row['channel_name'],
                          publisher=row.get('publisher') or row['channel_name'],type=row['source_type'],
                          topic=body['topic'],published_at=row['published_at'],thumbnail=row.get('thumbnail_url'),duration=row.get('duration_seconds'))
                result[item['id']]=item
                if not source.get('screen', True):
                    direct_ids.add(item['id'])
        except Exception as error:
            message=f"{source.get('label') or source['url']}：{error}"
            errors.append(message);log("抓取失败："+message)
    items=sorted(result.values(),key=lambda r:r['published_at'],reverse=True)
    if body.get('screen', True):
        candidates=[item for item in items if item['id'] not in direct_ids]
        direct=[item for item in items if item['id'] in direct_ids]
        screened=screen_topic(candidates,body['topic'],log) if candidates else []
        filtered=sorted(direct+screened,key=lambda r:r['published_at'],reverse=True)
        log(f'合并完成：直接保留 {len(direct)} 条，LLM 筛选保留 {len(screened)}/{len(candidates)} 条，共 {len(filtered)} 条')
    else:
        log(f'只拉取：{body["topic"]}，跳过 Luna 主题筛选，保留 {len(items)} 条报道')
        filtered=items
    return {'items':filtered,'errors':errors,'fetched_count':len(items),'filtered_count':len(filtered)}


def screen_topic(items, topic, log=lambda message: None):
    if not items:return []
    log(f'开始 Luna 主题筛选：{topic}，{len(items)} 条报道（文章与视频）')
    COST.parent.mkdir(parents=True,exist_ok=True)
    results=ChatGPT(usage_report_path=COST).screen_news_titles([
        {'video_id':r['id'],'title':r['title'],'channel':r['source'],
         'source_type':r['type'],'published_at':r['published_at']} for r in items], [topic], topic_descriptions={topic: load_topics()[topic]["prompt"]})
    mapping={r.get('video_id'):r for r in results if isinstance(r,dict)}
    selected=[]
    for item in items:
        judgment=mapping.get(item['id'],{})
        if judgment.get('relevant') is True and topic in (judgment.get('matched_topics') or []):
            translation = judgment.get('title_zh')
            selected.append({**item,'reason':judgment.get('reason',''),
                             'title_zh':translation.strip() if isinstance(translation,str) else ''})
    missing=sum(r['id'] not in mapping for r in items)
    log(f'Luna 主题筛选完成：{topic}，保留 {len(selected)}/{len(items)} 条，费用已记录')
    if missing:log(f'Luna 未返回 {missing} 条报道的判断，已跳过，任务继续')
    return selected

def group_news(body, log=lambda message: None):
    items=body['items'];by_id={r['id']:r for r in items}
    if not items:return {'groups':[]}
    llm=ChatGPT();model=llm.config['models']['group_commentary_news']
    prompt=PROMPT+'\n当前主题：'+body['topic']+'\n主题范围：'+load_topics()[body['topic']]['prompt']+'\n新闻：'+json.dumps([{'id':r['id'],'title':r['title'],'source':r['source']} for r in items],ensure_ascii=False)
    log(f'开始 {model} 分组：{len(items)} 条报道')
    response=llm.client.chat.completions.create(model=model,messages=[{'role':'user','content':prompt}])
    COST.parent.mkdir(parents=True,exist_ok=True)
    record_llm_usage(COST,llm.provider,'group_commentary_news',model,response.usage)
    raw=safe_json_parse(response.choices[0].message.content)
    groups=[];seen=set();covered=set()
    for g in raw.get('groups',[]):
        ids=list(dict.fromkeys(i for i in g.get('news_ids',[]) if i in by_id))
        key=tuple(sorted(ids))
        if not ids or key in seen:continue
        seen.add(key);covered.update(ids)
        groups.append([str(g.get('title') or '相关报道'),[by_id[i] for i in ids],str(g.get('reason') or '')])
    for i in by_id.keys()-covered:groups.append([by_id[i]['title'],[by_id[i]],'独立报道'])
    log(f'{model} 分组完成：{len(groups)} 组，费用已记录')
    return {'groups':groups,'model':model,'cost_file':str(COST)}
