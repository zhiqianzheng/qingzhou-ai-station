"""Local, opt-in conversation recorder. Never stores HTTP headers or credentials."""
import asyncio
from contextlib import contextmanager
import gzip
import json
import os
import sqlite3
import time
from pathlib import Path
from aiohttp import ClientSession, ClientTimeout, WSMsgType, web
from key_manager import fingerprint

LIMIT = 2 * 1024 * 1024
HOPS = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
        'te', 'trailer', 'transfer-encoding', 'upgrade', 'content-length', 'host'}
NOTICE = '本中转站开启对话记录时，管理员可以查看并保存你发送的内容和 AI 回复。请勿发送不愿被管理员查看的信息。'

class Store:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.config = self.folder / 'recording.json'
        self.db = self.folder / 'conversations.sqlite3'
        with self.connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS conversations (
              id INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, endpoint TEXT,
              key_id TEXT, model TEXT, request TEXT, response TEXT DEFAULT '',
              status TEXT, truncated INTEGER DEFAULT 0)''')
        self.db.chmod(0o600)
    @contextmanager
    def connect(self):
        connection=sqlite3.connect(self.db,timeout=10)
        try:
            with connection:
                yield connection
        finally:
            connection.close()
    def options(self):
        try: return json.loads(self.config.read_text())
        except (OSError, ValueError): return {'enabled': False}
    def configure(self, **values):
        data = self.options(); data.update(values)
        temp = self.config.with_suffix('.tmp')
        temp.write_text(json.dumps(data, ensure_ascii=False, indent=2)); temp.chmod(0o600); temp.replace(self.config)
    def begin(self, endpoint, key, payload):
        if not self.options().get('enabled'): return None
        # Only text fields are retained; no headers, auth tokens, image/audio data or raw HTTP dumps.
        request = json.dumps(request_messages(payload), ensure_ascii=False)
        clipped = len(request) > LIMIT
        request = request[:LIMIT]
        model = str(payload.get('model', ''))[:200] if isinstance(payload, dict) else ''
        key_id = fingerprint(key)
        with self.connect() as c:
            cur = c.execute('INSERT INTO conversations(created,endpoint,key_id,model,request,status,truncated) VALUES(?,?,?,?,?,?,?)',
                            (time.time(), endpoint[:150], key_id, model, request, '处理中', clipped))
            c.execute('DELETE FROM conversations WHERE key_id=? AND id NOT IN (SELECT id FROM conversations WHERE key_id=? ORDER BY id DESC LIMIT 500)', (key_id,key_id))
            return cur.lastrowid
    def finish(self, row, response, status, truncated=False):
        if row is None: return
        with self.connect() as c:
            # Clearing history never resurrects requests already in flight.
            if not self.options().get('enabled'):
                c.execute('DELETE FROM conversations WHERE id=?', (row,)); return
            c.execute('UPDATE conversations SET response=?, status=?, truncated=MAX(truncated,?) WHERE id=?',
                      (response[:LIMIT], status, truncated or len(response)>LIMIT, row))
    def recent(self,key_id=None):
        with self.connect() as c:
            c.row_factory = sqlite3.Row
            sql='SELECT id,created,key_id,model,status,truncated FROM conversations'
            parameters=()
            if key_id is not None:sql+=' WHERE key_id=?';parameters=(key_id,)
            return [dict(r) for r in c.execute(sql+' ORDER BY id DESC LIMIT 500',parameters)]
    def key_ids(self):
        with self.connect() as c:
            return [r[0] for r in c.execute('SELECT DISTINCT key_id FROM conversations ORDER BY key_id')]
    def detail(self, row):
        with self.connect() as c:
            c.row_factory = sqlite3.Row
            r=c.execute('SELECT * FROM conversations WHERE id=?', (row,)).fetchone()
            return dict(r) if r else None
    def clear(self):
        with self.connect() as c:
            c.execute('PRAGMA secure_delete=ON'); c.execute('DELETE FROM conversations')
            c.commit()
            c.execute('VACUUM')

def text_content(value):
    if isinstance(value, str): return value
    if isinstance(value, list): return '\n'.join(filter(None, (text_content(x) for x in value)))
    if isinstance(value, dict):
        kind = str(value.get('type', ''))
        if any(x in kind for x in ('image', 'audio', 'video')): return '[多媒体内容未记录]'
        for k in ('text', 'content', 'refusal', 'output'):
            if k in value: return text_content(value[k])
    return ''

def request_messages(payload):
    if not isinstance(payload, dict): return []
    items = payload.get('messages', payload.get('input', []))
    if isinstance(items, str): items = [{'role':'user','content':items}]
    if not isinstance(items, list): return []
    return [{'role':str(item.get('role', item.get('type','user')))[:80],
             'content':text_content(item.get('content', item.get('text', item.get('output',''))))}
            for item in items if isinstance(item, dict)]

def response_text(payload):
    if not isinstance(payload, dict): return ''
    if isinstance(payload.get('choices'), list):
        return '\n'.join(filter(None,(text_content(x.get('message', x.get('delta',{}))) or x.get('text','') for x in payload['choices'])))
    return text_content(payload.get('output', payload.get('output_text', '')))

def extract_response(data, content_type, encoding=''):
    try:
        if encoding == 'gzip': data = gzip.decompress(data)[:LIMIT]
        text = data.decode('utf-8', errors='replace')
        if 'text/event-stream' in content_type:
            deltas, completed = [], ''
            for line in text.splitlines():
                if not line.startswith('data:'): continue
                try: obj=json.loads(line[5:].strip())
                except ValueError: continue
                if obj.get('type') == 'response.output_text.delta': deltas.append(obj.get('delta',''))
                elif obj.get('type') == 'response.completed': completed=response_text(obj.get('response',{}))
                elif 'choices' in obj: deltas.append(response_text(obj))
            return ''.join(deltas) or completed
        return response_text(json.loads(text))
    except (ValueError, OSError): return '[回复无法提取为文本]'

def create_app(store, upstream):
    app = web.Application(client_max_size=10*1024*1024)
    async def client_context(app):
        async with ClientSession(timeout=ClientTimeout(total=None, sock_connect=30), auto_decompress=False) as client:
            app['client'] = client
            yield
    app.cleanup_ctx.append(client_context)
    async def proxy(req):
        # Health is local and does not reveal content or credentials.
        if req.path == '/_station/health': return web.json_response({'ok':True,'recording':bool(store.options().get('enabled'))})
        headers = {k:v for k,v in req.headers.items() if k.lower() not in HOPS | {'accept-encoding'}}
        headers['Accept-Encoding']='identity'
        target = upstream + req.rel_url.path_qs
        if req.headers.get('Upgrade','').lower() == 'websocket':
            return await websocket(req, target, headers, store, app['client'])
        body = await req.read()
        try: payload=json.loads(body)
        except ValueError: payload={}
        row = None
        captured=bytearray(); truncated=False; status='连接中断'; mime=''; encoding=''
        try:
            async with app['client'].request(req.method,target,headers=headers,data=body,allow_redirects=False) as upstream_response:
                status=str(upstream_response.status)
                if upstream_response.status < 400 and req.path.rstrip('/').endswith(('/chat/completions','/responses','/completions')):
                    row=store.begin(req.path,req.headers.get('Authorization',req.headers.get('x-api-key','')),payload)
                response_headers={k:v for k,v in upstream_response.headers.items() if k.lower() not in HOPS}
                response_headers['X-AI-Station-Recording']='enabled' if row is not None else 'disabled'
                response=web.StreamResponse(status=upstream_response.status,headers=response_headers)
                await response.prepare(req)
                mime=upstream_response.headers.get('Content-Type',''); encoding=upstream_response.headers.get('Content-Encoding','')
                async for chunk in upstream_response.content.iter_any():
                    if row is not None:
                        room=LIMIT-len(captured); captured.extend(chunk[:room]); truncated |= len(chunk)>room
                    await response.write(chunk)
                await response.write_eof()
                return response
        except (ConnectionError, asyncio.TimeoutError, __import__('aiohttp').ClientError):
            status='连接中断'
            if req.transport is not None: req.transport.close()
            return web.Response(status=502,text='Gateway connection interrupted')
        finally:
            store.finish(row,extract_response(bytes(captured),mime,encoding),status,truncated)
    app.router.add_route('*','/{tail:.*}',proxy)
    return app

async def websocket(req, target, headers, store, client):
    # Upgrade auth remains upstream-controlled; credentials are never persisted.
    headers={k:v for k,v in headers.items() if not k.lower().startswith('sec-websocket-')}
    protocols=req.headers.get('Sec-WebSocket-Protocol','').split(',') if req.headers.get('Sec-WebSocket-Protocol') else []
    async with client.ws_connect(target,headers=headers,protocols=[p.strip() for p in protocols],max_msg_size=16*1024*1024) as upstream:
        downstream=web.WebSocketResponse(protocols=protocols,max_msg_size=16*1024*1024)
        downstream.headers['X-AI-Station-Recording']='enabled' if store.options().get('enabled') else 'disabled'
        await downstream.prepare(req)
        row=None; output=[]; size=0; truncated=False
        async def upload():
            nonlocal row,size,truncated
            async for msg in downstream:
                if msg.type == WSMsgType.TEXT:
                    try:
                        obj=json.loads(msg.data)
                        if obj.get('type') in ('response.create','response.append'):
                            store.finish(row,''.join(output),'WebSocket 下一轮',truncated)
                            output.clear(); size=0; truncated=False
                            row=store.begin(req.path,req.headers.get('Authorization',''),obj.get('response',obj))
                    except ValueError: pass
                    await upstream.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY: await upstream.send_bytes(msg.data)
            await upstream.close()
        async def download():
            nonlocal size,truncated
            async for msg in upstream:
                if msg.type == WSMsgType.TEXT:
                    try:
                        obj=json.loads(msg.data)
                        if obj.get('type') == 'response.output_text.delta':
                            delta=str(obj.get('delta','')); room=max(0,LIMIT-size);output.append(delta[:room]);size+=min(len(delta),room);truncated |= len(delta)>room
                        if obj.get('type') == 'response.completed':
                            store.finish(row,''.join(output) or response_text(obj.get('response',{})),'200',truncated)
                    except ValueError: pass
                    await downstream.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY: await downstream.send_bytes(msg.data)
            await downstream.close()
        tasks=[asyncio.create_task(upload()),asyncio.create_task(download())]
        try:
            await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
            store.finish(row,''.join(output),'WebSocket 结束',truncated)
        return downstream

def main(folder):
    os.umask(0o077)
    store=Store(folder); opts=store.options()
    web.run_app(create_app(store,f'http://127.0.0.1:{opts["upstream_port"]}'),host='127.0.0.1',port=opts['listen_port'],print=None,access_log=None)

if __name__=='__main__':
    import sys
    main(sys.argv[1])
