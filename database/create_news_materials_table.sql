-- Run this script in the news database.
-- Articles: content.text contains the cleaned full text.
-- Videos: content.transcript contains subtitles after sentence merging and
-- speaker identification. No local media paths or metadata column are stored.
-- Set updated_at = NOW() explicitly when updating a record.
BEGIN;

CREATE TABLE public.news_materials (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    title TEXT NOT NULL,
    url TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL
        CHECK (source_type IN ('article', 'video')),
    publisher TEXT,
    language TEXT,
    published_at TIMESTAMPTZ,
    content JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CHECK (
        (
            source_type = 'article'
            AND content ? 'text'
            AND jsonb_typeof(content->'text') = 'string'
        )
        OR
        (
            source_type = 'video'
            AND content ? 'transcript'
            AND jsonb_typeof(content->'transcript') = 'object'
        )
    )
);

CREATE INDEX news_materials_published_at_idx
    ON public.news_materials (published_at DESC);

COMMIT;
