CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE subtitle (
    id BIGSERIAL PRIMARY KEY,

    drama_title TEXT NOT NULL,

    video_url TEXT NOT NULL,

    start_time BIGINT NOT NULL,

    end_time BIGINT NOT NULL,

    content TEXT NOT NULL,

    speaker TEXT NOT NULL,

    scene_id BIGINT,

    embedding VECTOR(512),

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);