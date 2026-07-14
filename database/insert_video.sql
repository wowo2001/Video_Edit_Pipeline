CREATE OR REPLACE FUNCTION insert_video_transcript(
    p_start_time INTEGER,
    p_end_time INTEGER,
    p_text TEXT,
    p_url TEXT,
    p_episode TEXT,
    p_speaker TEXT,
    p_embedding vector(512)
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    new_id BIGINT;
BEGIN

    INSERT INTO video_transcripts
    (
        start_time,
        end_time,
        text,
        url,
        episode,
        speaker,
        text_embedding
    )
    VALUES
    (
        p_start_time,
        p_end_time,
        p_text,
        p_url,
        p_episode,
        p_speaker,
        p_embedding
    )
    RETURNING id INTO new_id;

    RETURN new_id;

END;
$$;