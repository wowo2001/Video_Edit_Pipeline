-- Existing rows remain nullable until their episode has been verified.
-- Keep existing IDs, foreign keys, INSERT/upsert behavior and commits.
ALTER TABLE source_story ADD COLUMN IF NOT EXISTS episode integer;
ALTER TABLE scene ADD COLUMN IF NOT EXISTS episode integer;
ALTER TABLE subtitle ADD COLUMN IF NOT EXISTS episode integer;
