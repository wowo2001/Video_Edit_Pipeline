import inspect
import json
import re
from pathlib import Path

from openai import OpenAI

from config import ALI_API_KEY, OPENAI_API_KEY
from core.utils import read_json, safe_json_parse, srt_to_seconds, write_json
from prompts.editing_rules import EDITING_RULES
from prompts.fix_subtitles import FIX_SUBTITLE_PROMPT
from prompts.fix_subtitles_input import FIX_SUBTITLES_INPUT_PROMPT
from prompts.generate_hook import GENERATE_HOOK_PROMPT
from prompts.generate_script import GENERATE_SCRIPT_PROMPT
from prompts.generate_story import build_generate_story_prompt
from prompts.recognise_speaker_input import build_recognise_speaker_prompt
from prompts.refine_narration import REFINE_NARRATION_PROMPT
from prompts.script_schema import OUTPUT_SCHEMA
from prompts.select_scene import SELECT_SCENE_PROMPT
from prompts.split_scene_segment import SPLIT_SCENE_SEGMENT_PROMPT
from prompts.task_rules import TASK_RULES


PROVIDERS = {
    "openai": {
        "api_key": OPENAI_API_KEY,
        "models": {
            "generate_script": "gpt-5.6-luna", "fix_subtitles": "gpt-5.6-luna",
            "recognise_speaker": "gpt-5.6-sol", "generate_story": "gpt-5.6-sol",
            "select_scene": "gpt-5.6-luna",
            "split_scene_segment": "gpt-5.6-sol", "refine_narration": "gpt-5.4-mini",
            "generate_hook": "gpt-5.6-luna",
        },
    },
    "ali": {
        "api_key": ALI_API_KEY, "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "timeout": 600.0, "max_retries": 2,
        "models": {
            "generate_script": "qwen3.7-max", "fix_subtitles": "qwen3.7-max",
            "recognise_speaker": "qwen3.7-max", "generate_story": "qwen3.7-max",
            "select_scene": "qwen3.7-max",
            "split_scene_segment": "qwen3.7-max", "refine_narration": "qwen3.7-max",
            "generate_hook": "qwen3.7-max",
        },
    },
}


def segment_plan_issues(scene, plan):
    """Return human-readable issues that would make a scene plan too dialogue-heavy."""
    try:
        max_segments = max(1, int(scene.get("max_segments", 2)))
    except (TypeError, ValueError):
        max_segments = 2

    segments = plan.get("segments") if isinstance(plan, dict) else None
    if not isinstance(segments, list) or not segments:
        return ["必须输出至少一个 segment"]

    issues = []
    if len(segments) > max_segments:
        issues.append(f"segment 数为 {len(segments)}，超过上限 {max_segments}")

    subtitles = scene.get("subtitles", [])
    valid_ids = set(range(1, len(subtitles) + 1))
    used_ids = set()
    for position, segment in enumerate(segments, start=1):
        segment_id = segment.get("segment_id", position)
        subtitle_ids = segment.get("subtitle_ids")
        if not isinstance(subtitle_ids, list) or not subtitle_ids:
            issues.append(f"segment {segment_id} 必须选择至少一条原声高光")
            continue
        if any(not isinstance(subtitle_id, int) for subtitle_id in subtitle_ids):
            issues.append(f"segment {segment_id} 的 subtitle_ids 必须全部是整数")
            continue
        if subtitle_ids != sorted(set(subtitle_ids)):
            issues.append(f"segment {segment_id} 的 subtitle_ids 必须去重并严格递增")
        elif any(
            current_id != previous_id + 1
            for previous_id, current_id in zip(subtitle_ids, subtitle_ids[1:])
        ):
            issues.append(f"segment {segment_id} 的 subtitle_ids 必须连续，不能跳过中间字幕")

        invalid_ids = [subtitle_id for subtitle_id in subtitle_ids if subtitle_id not in valid_ids]
        if invalid_ids:
            issues.append(f"segment {segment_id} 引用了不存在的字幕编号 {invalid_ids}")
            continue

        repeated_ids = sorted(used_ids.intersection(subtitle_ids))
        if repeated_ids:
            issues.append(f"segment {segment_id} 重复使用了已选原声 {repeated_ids}")
        used_ids.update(subtitle_ids)

        dialogue_ms = sum(
            max(
                0,
                subtitles[subtitle_id - 1]["end_time"]
                - subtitles[subtitle_id - 1]["start_time"],
            )
            for subtitle_id in subtitle_ids
        )
        dialogue_seconds = dialogue_ms / 1000
        if dialogue_seconds > 12:
            issues.append(
                f"segment {segment_id} 的原声为 {dialogue_seconds:.1f} 秒，超过 12 秒上限"
            )

    return issues


def scene_selection_issues(candidates, plan):
    """Return issues in the global scene/segment budget produced by the director."""
    if not isinstance(plan, list) or not plan:
        return ["必须选择至少一个场景"]
    issues = []
    if len(plan) > 3:
        issues.append(f"选择了 {len(plan)} 个场景，超过 3 个上限")

    valid_scene_ids = {scene["scene_id"] for scene in candidates}
    selected_ids = [item.get("scene_id") for item in plan if isinstance(item, dict)]
    if len(selected_ids) != len(plan):
        issues.append("每个场景方案都必须是 JSON 对象并包含 scene_id")
        return issues
    if len(selected_ids) != len(set(selected_ids)):
        issues.append("scene_id 不得重复")
    invalid_ids = [scene_id for scene_id in selected_ids if scene_id not in valid_scene_ids]
    if invalid_ids:
        issues.append(f"引用了不存在的场景 {invalid_ids}")

    segment_budget = 0
    duration_budget = 0
    for item in plan:
        try:
            max_segments = int(item.get("max_segments"))
            target_duration = int(item.get("target_duration_seconds"))
        except (TypeError, ValueError):
            issues.append(
                f"scene {item.get('scene_id')} 必须提供整数 max_segments 和 target_duration_seconds"
            )
            continue
        if max_segments < 1:
            issues.append(f"scene {item.get('scene_id')} 的 max_segments 必须至少为 1")
        if target_duration < 1:
            issues.append(
                f"scene {item.get('scene_id')} 的 target_duration_seconds 必须大于 0"
            )
        segment_budget += max_segments
        duration_budget += target_duration

    if segment_budget > 6:
        issues.append(f"总 segment 预算为 {segment_budget}，超过 6 个上限")
    if duration_budget > 210:
        issues.append(f"场景总时长预算为 {duration_budget} 秒，超过 210 秒上限")

    ending_question = plan[-1].get("audience_question")
    if not isinstance(ending_question, str) or not ending_question.strip():
        issues.append("最后一个场景必须提供 audience_question")
    for item in plan[:-1]:
        if item.get("audience_question"):
            issues.append("audience_question 只能由最后一个场景提供")
    return issues


class ChatGPT:
    def __init__(self, provider="openai"):
        if provider not in PROVIDERS:
            raise ValueError(f"不支持的 LLM provider: {provider}")
        self.provider = provider
        self.config = PROVIDERS[provider]
        options = {key: value for key, value in self.config.items()
                   if key in {"api_key", "base_url", "timeout", "max_retries"}}
        self.client = OpenAI(**options)

    def _model(self):
        caller = inspect.currentframe().f_back
        if caller.f_code.co_name == "_complete":
            caller = caller.f_back
        return self.config["models"][caller.f_code.co_name]

    def _complete(self, prompt):
        return self.client.chat.completions.create(
            model=self._model(), messages=[{"role": "user", "content": prompt}]
        ).choices[0].message.content

    def generate_script(self, subtitles_path, script_path, story_path):
        subtitles = subtitles_path.read_text(encoding="utf-8")
        story_json = read_json(story_path)
        if self.provider == "ali":
            story = story_json.get("总故事")
        else:
            ids = set(story_json.get("推荐解说场景", []))
            story = "\n".join(scene["剧情"] for scene in story_json.get("场景", []) if scene["编号"] in ids)
        prompt = GENERATE_SCRIPT_PROMPT.format(task_rules=TASK_RULES, editing_rules=EDITING_RULES,
                                               output_schema=OUTPUT_SCHEMA, subtitles=subtitles, story=story)
        write_json(safe_json_parse(self._complete(prompt)), script_path, ensure_ascii=False, indent=2)

    def fix_subtitles(self, subtitles_path, fixed_subtitles_path):
        subtitles_path = Path(subtitles_path)
        fixed_subtitles_path = Path(fixed_subtitles_path)
        subtitles = subtitles_path.read_text(encoding="utf-8")
        prompt = FIX_SUBTITLES_INPUT_PROMPT.format(prompt=FIX_SUBTITLE_PROMPT, subtitles=subtitles)
        result = json.loads(self._complete(prompt))
        for item in result["popup_comments"]:
            item["start_time"] = srt_to_seconds(item["start_time"])
        fixed = re.sub(r"^```srt\s*|^```\s*|\s*```$", "", result["subtitle"])
        fixed_subtitles_path.write_text(fixed, encoding="utf-8")
        return result["popup_comments"], result["title"]

    def recognise_speaker(self, subtitles_path, mapping_path):
        mapping = json.loads(self._complete(build_recognise_speaker_prompt(subtitles_path.read_text(encoding="utf-8"))).strip())
        write_json(mapping, mapping_path, ensure_ascii=False, indent=2)

    def generate_story(self, subtitles_path, story_path):
        write_json(json.loads(self._complete(build_generate_story_prompt(subtitles_path.read_text(encoding="utf-8"))).strip()),
                   story_path, ensure_ascii=False, indent=2)

    def select_scene(self, candidate_path, question, theme, output_path):
        scenes = read_json(candidate_path)
        candidates = [{"scene_id": scene["scene_id"], "summary": scene["summary"]} for scene in scenes]
        prompt = SELECT_SCENE_PROMPT.format(question=question, theme=theme,
                                            candidates=json.dumps(candidates, ensure_ascii=False, indent=2))
        result = safe_json_parse(self._complete(prompt))
        issues = scene_selection_issues(candidates, result)
        if issues:
            retry_prompt = (
                f"{prompt}\n\n上一次总导演方案不合格：\n- "
                + "\n- ".join(issues)
                + "\n请重新取舍场景、压缩预算，并输出完整 JSON。"
            )
            result = safe_json_parse(self._complete(retry_prompt))
            issues = scene_selection_issues(candidates, result)
            if issues:
                raise ValueError("总导演连续两次未满足成片预算：" + "；".join(issues))
        write_json(result, output_path, ensure_ascii=False, indent=2)

    def split_scene_segment(self, theme, scene):
        prompt = SPLIT_SCENE_SEGMENT_PROMPT.format(theme=theme, summary=scene["summary"],
                                                   subtitles=scene["subtitles_plain_text"], task=scene["task"],
                                                   max_segments=scene.get("max_segments", 2),
                                                   target_duration_seconds=scene.get("target_duration_seconds", 60))
        result = safe_json_parse(self._complete(prompt))
        issues = segment_plan_issues(scene, result)
        if issues:
            retry_prompt = (
                f"{prompt}\n\n上一次方案不合格：\n- "
                + "\n- ".join(issues)
                + "\n请进一步删减原声和合并 segment，并重新输出完整 JSON。"
            )
            result = safe_json_parse(self._complete(retry_prompt))
            issues = segment_plan_issues(scene, result)
            if issues:
                raise ValueError("分段导演连续两次未满足剪辑预算：" + "；".join(issues))
        return result

    def refine_narration(self, scene_path):
        scenes = read_json(scene_path)
        ai_input = [{"scene_id": scene["scene_id"], "title": scene["title"],
                     "segments": [{key: segment[key] for key in ("segment_id", "purpose", "narration")}
                                  for segment in scene["segments"]]} for scene in scenes]
        refined = safe_json_parse(self._complete(REFINE_NARRATION_PROMPT.format(
            scenes=json.dumps(ai_input, ensure_ascii=False, indent=2))))
        refined_map = {scene["scene_id"]: {segment["segment_id"]: segment["narration"] for segment in scene["segments"]}
                       for scene in refined}
        for scene in scenes:
            for segment in scene["segments"]:
                narration = refined_map.get(scene["scene_id"], {}).get(segment["segment_id"])
                if narration:
                    segment["narration"] = narration
        write_json(scenes, scene_path, ensure_ascii=False, indent=2)
        return scenes

    def generate_hook(self, theme, scene_path, output_path):
        scenes = read_json(scene_path)
        ai_input = [{"scene_id": scene["scene_id"], "title": scene["title"],
                     "segments": [{"segment_id": seg["segment_id"], "purpose": seg["purpose"]} for seg in scene["segments"]]}
                    for scene in scenes]
        prompt = GENERATE_HOOK_PROMPT.format(theme=theme, scenes=json.dumps(ai_input, ensure_ascii=False, indent=2))
        write_json(safe_json_parse(self._complete(prompt)), output_path, ensure_ascii=False, indent=2)
