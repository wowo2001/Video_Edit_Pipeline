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
from prompts.recognise_parliament_speaker import build_recognise_parliament_speaker_prompt
from prompts.segment_parliament_content import build_segment_parliament_content_prompt
from prompts.select_chinese_australia_topic import build_select_chinese_australia_topic_prompt
from prompts.plan_parliament_commentary import build_plan_parliament_commentary_prompt
from prompts.plan_translation_advertisement import build_plan_translation_advertisement_prompt
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
            "translate_subtitles": "gpt-5.6-terra",
            "rewrite_australian_news_subtitle": "gpt-5.6-terra",
            "merge_english_subtitles_before_diarization": "gpt-5.6-terra",
            "translate_chinese_subtitles": "gpt-5.6-luna",
            "merge_chinese_subtitles_before_diarization": "gpt-5.6-terra",
            "recognise_parliament_speakers": "gpt-5.6-terra",
            "segment_parliament_content": "gpt-5.6-terra",
            "select_chinese_australia_topic": "gpt-5.6-terra",
            "plan_parliament_commentary": "gpt-5.6-terra",
            "screen_news_titles": "gpt-5.6-luna",
            "plan_translation_advertisement": "gpt-5.6-terra",
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
            "plan_translation_advertisement": "qwen3.7-max",
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

    def recognise_parliament_speakers(self, source_context, speaker_lines):
        """Return structured identities for Parliament-video voice clusters."""
        response = self._complete(
            build_recognise_parliament_speaker_prompt(source_context, speaker_lines)
        )
        return safe_json_parse(response)

    def segment_parliament_content(self, source_context, utterances):
        """Return consecutive topic segments for a Parliament source video."""
        return safe_json_parse(self._complete(
            build_segment_parliament_content_prompt(source_context, utterances)
        ))

    def select_chinese_australia_topic(self, source_context, segments):
        """Select a Chinese-Australian daily-life topic from content segments."""
        return safe_json_parse(self._complete(
            build_select_chinese_australia_topic_prompt(source_context, segments)
        ))

    def plan_parliament_commentary(self, selected_topic, source_context, utterances, advertisement=None):
        """Plan alternating Chinese narration and retained English dialogue."""
        return safe_json_parse(self._complete(
            build_plan_parliament_commentary_prompt(
                selected_topic, source_context, utterances, advertisement
            )
        ))

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

    def translate_subtitles(self, subtitles):
        """Translate subtitle text while preserving the caller's ordering."""
        prompt = """Translate each English subtitle into concise, natural Simplified Chinese.
Keep all person names, place names (including countries, states, cities, and
suburbs), and company names exactly as written in the source. Do not translate
or transliterate these names, or add Chinese names in parentheses. Translate
the surrounding text normally. Apply this rule to both translations and subtitle.
The source is Australian news. Unless the source explicitly identifies another
country or currency, interpret `dollar`/`dollars` as Australian dollars and
translate it as `澳元`, not `美元`. Preserve any explicitly stated currency,
country, measurement, quantity, and unit exactly in meaning: never convert,
replace, or guess a different currency or unit. Translate `USD` or `US$` as
`美元` only when they are explicitly present.
Also create one concise, audience-facing Chinese news-style subtitle (no more
than 16 characters) that summarizes the complete content. It must make clear
that this is Australian news (prefer an `澳洲` lead-in) and foreground the most
practical impact on ordinary Australian residents, such as their housing,
costs, income, benefits, rights, or daily life. Do not invent an impact that
the source does not support. Return only a JSON object with `subtitle`
and `translations`. Every item in `translations` must contain the original
`index` and its Chinese `text`. Preserve every index exactly once. Do not include
timestamps, speaker labels, explanations, or Markdown.

Input:
""" + json.dumps(subtitles, ensure_ascii=False)
        result = safe_json_parse(self._complete(prompt))
        if not isinstance(result, dict) or not isinstance(result.get("translations"), list):
            raise ValueError("字幕翻译结果必须包含 subtitle 和 translations")
        return result

    def rewrite_australian_news_subtitle(self, source_title: str) -> str:
        """Turn a supplied YouTube title into a short reader-facing Chinese subtitle."""
        prompt = """Rewrite this YouTube news title as one concise Simplified Chinese
subtitle for an Australian local-news short video. Use no more than 16 Chinese
characters. Make the Australian context explicit (prefer an `澳洲` lead-in) and
foreground the most practical impact on ordinary Australian residents, such as
housing, costs, income, benefits, rights, or daily life. Do not invent facts,
impact, currency, quantities, or locations not supported by the source title.
Return only JSON: {"subtitle":"..."}.

Source title:
""" + source_title
        result = safe_json_parse(self._complete(prompt))
        subtitle = result.get("subtitle") if isinstance(result, dict) else None
        if not isinstance(subtitle, str) or not subtitle.strip():
            raise ValueError("前端标题改写结果缺少 subtitle")
        return subtitle.strip()

    def plan_translation_advertisement(self, subtitles, advertisement):
        """Choose one safe insertion point for an independent ad record."""
        result = safe_json_parse(self._complete(
            build_plan_translation_advertisement_prompt(subtitles, advertisement)
        ))
        if not isinstance(result, dict):
            raise ValueError("广告规划结果必须是 JSON 对象")
        return result
    def merge_english_subtitles_before_diarization(self, subtitles):
        """Select complete sentence groups before speaker diarization."""
        prompt = """Group English subtitle fragments into individual grammatical sentences.
Speaker identity is intentionally unavailable and must not be inferred.
Return only JSON: {"groups": [[source_index, ...], ...]}.

Rules:
- Use every source index exactly once, in its original order.
- Each group must contain adjacent source indices.
- Each group must form one grammatical sentence, not a paragraph or a complete speech.
- Join adjacent fragments only to complete that sentence. Once the sentence is grammatically complete, start a new group for the next sentence.
- Determine sentence boundaries from English grammar even when the input has no punctuation. Never merge separate sentences merely because they share a topic, argument, or speaker.
- Keep an incomplete fragment alone if joining it to the next fragment would combine separate sentences or be grammatically unnatural.
- Do not alter, repeat, translate, label speakers, or explain any text.
- Do not use Markdown.

Input:
""" + json.dumps({"subtitles": subtitles}, ensure_ascii=False, separators=(",", ":"))
        result = safe_json_parse(self._complete(prompt))
        if not isinstance(result, dict) or not isinstance(result.get("groups"), list):
            raise ValueError("英文短句整合结果必须包含 groups")
        return result["groups"]

    def translate_chinese_subtitles(self, subtitles):
        """Translate Chinese subtitle records into concise natural English."""
        prompt = """Translate each Simplified Chinese subtitle into concise, natural English.
Also create one concise English news-style subtitle (no more than 4 words and
no more than 28 characters)
that summarizes the complete content. Return only a JSON object with `subtitle`
and `translations`. Every item in `translations` must contain the original
`index` and its English `text`. Preserve every index exactly once. Do not include
timestamps, speaker labels, explanations, or Markdown.

Input:
""" + json.dumps(subtitles, ensure_ascii=False)
        result = safe_json_parse(self._complete(prompt))
        if not isinstance(result, dict) or not isinstance(result.get("translations"), list):
            raise ValueError("字幕翻译结果必须包含 subtitle 和 translations")
        return result

    def merge_chinese_subtitles_before_diarization(self, subtitles):
        """Select complete Chinese thought groups before speaker diarization."""
        prompt = """You are selecting natural Simplified Chinese sentence boundaries in news subtitles.
Speaker identity is intentionally unavailable and must not be inferred.
Return only JSON: {"groups": [[source_index, ...], ...]}.

Rules:
- Use every source index exactly once, in its original order.
- Each group must contain adjacent source indices.
- Combine fragments into a natural, complete Chinese thought when possible.
- Keep a fragment alone if combining would be unnatural.
- Do not alter, repeat, translate, label speakers, or explain any text.
- Do not use Markdown.

Input:
""" + json.dumps({"subtitles": subtitles}, ensure_ascii=False, separators=(",", ":"))
        result = safe_json_parse(self._complete(prompt))
        if not isinstance(result, dict) or not isinstance(result.get("groups"), list):
            raise ValueError("中文短句整合结果必须包含 groups")
        return result["groups"]

    def screen_news_titles(self, videos, topics):
        """Classify YouTube news titles against the selected editorial topics."""
        prompt = """You are selecting Australian news videos for a Chinese-language
audience according to their selected topics. Judge relevance from the title and channel only; do not invent
facts that are not stated.

Selected topics: """ + json.dumps(topics, ensure_ascii=False) + """

Return only JSON in this exact form:
{"results":[{"video_id":"...","relevant":true,"matched_topics":["..."],"reason":"简短中文理由"}]}

Rules:
- Return every supplied video_id exactly once.
- relevant is true only when the title is substantively connected to at least one
  selected topic. Housing, rental, landlord or welfare news has no automatic exemption.
  For example, if only 移民 is selected, Airbnb rental-rule changes are irrelevant
  unless the title explicitly connects them to immigration, visas or migration policy.
- Set relevant to false for any broad news roundup, bulletin, headlines package,
  news update, or multi-story compilation, even if its title mentions a selected
  topic. Examples include titles such as "news roundup", "top stories", "headlines",
  "news bulletin", "latest news", "news update", or Chinese equivalents such as
  "综合报道", "新闻汇总", "新闻简报", "新闻速览". Select videos focused on one
  identifiable story instead.
- matched_topics must use only values from Selected topics.
- If relevant is true, matched_topics must contain at least one selected topic.
- reason must be concise Simplified Chinese (maximum 30 characters).
- Do not use Markdown or add fields.

Videos:
""" + json.dumps(videos, ensure_ascii=False, separators=(",", ":"))
        result = safe_json_parse(self._complete(prompt))
        if not isinstance(result, dict) or not isinstance(result.get("results"), list):
            raise ValueError("新闻筛选结果必须包含 results")
        return result["results"]
