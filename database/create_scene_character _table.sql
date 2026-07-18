CREATE TABLE scene_character (
    id BIGSERIAL PRIMARY KEY,

    drama_title TEXT NOT NULL,

    scene_id BIGINT NOT NULL REFERENCES scene(id),

    character_id BIGINT NOT NULL REFERENCES character(id),

    character_summary TEXT,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);