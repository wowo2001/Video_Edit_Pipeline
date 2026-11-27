"""Loopback-only selection UI. Saving releases the batch; closing never auto-skips."""
import copy
import json
import re
import secrets
import subprocess
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from core.captions import DEFAULT_CAPTION_LAYOUT, overlay_layout
from pipeline.final_render import render_final_video

from pipeline.source_preprocess import (
    default_profile, encode_master, probe_source, save_json, validate_profile,
)

PAGE = Path(__file__).resolve().parents[1]/"ui_pages/source_preprocess.html"


def selection_server(source, drama_title, profile_path, *, initial=None, batch_count=1,
                     configure_only=False, initial_time=60):
    """Return a server/state pair, also usable by headless integration tests."""
    source, profile_path = Path(source).resolve(), Path(profile_path)
    info = probe_source(source)
    initial = copy.deepcopy(initial or default_profile(info, drama_title))
    initial.setdefault("caption_layout", dict(DEFAULT_CAPTION_LAYOUT))
    initial["overlay_layout"] = overlay_layout(initial.get("overlay_layout"))
    validate_profile(initial, drama_title)
    token = secrets.token_urlsafe(24)
    state = {"done": threading.Event(), "profile": None, "cancelled": False,
             "frames": {}, "initial": initial, "info": info}
    frame_lock = threading.Lock()
    preview_lock = threading.Lock()
    preview_path = profile_path.parent/"preview"/f"{profile_path.stem}.mp4"

    def submitted(body):
        profile = copy.deepcopy(initial)
        for key in ("crop", "blur_regions", "crf"):
            profile[key] = body[key]
        profile["preset"] = body.get("preset", initial["preset"])
        profile["caption_layout"] = body.get("caption_layout", initial["caption_layout"])
        profile["overlay_layout"] = overlay_layout(body.get("overlay_layout", initial["overlay_layout"]))
        return validate_profile(profile, drama_title)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def respond(self, body, content_type="application/json; charset=utf-8", status=200):
            if isinstance(body, (dict, list)):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def authorized(self):
            query = parse_qs(urlparse(self.path).query)
            return secrets.compare_digest(query.get("token", [""])[0], token)

        def do_GET(self):
            if not self.authorized():
                return self.respond({"error": "无效的工具访问地址"}, status=403)
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            try:
                if parsed.path == "/":
                    return self.respond(PAGE.read_text(encoding="utf-8").replace("__TOKEN__", token).encode("utf-8"), "text/html; charset=utf-8")
                if parsed.path == "/source_preprocess.js":
                    return self.respond(PAGE.with_suffix(".js").read_bytes(), "text/javascript; charset=utf-8")
                if parsed.path == "/caption-font.otf":
                    from core.ffmpeg import FONT_PATH
                    return self.respond(FONT_PATH.read_bytes(), "font/otf")
                if parsed.path == "/api/meta":
                    return self.respond({"title": drama_title, "batch_count": batch_count,
                        "source": source.name, "info": info, "profile": initial,
                        "configure_only": configure_only, "initial_time": initial_time,
                        "profile_path": str(profile_path.resolve())})
                if parsed.path == "/frame":
                    time = max(0, min(float(query.get("t", ["0"])[0]), info["duration"]-.05))
                    width = 320 if query.get("thumb") == ["1"] else min(1280, info["width"])
                    key = (round(time, 3), width)
                    with frame_lock:
                        if key not in state["frames"]:
                            image = subprocess.run(["ffmpeg", "-v", "error", "-ss", str(time),
                                "-i", str(source), "-frames:v", "1", "-vf",
                                f"scale={info['width']}:{info['height']},setsar=1,scale={width}:-2",
                                "-f", "image2pipe", "-c:v", "mjpeg", "pipe:1"],
                                capture_output=True, timeout=60, check=True).stdout
                            if len(state["frames"]) >= 100:
                                state["frames"].pop(next(iter(state["frames"])))
                            state["frames"][key] = image
                        image = state["frames"][key]
                    return self.respond(image, "image/jpeg")
                if parsed.path == "/preview.mp4" and preview_path.exists():
                    # Native video controls need byte ranges for reliable seeking.
                    size = preview_path.stat().st_size
                    requested = self.headers.get("Range")
                    start, end, status = 0, size-1, 200
                    if requested:
                        match = re.fullmatch(r"bytes=(\d+)-(\d*)", requested)
                        if not match:
                            return self.respond(b"", status=416)
                        start = int(match[1])
                        end = min(size-1, int(match[2]) if match[2] else size-1)
                        if start > end:
                            return self.respond(b"", status=416)
                        status = 206
                    self.send_response(status)
                    self.send_header("Content-Type", "video/mp4")
                    self.send_header("Accept-Ranges", "bytes")
                    self.send_header("Content-Length", str(end-start+1))
                    if status == 206:
                        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
                    self.end_headers()
                    with preview_path.open("rb") as stream:
                        stream.seek(start)
                        remaining = end-start+1
                        while remaining:
                            chunk = stream.read(min(65536, remaining))
                            if not chunk:
                                break
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                    return
                return self.respond({"error": "没有此资源"}, status=404)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as error:
                self.respond({"error": str(error)}, status=400)

        def do_POST(self):
            if not self.authorized():
                return self.respond({"error": "无效的工具访问地址"}, status=403)
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 65536:
                    raise ValueError("请求大小无效")
                body = json.loads(self.rfile.read(length))
                route = urlparse(self.path).path
                if route == "/api/cancel":
                    state["cancelled"] = True
                    self.respond({"ok": True})
                    state["done"].set()
                    return
                profile = submitted(body)
                if route == "/api/preview":
                    with preview_lock:
                        start = max(0, min(float(body.get("time", 0)), max(0, info["duration"]-3)))
                        master_preview = preview_path.with_name(preview_path.stem+"_master.mp4")
                        encode_master(source, master_preview, profile, info, start=start, seconds=3)
                        sample = str(body.get("caption_sample", "为什么他明明知道有危险，却还要主动回到这里？"))[:2000]
                        sample_srt = preview_path.with_suffix(".srt")
                        sample_srt.write_text("1\n00:00:00,000 --> 00:00:03,000\n"+sample+"\n\n", encoding="utf-8")
                        render_final_video(master_preview, preview_path, sample_srt, drama_title,
                            "副标题预览", profile["caption_layout"],
                            [{"start_time": 0, "text": "这一步，他到底想干什么？"}],
                            speed=1, text_layout=profile["overlay_layout"])
                    return self.respond({"ok": True})
                if route == "/api/save":
                    save_json(profile_path, profile)
                    self.respond({"ok": True})
                    state["profile"] = profile
                    state["done"].set()
                    return
                self.respond({"error": "没有此操作"}, status=404)
            except Exception as error:
                self.respond({"error": str(error)}, status=400)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    state["url"] = f"http://127.0.0.1:{server.server_port}/?token={token}"
    return server, state


def choose_profile(source, drama_title, profile_path, **options):
    server, state = selection_server(source, drama_title, profile_path, **options)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"整批素材选区工具：{state['url']}", flush=True)
    action = "当前仅保存配置，不会制作或上传。" if options.get("configure_only") else "保存后自动继续全部集数。"
    print(action + "关闭网页不会自动跳过；也可点击取消退出。", flush=True)
    try:
        webbrowser.open(state["url"])
        while not state["done"].wait(.5):
            pass
        if state["cancelled"]:
            raise KeyboardInterrupt("已取消整批处理")
        return state["profile"]
    finally:
        server.shutdown()
        server.server_close()
