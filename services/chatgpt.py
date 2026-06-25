from openai import OpenAI
import re
from config import ALI_API_KEY, OPENAI_API_KEY
from core.utils import safe_json_parse
from prompts.editing_rules import EDITING_RULES
from prompts.fix_subtitles import FIX_SUBTITLE_PROMPT
from prompts.get_title import GET_TITLE_PROMPT
from prompts.script_schema import OUTPUT_SCHEMA
from prompts.task_rules import TASK_RULES
from prompts.brief import BRIEF
import json
class ChatGPT:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)
    def generate_script(self, subtitles_path, script_path):
        subtitles = subtitles_path.read_text(encoding="utf-8")
        prompt = f"{TASK_RULES}\n\n{EDITING_RULES}\n\n{OUTPUT_SCHEMA}\n\n字幕内容：{subtitles}"
        response = self.client.chat.completions.create(
            model="gpt-5.5",
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
            model="gpt-5.5",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        fixed_subtitles = response.choices[0].message.content
        fixed_subtitles = re.sub(r"^```srt\s*", "", fixed_subtitles)
        fixed_subtitles = re.sub(r"^```\s*", "", fixed_subtitles)
        fixed_subtitles = re.sub(r"\s*```$", "", fixed_subtitles)
        with open(fixed_subtitles_path, "w", encoding="utf-8") as f:
            f.write(fixed_subtitles)
        print(f"\n✅ 修正后的字幕已保存: {fixed_subtitles_path}")
    
    def recognise_speaker(self, subtitles_path, mapping_path):
        subtitles = subtitles_path.read_text(encoding="utf-8")
        prompt = f"""
            你是电视剧字幕角色识别助手。

            任务：
            根据剧情内容 + speaker标签，推断每个 speaker 对应的角色名称。

            规则：
            1. 结合剧情内容判断角色身份
            2. speaker只是帮助你辅助判断，不是绝对的。比如SPEAKER_01可能是张三，也可能是李四
            3. 如果无法确定，用“未知角色_xx”
            4. 只输出 JSON，不要输出任何解释或字幕内容

            输出格式：
            {
                "SPEAKER_18": "包拯",
                "SPEAKER_02": "公孙策"
            }

            剧情概要：
            {BRIEF}

            字幕内容：
            {subtitles}
            """
        response = self.client.chat.completions.create(
            model="gpt-5.5",
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
            model="gpt-5.5",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        result = response.choices[0].message.content.strip()
        result = re.sub(r'["“”\n\r]', '', result)
        return result