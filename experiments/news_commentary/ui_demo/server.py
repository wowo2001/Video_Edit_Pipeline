"""Local demo server; only source configuration is persisted, no news fetching."""
import json
import os
import sys
import uuid
import subprocess
from datetime import datetime
from threading import Thread
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from threading import Lock

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parents[2]))
from experiments.news_commentary.ui_demo.data import fetch_news, group_news
JOBS = {}
RUNS = {}
CONFIG = ROOT / 'sources.json'
LOCK = Lock()
TOPICS = ('房产', '移民', '税务', '经济')
MODULES = ('youtube', 'afr', 'the_australian', 'nsw_gov')

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def reply(self, status, payload):
        data = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split('?', 1)[0] in ('/news_comment', '/news_comment/'):
            self.path = '/index.html'
        if self.path.startswith('/api/runs/'):
            run=RUNS.get(self.path.rsplit('/',1)[-1])
            if not run:return self.reply(404,{'error':'任务不存在'})
            with run['path'].open('rb') as file:
                file.seek(0,2);size=file.tell();file.seek(max(0,size-64000))
                text=file.read().decode('utf-8',errors='replace')
            code=run['process'].poll()
            return self.reply(200,{'text':text,'status':'running' if code is None else ('completed' if code==0 else 'failed'),'exit_code':code})
        if self.path.startswith('/api/jobs/'):
            job = JOBS.get(self.path.rsplit('/',1)[-1])
            return self.reply(200 if job else 404, job or {'error':'任务不存在'})
        if self.path == '/api/sources':
            with LOCK:
                self.reply(200, json.loads(CONFIG.read_text()))
        else:
            super().do_GET()

    def do_POST(self):
        if self.path not in ('/api/sources','/api/fetch','/api/group','/api/start'):
            return self.reply(404, {'error': '接口不存在'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 1000000:
                raise ValueError('请求大小无效')
            body = json.loads(self.rfile.read(length))
            if self.path in ('/api/fetch','/api/group'):
                job_id=uuid.uuid4().hex
                JOBS[job_id]={'status':'running','logs':[]}
                action=fetch_news if self.path=='/api/fetch' else group_news
                def execute():
                    def log(message):JOBS[job_id]['logs'].append(datetime.now().strftime('[%H:%M:%S] ')+message)
                    try:JOBS[job_id].update(status='completed',result=action(body,log))
                    except Exception as error:
                        log('失败：'+str(error));JOBS[job_id].update(status='failed',error=str(error))
                Thread(target=execute,daemon=True).start()
                return self.reply(202,{'job_id':job_id})
            if self.path == '/api/start':
                items=list({r['id']:r for r in body['items']}.values())
                if not items:raise ValueError('请选择素材')
                job=Path('work/news_ui_queue')/('commentary_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8])
                job.mkdir(parents=True)
                task={'title':body.get('title') or '新闻评论','angle':body.get('angle',''),'广告':body.get('advertisement',''),
                      'sources':[{'url':r['url'],'title':r['title'],'source_type':r['type'],'publisher':r['publisher']} for r in items]}
                task_path=job/'commentary_tasks.json';task_path.write_text(json.dumps(task,ensure_ascii=False,indent=2))
                command=[sys.executable,'-u','-m','experiments.news_commentary.pipeline','--tasks',str(task_path.resolve()),'--workspace',str((job/'workspace').resolve())]
                if body.get('upload'):command.append('--upload')
                with (job/'commentary.log').open('w') as output:
                    process=subprocess.Popen(command,stdout=output,stderr=subprocess.STDOUT,start_new_session=True,
                        env={**os.environ,'PATH':str(Path(sys.executable).parent)+os.pathsep+os.environ.get('PATH','')})
                RUNS[job.name]={'process':process,'path':job/'commentary.log'}
                return self.reply(200,{'pid':process.pid,'log':str(job/'commentary.log'),'run_id':job.name})
            topic, sources = body.get('topic'), body.get('sources')
            if topic not in TOPICS or not isinstance(sources, list):
                raise ValueError('主题或来源格式无效')
            for source in sources:
                if (not isinstance(source, dict) or source.get('module') not in MODULES
                    or not isinstance(source.get('url'), str)
                    or not isinstance(source.get('label'), str)
                    or type(source.get('enabled')) is not bool):
                    raise ValueError('来源配置无效')
                source['days'] = int(source.get('days', 3))
                if not 1 <= source['days'] <= 30:
                    raise ValueError('时间范围必须为1至30天')
            with LOCK:
                data = json.loads(CONFIG.read_text())
                data[topic] = sources
                temporary = CONFIG.with_suffix('.tmp')
                temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
                os.replace(temporary, CONFIG)
            self.reply(200, {'saved': True})
        except (ValueError, TypeError) as error:
            self.reply(400, {'error': str(error)})
        except OSError:
            self.reply(500, {'error': '服务器无法写入来源配置'})

if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8510), Handler).serve_forever()
