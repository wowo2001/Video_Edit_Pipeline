"""Local news-selection console.

Run with: streamlit run news_ui.py

This first page is intentionally UI-only. YouTube retrieval, LLM screening, and
translation workflow execution will be connected in later steps.
"""

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4
from zoneinfo import ZoneInfo

import streamlit as st

from config import OPENAI_API_KEY, YOUTUBE_API_KEY
from services.chatgpt import ChatGPT
from services.youtube_news import YouTubeNews

DEFAULT_SOURCES = [
    {"name": "ABC News Australia", "channel_ref": "", "enabled": True},
]
DEFAULT_CONFERENCE_SOURCES = [
    {
        "name": "ABC News Australia · Live",
        "channel_ref": "https://www.youtube.com/@abcnewsaustralia/streams",
        "enabled": True,
        "live_streams_only": True,
    },
    {
        "name": "9 News Australia · Live",
        "channel_ref": "https://www.youtube.com/@9NewsAUS/streams",
        "enabled": True,
        "live_streams_only": True,
    },
    {
        "name": "指定 YouTube 播放列表",
        "playlist_id": "PLHpsRD1kEE6zaL9QK2446ntmZPOaI4aTa",
        "enabled": True,
    },
    {
        "name": "指定 YouTube 播放列表（dLJdXRVMdJs）",
        "playlist_id": "PLvo1VRu7zepSeLhUdjq1dPfILDA_Ajgpu",
        "enabled": True,
    },
    {
        "name": "指定 YouTube 播放列表（A8S42iSH-Es）",
        "playlist_id": "PLn2RjxYNpcayZxSQmTq_yw1iWAjlFrv8U",
        "enabled": True,
    },
    {
        "name": "指定 YouTube 播放列表（OeTRhAqo4gQ）",
        "playlist_id": "PL7LZL9cKgj6Rp-_ZSEDxtH0s8O1IyunMk",
        "enabled": True,
    },
    {
        "name": "AFR Interviews（澳洲金融评论人物访谈）",
        "playlist_id": "PLSrjl6O4Nd94",
        "enabled": True,
    },
    {
        "name": "The Issue（7NEWS 深度访谈）",
        "playlist_id": "PLK4IVkm259BZsqGQWywq-wkspXEFBNh3R",
        "enabled": True,
    },
    {
        "name": "Rask · Australian Property Podcast",
        "playlist_id": "PLECacouYcyPsf8T7pOrM7c0x1ChV_BPy4",
        "enabled": True,
    },
    {
        "name": "Property Investment Podcast Network",
        "playlist_id": "PLZWLiY_OqG3Oa8oks3CW9qMSYwe-830MW",
        "enabled": True,
    },
    {
        "name": "National Press Club of Australia",
        "channel_ref": "https://www.youtube.com/@NationalPressClubofAustralia",
        "enabled": True,
        "live_streams_only": False,
    },
]
SOURCES_PATH = Path("news_sources.json")
CONFERENCE_SOURCES_PATH = Path("conference_sources.json")
QUEUE_ROOT = Path("work/news_ui_queue")

# 后台可编辑的主题清单：增删此列表即可更新前端复选框。
TOPIC_OPTIONS = [
    "房产",
    "签证",
    "生活",
    "财经",
    "政治",
    "国际",
]
SYDNEY_TZ = ZoneInfo("Australia/Sydney")


def activate_page_state(page):
    # Keep each page's working selection separate when navigating within one session.
    keys = ('sources', 'candidates', 'selected_video_ids', 'workflow_runs',
            'ui_events', 'source_errors', 'active_mode')
    previous = st.session_state.get('news_active_page')
    if previous == page:
        return
    if previous:
        st.session_state[f'news_page_state_{previous}'] = {
            key: st.session_state[key] for key in keys if key in st.session_state}
    for key in keys:
        st.session_state.pop(key, None)
    st.session_state.update(st.session_state.get(f'news_page_state_{page}', {}))
    st.session_state.news_active_page = page


def initialise_state(source_path=SOURCES_PATH, allow_articles=False) -> None:
    if 'sources' not in st.session_state:
        st.session_state.sources = load_sources(source_path, DEFAULT_SOURCES)
    if not allow_articles:
        st.session_state.sources = [s for s in st.session_state.sources if s.get('source_type', 'video') == 'video']
    # Keep configured conference channels and playlists independent from
    # previously saved or in-session news sources.
    st.session_state.conference_sources = [
        source.copy() for source in DEFAULT_CONFERENCE_SOURCES
    ]
    for source in [*st.session_state.sources, *st.session_state.conference_sources]:
        source.setdefault("channel_ref", source.pop("channel_id", ""))
        source.setdefault("name", "")
        source.setdefault("enabled", True)
    if "candidates" not in st.session_state:
        st.session_state.candidates = []
    # Migrate candidates already loaded in this browser session.
    for item in st.session_state.candidates:
        if item.get('source_type') == 'afr':
            item.update(source_type='article', publisher='AFR')
    if "selected_video_ids" not in st.session_state:
        st.session_state.selected_video_ids = set()
    if "workflow_runs" not in st.session_state:
        st.session_state.workflow_runs = []
    if "ui_events" not in st.session_state:
        st.session_state.ui_events = []
    if "source_errors" not in st.session_state:
        st.session_state.source_errors = []


def log_ui_event(message: str) -> None:
    timestamp = datetime.now(SYDNEY_TZ).strftime("%H:%M:%S")
    st.session_state.ui_events.append(f"[{timestamp}] {message}")


def add_source(source_key: str) -> None:
    st.session_state[source_key].append({"name": "", "channel_ref": "", "enabled": True})


def remove_source(source_key: str, index: int) -> None:
    st.session_state[source_key].pop(index)


def load_sources(path: Path, defaults: list[dict]) -> list[dict]:
    if not path.exists():
        return [source.copy() for source in defaults]
    try:
        sources = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        st.warning(f"{path.name} 格式无效，已使用默认新闻源。")
        return [source.copy() for source in defaults]
    if not isinstance(sources, list):
        st.warning(f"{path.name} 必须是数组，已使用默认新闻源。")
        return [source.copy() for source in defaults]
    for source in sources:
        # 兼容此前已保存的 channel_id 配置。
        source.setdefault("channel_ref", source.pop("channel_id", ""))
        source.setdefault("name", "")
        source.setdefault("enabled", True)
    return sources


def save_sources(source_key: str, path: Path, defaults: list[dict]) -> None:
    sources = [
        {
            "name": source["name"].strip(),
            "channel_ref": source["channel_ref"].strip(),
            "enabled": bool(source["enabled"]),
            "source_type": source.get("source_type", "video"),
            "topic": source.get("topic", "房产"),
        }
        for source in st.session_state[source_key]
        if source["name"].strip() or source["channel_ref"].strip()
    ]
    path.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    st.session_state[source_key] = sources or [source.copy() for source in defaults]


def fetch_recent_news(days: int, sources: list[dict]) -> None:
    client = YouTubeNews(YOUTUBE_API_KEY) if YOUTUBE_API_KEY else None
    enabled_sources = [source for source in sources if source["enabled"]]
    if not enabled_sources :
        raise ValueError("请至少启用一个新闻源")

    candidates = []
    st.session_state.source_errors = []
    for source in enabled_sources:
        name = source.get('name') or '未命名'
        log_ui_event(f'正在拉取来源：{name}')
        try:
            if source.get('source_type', 'video') == 'article':
                from services.afr_news import fetch_afr_news, article_candidates
                url = source['channel_ref'].strip()
                listing = fetch_afr_news(url)
                skipped = []
                rows = article_candidates(listing, days, topic=source.get('topic', '房产'),
                                          source_name=name, skipped=skipped)
                if skipped:
                    log_ui_event(f'{name}：跳过 {len(skipped)} 篇缺少有效时间的文章')
                log_ui_event(f'{name}：列表 {len(listing)} 篇，时间范围内 {len(rows)} 篇，无需 LLM 分类')
                if listing and not rows:
                    st.info(f'{name} 已读取 {len(listing)} 篇，但最近 {days} 天内没有有效日期的文章。请扩大左侧时间范围后重新拉取。')
            else:
                if client is None:
                    raise ValueError('未配置 YOUTUBE_API_KEY')
                rows = client.recent_videos(source, days)
                for item in rows:
                    item['source_type'] = 'video'
            candidates.extend(rows)
            log_ui_event(f'来源完成：{name}，{len(rows)} 条')
        except Exception as error:
            message = f'{name}：{type(error).__name__}: {error}'
            st.session_state.source_errors.append(message)
            log_ui_event(f'来源失败，已跳过：{message}')
    videos = [item for item in candidates if item.get('source_type') == 'video']
    if videos:
        try:
            client.add_video_durations(videos)
        except Exception as error:
            message = f'视频时长读取失败，将以未知时长继续：{error}'
            st.session_state.source_errors.append(message)
            log_ui_event(message)
    unique = {}
    for item in candidates:
        key = item['video_id']
        if key in unique:
            unique[key]['classified_topics'] = list(dict.fromkeys(
                unique[key].get('classified_topics', []) + item.get('classified_topics', [])))
        else:
            unique[key] = item
    candidates = list(unique.values())
    if not candidates and st.session_state.source_errors:
        raise RuntimeError('未取得候选新闻，请查看来源错误。')
    st.session_state.candidates = sorted(candidates, key=lambda item: item["published_at"], reverse=True)
    st.session_state.selected_video_ids = set()


def screen_candidates(topics: list[str]) -> None:
    if not topics:
        raise ValueError("请至少勾选一个关注主题")
    if not st.session_state.candidates:
        raise ValueError("请先拉取新闻")

    llm_input = [
        {
            "video_id": item["video_id"],
            "channel": item["channel_name"],
            "title": item["title"],
            "published_at": item["published_at"],
        }
        for item in st.session_state.candidates if item.get("source_type") != "article"
    ]
    results = ChatGPT().screen_news_titles(llm_input, TOPIC_OPTIONS) if llm_input else []
    result_by_id = {
        result.get("video_id"): result
        for result in results
        if isinstance(result, dict) and result.get("video_id")
    }
    for item in st.session_state.candidates:
        if item.get("source_type") == "article":
            continue
        result = result_by_id.get(item["video_id"], {
            "relevant": False, "reason": "模型未返回该视频的筛选结果",
        })
        item["classified_topics"] = [
            topic for topic in (result.get("matched_topics") or []) if topic in TOPIC_OPTIONS
        ] if result.get("relevant") is True else []
        item["reason"] = str(result.get("reason", ""))
    filter_candidate_topics(topics)


def filter_candidate_topics(topics):
    for item in st.session_state.candidates:
        if "classified_topics" in item:
            item["matched_topics"] = [t for t in item["classified_topics"] if t in topics]
            item["relevant"] = bool(item["matched_topics"])


def format_sydney_time(timestamp: str) -> str:
    published_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    return published_at.astimezone(SYDNEY_TZ).strftime("%Y-%m-%d %H:%M %Z")


def format_video_duration(seconds: object) -> str:
    if not isinstance(seconds, int) or seconds < 0:
        return "时长未知"
    hours, remainder = divmod(seconds, 3_600)
    minutes, remaining_seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}小时{minutes:02d}分"
    if minutes:
        return f"{minutes}分{remaining_seconds:02d}秒"
    return f"{remaining_seconds}秒"


def start_translation_workflow(title: str, upload: bool, advertisement: str) -> None:
    selected_ids = st.session_state.selected_video_ids
    selected_items = [
        item for item in st.session_state.candidates if item["video_id"] in selected_ids
    ]
    if not selected_items:
        raise ValueError("请至少勾选一条候选新闻")

    run_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    run_dir = QUEUE_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    task_file = run_dir / "translate_tasks.json"
    log_file = run_dir / "translate.log"
    tasks = [
        {
            "urls": item["url"],
            "title": title.strip() or "今日要闻",
            "subtitle": item["title"],
            "广告": advertisement.strip(),
            "upload": upload,
        }
        for item in selected_items
    ]
    task_file.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with log_file.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "translate.py", "--tasks", str(task_file.resolve())],
            cwd=Path.cwd(),
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    st.session_state.workflow_runs.insert(0, {
        "workflow": "新闻翻译",
        "run_id": run_id,
        "pid": process.pid,
        "started_at": datetime.now(SYDNEY_TZ).strftime("%Y-%m-%d %H:%M %Z"),
        "count": len(tasks),
        "task_file": str(task_file),
        "log_file": str(log_file),
    })


def start_conference_workflow(title: str, advertisement: str) -> None:
    selected_ids = st.session_state.selected_video_ids
    selected_items = [
        item for item in st.session_state.candidates if item["video_id"] in selected_ids
    ]
    if not selected_items:
        raise ValueError("请至少勾选一条候选发布会")

    run_id = f"conference_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    run_dir = QUEUE_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    task_file = run_dir / "conference_tasks.json"
    log_file = run_dir / "conference.log"
    tasks = [
        {
            "urls": item["url"],
            "title": title.strip() or "澳洲政策解读",
            "subtitle": item["title"],
            "广告": advertisement.strip(),
        }
        for item in selected_items
    ]
    task_file.write_text(json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    with log_file.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            [sys.executable, "conference.py", "--tasks", str(task_file.resolve())],
            cwd=Path.cwd(),
            stdout=output,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        )
    st.session_state.workflow_runs.insert(0, {
        "workflow": "发布会政策解读",
        "run_id": run_id,
        "pid": process.pid,
        "started_at": datetime.now(SYDNEY_TZ).strftime("%Y-%m-%d %H:%M %Z"),
        "count": len(tasks),
        "task_file": str(task_file),
        "log_file": str(log_file),
    })


def start_commentary_workflow(title: str, upload: bool, advertisement: str, angle: str) -> None:
    selected = [item for item in st.session_state.candidates
                if item['video_id'] in st.session_state.selected_video_ids]
    if not selected:
        raise ValueError("请至少勾选一条新闻")
    run_id = f"commentary_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid4().hex[:8]}"
    run_dir = QUEUE_ROOT / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    task_file = run_dir / 'commentary_tasks.json'
    log_file = run_dir / 'commentary.log'
    workspace = (run_dir / 'workspace').resolve()
    task = {'title': title.strip() or '新闻评论', 'angle': angle.strip(),
            '广告': advertisement.strip(),
            'sources': [{'url': item['url'], 'title': item['title'],
                         'source_type': item.get('source_type', 'video'),
                         'publisher': item.get('publisher') or item['channel_name']} for item in selected]}
    task_file.write_text(json.dumps(task, ensure_ascii=False, indent=2), encoding='utf-8')
    command = [sys.executable, '-u', '-m', 'experiments.news_commentary.pipeline',
               '--tasks', str(task_file.resolve()), '--workspace', str(workspace)]
    if upload:
        command.append('--upload')
    with log_file.open('w', encoding='utf-8') as output:
        process = subprocess.Popen(command, cwd=Path.cwd(), stdout=output,
            stderr=subprocess.STDOUT, text=True,
            env={**os.environ, 'PYTHONIOENCODING': 'utf-8',
                 'PATH': str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', '')})
    st.session_state.workflow_runs.insert(0, {
        'workflow': '新闻评论', 'run_id': run_id, 'pid': process.pid,
        'started_at': datetime.now(SYDNEY_TZ).strftime('%Y-%m-%d %H:%M %Z'),
        'count': len(selected), 'task_file': str(task_file), 'log_file': str(log_file),
        'cost_file': str(workspace / 'cost_summary.json'),
    })


@st.cache_resource
def title_embedding_service():
    from services.text_embedding_service import TextEmbeddingService
    return TextEmbeddingService()


def encode_news_titles(titles):
    return title_embedding_service().encode(list(titles))


def cluster_news_titles(titles_and_ids, similarity):
    from services.news_title_clusters import group_titles
    items = [{'video_id': vid, 'title': title} for vid, title in titles_and_ids]
    return group_titles(items, encode_news_titles(tuple(i['title'] for i in items)), similarity)


def update_commentary_selection(video_id, widget_key):
    selected = st.session_state.selected_video_ids
    if st.session_state[widget_key]:
        selected.add(video_id)
    else:
        selected.discard(video_id)
    # Synchronize every occurrence before Streamlit redraws widgets.
    for key in list(st.session_state):
        if key.startswith('commentary_group_') and key.endswith('_' + video_id):
            st.session_state[key] = video_id in selected


def render_commentary_groups(items):
    similarity = st.slider('标题分组相似度', 0.60, 0.95, 0.75, 0.01,
                           help='调高分组更细，调低会把更多相关新闻放在一起。')
    try:
        with st.spinner('正在按标题分组…'):
            pool = [i for i in st.session_state.candidates if i.get('classified_topics')]
            if not pool:
                pool = items
            groups_result = cluster_news_titles(tuple(sorted((i['video_id'], i['title']) for i in pool)), similarity)
            visible = {i['video_id']: i for i in items}
            groups = [{'title': g['title'], 'items': [visible[i['video_id']] for i in g['items'] if i['video_id'] in visible]} for g in groups_result]
            groups = [g for g in groups if g['items']]
    except Exception as error:
        st.warning(f'标题分组暂不可用，先显示全部候选：{error}')
        groups = [{'title': '全部候选新闻', 'items': items}]
    st.caption(f'{len(groups)} 组 · {len(items)} 条新闻。同一新闻可出现在多个组，选择状态同步，制作时去重。')
    for number, group in enumerate(groups):
        with st.container(border=True):
            st.markdown(f"**{group['title']}**")
            st.caption(f"{len(group['items'])} 条相关报道")
            for item in group['items']:
                left, right = st.columns([5, 1])
                left.markdown(f"[{item['title']}]({item['url']})")
                kind = '文章' if item.get('source_type') == 'article' else format_video_duration(item.get('duration_seconds'))
                left.caption(f"{item['channel_name']} · {format_sydney_time(item['published_at'])} · {kind}")
                key = f"commentary_group_{number}_{item['video_id']}"
                st.session_state[key] = item['video_id'] in st.session_state.selected_video_ids
                right.checkbox('加入评论素材', key=key, on_change=update_commentary_selection,
                               args=(item['video_id'], key))


