from config import VOLC_APPID, VOLC_SECRET, SPEAKER
from core.utils import ms_to_srt_time
import requests
import time
import json
from core.utils import read_json, write_json
import base64
from pydub import AudioSegment

from pipeline import audio
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

    # =========================
    # 提交任务
    # =========================

        submit_url = f"{self.asr_url}/submit"

        params = {
            "appid": self.app_id,
            "language": "zh-CN",
            "use_itn": "True",
            "use_punc": "False",
            "max_lines": 1,
            "words_per_line": 15,
            "with_speaker_info": "True",
            "caption_type": "speech"
        }

        headers = {
            "Authorization": f"Bearer; {self.secret_key}",
            "Content-Type": "audio/wav"
        }

        with open(input_path, "rb") as f:
            audio_data = f.read()

        resp = requests.post(
            submit_url,
            params=params,
            headers=headers,
            data=audio_data
        )


        if resp.json()["code"] != 0:
            raise Exception(resp.json())

        job_id = resp.json()["id"]

        print(f"\n任务提交成功: {job_id}")

    # =========================
    # 查询结果
    # =========================

        query_url = f"{self.asr_url}/query"

        while True:

            query_resp = requests.get(
                query_url,
                params={
                    "appid": self.app_id,
                    "id": job_id,
                    "blocking": 0
                },
                headers={
                    "Authorization": f"Bearer; {self.secret_key}"
                }
            )

            result = query_resp.json()

            code = result.get("code")

        # 成功
            if code == 0:
                break

        # 处理中
            elif code == 2000:
                print("识别处理中...")
                time.sleep(2)

            else:
                raise Exception(result)
        
    # =========================
    # 保存完整 response
    # =========================

        write_json(result, output_path["json"], ensure_ascii=False, indent=2)
        print(f"✅ 原始JSON已保存: {output_path['json']}")

    # =========================
    # 写入 SRT
    # =========================

        utterances = result["utterances"]

        with open(output_path["srt"], "w", encoding="utf-8") as f:

            for i, u in enumerate(utterances, 1):

                start = ms_to_srt_time(u["start_time"])
                end = ms_to_srt_time(u["end_time"])

                text = u["text"].strip().replace("\n", " ")

                if speaker_info:
                    speaker = (
                        u.get("attribute", {})
                        .get("speaker")
                    )

                    if speaker:
                        text = f"[Speaker {speaker}] {text}"

                f.write(f"{i}\n")
                f.write(f"{start} --> {end}\n")
                f.write(f"{text}\n\n")

        print(f"\n✅ 字幕生成完成: {output_path['srt']}")  

    def generate_tts(self, script_path, output_path):
        data = read_json(script_path)
        text = data["hook"]["narrative"]["content"]
        audio_bytes = self._tts_stream(text)
        audio_path = output_path / "hook.mp3"
        audio_path.write_bytes(audio_bytes)

        audio = AudioSegment.from_file(audio_path)
        duration_ms = len(audio)

        data["hook"]["narrative"]["length"] = duration_ms

        for item in data["clips"]:
            text = item["narrative"]["content"]
            place = item["place"]

            audio_bytes = self._tts_stream(text)

            audio_path = output_path / f"clip_{place}.mp3"
            audio_path.write_bytes(audio_bytes)

            audio = AudioSegment.from_file(audio_path)
            duration_ms = len(audio)

            item["narrative"]["length"] = duration_ms

        write_json(data, script_path, ensure_ascii=False, indent=2)


    def _tts_stream(self, text: str) -> bytes:
        payload = {
            "user": {"uid": "123"},
            "req_params": {
                "text": text,
                "speaker": self.speaker,
                "audio_params": {
                    "format": "mp3",
                    "sample_rate": 24000
                }
            }
        }

        resp = requests.post(
            self.tts_url,
            headers=self.tts_headers,
            json=payload,
            stream=True
        )

        chunks = []

        for line in resp.iter_lines():
            if not line:
                continue

            try:
                obj = json.loads(line.decode("utf-8"))
            except:
                continue

            if obj.get("code") != 0 and obj.get("code") != 20000000:
                print("TTS error:", obj)
                continue

            if obj.get("data"):
                chunks.append(obj["data"])

        return base64.b64decode("".join(chunks))
    
    def generate_tts_temp(
        self,
        script_path,
        output_path
    ):
        """
        根据 segment narration 生成TTS
        回写 segment 的 narration_length。
        """

        output_path.mkdir(
            parents=True,
            exist_ok=True
        )


        data = read_json(script_path)

        for scene in data:

            scene_id = scene["scene_id"]


            for segment in scene.get(
                "segments",
                []
            ):

                segment_id = segment["segment_id"]


                text = segment.get(
                    "narration",
                    ""
                )


                if not text:
                    continue


                print(
                    f"TTS scene:{scene_id} segment:{segment_id}"
                )


                audio_bytes = self._tts_stream(
                    text
                )


                audio_path = (
                    output_path /
                    f"scene_{scene_id}_segment_{segment_id}.mp3"
                )


                audio_path.write_bytes(
                    audio_bytes
                )


                audio = AudioSegment.from_file(
                    audio_path
                )


                duration_ms = len(audio)


                segment["narration_length"] = duration_ms



        write_json(
                        data,
                        script_path,
                        ensure_ascii=False,
                        indent=2
                    )
    def generate_hook_tts(
        self,
        hook_path,
        output_path
    ):
        """
        根据 hook_narration 生成开场钩子TTS
        回写 hook_length。
        """

        output_path.mkdir(
            parents=True,
            exist_ok=True
        )


        hook = read_json(hook_path)

        text = hook.get(
            "hook_narration",
            ""
        )


        if not text:
            raise Exception(
                "hook_narration为空"
            )


        print(
            f"TTS hook scene: hook"
        )


        audio_bytes = self._tts_stream(
            text
        )


        audio_path = (
            output_path /
            f"hook.mp3"
        )


        audio_path.write_bytes(
            audio_bytes
        )


        audio = AudioSegment.from_file(
            audio_path
        )


        duration_ms = len(audio)


        hook["hook_length"] = duration_ms



        write_json(
                        hook,
                        hook_path,
                        ensure_ascii=False,
                        indent=2
                    )

        return hook
