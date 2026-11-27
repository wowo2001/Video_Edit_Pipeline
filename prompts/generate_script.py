import json

from prompts.editing_rules import EDITING_RULES
from prompts.script_input import INPUT_RULES, build_script_input
from prompts.script_schema import OUTPUT_SCHEMA

GENERATE_SCRIPT_PROMPT = """{editing_rules}

{input_rules}

{output_schema}

<剧情输入>
{story_input}
</剧情输入>
"""


def build_generate_script_prompt(subtitles, story):
    return GENERATE_SCRIPT_PROMPT.format(
        editing_rules=EDITING_RULES, input_rules=INPUT_RULES, output_schema=OUTPUT_SCHEMA,
        story_input=json.dumps(build_script_input(subtitles, story), ensure_ascii=False, separators=(",", ":")),
    )
