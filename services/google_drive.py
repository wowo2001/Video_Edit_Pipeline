
import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

from config import SCOPES
from core.path import ProjectPaths

def upload_to_drive(file_path, filename=None):
    creds = None

    with open(ProjectPaths().pickle, "rb") as token:
        creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                 ProjectPaths().credentials, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(ProjectPaths().pickle, "wb") as token:
            pickle.dump(creds, token)

    service = build("drive", "v3", credentials=creds)

    file_metadata = {"name": filename or os.path.basename(file_path)}
    media = MediaFileUpload(file_path, resumable=True)

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()

    print("✅ Uploaded File ID:", file.get("id"))