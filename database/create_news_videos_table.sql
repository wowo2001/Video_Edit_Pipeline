-- Run in the news database. Only landscape publications are stored.
-- plan includes tags; subtitles use final video timestamps in milliseconds.
BEGIN;

CREATE TABLE IF NOT EXISTS public.news_videos (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    video_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    plan JSONB NOT NULL,
    subtitles JSONB NOT NULL,
    published_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMIT;
