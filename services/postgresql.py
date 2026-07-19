from matplotlib import text
import psycopg
from pgvector.psycopg import register_vector
from config import POSTGRESQL_USER, POSTGRESQL_PASSWORD
from services.text_embedding_service import TextEmbeddingService


class PostgresClient:

    def __init__(
        self,
        host="localhost",
        port=5432
    ):
        self.conn = psycopg.connect(
            dbname="video",
            user=POSTGRESQL_USER,
            password=POSTGRESQL_PASSWORD,
            host=host,
            port=port
        )
        register_vector(self.conn)


    def insert_video_transcript(
        self,
        start_time,
        end_time,
        text,
        url,
        episode,
        speaker,
        embedding
    ):
        with self.conn.cursor() as cur:

            cur.execute(
                """
                SELECT insert_video_transcript(
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
                """,
                (
                    start_time,
                    end_time,
                    text,
                    url,
                    episode,
                    speaker,
                    str(embedding)
                )
            )

            row_id = cur.fetchone()[0]

        self.conn.commit()

        return row_id
    
    def insert_story(
    self,
    story,
    url,
    episode,
    person,
    embedding
    ):
        with self.conn.cursor() as cur:

            cur.execute(
            """
            SELECT insert_story(
                %s,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                story,
                url,
                episode,
                person,
                str(embedding)
            )
            )

            row_id = cur.fetchone()[0]

        self.conn.commit()

        return row_id
    
    def search_video_transcripts(
    self,
    text,
    limit=5,
    episode=None,
    speaker=None,
    url=None,
):
        text_embedding = TextEmbeddingService().encode(text)

        with self.conn.cursor() as cur:
            cur.execute(
            """
            SELECT *
            FROM search_video_transcripts(
                %s::vector,
                %s,
                %s,
                %s,
                %s
            )
            """,
            (
                str(text_embedding),
                limit,
                episode,
                speaker,
                url,
            ),
        )
            rows = cur.fetchall()

        return rows
    

    def search_story(
        self,
        person,
        episode=None,
        limit=5
    ):
        with self.conn.cursor() as cur:
            cur.execute(
            """
            SELECT *
            FROM search_story(
                %s,
                %s,
                %s
            )
            """,
            (
                person,
                episode,
                limit,
            ),
        )

            rows = cur.fetchall()

        return rows
    
    def get_context_transcripts(
    self,
    url,
    text,
    context=10
):
        with self.conn.cursor() as cur:
            cur.execute(
            """
            SELECT *
            FROM search_context_transcripts(
                %s,
                %s,
                %s
            )
            ORDER BY id ASC
            """,
            (
                url,
                text,
                context,
            )
        )

            rows = cur.fetchall()

        return rows



    def close(self):
        self.conn.close()

    def insert_scene(
        self,
        drama_title,
        video_url,
        title,
        event,
        summary,
        embedding
    ):
        sql = """
        INSERT INTO scene (
            drama_title,
            video_url,
            title,
            event,
            summary,
            summary_embedding
        )
        VALUES (
            %s,%s,%s,%s,%s,%s
        )
        RETURNING id;
        """

        with self.conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    drama_title,
                    video_url,
                    title,
                    event,
                    summary,
                    embedding
                )
            )

            scene_id = cur.fetchone()[0]

        self.conn.commit()

        return scene_id
    
    def get_or_create_character(
        self,
        drama_title,
        name
    ):
        # 先查询
        sql = """
        SELECT id
        FROM character
        WHERE drama_title = %s
        AND name = %s;
        """

        with self.conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    drama_title,
                    name
                )
            )

            row = cur.fetchone()

            if row:
                return row[0]


        # 不存在，创建
        sql = """
        INSERT INTO character (
            drama_title,
            name
        )
        VALUES (
            %s,%s
        )
        RETURNING id;
        """

        with self.conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    drama_title,
                    name
                )
            )

            character_id = cur.fetchone()[0]

        self.conn.commit()

        return character_id
    
    def insert_scene_character(
        self,
        scene_id,
        drama_title,
        character_id,
        character_summary
    ):
        sql = """
        INSERT INTO scene_character (
            scene_id,
            drama_title,
            character_id,
            character_summary
        )
        VALUES (
            %s,%s,%s,%s
        );
        """

        with self.conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    scene_id,
                    drama_title,
                    character_id,
                    character_summary
                )
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
        embedding
    ):
        sql = """
        INSERT INTO subtitle (
            drama_title,
            video_url,
            start_time,
            end_time,
            content,
            speaker,
            scene_id,
            embedding
        )
        VALUES (
            %s,%s,%s,%s,%s,%s,%s,%s
        );
        """

        with self.conn.cursor() as cur:
            cur.execute(
                sql,
                (
                drama_title,
                video_url,
                start_time,
                end_time,
                content,
                speaker,
                scene_id,
                embedding
                )
            )

        self.conn.commit()

    def search_scene(
        self,
        query_embedding,
        drama_title=None,
        limit=10,
    ):
        sql = """
        SELECT
            id,
            drama_title,
            video_url,
            title,
            event,
            summary
        FROM scene
        WHERE
            (%s::TEXT IS NULL OR drama_title = %s::TEXT)
        ORDER BY
            summary_embedding <=> %s::vector
        LIMIT %s;
        """

        with self.conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    drama_title,
                    drama_title,
                    query_embedding,
                    limit,
                ),
            )

            return cur.fetchall()
        
    def get_subtitles_by_scene_id(
        self,
        scene_id
    ):
        sql = """
        SELECT
            start_time,
            end_time,
            content,
            speaker
        FROM subtitle
        WHERE scene_id = %s
        ORDER BY start_time ASC;
        """

        with self.conn.cursor() as cur:
            cur.execute(
                sql,
                (
                    scene_id,
                )
            )

            return cur.fetchall()
        


    def search_scene_transcripts(
        self,
        text,
            scene_id,
    limit=5
    ):

        text_embedding = TextEmbeddingService().encode(
            text
        )


        with self.conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    id,
                    scene_id,
                    start_time,
                    end_time,
                    content,
                    speaker,
                    1 - (embedding <=> %s::vector) AS similarity

                FROM subtitle

                WHERE scene_id = %s

                ORDER BY embedding <=> %s::vector

                LIMIT %s
                """,
                (
                    str(text_embedding),
                    scene_id,
                    str(text_embedding),
                    limit
                )
            )

            rows = cur.fetchall()


        return rows
