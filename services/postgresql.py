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
    
