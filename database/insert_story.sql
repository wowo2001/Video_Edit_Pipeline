CREATE OR REPLACE FUNCTION insert_story(
    p_story TEXT,
    p_url TEXT,
    p_episode TEXT,
    p_person TEXT,
    p_embedding vector(512)
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    new_id BIGINT;
BEGIN

    INSERT INTO story
    (
        story,
        url,
        episode,
        person,
        text_embedding
    )
    VALUES
    (
        p_story,
        p_url,
        p_episode,
        p_person,
        p_embedding
    )
    RETURNING id INTO new_id;

    RETURN new_id;

END;
$$;