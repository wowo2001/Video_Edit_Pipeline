"""Start or reuse the local commentary web backend for the main Streamlit UI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:8510'


def ready():
    try:
        with urlopen(URL + '/api/sources', timeout=1) as response:
            data = json.load(response)
        return isinstance(data, dict) and all(topic in data for topic in ('房产', '移民', '税务', '经济'))
    except (OSError, ValueError):
        return False


def ensure_running():
    if ready():
        return URL
    log_path = ROOT / 'work/news_comment_ui/server.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open('a') as log:
        process = subprocess.Popen(
            [sys.executable, '-u', str(ROOT/'experiments/news_commentary/ui_demo/server.py')],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
            env={**os.environ, 'PATH':str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH','')})
    for _ in range(40):
        if ready():
            return URL
        if process.poll() is not None:
            raise RuntimeError(f'新闻评论服务启动失败，请查看 {log_path}')
        time.sleep(.25)
    raise RuntimeError(f'新闻评论服务未就绪，请查看 {log_path}')


if __name__ == '__main__':
    print('新闻评论后台已就绪：' + ensure_running())
