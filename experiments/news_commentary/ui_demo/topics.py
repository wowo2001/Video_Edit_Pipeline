"""Editable UI topic names and editorial screening criteria."""
import json
from pathlib import Path

CONFIG = Path(__file__).with_name("topics.json")


def load_topics():
    topics = json.loads(CONFIG.read_text(encoding="utf-8"))
    if not isinstance(topics, dict) or not topics or any(
        not isinstance(name, str) or not name.strip() or
        not isinstance(description, dict) or
        not isinstance(description.get("prompt"), str) or not description["prompt"].strip() or
        not isinstance(description.get("asr_language"), str) or not description["asr_language"].strip()
        for name, description in topics.items()
    ):
        raise ValueError("topics.json 每个主题必须包含非空 prompt 和 asr_language")
    return topics


def task_sources(items):
    """Snapshot each selected source's tab language into the task."""
    topics = load_topics()
    return [{"url": r["url"], "title": r["title"], "source_type": r["type"],
             "publisher": r["publisher"], "topic": r["topic"],
             "asr_language": topics[r["topic"]]["asr_language"]} for r in items]
