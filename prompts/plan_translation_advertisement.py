import json


def build_plan_translation_advertisement_prompt(subtitles, advertisement):
    return f'''你是一名短视频商业植入编辑。视频是一条新闻的中文配音译制版；给出的字幕是按播放顺序排列的中文译文。

广告资料（只能使用其中明确提供的信息，不得编造功效、价格、优惠、用户评价或事实）：
<advertisement>
{advertisement}
</advertisement>

要求：
1. 只规划一次独立广告口播，绝不能改写、删除或混入任何新闻译文。
2. 在整条视频前半段选择一个自然的译文断点之后插入；insert_after_index 必须是下面提供的 index 之一。
3. 广告文案使用中文，适合 8 到 12 秒口播，简洁自然。可以有必要的过渡和回到新闻的衔接，但不得新增广告资料以外的产品事实。
4. 只输出 JSON，不要 Markdown：
{{"insert_after_index": 12, "narration": "..."}}

字幕：
{json.dumps(subtitles, ensure_ascii=False)}
'''
