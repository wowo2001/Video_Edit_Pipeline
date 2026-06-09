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
        self.client = OpenAI(api_key=ALI_API_KEY,
                             base_url="https://dashscope.aliyuncs.com/compatible-mode/v1")
    def generate_script(self, subtitles_path, script_path):
        subtitles = subtitles_path.read_text(encoding="utf-8")
        prompt = f"{TASK_RULES}\n\n{EDITING_RULES}\n\n{OUTPUT_SCHEMA}\n\n字幕内容：{subtitles}"
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
        fixed_subtitles = response.choices[0].message.content
        fixed_subtitles = re.sub(r"^```srt\s*", "", fixed_subtitles)
        fixed_subtitles = re.sub(r"^```\s*", "", fixed_subtitles)
        fixed_subtitles = re.sub(r"\s*```$", "", fixed_subtitles)
        with open(fixed_subtitles_path, "w", encoding="utf-8") as f:
            f.write(fixed_subtitles)
        print(f"\n✅ 修正后的字幕已保存: {fixed_subtitles_path}")
    
    def recognise_speaker(self, subtitles_path):
        subtitles = subtitles_path.read_text(encoding="utf-8")
        prompt = f"""
        根据剧情概要，将字幕文件中speaker标签替换为具体的角色名称，输出格式仍为srt字幕格式。
        角色名称需要根据剧情内容进行推断，不能直接使用speaker标签中的数字，而是要结合剧情内容分析每个角色的身份后进行替换。
        speaker信息是通过声音特征分析得出的，虽然不一定完全准确，但通常同一个speaker标签对应的台词是同一个角色说的。请根据这个线索结合剧情概要进行推断。
        剧情概要：{BRIEF}
        字幕内容：{subtitles}"""
        response = self.client.chat.completions.create(
            model="qwen3.7-max",
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        fixed_subtitles = response.choices[0].message.content
        fixed_subtitles = re.sub(r"^```srt\s*", "", fixed_subtitles)
        fixed_subtitles = re.sub(r"^```\s*", "", fixed_subtitles)
        fixed_subtitles = re.sub(r"\s*```$", "", fixed_subtitles)
        with open(subtitles_path, "w", encoding="utf-8") as f:
            f.write(fixed_subtitles)
        print(f"\n✅ 替换说话人后的字幕已保存: {subtitles_path}")


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