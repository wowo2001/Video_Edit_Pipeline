from services.postgresql import PostgresClient

result = PostgresClient().search_video_transcripts(text="这回许是个有来头的人物", limit=5)    
print(result)