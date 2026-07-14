CREATE OR REPLACE FUNCTION search_video_transcripts(
    p_embedding vector(512),
    p_limit INTEGER DEFAULT 5
)
RETURNS TABLE (
    id BIGINT,
    start_time INTEGER,
    end_time INTEGER,
    text TEXT,
    url TEXT,
    episode TEXT,
    speaker TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN

    RETURN QUERY
    SELECT
        vt.id,
        vt.start_time,
        vt.end_time,
        vt.text,
        vt.url,
        vt.episode,
        vt.speaker,
        1 - (vt.text_embedding <=> p_embedding) AS similarity
    FROM video_transcripts vt
    ORDER BY vt.text_embedding <=> p_embedding
    LIMIT p_limit;

END;
$$;