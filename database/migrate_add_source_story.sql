BEGIN;

CREATE TABLE IF NOT EXISTS source_story (
    id BIGSERIAL PRIMARY KEY,
    drama_title TEXT NOT NULL,
    video_url TEXT NOT NULL,
    summary TEXT NOT NULL,
    summary_embedding VECTOR(512),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT source_story_drama_video_unique UNIQUE (drama_title, video_url)
);

ALTER TABLE scene
    ADD COLUMN IF NOT EXISTS story_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'scene_story_id_fkey'
    ) THEN
        ALTER TABLE scene
            ADD CONSTRAINT scene_story_id_fkey
            FOREIGN KEY (story_id) REFERENCES source_story(id)
            ON DELETE RESTRICT;
    END IF;
END;
$$;

CREATE INDEX IF NOT EXISTS scene_story_id_idx ON scene (story_id);

COMMIT;
