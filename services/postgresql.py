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
    
    def search_video_transcripts(
    self,
    text,
    limit=5
    ):
        text_embedding = TextEmbeddingService().encode(text)
        with self.conn.cursor() as cur:
            cur.execute(
            """
            SELECT *
            FROM search_video_transcripts(
                %s::vector,
                %s
            )
            """,
            (
                str(text_embedding),
                limit
            )
        )
            rows = cur.fetchall()

        return rows


    def close(self):
        self.conn.close()