from sentence_transformers import SentenceTransformer


class TextEmbeddingService:

    def __init__(self):
        self.model = SentenceTransformer(
            "BAAI/bge-small-zh-v1.5"
        )


    def encode(self, text):
        embedding = self.model.encode(
            text,
            normalize_embeddings=True
        )

        return embedding.tolist()