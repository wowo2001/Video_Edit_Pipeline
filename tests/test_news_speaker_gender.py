import unittest
from experiments.news_commentary.speaker_gender import attach_genders, mapping_from_transcript

class GenderCacheTests(unittest.TestCase):
    def test_subtitle_gender_round_trip(self):
        transcript = {'utterances': [{'attribute': {'speaker': 'SPEAKER_06', 'speaker_name': 'James'}}, {'attribute': {'speaker': 'UNKNOWN'}}]}
        mapping = {'SPEAKER_06': {'gender': 'male', 'confidence': .99}}
        attach_genders(transcript, mapping)
        self.assertEqual(mapping_from_transcript(transcript), mapping)
        self.assertEqual(transcript['utterances'][0]['attribute']['speaker_name'], 'James')
        self.assertNotIn('gender', transcript['utterances'][1]['attribute'])
