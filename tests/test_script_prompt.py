import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from core.utils import write_json
from pipeline.subtitles import apply_timeline
from prompts.generate_script import build_generate_script_prompt
from prompts.script_input import build_script_input
from services.chatgpt import ChatGPT


class ScriptPromptTests(unittest.TestCase):
    def setUp(self):
        self.subtitles = '\n'.join(f'[{i}] [人物] 台词{i}' for i in range(6))
        self.story = {'总故事':'全局背景', '推荐解说场景':[2], '场景':[
            {'编号':1,'标题':'必要前情','事件':'起因','剧情':'建立人物处境','开始SRT':0,'结束SRT':2},
            {'编号':2,'标题':'关键选择','事件':'冲突','剧情':'人物作出选择','开始SRT':3,'结束SRT':5}]}
        self.result = {'hook':{'narrative':{'content':'原声之后的悬念'},'clip':[4,5]},
            'clips':[{'place':1,'narrative':{'content':'原声之前的必要背景'},'clip':[1,2]}]}

    def test_mixed_types_preserve_timeline_and_pure_narration_scene_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script, subtitles, story = (root/name for name in ('script.json', 'subtitles.json', 'story.json'))
            result = json.loads(json.dumps(self.result))
            result['clips'] = [
                {'place': 1, 'type': 'narration_only', 'purpose': '交代背景',
                 'narrative': {'content': '转述或分析'}, 'clip': [0, 1]},
                {'place': 2, 'type': 'with_dialogue', 'purpose': '人物表态',
                 'narrative': {'content': '眼前局面'}, 'clip': [3, 4]}]
            write_json(result, script)
            write_json(self.story, story)
            write_json({'utterances': [{'text': str(i), 'start_time': i*1000, 'end_time': i*1000+900}
                                       for i in range(6)]}, subtitles)
            apply_timeline(script, subtitles, story)
            result = json.loads(script.read_text(encoding='utf-8'))
            self.assertEqual(result['clips'][0]['visual_bounds'], {'start': 0, 'end': 2900})
            self.assertEqual(result['clips'][1]['clip'][0]['start'], 3000)
            self.assertEqual(result['clips'][0]['type'], 'narration_only')
            self.assertNotIn('visual_bounds', result['clips'][1])

    def test_all_scenes_and_original_global_subtitle_ids_are_kept(self):
        data = build_script_input(self.subtitles,self.story)
        self.assertEqual([s['编号'] for s in data['场景']],[1,2])
        self.assertEqual(data['推荐解说场景'],[2])
        self.assertEqual(data['场景'][1]['字幕'],[[i,f'[人物] 台词{i}'] for i in (3,4,5)])
        self.assertEqual(data['场景'][0]['字幕范围'],[0,2])
        self.assertNotIn('未归属字幕',data)

    def test_multiline_cue_keeps_one_global_id(self):
        data = build_script_input(self.subtitles+'\n[5] 第二行',self.story)
        self.assertEqual(data['场景'][1]['字幕'][-1],[5,'[人物] 台词5\n第二行'])

    def test_service_does_not_read_or_add_sibling_timing(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            subs,story,script=root/'subtitles_stripped.srt',root/'story.json',root/'script.json'
            subs.write_text(self.subtitles,encoding='utf-8')
            write_json(self.story,story)
            (root/'subtitles.json').write_text('This file must not be read by script planning.',encoding='utf-8')
            ai=ChatGPT.__new__(ChatGPT)
            ai._complete=Mock(return_value=json.dumps(self.result,ensure_ascii=False))
            ai.generate_script(subs,script,story)
            prompt=ai._complete.call_args.args[0]
            data=json.loads(prompt.split('<剧情输入>\n',1)[1].rsplit('\n</剧情输入>',1)[0])
            self.assertEqual(data['场景'][1]['字幕'][1],[4,'[人物] 台词4'])
            self.assertTrue(all(len(row)==2 for scene in data['场景'] for row in scene['字幕']))
            self.assertEqual(json.loads(script.read_text(encoding='utf-8')),self.result)

    def test_subtitles_missing_from_scene_ranges_are_not_silently_dropped(self):
        data = build_script_input(self.subtitles+'\n[6] 未分场的背景',self.story)
        self.assertEqual(data['未归属字幕'],[[6,'未分场的背景']])

    def test_overlapping_scene_ranges_are_rejected_before_calling_model(self):
        self.story['场景'][1]['开始SRT']=2
        with self.assertRaisesRegex(ValueError,'重叠'):
            build_script_input(self.subtitles,self.story)

    def test_prompt_contains_one_structured_input_without_expanding_format_braces(self):
        prompt = build_generate_script_prompt(self.subtitles,self.story)
        data = json.loads(prompt.split('<剧情输入>\n',1)[1].rsplit('\n</剧情输入>',1)[0])
        self.assertEqual(data,build_script_input(self.subtitles,self.story))
        self.assertIn('"narrative":{"content":',prompt)

    def test_service_keeps_exact_output_shape_and_calls_model_once_for_both_providers(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            subs,story,script=root/'subtitles.srt',root/'story.json',root/'script.json'
            subs.write_text(self.subtitles,encoding='utf-8')
            write_json(self.story,story)
            for provider in ('ali','openai'):
                with self.subTest(provider=provider):
                    ai=ChatGPT.__new__(ChatGPT)
                    ai.provider=provider
                    ai._complete=Mock(return_value=json.dumps(self.result,ensure_ascii=False))
                    ai.generate_script(subs,script,story)
                    self.assertEqual(json.loads(script.read_text(encoding='utf-8')),self.result)
                    ai._complete.assert_called_once()
            utterances=root/'subtitles.json'
            write_json({'utterances':[{'text':f'原句{i}','start_time':i*1000,'end_time':i*1000+900}
                                     for i in range(6)]},utterances)
            apply_timeline(script,utterances)
            expanded=json.loads(script.read_text(encoding='utf-8'))
            self.assertEqual(expanded['hook']['clip'][0]['index'],4)
            self.assertEqual(expanded['hook']['clip'][0]['start'],4000)
            self.assertEqual(expanded['clips'][0]['narrative'],self.result['clips'][0]['narrative'])


if __name__=='__main__':
    unittest.main()
