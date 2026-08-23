import psycopg
from pgvector.psycopg import register_vector

from config import POSTGRESQL_PASSWORD, POSTGRESQL_USER


class PostgresClient:
    def __init__(self, host="localhost", port=5432):
        self.conn = psycopg.connect(
            dbname="video",
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD,
            host=host,
            port=port,
        )
        register_vector(self.conn)

    def close(self):
        self.conn.close()

    def upsert_source_story(self, drama_title, video_url, summary, embedding):
        sql = """
            INSERT INTO source_story (
                drama_title, video_url, summary, summary_embedding
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (drama_title, video_url)
            DO UPDATE SET
                summary = EXCLUDED.summary,
                summary_embedding = EXCLUDED.summary_embedding
            RETURNING id;
        """
        with self.conn.cursor() as cursor:
            cursor.execute(sql, (drama_title, video_url, summary, embedding))
            story_id = cursor.fetchone()[0]

        self.conn.commit()
        return story_id

    def insert_scene(
        self,
        drama_title,
        video_url,
        title,
        event,
        summary,
        embedding,
        story_id,
    ):
        sql = """
            INSERT INTO scene (
                drama_title, video_url, title, event, summary, summary_embedding, story_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id;
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                sql,
                (drama_title, video_url, title, event, summary, embedding, story_id),
            )
            scene_id = cursor.fetchone()[0]

        self.conn.commit()
        return scene_id

    def get_or_create_character(self, drama_title, name):
        select_sql = """
            SELECT id
            FROM character
            WHERE drama_title = %s AND name = %s;
        """
        with self.conn.cursor() as cursor:
            cursor.execute(select_sql, (drama_title, name))
            row = cursor.fetchone()

        if row:
            return row[0]

        insert_sql = """
            INSERT INTO character (drama_title, name)
            VALUES (%s, %s)
            RETURNING id;
        """
        with self.conn.cursor() as cursor:
            cursor.execute(insert_sql, (drama_title, name))
            character_id = cursor.fetchone()[0]

        self.conn.commit()
        return character_id

    def insert_scene_character(
        self,
        scene_id,
        drama_title,
        character_id,
        character_summary,
    ):
        sql = """
            INSERT INTO scene_character (
                scene_id, drama_title, character_id, character_summary
            )
            VALUES (%s, %s, %s, %s);
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                sql,
                (scene_id, drama_title, character_id, character_summary),
            )

        self.conn.commit()

    def insert_subtitle(
        self,
        drama_title,
        video_url,
        start_time,
        end_time,
        content,
        speaker,
        scene_id,
        embedding,
    ):
        sql = """
            INSERT INTO subtitle (
                drama_title, video_url, start_time, end_time,
                content, speaker, scene_id, embedding
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                sql,
                (
                    drama_title,
                    video_url,
                    start_time,
                    end_time,
                    content,
                    speaker,
                    scene_id,
                    embedding,
                ),
            )

        self.conn.commit()

    def search_scene(self, query_embedding, drama_title=None, limit=30):
        sql = """
            SELECT id, drama_title, video_url, title, event, summary
            FROM scene
            WHERE (%s::TEXT IS NULL OR drama_title = %s::TEXT)
            ORDER BY summary_embedding <=> %s::vector
            LIMIT %s;
        """
        with self.conn.cursor() as cursor:
            cursor.execute(
                sql,
                (drama_title, drama_title, query_embedding, limit),
            )
            return cursor.fetchall()

    def search_scene_by_id(self, scene_id, drama_title=None):
        sql = """
            SELECT id, drama_title, video_url, title, event, summary
            FROM scene
            WHERE id = %s
              AND (%s::TEXT IS NULL OR drama_title = %s::TEXT);
        """
        with self.conn.cursor() as cursor:
            cursor.execute(sql, (scene_id, drama_title, drama_title))
            return cursor.fetchone()

    def get_subtitles_by_scene_id(self, scene_id):
        sql = """
            SELECT start_time, end_time, content, speaker
            FROM subtitle
            WHERE scene_id = %s
            ORDER BY start_time ASC;
        """
        with self.conn.cursor() as cursor:
            cursor.execute(sql, (scene_id,))
            return cursor.fetchall()
