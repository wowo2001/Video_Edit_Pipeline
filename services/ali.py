from openai import OpenAI
import re
from config import ALI_API_KEY, OPENAI_API_KEY
from core.utils import safe_json_parse, srt_to_seconds
from prompts.editing_rules import EDITING_RULES
from prompts.fix_subtitles import FIX_SUBTITLE_PROMPT
from prompts.get_title import GET_TITLE_PROMPT
from prompts.review_script import REVIEW_SCRIPT_PROMPT
from prompts.script_schema import OUTPUT_SCHEMA
from prompts.summerize_story import SUMMARY_STORY_PROMPT
from prompts.task_rules import TASK_RULES
from prompts.brief import BRIEF
from prompts.recognise_speaker import RECOGNISE_SPEAKER_PROMPT
from prompts.select_conversation import SELECT_CONVERSATION
from prompts.story_draft import STORY_DRAFT
from prompts.scene_draft import SCENE_DRAFT
import json
class Ali:
    def __init__(self):
        self.client = OpenAI(api_key=ALI_API_KEY,
                            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                            timeout=600.0,
                            max_retries=2)
    def generate_script(self, subtitles_path, script_path, story_path):
        subtitles = subtitles_path.read_text(encoding="utf-8")
        with open(story_path, "r", encoding="utf-8") as f:
            story_json = json.load(f)
        recommend_ids = set(
            story_json.get("推荐解说场景", [])
        )
        stories = []
        for scene in story_json.get("场景", []):

            if scene["编号"] in recommend_ids:
                stories.append(
                    scene["剧情"]
                )
        story = "\n".join(stories)
        prompt = f"{TASK_RULES}\n\n{EDITING_RULES}\n\n{OUTPUT_SCHEMA}\n\n字幕内容：{subtitles}\n\n故事内容：{story}"
        response = self.client.chat.completions.create(
            model="qwen3.7-max",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        script = response.choices[0].message.content
        try:
            result = safe_json_parse(script)

        except Exception:
            print("\n❌ GPT 输出 JSON 解析失败：\n")
            print(script)
            raise
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
        print(f"\n✅ GPT 脚本已保存: {script_path}")
    
    def fix_subtitles(self, subtitles_path, fixed_subtitles_path):
        subtitles = subtitles_path.read_text(encoding="utf-8")
        prompt = f"{FIX_SUBTITLE_PROMPT}\n\n{subtitles}"
        response = self.client.chat.completions.create(
            model="qwen3.7-max",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )

        result = json.loads(response.choices[0].message.content)

        fixed_subtitles = result["subtitle"]
        popup_comments = result["popup_comments"]
        for item in popup_comments:
            item["start_time"] = srt_to_seconds(item["start_time"])
        
        print(popup_comments)
        title = result["title"]
        fixed_subtitles = re.sub(r"^```srt\s*", "", fixed_subtitles)
        fixed_subtitles = re.sub(r"^```\s*", "", fixed_subtitles)
        fixed_subtitles = re.sub(r"\s*```$", "", fixed_subtitles)
        with open(fixed_subtitles_path, "w", encoding="utf-8") as f:
            f.write(fixed_subtitles)
        print(f"\n✅ 修正后的字幕已保存: {fixed_subtitles_path}")
        return popup_comments, title
    
    def recognise_speaker(self, subtitles_path, mapping_path):
        subtitles = subtitles_path.read_text(encoding="utf-8")
        prompt = f"""
            {RECOGNISE_SPEAKER_PROMPT}

            剧情概要：
            {BRIEF}

            字幕内容：
            {subtitles}
        """
        response = self.client.chat.completions.create(
            model="qwen3.7-max",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        content = response.choices[0].message.content.strip()
        mapping = json.loads(content)
        with open(mapping_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)

        print(f"\n✅ speaker映射已保存: {mapping_path}")


    def get_subtitle(self, subtitles_path):
        subtitles = subtitles_path.read_text(encoding="utf-8")
        prompt = f"{GET_TITLE_PROMPT}\n\n{subtitles}"
        response = self.client.chat.completions.create(
            model="qwen3.7-max",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        result = response.choices[0].message.content.strip()
        result = re.sub(r'["“”\n\r]', '', result)
        return result

    def review_script(self, script_path):
    # 读取原始脚本 JSON
        with open(script_path, "r", encoding="utf-8") as f:
            script_json = json.load(f)

        prompt = f"""{REVIEW_SCRIPT_PROMPT}

脚本内容：
{json.dumps(script_json, ensure_ascii=False, indent=2)}
"""

        response = self.client.chat.completions.create(
        model="qwen3.7-plus",
        messages=[
            {"role": "user", "content": prompt}
        ]
    )

        content = response.choices[0].message.content

        try:
            result = safe_json_parse(content)
        except Exception:
            print("\n❌ GPT 输出 JSON 解析失败：\n")
            print(content)
            raise

    # 覆盖保存到原路径
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"\n✅ GPT 审核后的脚本已保存: {script_path}")
    
    def generate_story(self, subtitles_path, story_path):
        subtitles = subtitles_path.read_text(encoding="utf-8")
        prompt = f"""
            {SUMMARY_STORY_PROMPT}

            剧情概要：
            {BRIEF}

            字幕内容：
            {subtitles}
        """
        response = self.client.chat.completions.create(
            model="qwen3.7-max",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        content = response.choices[0].message.content.strip()
        story = json.loads(content)
        with open(story_path, "w", encoding="utf-8") as f:
            json.dump(story, f, ensure_ascii=False, indent=2)

        print(f"\n✅ 故事已保存: {story_path}")

    
    def generate_script_temp(self, script_path, story_path):


        # 读取 search_story 返回的故事
        with open(story_path, "r", encoding="utf-8") as f:
            stories = json.load(f)

        story_text = "\n\n".join(
    [
        f"""
        视频资源ID:{i}
        该视频资源包含的剧情：:
        {item['story']}

        对应视频资源:
        {item['url']}
        """
        for i, item in enumerate(stories)
    ]
    )

        prompt = f"""

        {STORY_DRAFT}
        {story_text}
        """

        response = self.client.chat.completions.create(
        model="qwen3.7-max",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

        script = response.choices[0].message.content

        try:
            result = safe_json_parse(script)

        except Exception:
            print("\n❌ GPT 输出 JSON 解析失败：\n")
            print(script)
            raise


        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2
            )

        print(f"\n✅ GPT 解说脚本已保存: {script_path}")
    
    def generate_scene(self, scene_path, story_path):


        # 读取 search_story 返回的故事
        with open(story_path, "r", encoding="utf-8") as f:
            stories = json.load(f)

        story_text = "\n\n".join(
    [
        f"""
        视频资源ID:{i}
        该视频资源包含的剧情：:
        {item['story']}

        对应视频资源:
        {item['url']}
        """
        for i, item in enumerate(stories)
    ]
    )

        prompt = f"""

        {SCENE_DRAFT}
        {story_text}
        """

        response = self.client.chat.completions.create(
        model="qwen3.7-max",
        messages=[
            {
                "role": "user",
                "content": prompt
            }
        ]
    )

        script = response.choices[0].message.content

        try:
            result = safe_json_parse(script)

        except Exception:
            print("\n❌ GPT 输出 JSON 解析失败：\n")
            print(script)
            raise


        with open(scene_path, "w", encoding="utf-8") as f:
            json.dump(
            result,
            f,
            ensure_ascii=False,
            indent=2
            )

        print(f"\n✅ 场景拆分结果已保存: {scene_path}")

    def generate_script_final(self, script_path):

        with open(script_path, "r", encoding="utf-8") as f:
            script = json.load(f)

        for item in script:

        # 只保留 AI 需要的信息
            llm_input = {
            "place": item["place"],
            "narrative": item["narrative"],
            "clip": {
                "search_content": item["clip"]["search_content"],
                "candidates": item["clip"]["candidates"],
            },
        }

            prompt = f"""
            {SELECT_CONVERSATION}
            {json.dumps(llm_input, ensure_ascii=False, indent=2)}
            """

            response = self.client.chat.completions.create(
                model="qwen3.7-max",
                messages=[
                {
                    "role": "user",
                    "content": prompt
                }
            ]
            )

            result = safe_json_parse(
                response.choices[0].message.content
            )

        # 更新解说
            item["narrative"] = result["narrative"]

        # 保存选择结果
            item["clip"]["candidate_id"] = result["candidate_id"]
            item["clip"]["keep_range"] = result["keep_range"]

        # 删除候选，避免 script 过大
            del item["clip"]["candidates"]

        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(
            script,
            f,
            ensure_ascii=False,
            indent=2
            )

        print(f"\n✅ 最终脚本已保存: {script_path}")
