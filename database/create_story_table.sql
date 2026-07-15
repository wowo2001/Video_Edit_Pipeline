CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE story (
    id BIGSERIAL PRIMARY KEY,
    story TEXT NOT NULL,
    url TEXT,
    episode TEXT,
    person TEXT,
    text_embedding vector(512),
    created_at TIMESTAMP DEFAULT NOW()
);