"""Bounded, evidence-based checks for a selected client key and model."""
import asyncio
import base64
import json
import socket
import struct
import threading
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass
from aiohttp import ClientSession, ClientTimeout, WSMsgType
from recorder import response_text

PREFIX='[Qingzhou capability test] '
BASIC=[('text','普通文字对话'),('stream','SSE 流式回复'),('responses','Responses 接口'),
       ('vision','图片识别'),('functions','函数 / 工具调用'),('json','JSON 结构化输出'),('websocket','Responses WebSocket')]
EXTENDED=[('web','联网搜索工具'),('code','代码执行工具'),('image','图片生成'),
          ('speech','文字转语音'),('transcription','语音转文字'),('embeddings','向量嵌入')]

@dataclass
class Reply:
    status:int
    headers:dict
    data:object=None
    raw:bytes=b''

class Unverified(Exception):pass
class Cancelled(Exception):pass
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

class ProbeFailure(Exception):
    def __init__(self,status,code='',unsupported=False):
        self.status=status;self.code=code;self.unsupported=unsupported

class Transport:
    def __init__(self,key,cancel):
        self.key=key;self.cancel=cancel
        self.opener=urllib.request.build_opener(NoRedirect())
    def request(self,base,path,payload=None,stream=False,timeout=45,binary=False,body=None,content_type=None):
        if self.cancel.is_set():raise Cancelled()
        headers={'Authorization':'Bearer '+self.key,'User-Agent':'Qingzhou-Capability-Test/1.0'}
        if body is None and payload is not None:
            body=json.dumps(payload).encode();content_type='application/json'
        if content_type:headers['Content-Type']=content_type
        req=urllib.request.Request(base.rstrip('/')+'/'+path.lstrip('/'),data=body,headers=headers)
        try:
            with self.opener.open(req,timeout=timeout) as r:
                rh={k.lower():v for k,v in r.headers.items()}
                if stream:
                    if 'text/event-stream' not in rh.get('content-type',''):raise Unverified('接口返回了非 SSE 内容，尚未证实流式能力。')
                    pieces=[];complete=False;size=0;deadline=time.monotonic()+timeout
                    while True:
                        if self.cancel.is_set():raise Cancelled()
                        if time.monotonic()>deadline:raise TimeoutError()
                        line=r.readline(65536)
                        if not line:break
                        size+=len(line)
                        if size>2*1024*1024:raise Unverified('流式结果超过测试采集上限。')
                        if not line.startswith(b'data:'):continue
                        data=line[5:].strip()
                        if data==b'[DONE]':complete=True;break
                        try:item=json.loads(data)
                        except ValueError:continue
                        if item.get('error'):raise Unverified('流式接口报告错误，本次未验证通过。')
                        pieces.append(response_text(item))
                    return Reply(r.status,rh,{'text':''.join(pieces),'complete':complete})
                raw=r.read(16*1024*1024+1)
                if len(raw)>16*1024*1024:raise Unverified('返回内容超过测试采集上限。')
                if self.cancel.is_set():raise Cancelled()
                if binary:return Reply(r.status,rh,raw=raw)
                try:data=json.loads(raw)
                except ValueError:raise Unverified('返回内容不是有效 JSON，不能据此判断能力可用。')
                if isinstance(data,dict) and data.get('error'):
                    self._error(r.status,raw)
                return Reply(r.status,rh,data=data)
        except urllib.error.HTTPError as e:
            self._error(e.code,e.read(32768))
    @staticmethod
    def _error(status,raw):
        # Never display or persist raw provider errors: they may echo credentials.
        try:
            obj=json.loads(raw);error=obj.get('error',{})
            if isinstance(error,str):error={'message':error}
            message=str(error.get('message','')).lower();code=str(error.get('code','')).lower()
        except (ValueError,AttributeError):message='';code=''
        unsupported=any(x in message+' '+code for x in ('not supported','unsupported','not available for','not implemented','unknown tool','unknown parameter','unrecognized request argument'))
        safe_code=code if code in ('rate_limit_exceeded','insufficient_quota','model_not_found','context_length_exceeded') else ''
        raise ProbeFailure(status,safe_code,unsupported)


def test_image():
    """A generated two-color PNG; no external image, screenshot or user file is sent."""
    w,h=128,64
    row=b'\0'+bytes((0,0,255))*(w//2)+bytes((255,255,0))*(w//2)
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    png=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',w,h,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(row*h))+chunk(b'IEND',b'')
    return 'data:image/png;base64,'+base64.b64encode(png).decode()

class Tester:
    def __init__(self,key,model,base_url,public_url=None,extended=False,on_update=None,cancel=None,transport=None):
        self.model=model;self.base=base_url;self.public=public_url;self.extended=extended
        self.cancel=cancel or threading.Event();self.transport=transport or Transport(key,self.cancel)
        self.key=key;self.on_update=on_update or (lambda row:None);self.models=[];self.audio=None
        self.rows=[]
    def check(self):
        if self.cancel.is_set():raise Cancelled()
    def emit(self,row):self.on_update(dict(row))
    def execute(self,id,name,fn):
        self.check();row={'id':id,'name':name,'status':'测试中','detail':'正在发送实际测试请求…','seconds':0,'http_status':None}
        self.emit(row);start=time.monotonic()
        try:
            detail=fn();row.update(status='通过',detail=detail)
        except ProbeFailure as e:
            row['http_status']=e.status
            if e.status==401:row.update(status='失败',detail='HTTP 401：这把 Key 未通过鉴权，可能已停用、删除或未生效。')
            elif e.status==403:row.update(status='失败',detail='HTTP 403：当前请求被拒绝；需检查账号权限或网络访问策略。')
            elif e.status==429:row.update(status='未验证',detail='HTTP 429：限流或额度不足，无法据此判断能力是否支持。')
            elif e.status in (404,405,501):row.update(status='不支持',detail=f'HTTP {e.status}：当前中转未提供本项所测试的接口 / 调用方式。')
            elif e.status in (400,422) and e.unsupported:row.update(status='不支持',detail=f'HTTP {e.status}：上游明确拒绝本项能力或请求参数；结论限于当前模型和接口。')
            elif e.code=='model_not_found':row.update(status='未验证',detail='模型未找到或当前账号无权访问，未证实该能力。')
            else:row.update(status='未验证',detail=f'HTTP {e.status}：本次调用未通过，可能是上游错误或请求兼容性问题。')
        except (TimeoutError,socket.timeout,urllib.error.URLError,ConnectionError,OSError):
            row.update(status='未验证',detail='网络连接失败或等待超时；不代表不支持该能力。')
        except Unverified as e:row.update(status='未验证',detail=str(e))
        except Cancelled:row.update(status='已取消',detail='已取消；已发出的请求可能仍产生用量。')
        except Exception:row.update(status='未验证',detail='返回数据未通过测试校验，不能判定能力可用。')
        row['seconds']=round(time.monotonic()-start,2);self.rows.append(row);self.emit(row);return row
    def skip(self,id,name,detail,status='跳过'):
        row={'id':id,'name':name,'status':status,'detail':detail,'seconds':0,'http_status':None}
        self.rows.append(row);self.emit(row)
    def run(self):
        try:
            auth=self.execute('auth','连接 / 鉴权 / 模型列表',self.auth)
            if auth['status']!='通过':
                for id,name in BASIC+EXTENDED:self.skip(id,name,'当前目标的连接或鉴权未通过，未发送生成请求。')
                return self.report()
            if self.public and self.public.rstrip('/')!=self.base.rstrip('/'):
                self.execute('public','公网地址连通性',lambda:self.public_auth())
            elif not self.public:self.skip('public','公网地址连通性','未取得可测试的公网地址，仅检查本机中转。','未验证')
            if self.model not in self.models:
                self.skip('model','当前模型可见性','模型列表未包含所选模型，未自动替换；以下仍用所选模型实际测试。','未验证')
            else:self.skip('model','当前模型可见性','所选模型出现在本次模型列表中；实际能力以下方调用结果为准。','通过')
            for id,name in BASIC:self.execute(id,name,getattr(self,'probe_'+id))
            for id,name in EXTENDED:
                if self.extended:self.execute(id,name,getattr(self,'probe_'+id))
                else:self.skip(id,name,'基础测试不执行可能额外计费的扩展调用；点击「全部测试」可检查。','未测试')
        except Cancelled:
            completed={r['id'] for r in self.rows}
            for id,name in BASIC+EXTENDED:
                if id not in completed:self.skip(id,name,'用户取消了测试。','已取消')
        return self.report()
    def report(self):
        return {'model':self.model,'base_url':self.base,'public_url':self.public,'created':time.time(),
                'extended':self.extended,'models':self.models,'results':list(self.rows),
                'scope':'结果只代表本次选中 Key、模型和测试接口；未覆盖所有模型、文件类型、长上下文或负载场景。能力请求使用目标地址，额外公网检查只验证模型列表和鉴权。'}
    def auth(self):
        reply=self.transport.request(self.base,'models',timeout=15)
        if not isinstance(reply.data,dict) or not isinstance(reply.data.get('data'),list):raise Unverified('模型列表格式异常。')
        self.models=[m['id'] for m in reply.data['data'] if isinstance(m,dict) and isinstance(m.get('id'),str)]
        return f'所选 Key 鉴权通过，读取到 {len(self.models)} 个模型。'
    def public_auth(self):
        r=self.transport.request(self.public,'models',timeout=12)
        if not isinstance(r.data,dict) or not isinstance(r.data.get('data'),list):raise Unverified('公网返回内容未通过模型列表校验。')
        return '从当前电脑通过公网地址鉴权成功；其他设备仍需能够访问该域名。'
    def chat(self,prompt,**extra):
        payload={'model':self.model,'messages':[{'role':'user','content':PREFIX+prompt}],'max_tokens':96}
        payload.update(extra);return self.transport.request(self.base,'chat/completions',payload)
    def responses(self,prompt,**extra):
        payload={'model':self.model,'input':PREFIX+prompt,'max_output_tokens':128}
        payload.update(extra);return self.transport.request(self.base,'responses',payload)
    def probe_text(self):
        r=self.chat('Reply exactly TEST_OK.')
        if 'TEST_OK' not in response_text(r.data):raise Unverified('收到响应，但未返回预期测试文字。')
        return '实际文字请求返回 TEST_OK。'
    def probe_stream(self):
        p={'model':self.model,'messages':[{'role':'user','content':PREFIX+'Reply exactly STREAM_OK.'}],'max_tokens':64,'stream':True}
        r=self.transport.request(self.base,'chat/completions',p,stream=True)
        if not r.data.get('complete') or 'STREAM_OK' not in r.data.get('text',''):raise Unverified('未同时收到预期文字与流式结束标记。')
        return '收到有效 SSE 文字增量和结束标记。'
    def probe_responses(self):
        r=self.responses('Reply exactly RESPONSE_OK.')
        if 'RESPONSE_OK' not in response_text(r.data):raise Unverified('Responses 返回内容未通过测试文字校验。')
        return 'Responses 实际生成请求返回预期文字。'
    def probe_vision(self):
        p={'model':self.model,'messages':[{'role':'user','content':[
            {'type':'text','text':PREFIX+'Identify the colors of the LEFT and RIGHT halves of this image. Reply LEFT_COLOR,RIGHT_COLOR in English.'},
            {'type':'image_url','image_url':{'url':test_image()}}]}],'max_tokens':64}
        r=self.transport.request(self.base,'chat/completions',p);text=response_text(r.data).lower()
        if 'blue' not in text or 'yellow' not in text or text.index('blue')>text.index('yellow'):raise Unverified('图片已提交，但左右颜色识别未通过，不能认定图片识别可用。')
        return '实际上传程序生成的双色 PNG，正确识别左右颜色。'
    def probe_functions(self):
        tool={'type':'function','function':{'name':'station_probe','description':'Return a test marker.',
            'parameters':{'type':'object','properties':{'value':{'type':'string','enum':['ping']}},'required':['value'],'additionalProperties':False}}}
        r=self.chat('Call station_probe with value ping.',tools=[tool],tool_choice={'type':'function','function':{'name':'station_probe'}})
        try:calls=r.data['choices'][0]['message']['tool_calls']
        except (KeyError,IndexError,TypeError):raise Unverified('未收到结构化 function tool_call；仅文字描述不算通过。')
        for call in calls:
            fn=call.get('function',{})
            if fn.get('name')=='station_probe' and json.loads(fn.get('arguments','{}')).get('value')=='ping':return '收到正确函数名称和 JSON 参数；本测试未执行外部函数。'
        raise Unverified('工具调用名称或参数未通过校验。')
    def probe_json(self):
        schema={'type':'object','properties':{'ok':{'type':'boolean'}},'required':['ok'],'additionalProperties':False}
        r=self.chat('Return ok=true using the required JSON schema.',response_format={'type':'json_schema','json_schema':{'name':'station_probe','strict':True,'schema':schema}})
        try:value=json.loads(response_text(r.data))
        except ValueError:raise Unverified('返回内容不是纯 JSON。')
        if value!={'ok':True}:raise Unverified('返回 JSON 不符合测试 schema。')
        return '接口接受 JSON Schema，实际返回内容符合指定结构；不代表验证了所有 schema。'
    def probe_websocket(self):
        async def check():
            url=self.base.rstrip('/')+'/responses';url=url.replace('https://','wss://',1).replace('http://','ws://',1)
            async with ClientSession(timeout=ClientTimeout(total=45)) as session:
                try:
                    async with session.ws_connect(url,headers={'Authorization':'Bearer '+self.key},timeout=15) as ws:
                        await ws.send_json({'type':'response.create','model':self.model,'store':False,'input':[{'type':'message','role':'user','content':[{'type':'input_text','text':PREFIX+'Reply exactly WS_OK.'}]}]})
                        output=[];deadline=time.monotonic()+45
                        while time.monotonic()<deadline:
                            self.check();msg=await ws.receive(timeout=10)
                            if msg.type!=WSMsgType.TEXT:break
                            obj=json.loads(msg.data)
                            if obj.get('type')=='response.output_text.delta':output.append(str(obj.get('delta','')))
                            if obj.get('type')=='response.completed':
                                if 'WS_OK' in ''.join(output) or 'WS_OK' in response_text(obj.get('response',{})):return
                                break
                            if obj.get('type') in ('error','response.failed'):raise Unverified('WebSocket 已连接，但生成请求未通过。')
                except __import__('aiohttp').WSServerHandshakeError as e:raise ProbeFailure(e.status)
            raise Unverified('未收到 WebSocket 预期文字和完成事件。')
        asyncio.run(check());return 'WebSocket 握手、文字生成与完成事件均验证通过。'
    def tool_completed(self,data,type):
        return [x for x in data.get('output',[]) if isinstance(x,dict) and x.get('type')==type and x.get('status')=='completed']
    def probe_web(self):
        r=self.responses('Use web search to find the official OpenAI homepage. Return one short URL.',tools=[{'type':'web_search'}],tool_choice='required')
        if not self.tool_completed(r.data,'web_search_call'):raise Unverified('没有收到已完成的 web_search_call，仅生成网址不算联网验证通过。')
        return '实际收到已完成的内置联网搜索调用。'
    def probe_code(self):
        r=self.responses('Use the code interpreter to run print(1+1). Return the result only.',tools=[{'type':'code_interpreter','container':{'type':'auto'}}],tool_choice='required',include=['code_interpreter_call.outputs'])
        if not self.tool_completed(r.data,'code_interpreter_call'):raise Unverified('未收到已完成的 code_interpreter_call，仅回答 2 不算代码执行通过。')
        return '实际收到已完成的代码解释器调用。'
    def candidate(self,words):return next((id for id in self.models if any(w in id.lower() for w in words)),None)
    def no_model(self,path,label):
        try:self.transport.request(self.base,path,timeout=12)
        except ProbeFailure as e:
            if e.status==404:raise
            if e.status==405:raise Unverified(f'{label}接口可能存在，但未找到可测试的专用模型，未执行生成请求。')
            raise
        raise Unverified(f'模型列表中未发现可测试的{label}模型，未验证实际生成。')
    def probe_image(self):
        model=self.candidate(['gpt-image','dall-e','imagen'])
        if model:
            try:
                r=self.transport.request(self.base,'images/generations',{'model':model,'prompt':PREFIX+'A plain blue square.','n':1,'size':'1024x1024','quality':'low'},timeout=90)
                items=r.data.get('data',[])
                if any(x.get('b64_json') or x.get('url') for x in items if isinstance(x,dict)):return f'图片生成接口实际返回图像结果（模型 {model}）；未保存图像。'
                raise Unverified('图片接口未返回图像结果。')
            except ProbeFailure as e:
                if e.status not in (404,405,501):raise
        r=self.responses('Generate a plain blue square image.',tools=[{'type':'image_generation','quality':'low'}],tool_choice='required')
        if any(x.get('type')=='image_generation_call' and x.get('result') for x in r.data.get('output',[]) if isinstance(x,dict)):
            return 'Responses 图片生成工具实际返回图像结果；未保存图像。'
        raise Unverified('没有收到实际生成图像，仅文字描述不算通过。')
    def probe_speech(self):
        model=self.candidate(['tts','speech'])
        if not model:return self.no_model('audio/speech','文字转语音')
        r=self.transport.request(self.base,'audio/speech',{'model':model,'input':'test','voice':'alloy','response_format':'wav'},binary=True)
        if not r.raw.startswith(b'RIFF') or len(r.raw)<44:raise Unverified('未收到有效 WAV 音频。')
        self.audio=r.raw;return f'实际生成 WAV 音频（模型 {model}）；未保存文件。'
    def probe_transcription(self):
        model=self.candidate(['transcribe','whisper'])
        if not model:return self.no_model('audio/transcriptions','语音转文字')
        audio=self.audio
        if not audio:
            raise Unverified('找到转写模型，但本次未生成已知内容的测试音频，不能验证识别正确性。')
        boundary='QingzhouTestBoundary'
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="model"\r\n\r\n{model}\r\n--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="test.wav"\r\nContent-Type: audio/wav\r\n\r\n').encode()+audio+f'\r\n--{boundary}--\r\n'.encode()
        r=self.transport.request(self.base,'audio/transcriptions',body=body,content_type='multipart/form-data; boundary='+boundary)
        if 'test' not in str(r.data.get('text','')).lower():raise Unverified('音频转写结果未通过已知测试词校验。')
        return f'实际识别已知测试音频（模型 {model}）。'
    def probe_embeddings(self):
        model=self.candidate(['embedding'])
        if not model:return self.no_model('embeddings','向量嵌入')
        r=self.transport.request(self.base,'embeddings',{'model':model,'input':'test'})
        try:v=r.data['data'][0]['embedding']
        except (KeyError,IndexError,TypeError):raise Unverified('未返回向量数组。')
        if not isinstance(v,list) or not v or not all(isinstance(x,(int,float)) for x in v):raise Unverified('向量内容未通过校验。')
        return f'实际返回 {len(v)} 维数值向量（模型 {model}）。'


def report_text(report):
    lines=[f'轻舟 API Key 能力测试',f'使用者：{report.get("name","")}',f'Key 指纹：{report.get("key_id","")}',
           f'模型：{report["model"]}',f'目标地址：{report["base_url"]}',time.strftime('时间：%Y-%m-%d %H:%M:%S',time.localtime(report['created']))]
    for row in report['results']:lines.append(f'[{row["status"]}] {row["name"]}（{row["seconds"]}秒）\n  {row["detail"]}')
    lines.append(report['scope']);return '\n'.join(lines)
