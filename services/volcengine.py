import base64
import json
import time

import requests
from pydub import AudioSegment

from config import SPEAKER, VOLC_APPID, VOLC_SECRET
from core.utils import ms_to_srt_time, read_json, write_json


class Volcengine:
    def __init__(self):
        self.app_id = VOLC_APPID
        self.secret_key = VOLC_SECRET
        self.tts_url = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
        self.asr_url = "https://openspeech.bytedance.com/api/v1/vc"
        self.tts_headers = {
            "X-Api-Key": VOLC_SECRET,
            "X-Api-Resource-Id": "seed-tts-2.0",
        }
        self.speaker = SPEAKER

    def transcribe_audio(self, input_path, output_path, speaker_info=False):
        submit_url = f"{self.asr_url}/submit"
        params = {
            "appid": self.app_id,
            "language": "zh-CN",
            "use_itn": "True",
            "use_punc": "False",
            "max_lines": 1,
            "words_per_line": 30,
            "with_speaker_info": "True",
            "caption_type": "speech",
        }
        headers = {
            "Authorization": f"Bearer; {self.secret_key}",
            "Content-Type": "audio/wav",
        }

        with open(input_path, "rb") as file:
            audio_data = file.read()

        response = requests.post(
            submit_url,
            params=params,
            headers=headers,
            data=audio_data,
        )
        if response.json()["code"] != 0:
            raise Exception(response.json())

        job_id = response.json()["id"]
        print(f"\n任务提交成功: {job_id}")

        query_url = f"{self.asr_url}/query"
        while True:
            response = requests.get(
                query_url,
                params={"appid": self.app_id, "id": job_id, "blocking": 0},
                headers={"Authorization": f"Bearer; {self.secret_key}"},
            )
            result = response.json()

            if result.get("code") == 0:
                break
            if result.get("code") == 2000:
                print("识别处理中...")
                time.sleep(2)
                continue
            raise Exception(result)

        write_json(result, output_path["json"], ensure_ascii=False, indent=2)
        print(f"✅ 原始JSON已保存: {output_path['json']}")
        self._write_srt(result["utterances"], output_path["srt"], speaker_info)
        print(f"\n✅ 字幕生成完成: {output_path['srt']}")

    @staticmethod
    def _write_srt(utterances, output_path, speaker_info):
        with open(output_path, "w", encoding="utf-8") as file:
            for index, utterance in enumerate(utterances, 1):
                start = ms_to_srt_time(utterance["start_time"])
                end = ms_to_srt_time(utterance["end_time"])
                text = utterance["text"].strip().replace("\n", " ")

                speaker = utterance.get("attribute", {}).get("speaker")
                if speaker_info and speaker:
                    text = f"[Speaker {speaker}] {text}"

                file.write(f"{index}\n{start} --> {end}\n{text}\n\n")

    def generate_tts(self, text, audio_path):
        """把一段文本转换为指定路径的 MP3，并返回时长（毫秒）。"""
        audio_path.parent.mkdir(parents=True, exist_ok=True)
        audio_path.write_bytes(self._tts_stream(text))
        return len(AudioSegment.from_file(audio_path))

    def _tts_stream(self, text: str) -> bytes:
        payload = {
            "user": {"uid": "123"},
            "req_params": {
                "text": text,
                "speaker": self.speaker,
                "audio_params": {"format": "mp3", "sample_rate": 24000},
            },
        }
        response = requests.post(
            self.tts_url,
            headers=self.tts_headers,
            json=payload,
            stream=True,
        )

        chunks = []
        for line in response.iter_lines():
            if not line:
                continue
            try:
                result = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError:
                continue

            if result.get("code") not in {0, 20000000}:
                print("TTS error:", result)
                continue
            if result.get("data"):
                chunks.append(result["data"])

        return base64.b64decode("".join(chunks))
