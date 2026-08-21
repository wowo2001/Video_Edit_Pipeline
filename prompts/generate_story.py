from prompts.brief import BRIEF
from prompts.summerize_story import SUMMARY_STORY_PROMPT

GENERATE_STORY_PROMPT = """{story_prompt}

剧情概要：
{brief}

字幕内容：
{subtitles}
"""


def build_generate_story_prompt(subtitles):
    return GENERATE_STORY_PROMPT.format(
        story_prompt=SUMMARY_STORY_PROMPT,
        brief=BRIEF,
        subtitles=subtitles,
    )
