"""Source adapters and commentary grouping for the local news page."""
import json
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from config import YOUTUBE_API_KEY
from services.youtube_news import YouTubeNews
from services.afr_news import fetch_afr_news, article_candidates
from services.chatgpt import ChatGPT
from core.utils import safe_json_parse
from core.llm_cost import record_llm_usage

COST = Path('work/news_comment_ui/llm_cost_report.json')
PROMPT = '''你是一名新闻评论选题编辑。根据输入标题和来源，将适合放在同一条评论视频中讨论的报道分组。
每组围绕具体问题、同一事件、因果关系或不同观点，不要仅因属于同一大类就放在一起。
同一新闻可以出现在多个组中，不要求互斥；同组内不重复，不输出完全相同的组。
无法合理关联的新闻单独成组，不强行拼凑，不限制组数或每组数量。
只依据输入信息，不编造事实、因果或立场；不确定时分开。
每组给出简短中文问题标题及一句 reason 说明关联和评论切入点。
使用输入 ID 引用，所有新闻至少出现一次。只输出 JSON：
{"groups":[{"title":"评论问题","reason":"关联和切入点","news_ids":["ID1","ID2"]}]}
'''

def fetch_news(body, log=lambda message: None):
    result,errors={},[]
    for source in body['sources']:
        if not source['enabled']: continue
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
                    (output/(row['video_id']+'.json')).write_text(json.dumps(row,ensure_ascii=False,indent=2))
            elif source['module']=='afr':
                if urlparse(url).hostname not in ('afr.com','www.afr.com'):raise ValueError('AFR 模组需要 AFR 栏目网址')
                rows=article_candidates(fetch_afr_news(url),days,topic=body['topic'],source_name=name)
            else: raise ValueError('澳大利亚人报模组尚未接入，请先使用 YouTube 或 AFR')
            log(f'抓取成功：{name}，{len(rows)} 条')
            for row in rows:
                item=dict(id=row['video_id'],title=row['title'],url=row['url'],source=row['channel_name'],
                          publisher=row.get('publisher') or row['channel_name'],type=row['source_type'],
                          topic=body['topic'],published_at=row['published_at'],thumbnail=row.get('thumbnail_url'),duration=row.get('duration_seconds'))
                result[item['id']]=item
        except Exception as error:
            message=f"{source.get('label') or source['url']}：{error}"
            errors.append(message);log("抓取失败："+message)
    items=sorted(result.values(),key=lambda r:r['published_at'],reverse=True)
    filtered=screen_topic(items,body['topic'],log)
    return {'items':filtered,'errors':errors,'fetched_count':len(items),'filtered_count':len(filtered)}


def screen_topic(items, topic, log=lambda message: None):
    if not items:return []
    log(f'开始 Luna 主题筛选：{topic}，{len(items)} 条报道（文章与视频）')
    COST.parent.mkdir(parents=True,exist_ok=True)
    results=ChatGPT(usage_report_path=COST).screen_news_titles([
        {'video_id':r['id'],'title':r['title'],'channel':r['source'],
         'source_type':r['type'],'published_at':r['published_at']} for r in items], [topic])
    mapping={r.get('video_id'):r for r in results if isinstance(r,dict)}
    selected=[]
    for item in items:
        judgment=mapping.get(item['id'],{})
        if judgment.get('relevant') is True and topic in (judgment.get('matched_topics') or []):
            selected.append({**item,'reason':judgment.get('reason','')})
    missing=sum(r['id'] not in mapping for r in items)
    log(f'Luna 主题筛选完成：{topic}，保留 {len(selected)}/{len(items)} 条，费用已记录')
    if missing:log(f'Luna 未返回 {missing} 条报道的判断，已跳过，任务继续')
    return selected

def group_news(body, log=lambda message: None):
    items=body['items'];by_id={r['id']:r for r in items}
    if not items:return {'groups':[]}
    llm=ChatGPT();model=llm.config['models']['screen_news_titles']
    prompt=PROMPT+'\n当前主题：'+body['topic']+'\n新闻：'+json.dumps([{'id':r['id'],'title':r['title'],'source':r['source']} for r in items],ensure_ascii=False)
    log(f'开始 Luna 分组：{len(items)} 条报道')
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
    log(f'Luna 分组完成：{len(groups)} 组，费用已记录')
    return {'groups':groups,'model':model,'cost_file':str(COST)}
