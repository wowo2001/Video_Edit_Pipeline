CREATE OR REPLACE FUNCTION search_context_transcripts(
    p_url TEXT,
    p_text TEXT,
    p_context INT DEFAULT 10
)
RETURNS TABLE (
    id BIGINT,
    start_time INTEGER,
    end_time INTEGER,
    text TEXT,
    url TEXT,
    episode TEXT,
    speaker TEXT
)
LANGUAGE sql
AS $$
WITH target AS (
    SELECT id
    FROM video_transcripts
    WHERE url = p_url
      AND text = p_text
    LIMIT 1
)
SELECT
    v.id,
    v.start_time,
    v.end_time,
    v.text,
    v.url,
    v.episode,
    v.speaker
FROM video_transcripts v,
     target t
WHERE v.url = p_url
  AND v.id BETWEEN 
      t.id - p_context 
      AND 
      t.id + p_context
ORDER BY v.id ASC;
$$;