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
    if "sources" not in st.session_state:
        st.session_state.sources = load_sources(SOURCES_PATH, DEFAULT_SOURCES)
    # Conference production deliberately uses only the configured sources'
    # archived live streams;
    # keep it independent from any previously saved or in-session news sources.
    st.session_state.conference_sources = [
        source.copy() for source in DEFAULT_CONFERENCE_SOURCES
    ]
    for source in [*st.session_state.sources, *st.session_state.conference_sources]:
        source.setdefault("channel_ref", source.pop("channel_id", ""))
        source.setdefault("name", "")
        source.setdefault("enabled", True)
    if "candidates" not in st.session_state:
        st.session_state.candidates = []
    if "selected_video_ids" not in st.session_state:
        st.session_state.selected_video_ids = set()
    if "workflow_runs" not in st.session_state:
        st.session_state.workflow_runs = []
    if "ui_events" not in st.session_state:
        st.session_state.ui_events = []


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
        }
        for source in st.session_state[source_key]
        if source["name"].strip() or source["channel_ref"].strip()
    ]
    path.write_text(json.dumps(sources, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    st.session_state[source_key] = sources or [source.copy() for source in defaults]


def fetch_recent_news(days: int, sources: list[dict]) -> None:
    client = YouTubeNews(YOUTUBE_API_KEY)
    enabled_sources = [source for source in sources if source["enabled"]]
    if not enabled_sources:
        raise ValueError("请至少启用一个新闻源")
    candidates = []
    for source in enabled_sources:
        channel_ref = str(source.get("channel_ref") or "").strip()
        playlist_id = str(source.get("playlist_id") or "").strip()
        if not channel_ref and not playlist_id:
            raise ValueError(f"新闻源“{source['name'] or '未命名'}”缺少频道网址、@handle 或播放列表 ID")
        candidates.extend(client.recent_videos(source, days))
    client.add_video_durations(candidates)
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
        for item in st.session_state.candidates
    ]
    results = ChatGPT().screen_news_titles(llm_input, topics)
    result_by_id = {
        result.get("video_id"): result
        for result in results
        if isinstance(result, dict) and result.get("video_id")
    }
    expected_ids = {item["video_id"] for item in st.session_state.candidates}
    if set(result_by_id) != expected_ids:
        raise ValueError("LLM 筛选结果的视频编号不完整，请重试")

    for item in st.session_state.candidates:
        result = result_by_id[item["video_id"]]
        item["relevant"] = bool(result.get("relevant"))
        item["matched_topics"] = [
            topic for topic in result.get("matched_topics", []) if topic in topics
        ]
        item["reason"] = str(result.get("reason", ""))


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


def start_translation_workflow(title: str, upload: bool) -> None:
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


def start_conference_workflow(title: str) -> None:
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


st.set_page_config(page_title="澳洲房东新闻选题", page_icon="🏠", layout="wide")
initialise_state()

st.title("🎬 澳洲新闻视频制作")
mode = st.radio(
    "选择制作模式",
    ("新闻翻译", "发布会政策解读"),
    horizontal=True,
    key="production_mode",
)
is_conference = mode == "发布会政策解读"
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
    st.caption("从 YouTube 新闻源筛选与房产、租赁、福利相关的内容，再启动中文翻译视频工作流。")
    source_key, source_path, source_defaults = "sources", SOURCES_PATH, DEFAULT_SOURCES
sources = st.session_state[source_key]

with st.sidebar:
    st.header("本次范围")
    days = st.slider("最近几天", min_value=1, max_value=7, value=1)
    selected_topics = []
    if not is_conference:
        st.subheader("关注主题")
        st.caption("拉取后由 Luna 根据勾选主题筛选视频标题。")
        selected_topics = [
            topic for topic in TOPIC_OPTIONS
            if st.checkbox(topic, value=True, key=f"topic_{topic}")
        ]
    st.caption(f"本地时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")

source_tab, candidate_tab, workflow_tab = st.tabs(["1. 新闻源", "2. 候选新闻", "3. 工作流队列"])

with source_tab:
    st.subheader("YouTube 发布会源" if is_conference else "YouTube 新闻源")
    if is_conference:
        st.write("固定使用 ABC 与 9 News 的 Live 标签页，以及指定播放列表；只显示最近发布的视频。")
    else:
        st.write("粘贴公开频道的网址、@handle 或 Channel ID；下一步会自动解析为 Channel ID。")
    if not YOUTUBE_API_KEY:
        st.warning("未配置 YOUTUBE_API_KEY，暂时无法拉取 YouTube 新闻。")
    if not OPENAI_API_KEY:
        st.warning("未配置 OPENAI_KEY，暂时无法启动后续制作。")
    if st.button(
        "拉取发布会视频" if is_conference else "拉取并 AI 筛选新闻",
        type="primary",
        disabled=not bool(YOUTUBE_API_KEY and OPENAI_API_KEY),
    ):
        st.session_state.ui_events = []
        try:
            with st.status("正在处理新闻…", expanded=True) as status:
                status.write("正在解析频道并拉取 YouTube 公开视频…")
                log_ui_event("开始拉取 YouTube 新闻")
                fetch_recent_news(days, sources)
                log_ui_event(f"YouTube 拉取完成：{len(st.session_state.candidates)} 条")
                if is_conference:
                    status.update(label="发布会视频拉取完成", state="complete", expanded=False)
                else:
                    status.write(f"已拉取 {len(st.session_state.candidates)} 条，正在交给 Luna 筛选标题…")
                    screen_candidates(selected_topics)
                    log_ui_event("Luna 标题筛选完成")
                    status.update(label="新闻筛选完成", state="complete", expanded=False)
            if is_conference:
                st.success(f"已按发布时间拉取 {len(st.session_state.candidates)} 条视频。")
            else:
                relevant_count = sum(item.get("relevant", False) for item in st.session_state.candidates)
                st.success(f"已拉取 {len(st.session_state.candidates)} 条新闻；Luna 筛出 {relevant_count} 条相关候选。")
        except Exception as error:
            log_ui_event(f"失败：{type(error).__name__}: {error}")
            st.error(f"新闻筛选失败：{type(error).__name__}: {error}")
    if is_conference:
        st.caption(f"计划拉取最近 {days} 天的公开视频；不进行 LLM 标题或主题筛选。")
    else:
        st.caption(f"计划拉取最近 {days} 天的公开视频，并按主题“{'、'.join(selected_topics) or '未选择'}”筛选。")
    st.divider()
    if is_conference:
        st.caption("固定来源")
        st.markdown("- [ABC News Australia · Live](https://www.youtube.com/@abcnewsaustralia/streams)")
        st.markdown("- [9 News Australia · Live](https://www.youtube.com/@9NewsAUS/streams)")
        st.markdown("- [指定 YouTube 播放列表](https://www.youtube.com/playlist?list=PLHpsRD1kEE6zaL9QK2446ntmZPOaI4aTa)")
    else:
        for index, source in enumerate(sources):
            with st.container(border=True):
                left, middle, right, remove = st.columns([1.4, 2.4, 0.8, 0.5])
                source["name"] = left.text_input("频道名称", value=source["name"], key=f"{source_key}_name_{index}")
                source["channel_ref"] = middle.text_input(
                    "频道网址或 @handle", value=source["channel_ref"], key=f"{source_key}_channel_{index}",
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

with candidate_tab:
    st.subheader("候选发布会" if is_conference else "候选新闻")
    if not st.session_state.candidates:
        st.info("尚未拉取视频。拉取后勾选要制作的内容。" if is_conference else "尚未拉取新闻。拉取后，使用 AI 按当前主题筛选并勾选要制作的视频。")
    else:
        if not is_conference and st.button("按当前主题重新 AI 筛选", type="secondary", disabled=not bool(OPENAI_API_KEY)):
            try:
                log_ui_event("开始按当前主题重新调用 Luna 筛选")
                with st.status("Luna 正在筛选标题…", expanded=False) as status:
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
                st.caption(f"AI 筛选结果：{len(relevant)} 条相关，{irrelevant_count} 条未选中。只显示相关内容。")
            if not relevant:
                st.info("没有标题与当前主题相关；可修改主题后重新筛选。")
            for item in relevant:
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
                        columns[1].write(f"主题：{'、'.join(item.get('matched_topics', [])) or '未明确'}  \\nAI 判断：{item.get('reason') or '相关'}")
                    checked = columns[2].checkbox(
                        "加入解读队列" if is_conference else "加入翻译队列",
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
    st.info(f"已选择 {selected_count} 条视频。" + ("每条都会建立独立工作区，并启动 conference.py；成片会自动上传 Google Drive。" if is_conference else "每条都会建立独立工作区，并启动 translate.py。"))
    task_title = st.text_input("视频大标题", value="澳洲政策解读" if is_conference else "今日要闻", key=f"{mode}_title")
    upload_to_drive = False if is_conference else st.checkbox("完成后上传 Google Drive", value=True)
    action_label = "启动已选发布会的政策解读制作" if is_conference else "启动已选视频的翻译工作流"
    if st.button(action_label, disabled=selected_count == 0, type="primary"):
        try:
            if is_conference:
                start_conference_workflow(task_title)
            else:
                start_translation_workflow(task_title, upload_to_drive)
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
