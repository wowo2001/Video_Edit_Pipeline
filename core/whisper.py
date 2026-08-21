import json
from core.utils import read_json, write_json

from config import HF_TOKEN
from core.utils import ms_to_srt_time
from core.path import ProjectPaths
from pyannote.audio import Pipeline
import torchaudio
from pyannote.audio.pipelines.utils.hook import ProgressHook
from faster_whisper import WhisperModel
import numpy as np


class Whisper:

    def __init__(self):
        self.hf_token = HF_TOKEN
        self.model = WhisperModel(
            "large-v3",
            device="auto",
            compute_type="int8"
        )

    def find_speaker(self, start, end, diarization):

        best_speaker = None
        best_score = 0

        duration = end - start

        for turn, _, speaker in diarization.itertracks(yield_label=True):

            overlap = max(0, min(end, turn.end) - max(start, turn.start))

            if overlap <= 0:
                continue

            score = overlap / duration  # ⭐关键修复

            if score > best_score:
                best_score = score
                best_speaker = speaker

        return best_speaker

    def diarize(
            self,
            audio_path,
            output_path
    ):

        # =========================
        # 1. 读取ASR结果
        # =========================

        cloud_json = read_json(output_path["json"])
        # =========================
        # 2. Speaker Diarization
        # =========================

        
        pipeline = Pipeline.from_pretrained(
            "pyannote/speaker-diarization-community-1",
            token=self.hf_token
            )
        waveform, sample_rate = torchaudio.load(str(audio_path))
        
        
        with ProgressHook() as hook:
            result = pipeline({"waveform": waveform, "sample_rate": sample_rate}, hook=hook)

        diarization = result.speaker_diarization
        embeddings = result.speaker_embeddings

        print(type(embeddings))
        print(embeddings.shape)

        segments = []

        for segment, _, speaker in diarization.itertracks(yield_label=True):
            segments.append({
                "start": round(segment.start, 3),
                "end": round(segment.end, 3),
                "speaker": speaker
            })

        write_json(
                        segments,
                        ProjectPaths().root / "segments.json",
                        indent=2,
                        ensure_ascii=False
                    )


        # =========================
        # 3. 匹配 Speaker
        # =========================

        for utt in cloud_json["utterances"]:

            start = utt["start_time"] / 1000
            end = utt["end_time"] / 1000

            speaker = self.find_speaker(
                start,
                end,
                diarization
            )

            if "attribute" not in utt:
                utt["attribute"] = {}

            utt["attribute"]["speaker"] = speaker

        # =========================
        # 4. 保存 JSON
        # =========================

        write_json(
                        cloud_json,
                        output_path["json"],
                        ensure_ascii=False,
                        indent=2
                    )
        print(
            f"✅ JSON saved: {output_path['json']}"
        )

        # =========================
        # 5. 输出 SRT
        # =========================

        with open(
                output_path["srt"],
                "w",
                encoding="utf-8"
        ) as f:

            for i, utt in enumerate(cloud_json["utterances"], start=1):

                start = ms_to_srt_time(utt["start_time"])
                end = ms_to_srt_time(utt["end_time"])
                text = utt["text"].strip()

                speaker = utt["attribute"].get("speaker", "UNKNOWN")

                text = f"[{speaker}] {text}"

                f.write(f"{i}\n")
                f.write(f"{start} --> {end}\n")
                f.write(f"{text}\n\n")

        print(
            f"✅ Subtitle generated: "
            f"{output_path['srt']}"
        )

    def transcribe(
        self,
        audio_path,
        output_path
    ):

        segments, info = self.model.transcribe(
            str(audio_path),
            language="zh",
            vad_filter=True,
            word_timestamps=True,
            beam_size=5
        )

        result = {
            "utterances": []
        }

        for segment in segments:
            print(segment.start, segment.end, segment.text)
            utterance = {
                "start_time": int(segment.start * 1000),
                "end_time": int(segment.end * 1000),
                "text": segment.text.strip(),
            }

            result["utterances"].append(utterance)    

        # JSON
        write_json(
                        result,
                        output_path["json"],
                        ensure_ascii=False,
                        indent=2
                    )
        print(
            f"✅ Subtitle generated: "
            f"{output_path['json']}"
        )

        # SRT
        with open(
        output_path["srt"],
        "w",
        encoding="utf-8"
        )as f:

            for i, utt in enumerate(result["utterances"], start=1):

                start = ms_to_srt_time(utt["start_time"])
                end = ms_to_srt_time(utt["end_time"])

                text = utt["text"].strip()

                f.write(f"{i}\n")
                f.write(f"{start} --> {end}\n")
                f.write(f"{text}\n\n")

        print(
            f"✅ Subtitle generated: "
            f"{output_path['srt']}"
        )

