"""Perceived voice-gender classification for speaker clusters."""

import argparse
import json
import os

# This Wav2Vec2 classifier is run as an isolated worker on Windows.  Force a
# single native thread before importing PyTorch to avoid intermittent c10.dll
# access violations from the CPU parallel runtime.
for _thread_env in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_thread_env] = "1"

import numpy as np
import torch
import torchaudio

from transformers import AutoFeatureExtractor, AutoModelForAudioClassification


GENDER_MODEL_ID = "alefiury/wav2vec2-large-xlsr-53-gender-recognition-librispeech"


class VoiceGenderClassifier:
    """Classify aggregated speaker audio as male, female, or unknown."""

    def __init__(self, model_id=GENDER_MODEL_ID):
        torch.set_num_threads(1)
        try:
            torch.set_num_interop_threads(1)
        except RuntimeError:
            # The setting may already be fixed by an embedding application.
            pass
        # The model is pre-downloaded in the local Hugging Face cache.  Staying
        # offline avoids network retries and makes this pipeline deterministic.
        self.feature_extractor = AutoFeatureExtractor.from_pretrained(
            model_id,
            local_files_only=True,
        )
        self.model = AutoModelForAudioClassification.from_pretrained(
            model_id,
            local_files_only=True,
        )
        self.model.eval()

    def classify(self, waveform, sample_rate):
        audio = waveform.squeeze().cpu().numpy().astype(np.float32)
        if audio.size == 0:
            return {"gender": "unknown", "confidence": 0.0}

        expected_rate = self.feature_extractor.sampling_rate
        if sample_rate != expected_rate:
            audio = torchaudio.functional.resample(
                torch.from_numpy(audio).unsqueeze(0),
                sample_rate,
                expected_rate,
            ).squeeze(0).numpy()
            sample_rate = expected_rate
        inputs = self.feature_extractor(audio, sampling_rate=sample_rate, return_tensors="pt")
        with torch.no_grad():
            probabilities = torch.softmax(self.model(**inputs).logits[0], dim=-1)
        best_index = int(torch.argmax(probabilities))
        label = self.model.config.id2label[best_index].lower()
        confidence = float(probabilities[best_index])
        if "female" in label:
            return {"gender": "female", "confidence": confidence}
        if "male" in label:
            return {"gender": "male", "confidence": confidence}
        raise ValueError(f"未识别的性别分类标签: {label}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("audio_path")
    args = parser.parse_args()

    waveform, sample_rate = torchaudio.load(args.audio_path)
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)
    print(json.dumps(VoiceGenderClassifier().classify(waveform, sample_rate)))


if __name__ == "__main__":
    main()
