import torchaudio
from faster_whisper import WhisperModel
from pyannote.audio import Pipeline
from pyannote.audio.pipelines.utils.hook import ProgressHook

from config import HF_TOKEN
from core.path import ProjectPaths
from core.utils import ms_to_srt_time, read_json, write_json


class Whisper:
    def __init__(self):
        self.hf_token = HF_TOKEN
        self.model = WhisperModel(
            "large-v3",
            device="auto",
            compute_type="int8",
        )

    def find_speaker(self, start, end, diarization):
        best_speaker = None
        best_score = 0
        duration = end - start

        for turn, _, speaker in diarization.itertracks(yield_label=True):
            overlap = max(0, min(end, turn.end) - max(start, turn.start))
            if overlap <= 0:
                continue

            score = overlap / duration
            if score > best_score:
                best_score = score
                best_speaker = speaker

        return best_speaker

    def diarize(self, audio_path, output_path):
        # 1. 读取 ASR 结果
        cloud_json = read_json(output_path["json"])

        # 2. Speaker Diarization
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1",
            token=self.hf_token,
        )
        waveform, sample_rate = torchaudio.load(str(audio_path))
        with ProgressHook() as hook:
            result = pipeline(
                {"waveform": waveform, "sample_rate": sample_rate},
                hook=hook,
            )

        diarization = result.speaker_diarization
        embeddings = result.speaker_embeddings
        print(type(embeddings))
        print(embeddings.shape)

        segments = [
            {
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "speaker": speaker,
            }
            for segment, _, speaker in diarization.itertracks(yield_label=True)
        ]
        write_json(segments, ProjectPaths().root / "segments.json")

        # 3. 匹配 Speaker
        for utterance in cloud_json["utterances"]:
            speaker = self.find_speaker(
                utterance["start_time"] / 1000,
                utterance["end_time"] / 1000,
                diarization,
            )
            utterance.setdefault("attribute", {})["speaker"] = speaker

        # 4. 保存 JSON
        write_json(cloud_json, output_path["json"])
        print(f"✅ JSON saved: {output_path['json']}")

        # 5. 输出 SRT
        with open(output_path["srt"], "w", encoding="utf-8") as file:
            for index, utterance in enumerate(cloud_json["utterances"], start=1):
                start = ms_to_srt_time(utterance["start_time"])
                end = ms_to_srt_time(utterance["end_time"])
                speaker = utterance["attribute"].get("speaker", "UNKNOWN")
                text = f"[{speaker}] {utterance['text'].strip()}"

                file.write(f"{index}\n{start} --> {end}\n{text}\n\n")

        print(f"✅ Subtitle generated: {output_path['srt']}")

    def transcribe(self, audio_path, output_path):
        segments, info = self.model.transcribe(
            str(audio_path),
            language="zh",
            vad_filter=True,
            word_timestamps=True,
            beam_size=5,
        )
        result = {"utterances": []}

        for segment in segments:
            print(segment.start, segment.end, segment.text)
            result["utterances"].append(
                {
                    "start_time": int(segment.start * 1000),
                    "end_time": int(segment.end * 1000),
                    "text": segment.text.strip(),
                }
            )

        write_json(result, output_path["json"])
        print(f"✅ Subtitle generated: {output_path['json']}")

        with open(output_path["srt"], "w", encoding="utf-8") as file:
            for index, utterance in enumerate(result["utterances"], start=1):
                start = ms_to_srt_time(utterance["start_time"])
                end = ms_to_srt_time(utterance["end_time"])
                file.write(
                    f"{index}\n{start} --> {end}\n{utterance['text'].strip()}\n\n"
                )

        print(f"✅ Subtitle generated: {output_path['srt']}")
