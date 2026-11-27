"""Generate continuous narration, then split PCM using provider subtitle timestamps."""
import hashlib
from pydub import AudioSegment
from core.utils import read_json, write_json
from services.volcengine import Volcengine
from conference import NARRATOR_TTS_VOICE, FEMALE_DIALOGUE_TTS_VOICES
from core.tts_alignment import paragraph_times


def generate_part_tts(paths):
    plan_path = paths.root / 'commentary_plan.json'
    plan = read_json(plan_path)
    records = read_json(paths.root / 'dialogue_dubbing.json')
    directory = paths.root / 'commentary_tts'
    directory.mkdir(exist_ok=True)
    tts = Volcengine()
    groups = []

    def append(target, text, voice, label, role):
        entry = (target, text, label, role)
        # Quotes remain separate even if their configured voice matches the host.
        if role == 'narrator' and groups and groups[-1]['role'] == role and groups[-1]['voice'] == voice:
            groups[-1]['items'].append(entry)
        else:
            groups.append(dict(voice=voice, role=role, items=[entry]))

    for segment in plan['segments']:
        number = segment['segment_id']
        parts = segment.setdefault('narration_parts', [{'kind': 'bridge', 'text': segment.get('narration', '')}])
        for index, part in enumerate(parts, 1):
            quote = part.get('role') == 'article_quote'
            voice = FEMALE_DIALOGUE_TTS_VOICES[0] if quote else NARRATOR_TTS_VOICE
            part['voice'] = voice
            append(part, part['text'], voice, f'segment_{number:02d}_part_{index:02d}',
                   'quote' if quote else 'narrator')
        if segment['type'] == 'with_dialogue':
            dub = next(r for r in records if r['segment_id'] == number)
            append(dub, dub['chinese_text'], dub['voice'], f'segment_{number:02d}_dialogue', 'quote')
        if segment.get('audience_question'):
            append(segment, segment['audience_question'], NARRATOR_TTS_VOICE,
                   f'segment_{number:02d}_question', 'narrator')

    for group in groups:
        text = '\n'.join(' '.join(item[1].splitlines()) for item in group['items'])
        digest = hashlib.sha256(('merged_subtitles_v2\n'+group['voice']+'\n'+text).encode()).hexdigest()[:16]
        target = directory / f'group_{digest}.mp3'
        marker = target.with_suffix('.done')
        subtitle_path = target.with_suffix('.subtitles.json')
        print(f"合并配音：{len(group['items'])} 个部分，{len(text)} 字符 ({group['role']})", flush=True)
        if not target.exists() or not marker.exists() or not subtitle_path.exists():
            tts.generate_tts(text, target, speaker=group['voice'], subtitle_path=subtitle_path)
            marker.touch()
        clip = AudioSegment.from_file(target).set_frame_rate(24000).set_channels(1).set_sample_width(2)
        count = len(clip.raw_data) // 2
        aligned = paragraph_times(read_json(subtitle_path)['sentences'])
        boundaries = [0] + [round((a[-1]['end']+b[0]['start'])/2*24000)
                            for a, b in zip(aligned, aligned[1:])] + [count]
        for (obj, _, label, _), rows, start, end in zip(
                group['items'], aligned, boundaries, boundaries[1:]):
            timing = [dict(r, start=r['start']-start/24000,
                           end=r['end']-start/24000) for r in rows]
            # Slice at sample boundaries; concatenating parts preserves every sample.
            piece = clip._spawn(clip.raw_data[start*2:end*2])
            output = directory / f'{label}_{digest}.wav'
            piece.export(output, format='wav').close()
            if label.endswith('_question'):
                obj.update(audience_question_audio_path=str(output),
                           audience_question_duration_ms=round((end-start)/24),
                           audience_question_tts_words=timing)
            else:
                obj.update(audio_path=str(output), duration_ms=round((end-start)/24), tts_words=timing)
            start = end

    for segment in plan['segments']:
        samples, clips = 0, []
        for part in segment['narration_parts']:
            clip = AudioSegment.from_file(part['audio_path'])
            count = len(clip.raw_data)//2
            part.update(start_ms=round(samples/24), end_ms=round((samples+count)/24))
            samples += count
            clips.append(clip)
        combined = clips[0]
        for clip in clips[1:]:
            combined += clip
        target = directory / f"segment_{segment['segment_id']:02d}_narration_parts.wav"
        combined.export(target, format='wav').close()
        segment.update(narration=''.join(p['text'] for p in segment['narration_parts']),
                       narration_audio_path=str(target), narration_duration_ms=round(samples/24))
        if segment['type'] == 'with_dialogue':
            dub = next(r for r in records if r['segment_id'] == segment['segment_id'])
            segment.setdefault('dubbed_dialogue', dict(dub)).update(
                audio_path=dub['audio_path'], duration_ms=dub['duration_ms'],
                tts_words=dub['tts_words'])
    write_json(plan, plan_path, ensure_ascii=False, indent=2)
    write_json(records, paths.root / 'dialogue_dubbing.json', ensure_ascii=False, indent=2)
