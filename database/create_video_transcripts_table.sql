CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE video_transcripts (
    id BIGSERIAL PRIMARY KEY,
    start_time INTEGER NOT NULL,
    end_time INTEGER NOT NULL,
    text TEXT NOT NULL,
    url TEXT,
    episode TEXT,
    speaker TEXT,
    text_embedding vector(512),
    created_at TIMESTAMP DEFAULT NOW()
);