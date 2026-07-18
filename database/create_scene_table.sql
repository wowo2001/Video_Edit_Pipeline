CREATE TABLE scene (
    id BIGSERIAL PRIMARY KEY,

    drama_title TEXT NOT NULL,

    video_url TEXT NOT NULL,

    title TEXT NOT NULL,

    event TEXT,

    summary TEXT NOT NULL,

    summary_embedding VECTOR(512),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);