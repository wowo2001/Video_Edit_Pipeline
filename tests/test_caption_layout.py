import re
import tempfile
import unittest
from pathlib import Path

from PIL import ImageFont
from core.captions import (DEFAULT_CAPTION_LAYOUT, caption_box_height, read_srt, validate_background_opacity,
                           validate_caption_layout, wrap_caption, write_caption_ass)
from core.ffmpeg import FONT_PATH


class CaptionLayoutTests(unittest.TestCase):
    def test_background_opacity_rejects_invalid_values(self):
        for value in (-.1, 1.1, float('nan'), True, '0.5'):
            with self.assertRaises(ValueError):
                validate_background_opacity(value)
        self.assertEqual(validate_background_opacity(.65), .65)

    def test_wrap_preserves_text_and_every_line_fits(self):
        font = ImageFont.truetype(str(FONT_PATH), 64)
        text = "为什么他明明知道有危险，却还要回来？OpenAI video 2026"
        lines = wrap_caption(text, font, 360)
        self.assertEqual(''.join(lines), text)
        self.assertGreater(len(lines), 1)
        self.assertTrue(all(font.getlength(line) <= 360 for line in lines))

    def test_rejects_caption_box_outside_canvas(self):
        for override in ({"x": 1000}, {"y": 1900}, {"max_lines": 5}, {"width": 100}):
            with self.assertRaises(ValueError):
                validate_caption_layout({**DEFAULT_CAPTION_LAYOUT, **override})

    def test_long_cues_paginate_without_losing_text_or_exceeding_line_limit(self):
        layout = {**DEFAULT_CAPTION_LAYOUT, "width": 320, "max_lines": 2}
        text = "为什么他明明知道前面有危险，却还要独自回去面对所有人，甚至主动说出自己的名字？"
        with tempfile.TemporaryDirectory() as temporary:
            ass = Path(temporary)/"captions.ass"
            write_caption_ass([(1000, 6000, text)], ass, layout)
            events = [line.split(',', 9) for line in ass.read_text(encoding='utf-8').splitlines()
                      if line.startswith('Dialogue:')]
        self.assertEqual(''.join(re.sub(r'^\{[^}]+\}', '', e[9]) for e in events), text)
        pages = {}
        for e in events:
            pages.setdefault((e[1], e[2]), []).append(e)
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page) <= 2 for page in pages.values()))
        self.assertEqual(events[0][1], '0:00:01.00')
        self.assertEqual(events[-1][2], '0:00:06.00')

    def test_windows_srt_with_bom_and_multiline(self):
        with tempfile.TemporaryDirectory() as temporary:
            srt = Path(temporary)/"subtitles.srt"
            srt.write_bytes(('\ufeff1\r\n00:00:00,200 --> 00:00:01,400\r\n第一行\r\n第二行\r\n\r\n'
                             '2\r\n00:00:01,400 --> 00:00:02,000\r\n继续\r\n').encode('utf-8'))
            rows = read_srt(srt)
        self.assertEqual(rows, [(200, 1400, '第一行\n第二行'), (1400, 2000, '继续')])


if __name__ == '__main__':
    unittest.main()
