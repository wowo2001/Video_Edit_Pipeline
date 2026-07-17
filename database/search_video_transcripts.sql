CREATE OR REPLACE FUNCTION search_video_transcripts(
    p_embedding vector(512),
    p_limit INTEGER DEFAULT 5,
    p_episode TEXT DEFAULT NULL,
    p_speaker TEXT DEFAULT NULL,
    p_url TEXT DEFAULT NULL
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
    WHERE
        (p_episode IS NULL OR vt.episode = p_episode)
        AND (p_speaker IS NULL OR vt.speaker = p_speaker)
        AND (p_url IS NULL OR vt.url = p_url)
    ORDER BY vt.text_embedding <=> p_embedding
    LIMIT p_limit;
END;
$$;