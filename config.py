import os


def _setting(name: str) -> str | None:
    """Read an environment variable, falling back to local Streamlit secrets."""
    value = os.getenv(name)
    if value:
        return value

    try:
        import streamlit as st

        secret = st.secrets.get(name)
        return str(secret) if secret else None
    except (ImportError, FileNotFoundError, KeyError):
        return None

VOLC_SECRET = os.getenv("VOLC_KEY")
VOLC_APPID = "test"
# 兼容旧项目配置 OPENAI_KEY，并支持 OpenAI 标准环境变量名。
OPENAI_API_KEY = _setting("OPENAI_API_KEY") or _setting("OPENAI_KEY")
YOUTUBE_API_KEY = _setting("YOUTUBE_API_KEY")
ALI_API_KEY = os.getenv("ALI_API_KEY")
SPEAKER = "zh_male_jieshuoxiaoming_uranus_bigtts"
SCOPES = ["https://www.googleapis.com/auth/drive.file"]
HF_TOKEN = os.getenv("HF_TOKEN")
POSTGRESQL_USER = os.getenv("POSTGRESQL_USER")
POSTGRESQL_PASSWORD = os.getenv("POSTGRESQL_PASSWORD")
