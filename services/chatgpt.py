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
class ChatGPT:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY)
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
            model="gpt-5.6-luna",
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
            model="gpt-5.6-luna",
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
            model="gpt-5.6-sol",
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
            model="gpt-5.6-luna",
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
            model="gpt-5.6-sol",
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
        model="gpt-5.6-luna",
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
        model="gpt-5.6-luna",
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
                model="gpt-5.6-luna",
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
        question,
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
                    "summary": scene["summary"],
                }
            )


        prompt = f"""
    问题：
    {question}
    主题：
    {theme}

    候选场景：

    {json.dumps(
        candidates,
        ensure_ascii=False,
        indent=2
    )}

你是一名短视频剧情解说总导演。

你的任务不是复述原剧剧情，而是根据【主题】重新组织已有场景，设计一篇围绕主题展开的短视频解说结构。

你需要站在整篇视频的宏观角度，对候选场景进行筛选和分配任务，让后续解说导演根据你的规划完成具体文案。

给到你的候选场景不一定全部都要用到，你可以把与解说有关的内容总到其他场景的背景交代中去，要注意节奏。

scene_id是故事发生的顺序，你最好按这个顺序安排避免逻辑漏洞

---

## 一、内部分析（不要输出分析过程）

在制定场景规划前，请先完成以下分析：

### 1. 提炼全文核心观点

最多提炼1个核心观点。

要求：
- 必须服务于解说主题。
- 不是剧情总结，而是观众最终应该理解的观点。
- 不要提炼人物经历、事件经过等表面信息。


### 2. 确定全文唯一高潮场景

只能选择1个场景作为全文高潮。

要求：
- 该场景必须是情绪、冲突或观点爆发最高的位置。
- 后续所有场景安排需要围绕这个高潮服务。


### 3. 分配每个场景唯一职责

每个场景只能承担一个职责：

- 剧情铺垫
- 转折
- 观点分析
- 情绪积累
- 高潮
- 结尾

禁止多个场景承担相同职责。


---

## 二、场景筛选原则

根据主题筛选候选场景。

要求：

1. 只保留真正能够支撑主题表达的场景。

以下情况直接删除：
- 与主题无关的日常剧情。
- 只是补充人物关系但无法推动主题的场景。
- 重复表达相同观点的场景。


2. 场景数量控制：

- 最多保留3个场景。
- 优先选择信息价值高、冲突强、能够产生观点的场景。


3. 你不是在讲完整电视剧。

需要主动舍弃大量剧情，只保留能够完成主题表达的关键节点。

---

## 三、整体结构设计要求

请根据选中的场景设计完整解说逻辑


注意：

每个场景导演不知道其他场景安排。

因此：

如果两个保留场景之间存在剧情跳跃，导致观众无法理解后续场景：

需要在后一个场景 task 中要求：

“用1-2句话快速补充前面发生的关键事件，再进入当前场景。”

补充内容只能包含：
- 理解当前场景必须的信息。

禁止：
- 展开讲完整剧情。


---

## 四、为每个场景制定导演任务

每个场景输出一个 task，写给后续解说导演。

task 必须说明：

### 1. 场景作用

说明该场景在全文中的职责：

例如：
- 建立人物困境。
- 推动人物关系变化。
- 引出核心观点。
- 制造情绪压力。
- 完成高潮爆发。
- 收束主题。

### 2. 解说重点

根据场景重要程度决定：

- 简单交代剧情。
- 重点分析人物选择。
- 深入输出主题观点。
- 留白，让观众自行理解。

### 3. 控制比例

请以总导演视角安排：

- 哪些场景只讲剧情，作为连接。
- 哪些场景承担主要观点输出。
- 哪些场景只负责情绪积累。
- 场景中哪些内容与【问题】和【核心观点】有直接因果关系需要展开讲，哪些不需要讲。


### 5. 最后一个场景特殊要求

最后一个场景：

除完成结尾总结外，可以要求解说：

- 提炼全文观点。
- 留下思考。
- 引导观众评论讨论。

---

## 五、输出格式

只输出最终规划结果：

```json
[
    {{
        "scene_id": 1,
        "task": "作为背景铺垫，简单交代武松进入体制即可，重点说明这是后续相信法律的起点，不要详细复述剧情和对白。"
    }},
]
    """


        response = self.client.chat.completions.create(
                model="gpt-5.6-luna",
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
            model="gpt-5.6-luna",
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
            model="gpt-5.6-luna",
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

        【解说主题】： {theme}

        【当前场景】：{scene["summary"]}

        【原始对白】：{scene["subtitles_plain_text"]}

        【解说要求】： {scene["task"]}

        你是一名短视频影视解说分镜导演。

你的任务是：
根据【当前场景】和【解说要求】，把当前场景拆分成适合短视频解说的若干 segment。

你的目标不是复述原剧情，而是完成当前场景在整篇解说中的任务。必须听从【解说要求】指挥，没有提到的一概舍弃

每个 segment 必须由：

【解说旁白】+【原剧台词】组成。

其中：

- 解说台词负责：
  - 按【解说要求完成解说任务】

- 原剧台词负责配合解说台词进行演出，选取原句台词不能重复解说的内容，而是顺着解说内容进行表演


========================
【核心执行原则】
========================

1. 当前场景已经由总导演规划好职责。

2. segment 数量服从场景任务，如果任务要求是简单交代、过连接等，最多选取2个segment就可以了。

3. 每个 segment 必须有明确作用。如果segment作用是观点输出，每个segment只输出1个观点。

4. 与解说主题和任务无关segment统统舍弃

========================
【字幕编号规则】
========================

- 每句对白前面的 [i] 是唯一字幕编号。
- subtitle_ids 必须引用已有编号。
- 返回的subtitle_ids必须是连续递增的
- 不允许修改编号。
- 不返回对白文本。

========================
【台词选择规则】
========================

解说任务会告诉你当前场景是哪一种
- 剧情铺垫
- 转折
- 观点分析
- 情绪积累
- 高潮
- 结尾

要根据场景任务来控制篇幅，重点应该是高潮部分

每个segment中只选出少量的连续的台词

选择台词【必须】满足：

- 来自序号连续递增字幕。
- 相邻两句台词之间编号的差值为1
- 保持原始顺序。
- 不修改字幕编号。


台词优先选择：

- 与主题相关人物的台词，最好选择同一个人物的连续台词配合解说进行表演
- 能够配合解说任务进行表演的台词。


========================
【segment衔接规则】
========================

如果当前 segment 与前后剧情存在跳跃：

可以在 narration 中：

用1-2句话补充理解当前剧情所必须的信息。

禁止：
- 展开介绍完整背景。
- 重复前面场景剧情。


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
            model="gpt-5.6-sol",
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
你是一名专业短视频解说文案编辑。

下面是一条已经完成导演规划的短视频。

每个segment已经确定：

- 剧情顺序
- purpose
- narration方向

你的任务：
只负责润色表达，不重新设计内容。


========================
严格限制
========================

1. 保持所有segment顺序不变。

2. scene数量、segment数量必须完全一致。

3. 不新增剧情。

4. 不删除剧情。

5. 不改变purpose。

6. 不改变原有核心观点。

7. 不新增原narration没有表达的新观点。


========================
优化目标
========================

优化每段narration：

- 更像真人短视频解说。
- 减少AI书面表达。
- 提高口语化程度。
- 删除重复表达。
- 避免重复介绍人物和背景。
- 增强segment之间衔接。
- 控制句子长度，提高听感。


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
            model="gpt-5.4-mini",
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
主题：
{theme}


你是一名短视频影视解说开场导演。

你的任务：
从完整视频segment中选择最适合作为开头hook的片段。

注意：
hook不是选择剧情最高潮，而是选择最适合第一次吸引观众的片段。

选择标准：

1. 与主题高度相关。

2. 优先选择：
- 能快速制造核心疑问。
- 能体现人物命运反转。
- 能展示强烈冲突。
- 能让观众想知道原因。

3. 避免选择：
- 需要大量背景才能理解的片段。
- 单纯介绍人物关系的片段。
- 普通剧情推进片段。

4. hook目标：
解说不是讲清剧情，而是在3秒内建立观看动力。


hook解说要求：

- 不复述segment完整剧情。
- 不解释所有背景。
- 不直接揭露最终答案。
- 结合主题制造悬念。



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
            model="gpt-5.6-luna",
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
