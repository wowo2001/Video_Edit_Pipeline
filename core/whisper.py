import whisperx
import json
from core.utils import ms_to_srt_time
from config import HF_TOKEN
from whisperx.diarize import DiarizationPipeline


class Whisper:
    def __init__(self):
        self.hf_token = HF_TOKEN

    def transcribe_audio(self, input_path, output_path, speaker_info=False):

        device = "cpu"

        # =========================
        # 1. Whisper 转写
        # =========================
        model = whisperx.load_model(
            "small",
            device=device,
            compute_type="int8"
        )

        result = model.transcribe(str(input_path))

        # =========================
        # 2. 时间对齐
        # # =========================
        align_model, metadata = whisperx.load_align_model(
            language_code="zh",
            device=device
        )

        result = whisperx.align(
            result["segments"],
            align_model,
            metadata,
            str(input_path),
            device=device
        )

        # =========================
        # 3. speaker diarization（CPU版）
        # =========================
        diarize_model = DiarizationPipeline(
            token=self.hf_token,
            device=device
        )

        diarize_segments = diarize_model(str(input_path))
        print(f"🎤 说话人分离完成，检测到 {len(diarize_segments)} 个说话人")

        result = whisperx.assign_word_speakers(
            diarize_segments,
            result
        )

        # =========================
        # 4. 保存 JSON
        # =========================
        with open(output_path["json"], "w", encoding="utf-8") as f:
            json.dump(result, f, ensure_ascii=False, indent=2)

        print(f"✅ 原始JSON已保存: {output_path['json']}")

        # =========================
        # 5. 写 SRT
        # =========================
        segments = result["segments"]

        with open(output_path["srt"], "w", encoding="utf-8") as f:

            for i, seg in enumerate(segments, 1):

                start = ms_to_srt_time(int(seg["start"] * 1000))
                end = ms_to_srt_time(int(seg["end"] * 1000))

                text = seg["text"].strip().replace("\n", " ")

                # speaker 标注
                if speaker_info:
                    speaker = seg.get("speaker")
                    if speaker is not None:
                        text = f"[Speaker {speaker}] {text}"

                f.write(f"{i}\n")
                f.write(f"{start} --> {end}\n")
                f.write(f"{text}\n\n")

        print(f"✅ 字幕生成完成: {output_path['srt']}")