OUTPUT_SCHEMA = """只输出一个合法 JSON 对象，不加 Markdown、注释、解释或额外字段：
{"hook":{"narrative":{"content":"开场原声之后的解说"},"clip":[12,13]},"clips":[{"place":1,"type":"narration_only","purpose":"交代必要前情或承接上一段原声","narrative":{"content":"配合画面的转述、衔接或分析"},"clip":[30,31]},{"place":2,"type":"with_dialogue","purpose":"铺垫人物即将作出的关键选择","narrative":{"content":"本段原声之前的具体局面"},"clip":[45,46,47]}]}

- hook 和每个 clips 元素各是一段剪辑，clip 是全局字幕索引数组；示例数字只说明格式，实际必须使用输入中存在的整数索引。
- 每个 clip 数组非空、索引连续递增，且全部属于同一个输入场景，不能跨场景或重新编号。
- 正文 clips 按剧情时间升序排列，前段最后一个索引小于后段第一个，不能重复或倒放；place 从 1 连续递增。只有 hook 可以提前选用后段场景。
- 正文每段必须有 type（只能为 narration_only 或 with_dialogue）和非空 purpose（简短说明本段作用，不参与配音）。hook 的结构不变。
- with_dialogue 的 clip 指定保留原声；narration_only 的 clip 只定位承载旁白的画面起点和相关事件，不会追加原声，实际连续画面长度由 TTS 决定。两种类型都沿用全局 clip 索引，不另设字幕字段。
- narrative.content 是非空、可直接朗读的解说文本，不写制作指令；不要增加 scene_id、策略、分析、时间戳或其他字段。
"""
