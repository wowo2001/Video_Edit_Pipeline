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

    def select_scene(
    self,
        candidate_path,
        theme,
        output_path
    ):

        with open(
            candidate_path,
            "r",
            encoding="utf-8"
        ) as f:
            scenes = json.load(f)


        candidates = []

        for scene in scenes:
            candidates.append(
                {
                    "scene_id": scene["scene_id"],
                    "title": scene["title"],
                    "event": scene["event"],
                    "summary": scene["summary"],
                }
            )


        prompt = f"""
    你是一个视频选题策划。

    主题：
    {theme}

    候选场景：

    {json.dumps(
        candidates,
        ensure_ascii=False,
        indent=2
    )}

    请筛选真正符合主题的场景。

    要求：
    1. 只保留相关场景
    2. 按相关程度排序

    只输出JSON：

    [
    {{
        "scene_id": 1
    }}
    ]
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

        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as f:
            json.dump(
                result,
                f,
                ensure_ascii=False,
                indent=2
            )



    def select_scene_clip(
        self,
        theme,
        scene
    ):

        prompt = f"""
你的任务：
从一个剧情场景中，选择最有价值的原剧对白，作为后续视频剪辑素材。


========================
【主题】
========================

{theme}


========================
【当前场景】
========================

标题：
{scene["title"]}

剧情简介：
{scene["summary"]}


========================
【原始对白】
========================

{scene["subtitles_plain_text"]}


========================
【字幕编号规则】
========================

- 每句对白前面的 [i] 是唯一字幕编号
- 返回的 clip 必须使用这些 index
- 不允许修改 index
- 不允许返回对白文本


========================
【选择规则】
========================

1. 只选择当前 scene 内的对白。

2. 选择能够体现当前剧情发展的关键对白：
   - 人物冲突
   - 重要信息
   - 情绪爆发
   - 剧情转折

3. 删除：
   - 寒暄
   - 重复对白
   - 无剧情推进内容


========================
【顺序约束】
========================

1. clip 内 index 必须按照剧情时间递增排列。

2. 不允许倒序。

3. 可以跳过无关对白。

4. 所选对白必须属于同一个剧情事件。


========================
【输出格式】
========================

只输出 JSON：

{{
    "scene_id": {scene["scene_id"]},
    "clip": [1,2,3]
}}

"""


        response = self.client.chat.completions.create(
            model="qwen3.7-max",
            messages=[
                {
                    "role":"user",
                    "content":prompt
                }
            ]
        )


        return safe_json_parse(
            response.choices[0].message.content
        )
    
    def generate_scene_narration(
        self,
        theme,
        scene_path,
        output_path
    ):

        with open(
            scene_path,
            "r",
            encoding="utf-8"
        ) as f:
            scenes = json.load(f)


        scene_list = []

        for scene in scenes:

            scene_list.append(
                {
                    "scene_id": scene["scene_id"],
                    "title": scene["title"],
                    "summary": scene["summary"]
                }
            )


        prompt = f"""
        你是短视频剧解说作者。

        根据下面的剧情场景，为每个scene生成旁白。

        这个短视频的主题是： {theme}
        要求：

        结合解说主题，把场景之间自然流畅的串联起来


        输入：

        {json.dumps(
            scene_list,
            ensure_ascii=False,
            indent=2
        )}


        只输出JSON：

        [
        {{
        "scene_id":1,
        "narration":"..."
        }}
        ]

        """


        response = self.client.chat.completions.create(
            model="qwen3.7-max",
            messages=[
                {
                    "role":"user",
                    "content":prompt
                }
            ]
        )


        result = safe_json_parse(
            response.choices[0].message.content
        )


        with open(
            output_path,
            "w",
        encoding="utf-8"
        ) as f:
            json.dump(
                result,
                f,
                ensure_ascii=False,
                indent=2
            )


        return result

    def split_scene_segment(
        self,
        theme,
        scene
    ):

        prompt = f"""

        你的任务：
        把一个剧情场景拆解成多个适合短视频解说的叙事片段。

        每个片段必须由：

        【解说旁白】+【原剧对白】组成。

        ========================
        【主题】
        ========================

        {theme}


        ========================
        【当前场景】
        ========================

        标题：
        {scene["title"]}

        剧情简介：
        {scene["summary"]}


        ========================
        【原始对白】
        ========================

        {scene["subtitles_plain_text"]}


========================
【字幕编号规则】
========================

- 每句对白前面的 [i] 是唯一字幕编号。
- subtitle_ids 必须引用已有编号。
- 不允许修改编号。
- 不返回对白文本。


========================
【segment划分规则】
========================

根据剧情发展拆分segment。

每个segment表达一个独立的小剧情节点，例如：

- 一段完整的对话

只保留与主题相关segment。

========================
【对白选择规则】
========================

原剧对白不是用来完整讲述剧情。选取的对白必须是连续的。

对白只用于：
- 展示人物冲突
- 强化关键情绪
- 保留代表性台词

每个segment选择少量关键对白。



        ========================
        【输出格式】
        ========================

        只输出 JSON：

{{
  "segments":[
    {{
      "segment_id":1,
      "purpose":"交代晁盖被官府追捕",
      "narration":"...",
      "subtitle_ids":[1,2,3]
    }},
    {{
      "segment_id":2,
      "purpose":"晁盖投奔梁山",
      "narration":"...",
      "subtitle_ids":[20,21]
    }}
  ]
}}

    """


        response = self.client.chat.completions.create(
            model="qwen3.7-max",
            messages=[
                {
                    "role":"user",
                    "content":prompt
                }
            ]
        )


        return safe_json_parse(
            response.choices[0].message.content
        )
    
    def refine_narration(
        self,
        scene_path
    ):

        with open(
            scene_path,
            "r",
            encoding="utf-8"
        ) as f:
            scenes = json.load(f)


        # 给AI的数据
        ai_input = []

        for scene in scenes:

            ai_scene = {
                "scene_id": scene["scene_id"],
                "title": scene["title"],
                "segments": []
            }

            for segment in scene["segments"]:

                ai_scene["segments"].append(
                    {
                        "segment_id": segment["segment_id"],
                        "purpose": segment["purpose"],
                        "narration": segment["narration"]
                    }
                )

            ai_input.append(
                ai_scene
            )


        prompt = f"""
你是一名专业影视解说编剧。

下面是一条已经规划好的短视频。

每个segment已经确定：

- 剧情顺序
- purpose
- narration

你的任务不是重新写剧情。

而是把整条视频的解说词润色得更加连贯。


========================
要求
========================

1. 保持所有segment顺序不变。

2. 不新增剧情。

3. 不删除剧情。

4. 不改变purpose。

5. 每段仍然对应原来的segment。

6. 可以修改 narration。

7. 优化目标：

- 上下段衔接自然
- 避免重复介绍人物
- 避免重复背景
- 增强故事连续感
- 更符合短视频解说节奏

8. narration长度不要变化太大。

9. 返回scene数量、segment数量必须完全一致。


========================
当前视频
========================

{json.dumps(
    ai_input,
    ensure_ascii=False,
    indent=2
)}


========================
输出
========================

只输出JSON：

[
  {{
    "scene_id":5,
    "segments":[
      {{
        "segment_id":1,
        "narration":"..."
      }},
      {{
        "segment_id":2,
        "narration":"..."
      }}
    ]
  }}
]
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


        refined = safe_json_parse(
            response.choices[0].message.content
        )

        # 建立索引
        refine_map = {
            scene["scene_id"]: {
                seg["segment_id"]: seg["narration"]
                for seg in scene["segments"]
            }
            for scene in refined
        }


        # 回填
        for scene in scenes:

            scene_map = refine_map.get(
                scene["scene_id"],
                {}
            )

            for segment in scene["segments"]:

                narration = scene_map.get(
                    segment["segment_id"]
                )

                if narration:

                    segment["narration"] = narration


        with open(
            scene_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                scenes,
                f,
                ensure_ascii=False,
                indent=2
            )


        return scenes
    

    def generate_hook(
    self,
    theme,
    scene_path,
    output_path
    ):

        with open(
            scene_path,
            "r",
            encoding="utf-8"
        ) as f:
            scenes = json.load(f)


        ai_input = []


        for scene in scenes:

            segments = []

            for seg in scene["segments"]:

                segments.append(
                    {
                        "segment_id": seg["segment_id"],
                        "purpose": seg["purpose"]
                    }
                )


            ai_input.append(
                {
                    "scene_id": scene["scene_id"],
                    "title": scene["title"],
                    "segments": segments
                }
            )


        prompt = f"""
你是一名短视频影视解说编剧。

你的任务：
从已有剧情segment中选择最适合作为视频开头hook的部分。

主题：
{theme}


选择规则：

1. hook必须和主题高度相关。

2. 优先选择：
- 最大冲突
- 最大反转
- 最大情绪爆点
- 最能引起观看兴趣的剧情

3. hook只是吸引观众继续观看。
4. 你选了hook之后还需要为hook配上解说,解说需要吸引观众继续观看



====================

输入剧情：

{json.dumps(
    ai_input,
    ensure_ascii=False,
    indent=2
)}


====================

输出JSON：

  {{
    "scene_id":8,
    "segment_id":2,
    "hook_narration":"..."
  }}

只输出JSON。
"""


        response = self.client.chat.completions.create(
            model="qwen3.7-max",
            messages=[
                {
                    "role":"user",
                    "content":prompt
                }
            ]
        )

        result = safe_json_parse(
            response.choices[0].message.content
        )
        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as f:

            json.dump(
                result,
                f,
                ensure_ascii=False,
                indent=2
            )
