import torch
import numpy as np
import torchaudio
from collections import Counter
from speechbrain.pretrained import EncoderClassifier
from sklearn.cluster import AgglomerativeClustering
import json


class SpeechBrain:

    # =========================
    # init (load model once)
    # =========================
    def __init__(self, device="cpu"):

        self.device = device

        self.model = EncoderClassifier.from_hparams(
            source="speechbrain/spkrec-ecapa-voxceleb",
            run_opts={"device": device}
        )

    # =========================
    # waveform prep
    # =========================
    def prepare_waveform(self, waveform, sample_rate):

        if waveform.shape[0] > 1:
            waveform = waveform.mean(dim=0, keepdim=True)

        if sample_rate != 16000:
            resampler = torchaudio.transforms.Resample(sample_rate, 16000)
            waveform = resampler(waveform)
            sample_rate = 16000

        return waveform, sample_rate

    # =========================
    # embedding
    # =========================
    def get_embedding(self, waveform, sample_rate, start, end):

        start_sample = int(start * sample_rate)
        end_sample = int(end * sample_rate)

        chunk = waveform[:, start_sample:end_sample]

        if chunk.shape[1] < sample_rate * 0.3:
            return None

        with torch.no_grad():
            emb = self.model.encode_batch(chunk)

        return emb.squeeze().cpu().numpy()

    # =========================
    # main API
    # =========================
    def diarize(
        self,
        audio_path,
        output_path,
        threshold=0.8,
        min_duration=0.5,
        min_cluster_ratio=0.05
    ):
        with open(output_path["json"], "r", encoding="utf-8") as f:
            cloud_json = json.load(f)

        # =========================
        # load audio
        # =========================
        waveform, sample_rate = torchaudio.load(audio_path)
        waveform, sample_rate = self.prepare_waveform(waveform, sample_rate)

        utterances = cloud_json["utterances"]

        embeddings = []
        valid_utts = []

        # =========================
        # build embeddings
        # =========================
        for i, utt in enumerate(utterances):

            start = utt["start_time"] / 1000
            end = utt["end_time"] / 1000

            duration = end - start

            if end <= start:
                continue
            if duration < min_duration:
                continue

            emb = self.get_embedding(
                waveform,
                sample_rate,
                start,
                end
            )

            if emb is None:
                continue

            embeddings.append(emb)
            valid_utts.append(i)

        embeddings = np.vstack(embeddings)

        print("embedding shape:", embeddings.shape)

        # =========================
        # clustering
        # =========================
        clusterer = AgglomerativeClustering(
            n_clusters=None,
            metric="cosine",
            linkage="average",
            distance_threshold=threshold
        )

        labels = clusterer.fit_predict(embeddings)

        print("cluster distribution:", Counter(labels))

        # =========================
        # filter small clusters
        # =========================
        counts = Counter(labels)
        total = len(labels)

        valid_clusters = {
            c for c, cnt in counts.items()
            if cnt / total >= min_cluster_ratio
        }

        print("valid clusters:", valid_clusters)

        # =========================
        # build full labels
        # =========================
        full_labels = ["UNKNOWN"] * len(utterances)

        for idx, label in zip(valid_utts, labels):

            if label in valid_clusters:
                full_labels[idx] = f"SPEAKER_{label:02d}"
            else:
                full_labels[idx] = "UNKNOWN"

        # =========================
        # write back
        # =========================
        for utt, label in zip(utterances, full_labels):

            if "attribute" not in utt:
                utt["attribute"] = {}

            utt["attribute"]["speaker"] = label

            print(label, utt["text"])

        return cloud_json