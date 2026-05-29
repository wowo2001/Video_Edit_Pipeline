
import os
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
import pickle

from config import SCOPES
from core.path import ProjectPaths

def upload_to_drive(file_path, folder_name=None, filename=None):
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

    # 👇 自动创建/获取文件夹
    print(f"🔍 查找文件夹: {folder_name}")
    folder_id = None
    if folder_name:
        folder_id = _get_or_create_folder(service, folder_name)
        print("\n✅ 文件夹 ID:", folder_id)

    file_metadata = {
        "name": filename or os.path.basename(file_path)
    }

    if folder_id:
        file_metadata["parents"] = [folder_id]

    media = MediaFileUpload(file_path, resumable=True)

    file = service.files().create(
        body=file_metadata,
        media_body=media,
        fields="id"
    ).execute()

    return file.get("id")

def _get_or_create_folder(service, folder_name, parent_id=None):
    # 1. 查找文件夹
    query = (
        "mimeType='application/vnd.google-apps.folder' "
        f"and name='{folder_name}' "
        "and trashed=false"
    )

    if parent_id:
        query += f" and '{parent_id}' in parents"

    results = service.files().list(
        q=query,
        spaces="drive",
        fields="files(id, name)"
    ).execute()

    files = results.get("files", [])

    if files:
        return files[0]["id"]

    # 2. 不存在 → 创建
    metadata = {
        "name": folder_name,
        "mimeType": "application/vnd.google-apps.folder"
    }

    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(
        body=metadata,
        fields="id"
    ).execute()

    return folder["id"]