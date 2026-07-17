CREATE OR REPLACE FUNCTION search_story(
    p_person TEXT,
    p_episode TEXT,
    p_limit INT DEFAULT 100
)
RETURNS TABLE (
    story TEXT,
    url TEXT
)
LANGUAGE sql
AS $$
    SELECT 
        story,
        url
    FROM public.story
    WHERE person = p_person
      AND episode = p_episode
    ORDER BY id ASC
    LIMIT p_limit;
$$;