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
    "移民",
    "生活",
    "财经",
    "政治",
    "国际",
]
SYDNEY_TZ = ZoneInfo("Australia/Sydney")


def initialise_state() -> None:
    for key in ("afr_listing_cache", "title_classification_cache", "title_embeddings_cache", "title_clusters_cache", "article_candidate_scope"):
        st.session_state.pop(key, None)
    if "sources" not in st.session_state:
        st.session_state.sources = load_sources(SOURCES_PATH, DEFAULT_SOURCES)
    if not st.session_state.get('unified_article_sources_v1'):
        configured = load_sources(SOURCES_PATH, DEFAULT_SOURCES)
        existing = {source.get('channel_ref') for source in st.session_state.sources}
        st.session_state.sources.extend(source for source in configured
                                        if source.get('source_type') == 'article' and source.get('channel_ref') not in existing)
        st.session_state.unified_article_sources_v1 = True
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


st.set_page_config(page_title="澳洲房东新闻选题", page_icon="🏠", layout="wide")
initialise_state()

st.title("🎬 澳洲新闻视频制作")
mode = st.radio(
    "选择制作模式",
    ("新闻翻译", "发布会政策解读", "新闻评论"),
    horizontal=True,
    key="production_mode",
)
is_conference = mode == "发布会政策解读"
is_commentary = mode == "新闻评论"
if st.session_state.get("active_mode") != mode:
    st.session_state.active_mode = mode
    st.session_state.candidates = []
    st.session_state.selected_video_ids = set()

if is_conference:
    st.caption("从新闻发布会视频中按发布时间选择素材，生成面向在澳华人的政策解读短视频。")
    source_key, source_path, source_defaults = (
        "conference_sources", CONFERENCE_SOURCES_PATH, DEFAULT_CONFERENCE_SOURCES
    )
else:
    st.caption("选择几条相关新闻，综合成一条新闻评论视频。" if is_commentary else "从 YouTube 新闻源筛选与房产、租赁、福利相关的内容，再启动中文翻译视频工作流。")
    source_key, source_path, source_defaults = "sources", SOURCES_PATH, DEFAULT_SOURCES
sources = st.session_state[source_key]

with st.sidebar:
    st.header("本次范围")
    days = st.slider("最近几天", min_value=1, max_value=7, value=1)

    selected_topics = []
    if not is_conference:
        st.subheader("关注主题")
        st.caption("拉取或重新分类时由 Luna 处理全部视频标题；切换主题只筛选当前结果。")
        selected_topics = [
            topic for topic in TOPIC_OPTIONS
            if st.checkbox(topic, value=True, key=f"topic_{topic}")
        ]
    st.caption(f"本地时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

if not is_conference:
    filter_candidate_topics(selected_topics)

source_tab, candidate_tab, workflow_tab = st.tabs(["1. 新闻源", "2. 候选新闻", "3. 工作流队列"])

with source_tab:
    st.subheader("YouTube 发布会源" if is_conference else "新闻源（视频 / 文章）")
    if is_conference:
        st.write("固定使用 ABC 与 9 News 的 Live 标签页、National Press Club 全频道，以及指定播放列表；按所选天数显示最近发布的视频。")
    else:
        st.write("视频源填写 YouTube 频道网址；文章源填写 AFR 栏目网址。统一按所选天数拉取，文章按栏目主题归类，无需 LLM，每次点击拉取都会重新读取列表。")
    if not YOUTUBE_API_KEY:
        st.warning("未配置 YOUTUBE_API_KEY，暂时无法拉取 YouTube 新闻。")
    if not OPENAI_API_KEY:
        st.warning("未配置 OPENAI_KEY，暂时无法启动后续制作。")
    if st.button(
        "拉取发布会视频" if is_conference else "拉取并 AI 筛选新闻",
        type="primary",
        disabled=not any(source.get("enabled") for source in sources),
    ):
        st.session_state.ui_events = []
        try:
            with st.status("正在处理新闻…", expanded=True) as status:
                status.write("正在解析频道并拉取 YouTube 公开视频…")
                log_ui_event("开始拉取 YouTube 新闻")
                fetch_recent_news(days, sources)
                log_ui_event(f"新闻拉取完成：{len(st.session_state.candidates)} 条")
                if is_conference:
                    status.update(label="发布会视频拉取完成", state="complete", expanded=False)
                else:
                    status.write(f"已拉取 {len(st.session_state.candidates)} 条，正在将全部视频标题交给 Luna 分类…")
                    screen_candidates(selected_topics)
                    log_ui_event("Luna 标题筛选完成")
                    status.update(label="新闻筛选完成", state="complete", expanded=False)
            if is_conference:
                st.success(f"已按发布时间拉取 {len(st.session_state.candidates)} 条视频。")
            else:
                relevant_count = sum(item.get("relevant", False) for item in st.session_state.candidates)
                st.success(f"已拉取 {len(st.session_state.candidates)} 条新闻；按主题筛出 {relevant_count} 条相关候选。")
        except Exception as error:
            log_ui_event(f"失败：{type(error).__name__}: {error}")
            st.error(f"新闻筛选失败：{type(error).__name__}: {error}")
    if is_conference:
        st.caption(f"计划拉取最近 {days} 天的公开视频；不进行 LLM 标题或主题筛选。")
    else:
        st.caption(f"计划拉取最近 {days} 天的视频和文章，并按主题“{'、'.join(selected_topics) or '未选择'}”筛选。")
    st.divider()
    if is_conference:
        st.caption("固定来源")
        st.markdown("- [ABC News Australia · Live](https://www.youtube.com/@abcnewsaustralia/streams)")
        st.markdown("- [9 News Australia · Live](https://www.youtube.com/@9NewsAUS/streams)")
        for source in sources:
            playlist_id = str(source.get("playlist_id") or "").strip()
            if playlist_id:
                source_name = source.get("name") or "指定 YouTube 播放列表"
                st.markdown(
                    f"- [{source_name}](https://www.youtube.com/playlist?list={playlist_id})"
                )
    else:
        for index, source in enumerate(sources):
            with st.container(border=True):
                left, middle, right, remove = st.columns([1.4, 2.4, 0.8, 0.5])
                source["source_type"] = st.selectbox("内容类型", ["video", "article"], index=1 if source.get("source_type") == "article" else 0, format_func=lambda value: "文章" if value == "article" else "视频", key=f"{source_key}_type_{index}")
                if source["source_type"] == "article":
                    source["topic"] = st.selectbox("栏目主题", TOPIC_OPTIONS, index=TOPIC_OPTIONS.index(source.get("topic", "房产")), key=f"{source_key}_article_topic_{index}")
                source["name"] = left.text_input("来源名称", value=source["name"], key=f"{source_key}_name_{index}")
                source["channel_ref"] = middle.text_input(
                    "来源网址或 @handle", value=source["channel_ref"], key=f"{source_key}_channel_{index}",
                    placeholder="例如 https://youtube.com/@ABCNewsAustralia 或 @ABCNewsAustralia",
                )
                source["enabled"] = right.checkbox("启用", value=source["enabled"], key=f"{source_key}_enabled_{index}")
                remove.button("删除", key=f"{source_key}_remove_{index}", on_click=remove_source, args=(source_key, index))
        st.button("＋ 添加新闻源", key=f"{source_key}_add", on_click=add_source, args=(source_key,))
        if st.button("保存新闻源", key=f"{source_key}_save", type="secondary"):
            save_sources(source_key, source_path, source_defaults)
            st.success(f"已保存到 {source_path.name}")
    if st.session_state.ui_events:
        with st.expander("执行日志", expanded=True):
            st.code("\n".join(st.session_state.ui_events), language="text")
    if st.session_state.source_errors:
        st.warning("部分来源未能拉取，已跳过：\n\n" + "\n\n".join(
            f"- {message}" for message in st.session_state.source_errors
        ))

with candidate_tab:
    st.subheader("候选发布会" if is_conference else "候选新闻")
    if not st.session_state.candidates:
        st.info("尚未拉取视频。拉取后勾选要制作的内容。" if is_conference else "尚未拉取新闻。拉取后，使用 AI 按当前主题筛选并勾选要制作的视频。")
    else:
        if not is_conference and st.button("重新分类全部新闻", type="secondary", disabled=not bool(OPENAI_API_KEY)):
            try:
                log_ui_event("开始按当前主题重新调用 Luna 筛选")
                with st.status("正在重新分类全部视频标题…", expanded=False) as status:
                    screen_candidates(selected_topics)
                    status.update(label="Luna 筛选完成", state="complete", expanded=False)
                log_ui_event("Luna 重新筛选完成")
                relevant_count = sum(item.get("relevant", False) for item in st.session_state.candidates)
                st.success(f"已完成筛选：{relevant_count} 条相关，{len(st.session_state.candidates) - relevant_count} 条不相关。")
            except Exception as error:
                log_ui_event(f"重新筛选失败：{type(error).__name__}: {error}")
                st.error(f"重新筛选失败：{type(error).__name__}: {error}")

        screened = st.session_state.candidates if is_conference else [item for item in st.session_state.candidates if "relevant" in item]
        if not screened:
            st.caption("新闻已拉取，等待 AI 筛选。")
        else:
            relevant = screened if is_conference else [item for item in screened if item["relevant"]]
            if is_conference:
                st.caption(f"按发布时间显示 {len(relevant)} 条视频；未进行 AI 筛选。")
            else:
                irrelevant_count = len(screened) - len(relevant)
                st.caption(f"主题筛选结果：{len(relevant)} 条相关，{irrelevant_count} 条未选中。只显示相关内容。")
            article_count = sum(item.get('source_type') == 'article' for item in relevant)
            st.caption(f"当前显示：{len(relevant) - article_count} 条视频 · {article_count} 篇文章")
            if not relevant:
                st.info("没有标题与当前主题相关；可修改主题后重新筛选。")
            if is_commentary and relevant:
                render_commentary_groups(relevant)
            for item in ([] if is_commentary else relevant):
                with st.container(border=True):
                    columns = st.columns([0.7, 4.3, 1.2])
                    if item.get("thumbnail_url"):
                        columns[0].image(item["thumbnail_url"], use_container_width=True)
                    columns[1].markdown(f"**[{item['title']}]({item['url']})**")
                    columns[1].caption(
                        f"{item['channel_name']} · {format_sydney_time(item['published_at'])} · "
                        f"{format_video_duration(item.get('duration_seconds'))}"
                    )
                    if not is_conference:
                        columns[1].write(f"主题：{'、'.join(item.get('matched_topics', [])) or '未明确'}  \nAI 判断：{item.get('reason') or '相关'}")
                    checked = columns[2].checkbox(
                        "加入评论素材" if is_commentary else ("加入解读队列" if is_conference else "加入翻译队列"),
                        value=item["video_id"] in st.session_state.selected_video_ids,
                        key=f"{mode}_select_{item['video_id']}",
                    )
                    if checked:
                        st.session_state.selected_video_ids.add(item["video_id"])
                    else:
                        st.session_state.selected_video_ids.discard(item["video_id"])

with workflow_tab:
    st.subheader("制作队列")
    selected_count = len(st.session_state.selected_video_ids)
    st.info(f"已选择 {selected_count} 条素材。" + ("这些素材将综合制作成一条评论视频。" if is_commentary else "每条都会建立独立工作区，并启动 conference.py；成片会自动上传 Google Drive。" if is_conference else "每条都会建立独立工作区，并启动 translate.py。"))
    task_title = st.text_input("视频大标题", value="新闻评论" if is_commentary else ("澳洲政策解读" if is_conference else "今日要闻"), key=f"{mode}_title")
    advertisement = st.text_input(
        "广告文案",
        value="如果你想了解更多澳洲资讯，请关注土澳小红叔",
        help="新闻翻译会独立插入广告；发布会解读会将广告融入一段既有解说。",
        key=f"{mode}_advertisement",
    )
    upload_to_drive = False if is_conference else st.checkbox("完成后上传 Google Drive", value=True)
    angle = st.text_area("评论方向（可选）", key="commentary_angle", placeholder="例如：这些报道共同说明了什么，对在澳华人有何影响？") if is_commentary else ""
    action_label = "用已选新闻制作一条评论视频" if is_commentary else ("启动已选发布会的政策解读制作" if is_conference else "启动已选视频的翻译工作流")
    if st.button(action_label, disabled=selected_count == 0, type="primary"):
        try:
            if is_commentary:
                start_commentary_workflow(task_title, upload_to_drive, advertisement, angle)
            elif is_conference:
                start_conference_workflow(task_title, advertisement)
            else:
                start_translation_workflow(task_title, upload_to_drive, advertisement)
            st.success("工作流已在后台启动。日志会持续写入下方路径。")
        except (OSError, ValueError) as error:
            st.error(str(error))

    if st.session_state.workflow_runs:
        st.subheader("本次页面启动的任务")
        for run in st.session_state.workflow_runs:
            with st.container(border=True):
                st.write(
                    f"**{run.get('workflow', '新闻翻译')} · {run['count']} 条视频** · 已启动于 {run['started_at']} · "
                    f"进程 PID {run['pid']}"
                )
                st.caption(f"任务文件：{run['task_file']}")
                st.caption(f"日志文件：{run['log_file']}")
                if run.get("cost_file"):
                    st.caption(f"费用明细：{run['cost_file']}")
