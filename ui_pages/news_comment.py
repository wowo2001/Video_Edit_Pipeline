"""Unified entrypoint for the commentary workbench."""
from urllib.parse import urlsplit
from pathlib import Path
import hashlib
import streamlit as st
import streamlit.components.v1 as components
from services.news_comment_server import ensure_running

# The workbench owns its forms, selections and logs; do not mix Streamlit state.
st.markdown('''<style>
.block-container {padding: 0 0 1rem; max-width: 100%;}
iframe {border: 0;}
</style>''', unsafe_allow_html=True)
try:
    ensure_running()
except RuntimeError as error:
    st.error(str(error))
else:
    # Use the address the visitor used, including when visiting from a phone.
    hostname = urlsplit('//' + st.context.headers.get('Host', 'localhost:8501')).hostname
    host = f'[{hostname}]' if ':' in hostname else hostname
    page_file = Path(__file__).resolve().parents[1] / 'experiments/news_commentary/ui_demo/index.html'
    version = hashlib.sha256(page_file.read_bytes()).hexdigest()[:12]
    components.iframe(f'http://{host}:8510/news_comment?v={version}', height=1500, scrolling=True)
