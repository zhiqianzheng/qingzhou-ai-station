"""Platform services, configuration and browser authorization."""
import ctypes
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from recorder import Store

WINDOWS = sys.platform == 'win32'
HOME = Path.home()
BUNDLE = Path(getattr(sys,'_MEIPASS',Path(__file__).parent))
STATE = Path(os.environ.get('LOCALAPPDATA',HOME))/'QingzhouAIStation' if WINDOWS else HOME/'.local/share/ai-station'
CONFIG = STATE/'config.yaml' if WINDOWS else HOME/'.config/cliproxyapi/config.yaml'
AUTH = STATE/'auth' if WINDOWS else HOME/'.local/share/cliproxyapi/auth'
BIN = STATE/'core/cli-proxy-api.exe' if WINDOWS else HOME/'.local/opt/cliproxyapi/cli-proxy-api'
UNIT = HOME/'.config/systemd/user/cliproxyapi.service'
REC_UNIT = UNIT.with_name('ai-station-recorder.service')


def run(args, timeout=30):
    p=subprocess.run([str(x) for x in args],capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=timeout,
                     **({'creationflags':subprocess.CREATE_NO_WINDOW} if WINDOWS else {}))
    if p.returncode: raise RuntimeError((p.stderr or p.stdout or '操作失败').strip()[-1200:])
    return p.stdout.strip()

def store(): return Store(STATE)

def core_settings():
    s=CONFIG.read_text() if CONFIG.exists() else ''
    port=re.search(r'^\s*port:\s*(\d+)',s,re.M)
    key=re.search(r'api-keys:\s*\n\s*-\s*["\']?([^"\'\s]+)',s)
    return int(port[1]) if port else 8317, key[1] if key else ''

def settings():
    port,key=core_settings(); opts=store().options()
    return (opts['listen_port'] if opts.get('installed') else port),key

def recorder_command():
    if getattr(sys,'frozen',False): return [sys.executable,'--recorder',str(STATE)]
    return [sys.executable,str(BUNDLE/'recorder.py'),str(STATE)]

def configure():
    STATE.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not BIN.exists():
        bundled=BUNDLE/'core'/BIN.name
        if not bundled.exists(): raise RuntimeError('缺少核心程序，请重新安装 App。')
        BIN.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(bundled,BIN)
        if not WINDOWS: BIN.chmod(0o755)
    AUTH.mkdir(parents=True,exist_ok=True,mode=0o700)
    CONFIG.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    if not CONFIG.exists():
        CONFIG.write_text(f'''config-version: 8
server:
  host: "127.0.0.1"
  port: 8317
management:
  allow-remote: false
  disable-control-panel: true
access:
  api-keys:
    - "sk-station-{secrets.token_urlsafe(32)}"
oauth:
  auth-dir: {json.dumps(str(AUTH))}
observability:
  logs:
    request-log: false
plugins:
  enabled: false
''')
        CONFIG.chmod(0o600)
    if not WINDOWS and not UNIT.exists():
        UNIT.parent.mkdir(parents=True,exist_ok=True)
        UNIT.write_text(f'''[Unit]
Description=AI Station gateway
After=network.target
[Service]
ExecStart="{BIN}" -config "{CONFIG}" -local-model
Restart=on-failure
RestartSec=5
UMask=0077
[Install]
WantedBy=default.target
''')
        run(['systemctl','--user','daemon-reload'])

def process_identity(pid):
    """Creation timestamp prevents terminating a reused Windows PID."""
    if not WINDOWS: return None
    from ctypes import wintypes
    k=ctypes.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.restype=wintypes.HANDLE
    k.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
    k.GetProcessTimes.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    k.CloseHandle.argtypes=[wintypes.HANDLE]
    handle=k.OpenProcess(0x1000,False,pid)
    if not handle:return None
    times=[wintypes.FILETIME() for _ in range(4)]
    try:
        if k.GetProcessTimes(handle,*(ctypes.byref(t) for t in times)):
            return (times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
    finally:k.CloseHandle(handle)

def win_process(name, command=None, stop=False):
    file=STATE/(name+'.pid.json')
    try: old=json.loads(file.read_text())
    except (ValueError,OSError): old={}
    identity=process_identity(old['pid']) if old else None
    active=bool(identity is not None and identity==old['identity'])
    if stop:
        if active:run(['taskkill','/PID',str(old['pid']),'/T','/F'])
        file.unlink(missing_ok=True);return False
    if command and not active:
        proc=subprocess.Popen([str(x) for x in command],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                              creationflags=subprocess.CREATE_NO_WINDOW|subprocess.CREATE_NEW_PROCESS_GROUP,close_fds=True)
        file.write_text(json.dumps({'pid':proc.pid,'identity':process_identity(proc.pid)}))
        time.sleep(.4)
        if proc.poll() is not None:raise RuntimeError(name+' 启动失败，请检查端口和配置。')
        active=True
    return active

def start():
    configure()
    if WINDOWS:
        win_process('core',[BIN,'-config',CONFIG,'-local-model'])
        if store().options().get('installed'):win_process('recorder',recorder_command())
    else:
        run(['systemctl','--user','enable','--now','cliproxyapi'])
        if store().options().get('installed'):run(['systemctl','--user','enable','--now','ai-station-recorder'])
    return '中转服务已启动。'

def stop():
    if WINDOWS:
        win_process('recorder',stop=True);win_process('core',stop=True)
    else:
        if REC_UNIT.exists():run(['systemctl','--user','stop','ai-station-recorder'])
        run(['systemctl','--user','stop','cliproxyapi'])
    return '中转服务已停止。'

def restart(): stop();return start()

def active():
    try:
        if WINDOWS:
            return win_process('core') and (not store().options().get('installed') or win_process('recorder'))
        units=['cliproxyapi']+(['ai-station-recorder'] if store().options().get('installed') else [])
        return all(subprocess.run(['systemctl','--user','is-active','--quiet',unit]).returncode==0 for unit in units)
    except OSError:return False

def accounts():
    names=[]
    for f in AUTH.glob('*.json'):
        try:
            v=json.loads(f.read_text())
            if isinstance(v,dict) and v.get('type')=='codex':names.append(v.get('email','已授权账号')+('（停用）' if v.get('disabled') else ''))
        except (ValueError,OSError):pass
    return '、'.join(names) or '尚未登录'

def login():
    start()
    run([BIN,'-config',CONFIG,'-codex-login'],timeout=300)
    restart();return 'ChatGPT 账号授权完成。'

def recording(enabled):
    s=store();opts=s.options()
    if opts.get('installed'):
        s.configure(enabled=enabled)
        return '对话记录已'+('开启' if enabled else '关闭')
    if not enabled:return '对话记录未开启。'
    start();old=CONFIG.read_text();port,_=core_settings()
    # Keep the public address and key stable while moving the core to another loopback port.
    with socket.socket() as probe:
        probe.bind(('127.0.0.1',0));upstream=probe.getsockname()[1]
    try:
        stop()
        CONFIG.write_text(re.sub(r'(^\s*port:\s*)\d+',lambda m:m[1]+str(upstream),old,count=1,flags=re.M));CONFIG.chmod(0o600)
        s.configure(installed=True,listen_port=port,upstream_port=upstream,enabled=True)
        if not WINDOWS:
            cmd=' '.join('"'+str(x).replace('%','%%').replace('"','\\"')+'"' for x in recorder_command())
            REC_UNIT.write_text(f'''[Unit]
Description=AI Station conversation recorder
After=cliproxyapi.service
Requires=cliproxyapi.service
[Service]
ExecStart={cmd}
Restart=on-failure
RestartSec=3
UMask=0077
[Install]
WantedBy=default.target
''')
            run(['systemctl','--user','daemon-reload'])
        start()
        for _ in range(30):
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/_station/health',timeout=1) as r:
                    if json.load(r).get('ok'):return '对话记录已开启；原 URL 和 API Key 保持可用。'
            except OSError:time.sleep(.2)
        raise RuntimeError('记录服务未就绪')
    except Exception:
        try:stop()
        except Exception:pass
        CONFIG.write_text(old);s.configure(installed=False,enabled=False)
        if not WINDOWS and REC_UNIT.exists():
            run(['systemctl','--user','disable','ai-station-recorder']);REC_UNIT.unlink();run(['systemctl','--user','daemon-reload'])
        start();raise

def set_proxy(value):
    configure();data=CONFIG.read_text();line='  proxy-url: '+json.dumps(value)+'\n'
    if re.search(r'^  proxy-url:.*$',data,re.M):data=re.sub(r'^  proxy-url:.*\n?',lambda m:line,data,count=1,flags=re.M)
    elif re.search(r'^requests:[ \t]*$',data,re.M):data=re.sub(r'^requests:[ \t]*\n',lambda m:'requests:\n'+line,data,count=1,flags=re.M)
    else:data+='\nrequests:\n'+line
    temp=CONFIG.with_suffix('.tmp');temp.write_text(data);temp.chmod(0o600);temp.replace(CONFIG)
    restart();return '网络代理已保存。'

def request(path,data=None):
    port,key=settings()
    req=urllib.request.Request(f'http://127.0.0.1:{port}/v1/{path}',data=json.dumps(data).encode() if data else None,
                               headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    with urllib.request.urlopen(req,timeout=120) as r:return json.load(r)

def test(model):
    ids=[m['id'] for m in request('models').get('data',[])]
    if model not in ids:return '连接成功。可用模型：'+', '.join(ids)
    v=request('chat/completions',{'model':model,'messages':[{'role':'user','content':'Reply with OK only.'}],'max_tokens':32})
    return '模型列表和对话测试成功：'+v['choices'][0]['message']['content']

def tailscale():
    path=shutil.which('tailscale')
    if not path and WINDOWS:
        candidate=Path(os.environ.get('ProgramFiles','C:/Program Files'))/'Tailscale/tailscale.exe'
        if candidate.exists():path=str(candidate)
    return path

def public_status():
    exe=tailscale()
    if not exe:return '尚未安装 Tailscale。点击「开启公网」会引导安装。'
    return run([exe,'funnel','status'])

def elevated(command,timeout=600,on_line=None):
    if not WINDOWS:return run(['pkexec',*command],timeout=timeout)
    # Run the elevated command with a per-user output file so login URLs reach the browser.
    STATE.mkdir(parents=True,exist_ok=True)
    import tempfile
    output=Path(tempfile.mktemp(prefix='tailscale-',suffix='.txt',dir=STATE))
    script=output.with_suffix('.ps1')
    quote=lambda x:"'"+str(x).replace("'","''")+"'"
    script.write_text('& '+ ' '.join(quote(x) for x in command)+f' *> {quote(output)}\nexit $LASTEXITCODE',encoding='utf-8-sig')
    invocation=f"$p=Start-Process powershell.exe -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',\"{str(script).replace(chr(34),'`'+chr(34))}\") -Verb RunAs -PassThru -Wait; exit $p.ExitCode"
    p=subprocess.Popen(['powershell.exe','-NoProfile','-Command',invocation],creationflags=subprocess.CREATE_NO_WINDOW)
    seen='';end=time.monotonic()+timeout
    try:
        while p.poll() is None:
            if time.monotonic()>end:raise RuntimeError('管理员操作超时，请重试。')
            if output.exists():
                text=output.read_text(encoding='utf-16',errors='replace')
                if text!=seen and on_line:on_line(text)
                seen=text
            time.sleep(.3)
        text=output.read_text(encoding='utf-16',errors='replace') if output.exists() else ''
        if on_line:on_line(text)
        if p.returncode:raise RuntimeError('管理员操作未完成，请检查授权是否取消。')
        return text
    finally:
        script.unlink(missing_ok=True);output.unlink(missing_ok=True)

def enable_public(on_url=lambda url:None):
    exe=tailscale()
    if not exe:
        if WINDOWS:
            installer=STATE/'tailscale-setup.msi'
            urllib.request.urlretrieve('https://pkgs.tailscale.com/stable/tailscale-setup-latest-amd64.msi',installer)
            # Check Authenticode rather than executing an unsigned download.
            result=run(['powershell.exe','-NoProfile','-Command',"(Get-AuthenticodeSignature -LiteralPath '"+str(installer).replace("'","''")+"').Status"])
            if result!='Valid':raise RuntimeError('Tailscale 安装包签名验证失败。')
            elevated(['msiexec.exe','/i',str(installer),'/passive','/norestart'])
        else:elevated(['bash',str(BUNDLE/'install-tailscale.sh')])
        exe=tailscale()
        if not exe:raise RuntimeError('Tailscale 安装未完成。')
    seen=set()
    def urls(text):
        for url in re.findall(r'https://login\.tailscale\.com/[^\s<>]+',text):
            if url not in seen:seen.add(url);on_url(url)
    opts=json.loads(run([exe,'status','--json']))
    if opts.get('BackendState')!='Running':
        if WINDOWS:elevated([exe,'up','--timeout=180s'],on_line=urls)
        else:
            p=subprocess.Popen(['pkexec',exe,'up','--timeout=180s'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            for line in p.stdout:urls(line)
            if p.wait():raise RuntimeError('设备登录尚未完成。')
    port,_=settings()
    try:result=run([exe,'funnel','--bg',str(port)],timeout=10);urls(result)
    except (RuntimeError,subprocess.TimeoutExpired):
        if WINDOWS:elevated([exe,'funnel','--bg',str(port)],timeout=180,on_line=urls)
        else:
            p=subprocess.Popen(['pkexec',exe,'funnel','--bg',str(port)],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
            for line in p.stdout:urls(line)
            if p.wait():raise RuntimeError('请先在浏览器完成 Funnel 授权。')
    return public_status()

def disable_public():
    exe=tailscale()
    if not exe:return '公网入口未安装。'
    try:return run([exe,'funnel','--https=443','off']) or '公网入口已关闭。'
    except RuntimeError:return elevated([exe,'funnel','--https=443','off']) or '公网入口已关闭。'
