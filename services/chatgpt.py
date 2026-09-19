import inspect
import json
import re
from pathlib import Path

from openai import OpenAI

from config import ALI_API_KEY, OPENAI_API_KEY
from core.llm_cost import record_llm_usage
from core.utils import read_json, safe_json_parse, srt_to_seconds, write_json
from prompts.editing_rules import EDITING_RULES
from prompts.fix_subtitles import FIX_SUBTITLE_PROMPT
from prompts.fix_subtitles_input import FIX_SUBTITLES_INPUT_PROMPT
from prompts.generate_hook import GENERATE_HOOK_PROMPT
from prompts.generate_script import GENERATE_SCRIPT_PROMPT
from prompts.generate_story import build_generate_story_prompt
from prompts.recognise_speaker_input import build_recognise_speaker_prompt
from prompts.refine_narration import ADVERTISEMENT_RULES, REFINE_NARRATION_PROMPT
from prompts.script_schema import OUTPUT_SCHEMA
from prompts.select_scene import SELECT_SCENE_PROMPT
from prompts.split_scene_segment import SPLIT_SCENE_SEGMENT_PROMPT
from prompts.task_rules import TASK_RULES


PROVIDERS = {
    "openai": {
        "api_key": OPENAI_API_KEY,
        "models": {
            "generate_script": "gpt-5.6-luna", "fix_subtitles": "gpt-5.6-luna",
            "recognise_speaker": "gpt-5.6-terra", "generate_story": "gpt-5.6-terra",
            "select_scene": "gpt-5.6-sol",
            "split_scene_segment": "gpt-5.6-terra", "refine_narration": "gpt-5.6-terra",
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


class ChatGPT:
    def __init__(self, provider="openai", usage_report_path=None):
        if provider not in PROVIDERS:
            raise ValueError(f"不支持的 LLM provider: {provider}")
        self.provider = provider
        self.config = PROVIDERS[provider]
        self.usage_report_path = usage_report_path
        options = {key: value for key, value in self.config.items()
                   if key in {"api_key", "base_url", "timeout", "max_retries"}}
        self.client = OpenAI(**options)

    def _model(self):
        caller = inspect.currentframe().f_back
        if caller.f_code.co_name == "_complete":
            caller = caller.f_back
        return self.config["models"][caller.f_code.co_name]

    def _complete(self, prompt):
        stage, model = self._calling_stage(), self._model()
        response = self.client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": prompt}]
        )
        record_llm_usage(self.usage_report_path, self.provider, stage, model, response.usage)
        return response.choices[0].message.content

    def _calling_stage(self):
        caller = inspect.currentframe().f_back
        if caller.f_code.co_name == "_complete":
            caller = caller.f_back
        return caller.f_code.co_name

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
        write_json(result, output_path, ensure_ascii=False, indent=2)

    def split_scene_segment(self, theme, scene):
        ending_requirement = (
            "本场景之后会追加片尾互动问题；最后一个 segment 仍按是否展示原声选择 type。"
            "若选 with_dialogue，成片以‘旁白 → 原声 → 互动问题’结束；若选 narration_only，成片以‘旁白 → 互动问题’结束。"
            if scene.get("audience_question")
            else "本场景不是片尾场景，无额外要求。"
        )
        prompt = SPLIT_SCENE_SEGMENT_PROMPT.format(theme=theme, summary=scene["summary"],
                                                   subtitles=scene["subtitles_plain_text"], task=scene["task"],
                                                   max_segments=scene.get("max_segments", 2),
                                                   ending_requirement=ending_requirement)
        return safe_json_parse(self._complete(prompt))

    def refine_narration(self, scene_path, advertisement=None):
        scenes = read_json(scene_path)
        ai_input = [{"scene_id": scene["scene_id"], "title": scene["title"], "summary": scene.get("summary", ""),
                     "segments": [{"segment_id": segment["segment_id"],
                                   "type": segment.get("type", "with_dialogue"),
                                   "purpose": segment["purpose"],
                                   "narration": segment["narration"]}
                                  for segment in scene["segments"]]} for scene in scenes]
        prompt = REFINE_NARRATION_PROMPT.format(
            scenes=json.dumps(ai_input, ensure_ascii=False, indent=2))
        if advertisement:
            prompt += ADVERTISEMENT_RULES.format(advertisement=advertisement)
        refined = safe_json_parse(self._complete(prompt))
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
                     "segments": [{"segment_id": seg["segment_id"], "type": seg.get("type", "with_dialogue"),
                                   "purpose": seg["purpose"]} for seg in scene["segments"]]}
                    for scene in scenes]
        prompt = GENERATE_HOOK_PROMPT.format(theme=theme, scenes=json.dumps(ai_input, ensure_ascii=False, indent=2))
        write_json(safe_json_parse(self._complete(prompt)), output_path, ensure_ascii=False, indent=2)
