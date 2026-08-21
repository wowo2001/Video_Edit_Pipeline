from prompts.brief import BRIEF
from prompts.recognise_speaker import RECOGNISE_SPEAKER_PROMPT

RECOGNISE_SPEAKER_INPUT_PROMPT = """{speaker_prompt}

剧情概要：
{brief}

字幕内容：
{subtitles}
"""


def build_recognise_speaker_prompt(subtitles):
    return RECOGNISE_SPEAKER_INPUT_PROMPT.format(
        speaker_prompt=RECOGNISE_SPEAKER_PROMPT,
        brief=BRIEF,
        subtitles=subtitles,
    )
