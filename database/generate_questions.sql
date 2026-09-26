SELECT
  s.id AS scene_id,
  s.summary AS scene_summary,
  ss.summary AS source_story_summary
FROM public.scene AS s
JOIN public.source_story AS ss
  ON s.drama_title = ss.drama_title
 AND s.video_url = ss.video_url
WHERE s.drama_title = '雍正王朝'
  AND s.id > 1173;