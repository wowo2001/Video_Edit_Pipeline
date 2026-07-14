
import json

from services.postgresql import PostgresClient
from services.text_embedding_service import TextEmbeddingService


class PostCutService:
    def __init__(self):
        self.postgres_client = PostgresClient()
        self.text_embedding_service = TextEmbeddingService()

    def save_transcription_to_db(self, subtitles_path, speaker_mapping_path, video_url, episode):
        with open(subtitles_path, "r", encoding="utf-8") as f:
            subtitles = json.load(f)
        with open(speaker_mapping_path, "r", encoding="utf-8") as f:
            speaker_mapping = json.load(f)

        results = []

        for utterance in subtitles.get("utterances", []):

            raw_speaker = (
                utterance
                .get("attribute", {})
                .get("speaker")
            )

            speaker = speaker_mapping.get(
                raw_speaker,
                raw_speaker
            )

            if speaker == "UNKNOWN":
                continue


            results.append(
                {
                "start_time": utterance["start_time"],
                "end_time": utterance["end_time"],
                "text": utterance["text"],
                "speaker": speaker,
                "url": video_url,
                "episode": episode,
                "text_embedding": self.text_embedding_service.encode(utterance["text"])
                }
            )

        for item in results:
            self.postgres_client.insert_video_transcript(
                start_time=int(item["start_time"]),
                end_time=int(item["end_time"]),
                text=item["text"],
                speaker=item["speaker"],
                url=item["url"],
                episode=item["episode"],
                embedding=item["text_embedding"]
            )
        self.postgres_client.close()