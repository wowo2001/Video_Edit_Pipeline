import pickle
from collections import Counter
from pathlib import Path

import numpy as np
import torchaudio
import torch
from speechbrain.inference.speaker import EncoderClassifier
from sklearn.cluster import AgglomerativeClustering

from core.utils import ms_to_srt_time, read_json, write_json


class SpeechBrain:
    def __init__(self, device="cpu"):
        self.device = device
        self.model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": device},
        )

    def prepare_waveform(self, waveform, sample_rate):
        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)
            sample_rate = 16000

        return waveform, sample_rate

    def get_embedding(self, waveform, sample_rate, start, end):
        start_sample = int(start * sample_rate)
        end_sample = int(end * sample_rate)
        chunk = waveform[:, start_sample:end_sample]

        if chunk.shape[1] < sample_rate * 0.3:
            return None

        with torch.no_grad():
            emb = self.model.encode_batch(chunk)

        return emb.squeeze().cpu().numpy()

    @staticmethod
    def write_diarized_srt(subtitles_json_path, srt_path):
        """Rebuild an SRT from diarization labels stored in the subtitle JSON."""
        subtitles = read_json(subtitles_json_path)
        with open(srt_path, "w", encoding="utf-8") as f:
            for i, utt in enumerate(subtitles["utterances"], start=1):
                start = ms_to_srt_time(utt["start_time"])
                end = ms_to_srt_time(utt["end_time"])
                text = utt["text"].strip()
                speaker = utt.get("attribute", {}).get("speaker", "UNKNOWN")
                f.write(f"{i}\n{start} --> {end}\n[{speaker}] {text}\n\n")

    def diarize(
        self,
        audio_path,
        output_path,
        threshold=0.8,
        min_duration=1.0,
        core_min_duration=1.5,
        min_cluster_ratio=0.05,
        core_reassignment_threshold=0.50,
        short_assignment_threshold=0.45,
        assignment_margin=0.05,
    ):
        """Assign speakers with high-quality core clusters and short-utterance recovery.

        Only utterances at least ``core_min_duration`` long create clusters.  Shorter
        core utterances belonging to undersized clusters are reassigned to a valid
        core centroid only below ``core_reassignment_threshold``. Utterances between
        ``min_duration`` and ``core_min_duration`` use the stricter
        ``short_assignment_threshold``. In both cases the nearest core cluster must
        also beat the second-nearest cluster by ``assignment_margin``. This prevents
        ambiguous acknowledgements from being forced into an arbitrary cluster.
        """
        if min_duration <= 0 or core_min_duration < min_duration:
            raise ValueError("Require 0 < min_duration <= core_min_duration")

        cloud_json = read_json(output_path["json"])
        waveform, sample_rate = torchaudio.load(audio_path)
        waveform, sample_rate = self.prepare_waveform(waveform, sample_rate)
        utterances = cloud_json["utterances"]
        core_records = []
        short_records = []
        embedding_records = []

        for i, utt in enumerate(utterances):
            start = utt["start_time"] / 1000
            end = utt["end_time"] / 1000
            duration = end - start
            if end <= start or duration < min_duration:
                continue
            emb = self.get_embedding(waveform, sample_rate, start, end)
            if emb is None:
                continue
            record = {
                "utt_idx": i,
                "start": utt["start_time"],
                "end": utt["end_time"],
                "text": utt["text"],
                "embedding": emb,
                "duration": duration,
                "is_core": duration >= core_min_duration,
            }
            embedding_records.append(record)
            (core_records if record["is_core"] else short_records).append(record)

        full_labels = ["UNKNOWN"] * len(utterances)
        if not core_records:
            print("[WARN] No utterances meet core_min_duration; all speakers remain UNKNOWN")
        else:
            core_embeddings = np.vstack([record["embedding"] for record in core_records])
            clusterer = AgglomerativeClustering(
                n_clusters=None,
                metric="cosine",
                linkage="average",
                distance_threshold=threshold,
            )
            labels = clusterer.fit_predict(core_embeddings)

            counts = Counter(labels)
            valid_clusters = {
                cluster for cluster, count in counts.items()
                if count / len(labels) >= min_cluster_ratio
            }
            print("valid core clusters:", valid_clusters)

            cluster_centroids = {}
            for cluster in valid_clusters:
                embeddings = core_embeddings[labels == cluster]
                centroid = embeddings.mean(axis=0)
                cluster_centroids[cluster] = centroid / np.linalg.norm(centroid)

            def nearest_core_cluster(embedding):
                normalized_embedding = embedding / np.linalg.norm(embedding)
                candidates = sorted(
                    (
                        (candidate, 1 - float(np.dot(normalized_embedding, centroid)))
                        for candidate, centroid in cluster_centroids.items()
                    ),
                    key=lambda item: item[1],
                )
                candidate, distance = candidates[0]
                second_distance = candidates[1][1] if len(candidates) > 1 else float("inf")
                return candidate, distance, second_distance - distance

            for record, cluster in zip(core_records, labels):
                if cluster in valid_clusters:
                    full_labels[record["utt_idx"]] = f"SPEAKER_{cluster:02d}"

            for record, cluster in zip(core_records, labels):
                if cluster in valid_clusters:
                    continue
                candidate, distance, margin = nearest_core_cluster(record["embedding"])
                record["nearest_core_distance"] = distance
                record["nearest_core_margin"] = margin
                if distance <= core_reassignment_threshold and margin >= assignment_margin:
                    full_labels[record["utt_idx"]] = f"SPEAKER_{candidate:02d}"

            for record in short_records:
                cluster, distance, margin = nearest_core_cluster(record["embedding"])
                record["nearest_core_distance"] = distance
                record["nearest_core_margin"] = margin
                if distance <= short_assignment_threshold and margin >= assignment_margin:
                    full_labels[record["utt_idx"]] = f"SPEAKER_{cluster:02d}"

        for record in embedding_records:
            record["speaker"] = full_labels[record["utt_idx"]]

        embeddings_path = Path(output_path["json"]).parent / "embedding_records.pkl"
        with open(embeddings_path, "wb") as f:
            pickle.dump(embedding_records, f)

        for utt, label in zip(utterances, full_labels):
            utt.setdefault("attribute", {})
            utt["attribute"]["speaker"] = label

        write_json(cloud_json, output_path["json"])
        print(f"✅ Subtitle generated: {output_path['json']}")

        self.write_diarized_srt(output_path["json"], output_path["srt"])

        print(f"✅ Subtitle generated: {output_path['srt']}")
