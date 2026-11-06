import unittest
import json
import tempfile
from pathlib import Path

from experiments.news_commentary.article_sentences import split_article_sentences
from experiments.news_commentary.pipeline import validate_plan, build_source_catalog
from experiments.news_commentary.prompt import build_prompt


class ArticleSentenceTests(unittest.TestCase):
    def test_boundaries_and_exact_source_offsets(self):
        text = 'Heading\n\nDr. Smith paid $3.5 million. It rose 2.4%. “Why?”\n\n第一句。第二句！最后一句'
        rows = split_article_sentences(text)
        self.assertEqual([r['text'] for r in rows], [
            'Heading', 'Dr. Smith paid $3.5 million.', 'It rose 2.4%.',
            '“Why?”', '第一句。', '第二句！', '最后一句'])
        self.assertEqual([r['index'] for r in rows], list(range(7)))
        for row in rows:
            self.assertEqual(row['text'], text[row['start_offset']:row['end_offset']])
        self.assertEqual(''.join(text.split()), ''.join(''.join(r['text'].split()) for r in rows))

    def test_initials_and_abbreviations(self):
        rows = split_article_sentences('J. Smith met Mr. Jones in the U.S. market. Prices fell.')
        self.assertEqual(len(rows), 2)

    def test_article_catalog_needs_no_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_dir = root / 'sources' / 'source_01'
            source_dir.mkdir(parents=True)
            (source_dir / 'article.json').write_text(json.dumps({
                'content': 'First fact. Second fact. Third fact.', 'publisher': 'AFR'}))
            catalog = build_source_catalog({'sources': [dict(source_type='article', url='example')]}, root)
            self.assertEqual(len(catalog[0]['article_sentences']), 3)
            self.assertNotIn('paragraphs', catalog[0])
            payload = json.loads(build_prompt(catalog).split('输入：\n', 1)[1])
            self.assertNotIn('sections', payload['sources'][0])
            self.assertEqual(payload['sources'][0]['article_sentences'][1]['text'], 'Second fact.')

    def test_video_catalog_and_prompt_need_no_sections(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source_dir = root / 'sources' / 'source_01'
            source_dir.mkdir(parents=True)
            (source_dir / 'media.json').write_text(json.dumps({'main': {'source_context': {'channel': 'ABC'}}}))
            row = dict(text='Hello', start_time=0, end_time=1000,
                       attribute=dict(speaker='SPEAKER_00', speaker_name='Reporter'))
            (source_dir / 'subtitles.json').write_text(json.dumps({'utterances': [row]}))
            catalog = build_source_catalog({'sources': [dict(source_type='video', url='example')]}, root)
            self.assertNotIn('paragraphs', catalog[0])
            payload = json.loads(build_prompt(catalog).split('输入：\n', 1)[1])
            source = payload['sources'][0]
            self.assertNotIn('sections', source)
            self.assertEqual(source['utterances'][0]['end_time'], 1000)
            self.assertEqual(source['utterances'][0]['speaker'], 'SPEAKER_00')

    def test_single_sentence_quote_and_evidence(self):
        source = dict(source_id='source_01', source_type='article', url='example', context={},
                      article_sentences=split_article_sentences('First. Second. Third.'))
        plan = dict(title='Test', segments=[dict(source_id='source_01', type='with_dialogue',
            sentence_indices=[1, 1], narration_parts=[dict(kind='paraphrase', text='转述',
                evidence=[dict(source_id='source_01', sentence_indices=[0, 0])])])])
        segment = validate_plan(plan, [source])['segments'][0]
        self.assertEqual(segment['original_text'], 'Second.')
        self.assertEqual(segment['sentence_indices'], [1])
        self.assertEqual(segment['narration_parts'][0]['evidence'][0]['sentence_indices'], [0])
        prompt = build_prompt([source])
        self.assertIn('article_sentences', prompt)
        self.assertNotIn('paragraph_indices', prompt)


if __name__ == '__main__':
    unittest.main()
