"""Real FFmpeg coverage for final-clock captions, audio and finite animations."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from core.captions import DEFAULT_CAPTION_LAYOUT
from core.ffmpeg import mix_narration, mix_background_narration
from pipeline.final_render import export_recognition_audio, render_final_video
from pipeline.source_preprocess import probe_source


@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'requires FFmpeg')
class FinalRenderIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temporary.name)/"剧集's,100%"
        cls.root.mkdir()
        cls.source = cls.root/'source.mp4'
        cls.log = (cls.root/'ffmpeg.log').open('w', encoding='utf-8')
        cls.command(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
            'color=c=0x103050:s=640x360:r=25:d=4.8', '-f', 'lavfi', '-i',
            'sine=frequency=440:sample_rate=48000:duration=4.8',
            '-c:v', 'libx264', '-preset', 'ultrafast', '-c:a', 'aac', '-ac', '2', '-shortest', str(cls.source)])
        cls.music = cls.root/'music.wav'
        cls.command(['ffmpeg', '-v', 'error', '-y', '-f', 'lavfi', '-i',
            'sine=frequency=880:sample_rate=48000:duration=0.8', str(cls.music)])
        cls.gif = cls.root/'finite.gif'
        Image.new('RGB', (30,30), 'red').save(cls.gif, save_all=True,
            append_images=[Image.new('RGB', (30,30), 'lime')], duration=100)
        cls.srt = cls.root/'captions.srt'
        cls.srt.write_text('1\n00:00:00,600 --> 00:00:01,200\n字幕在成片时间出现\n\n', encoding='utf-8')
        cls.layout = {**DEFAULT_CAPTION_LAYOUT, 'x':300, 'y':1000, 'width':480, 'font_size':48}

    @classmethod
    def tearDownClass(cls):
        cls.log.close()
        cls.temporary.cleanup()

    @classmethod
    def command(cls, command):
        subprocess.run(command, check=True, stdout=cls.log, stderr=cls.log)

    def frame(self, path, time):
        png=self.root/f'frame_{time}.png'
        self.command(['ffmpeg','-v','error','-y','-ss',str(time),'-i',str(path),'-frames:v','1',str(png)])
        with Image.open(png) as frame:
            return frame.convert('RGB')

    @staticmethod
    def yellow_count(image):
        return sum(r>180 and g>100 and b<90
                   for r,g,b in image.crop((300,1000,780,1130)).getdata())

    def test_single_render_preserves_final_clock_and_does_not_end_at_finite_gif(self):
        output=self.root/'finished.mp4'
        result=render_final_video(self.source, output, self.srt, "剧名's 100%", '副标题\n第二行',
            self.layout, [{'start_time':1.4,'text':"弹幕's 100%: 正常"}], gif_path=self.gif,
            music_path=self.music, music_volume=.08)
        self.assertEqual(result['video_encode_passes'],1)
        self.assertEqual((result['video']['width'],result['video']['height']),(1080,1920))
        self.assertTrue(result['video']['has_audio'])
        self.assertAlmostEqual(result['video']['duration'],4,delta=.1)
        # Source cue timestamps already refer to the accelerated final timeline.
        self.assertEqual(self.yellow_count(self.frame(output,.3)),0)
        self.assertGreater(self.yellow_count(self.frame(output,.8)),100)
        self.assertEqual(self.yellow_count(self.frame(output,1.5)),0)
        # A finite 0.2s animation must not truncate a four-second video.
        late=self.frame(output,3.5)
        self.assertGreater(late.getpixel((520,1520))[1],180)

    def test_clean_recognition_audio_uses_the_same_speed_without_rendering_video(self):
        audio=export_recognition_audio(self.source,self.root/'recognition.mp3')
        result=subprocess.check_output(['ffprobe','-v','error','-show_entries',
            'stream=codec_type:format=duration','-of','json',str(audio)],text=True)
        import json
        data=json.loads(result)
        self.assertTrue(all(stream['codec_type']=='audio' for stream in data['streams']))
        self.assertAlmostEqual(float(data['format']['duration']),4,delta=.15)

    def test_custom_title_subtitle_and_popup_positions_are_rendered(self):
        output = self.root/'custom_text.mp4'
        render_final_video(self.source, output, self.srt, '顶部标题', '底部副标题',
            self.layout, [{'start_time': 0, 'text': '滚动弹幕'}],
            text_layout={'title': {'y': 100, 'font_size': 48},
                         'subtitle': {'y': 1700, 'font_size': 60},
                         'popup': {'y': 300, 'font_size': 36}})
        frame = self.frame(output, 2)
        for y, height in [(100, 70), (1700, 80)]:
            count = sum(r > 180 and g > 100 and b < 90
                        for r, g, b in frame.crop((0, y, 1080, y+height)).getdata())
            self.assertGreater(count, 100)
        white = sum(r > 190 and g > 190 and b > 190
                    for r, g, b in frame.crop((0, 300, 1080, 360)).getdata())
        self.assertGreater(white, 50)

    def test_narration_only_has_no_appended_source_dialogue(self):
        import array
        import math
        output = self.root/'narration_only.mp4'
        mix_background_narration(self.source, self.music, output)
        self.assertAlmostEqual(probe_source(output)['duration'], .8, delta=.15)
        pcm = subprocess.check_output(['ffmpeg', '-v', 'error', '-ss', '0.2', '-i', str(output),
            '-t', '0.2', '-vn', '-ac', '1', '-ar', '48000', '-f', 'f32le', 'pipe:1'])
        samples = array.array('f', pcm)
        def amplitude(frequency):
            phase = 2*math.pi*frequency/48000
            return abs(sum(value*complex(math.cos(phase*i), math.sin(phase*i))
                           for i, value in enumerate(samples)))/len(samples)
        self.assertGreater(amplitude(880), .005)
        self.assertLess(amplitude(440), amplitude(880)*.01)

    def test_source_sound_is_silent_during_both_start_and_end_narration(self):
        import array
        import math

        def tone_amplitude(path, start, frequency):
            decoded = subprocess.check_output(['ffmpeg','-v','error','-ss',str(start),
                '-i',str(path),'-t','0.2','-vn','-ac','1','-ar','48000','-f','f32le','pipe:1'])
            samples = array.array('f', decoded)
            phase = 2*math.pi*frequency/48000
            real = sum(value*math.cos(phase*i) for i,value in enumerate(samples))
            imaginary = sum(value*math.sin(phase*i) for i,value in enumerate(samples))
            return math.hypot(real,imaginary)/len(samples)

        for alignment, narration_time in [('start',.2),('end',4.2)]:
            with self.subTest(alignment=alignment):
                output = self.root/f'narration_{alignment}.mp4'
                # Source has a 440Hz tone; the 0.8s narration has an 880Hz tone.
                mix_narration(self.source,self.music,output,alignment=alignment)
                voice = tone_amplitude(output,narration_time,880)
                leaked_source = tone_amplitude(output,narration_time,440)
                self.assertGreater(voice,.005)
                self.assertLess(leaked_source,voice*.01)
                dialogue = tone_amplitude(output,2,440)
                self.assertGreater(dialogue,.005)
                self.assertLess(tone_amplitude(output,2,880),dialogue*.01)


if __name__=='__main__':
    unittest.main()
