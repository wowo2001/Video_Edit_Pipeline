"""Per-source preview adapter; reuse media primitives without changing conference."""
from pathlib import Path
from core.ffmpeg import get_duration, dub_video_segment
from core.utils import read_json, write_json
from pipeline.video import cut_video_range, fit_forward_video_range
from conference import replace_video_audio, concat_preview_clips


def render_segment(paths):
    plan_path = paths.root / 'commentary_plan.json'
    plan = read_json(plan_path)
    segment = plan['segments'][0]
    subtitles = read_json(paths.subtitles['json'])['utterances']
    directory = paths.root / 'commentary_preview_segments'
    directory.mkdir(exist_ok=True)
    number = segment['segment_id']
    duration = get_duration(paths.video)
    final = directory / f'{number:02d}_final.mp4'

    def narrated_clip(anchor, audio, seconds, name):
        start, end = fit_forward_video_range(anchor, seconds, duration)
        visual = directory / f'{number:02d}_{name}_visual.mp4'
        output = directory / f'{number:02d}_{name}_final.mp4'
        cut_video_range(paths.video, visual, start, end)
        replace_video_audio(visual, Path(audio), output)
        return output, end

    seconds = segment['narration_duration_ms'] / 1000
    if segment['type'] == 'with_dialogue':
        indices = segment['dialogue_subtitle_indices']
        start = subtitles[indices[0]]['start_time'] / 1000
        end = subtitles[indices[-1]]['end_time'] / 1000
        # When speech starts at frame zero, use the opening footage for the
        # prelude rather than asking the shared cutter for an empty 0..0 clip.
        prelude, _ = narrated_clip(max(0, start - seconds), segment['narration_audio_path'], seconds, 'prelude')
        dub = segment['dubbed_dialogue']
        dubbed = directory / f'{number:02d}_dubbed.mp4'
        dub_video_segment(paths.video, Path(dub['audio_path']), dubbed,
                          round(start * 1000), round(end * 1000), dub['duration_ms'])
        concat_preview_clips([prelude, dubbed], final, directory / f'{number:02d}_concat.txt')
    else:
        start = subtitles[segment['visual_subtitle_indices'][0]]['start_time'] / 1000
        clip, end = narrated_clip(start, segment['narration_audio_path'], seconds, 'narration')
        clip.replace(final)
    if segment.get('audience_question_audio_path'):
        question, _ = narrated_clip(end, segment['audience_question_audio_path'],
                                    segment['audience_question_duration_ms'] / 1000, 'question')
        combined = directory / f'{number:02d}_with_question.mp4'
        concat_preview_clips([final, question], combined, directory / f'{number:02d}_question_concat.txt')
        final = combined
    segment['render_preview'] = {'source_id': segment['source_id'], 'final_video_path': str(final)}
    write_json(plan, plan_path, ensure_ascii=False, indent=2)
