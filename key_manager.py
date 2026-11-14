"""Named client API keys. Secrets live only in per-user configuration files."""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import yaml


def fingerprint(value):
    """Keep old Bearer-header fingerprints stable; normalize other auth headers."""
    value=value.strip()
    if value.lower().startswith('bearer '):value=value[7:].strip()
    return hashlib.sha256(('Bearer '+value).encode()).hexdigest()[:12] if value else 'unknown'


def atomic_write(path, text):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    temp=path.with_name(path.name+'.tmp-'+secrets.token_hex(6))
    try:
        fd=os.open(str(temp),os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            f.write(text);f.flush();os.fsync(f.fileno())
        temp.replace(path)
    finally:temp.unlink(missing_ok=True)


class KeyManager:
    def __init__(self,config,state,on_change=None):
        self.config=Path(config);self.state=Path(state);self.registry=self.state/'api-keys.json';self.on_change=on_change
    @contextmanager
    def locked(self):
        self.state.mkdir(parents=True,exist_ok=True,mode=0o700)
        lock=self.state/'api-keys.lock'
        with lock.open('a+b') as f:
            lock.chmod(0o600)
            if f.tell()==0:f.write(b'0');f.flush()
            f.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(f.fileno(),msvcrt.LK_LOCK,1)
            else:
                import fcntl
                fcntl.flock(f.fileno(),fcntl.LOCK_EX)
            try:yield
            finally:
                f.seek(0)
                if os.name=='nt':msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
                else:fcntl.flock(f.fileno(),fcntl.LOCK_UN)
    def _load(self):
        data=yaml.safe_load(self.config.read_text(encoding='utf-8')) if self.config.exists() else {}
        if not isinstance(data,dict):raise RuntimeError('中转配置格式无效。')
        keys=data.get('access',{}).get('api-keys',[])
        if not isinstance(keys,list) or any(not isinstance(k,str) or not k for k in keys):
            raise RuntimeError('API Key 配置格式无效。')
        if self.registry.exists():
            entries=json.loads(self.registry.read_text(encoding='utf-8'))
            if not isinstance(entries,list):raise RuntimeError('密钥备注文件格式无效。')
        else:entries=[]
        previous=json.dumps(entries,sort_keys=True)
        by_id={e['id']:e for e in entries}
        for index,key in enumerate(keys):
            id=fingerprint(key)
            if id not in by_id:
                e={'id':id,'name':'默认密钥' if index==0 and not entries else f'已有密钥 {index+1}',
                   'secret':key,'enabled':True,'deleted':False,'created':time.time()}
                entries.append(e);by_id[id]=e
            else:by_id[id].update(secret=key,enabled=True,deleted=False)
        for e in entries:
            if e.get('secret') not in keys:e['enabled']=False
        if json.dumps(entries,sort_keys=True)!=previous:
            self._save_registry(entries)
        return data,entries
    def _save_registry(self,entries):
        atomic_write(self.registry,json.dumps(entries,ensure_ascii=False,indent=2))
    def _apply(self,data,entries):
        enabled=[e['secret'] for e in entries if e['enabled'] and not e.get('deleted')]
        if not enabled:raise ValueError('至少保留一把启用的 API Key，避免中转变为无密钥访问。')
        # Save the metadata first. If config replacement fails, restore it. Readers reconcile
        # active flags from the authoritative core config, so interrupted writes fail safely.
        old=self.registry.read_text(encoding='utf-8') if self.registry.exists() else None
        self._save_registry(entries)
        try:
            data.setdefault('access',{})['api-keys']=enabled
            atomic_write(self.config,yaml.safe_dump(data,sort_keys=False,allow_unicode=True))
        except Exception:
            if old is None:self.registry.unlink(missing_ok=True)
            else:atomic_write(self.registry,old)
            raise
    def list(self,include_deleted=False):
        with self.locked():_,entries=self._load()
        return [dict(e) for e in entries if include_deleted or not e.get('deleted')]
    def create(self,name):
        name=self._name(name)
        with self.locked():
            data,entries=self._load()
            if not self.config.exists():raise RuntimeError('请先一键配置 / 启动中转站。')
            secret='sk-station-'+secrets.token_urlsafe(32)
            entry={'id':fingerprint(secret),'name':name,'secret':secret,'enabled':True,'deleted':False,'created':time.time()}
            entries.append(entry);self._apply(data,entries)
        if self.on_change:self.on_change()
        return dict(entry)
    @staticmethod
    def _name(value):
        name=value.strip()
        if not name or len(name)>80 or any(ord(c)<32 for c in name):raise ValueError('使用者备注需要 1–80 个可显示字符。')
        return name
    def update(self,id,name=None,enabled=None,delete=False):
        with self.locked():
            data,entries=self._load()
            entry=next((e for e in entries if e['id']==id and not e.get('deleted')),None)
            if entry is None:raise ValueError('找不到这把 API Key。')
            if name is not None:entry['name']=self._name(name)
            if enabled is not None:entry['enabled']=bool(enabled)
            if delete:entry.update(enabled=False,deleted=True,secret=None)
            if enabled is not None or delete:self._apply(data,entries)
            else:self._save_registry(entries)
        if self.on_change and (enabled is not None or delete):self.on_change()
        return dict(entry)
