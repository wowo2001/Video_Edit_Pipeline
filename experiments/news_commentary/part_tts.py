"""Per-part narration audio and exact offsets in a concatenated PCM WAV."""
import hashlib
from pathlib import Path
from pydub import AudioSegment
from core.utils import read_json, write_json
from services.volcengine import Volcengine
from conference import NARRATOR_TTS_VOICE, FEMALE_DIALOGUE_TTS_VOICES


def generate_part_tts(paths):
    plan_path = paths.root / 'commentary_plan.json'
    plan = read_json(plan_path)
    records = read_json(paths.root / 'dialogue_dubbing.json')
    directory = paths.root / 'commentary_tts'
    directory.mkdir(exist_ok=True)
    tts = Volcengine()

    def generate(text, voice, label):
        digest = hashlib.sha256(('original_volume_v1\n'+voice+'\n'+text).encode()).hexdigest()[:16]
        target = directory / f'{label}_{digest}.mp3'
        marker = target.with_suffix('.done')
        if not target.exists() or not marker.exists():
            tts.generate_tts(text, target, speaker=voice)
            marker.touch()
        return target

    for segment in plan['segments']:
        number = segment['segment_id']
        parts = segment.get('narration_parts') or [{'kind':'bridge','text':segment['narration']}]
        clips, samples = [], 0
        for index, part in enumerate(parts, 1):
            print(f'段落 {number} / 旁白 {index} ({part["kind"]})', flush=True)
            voice = FEMALE_DIALOGUE_TTS_VOICES[0] if part.get('role') == 'article_quote' else NARRATOR_TTS_VOICE
            part['voice'] = voice
            target = generate(part['text'],voice,f'segment_{number:02d}_part_{index:02d}')
            clip = AudioSegment.from_file(target).set_frame_rate(24000).set_channels(1).set_sample_width(2)
            count = len(clip.raw_data)//2
            part.update(audio_path=str(target),start_ms=round(samples/24),
                        end_ms=round((samples+count)/24),duration_ms=round(count/24))
            samples += count
            clips.append(clip)
        combined = clips[0]
        for clip in clips[1:]:
            combined += clip
        target = directory / f'segment_{number:02d}_narration_parts.wav'
        combined.export(target,format='wav')
        segment.update(narration_parts=parts,narration=''.join(p['text'] for p in parts),
                       narration_audio_path=str(target),narration_duration_ms=round(samples/24))
        if segment.get('audience_question'):
            target = generate(
                segment['audience_question'],NARRATOR_TTS_VOICE,f'segment_{number:02d}_question')
            segment.update(audience_question_audio_path=str(target),
                           audience_question_duration_ms=len(AudioSegment.from_file(target)))
        if segment['type']=='with_dialogue':
            dub = next(r for r in records if r['segment_id']==number)
            target = generate(
                dub['chinese_text'],dub['voice'],f'segment_{number:02d}_dialogue')
            dub.update(audio_path=str(target),duration_ms=len(AudioSegment.from_file(target)))
            segment['dubbed_dialogue'].update(audio_path=str(target),duration_ms=dub['duration_ms'])
    write_json(plan,plan_path,ensure_ascii=False,indent=2)
    write_json(records,paths.root/'dialogue_dubbing.json',ensure_ascii=False,indent=2)
