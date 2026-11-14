"""Fetch pinned, checksum-verified upstream release without unpacking arbitrary paths."""
import hashlib
import io
import platform
import re
import tarfile
import urllib.request
import zipfile
from pathlib import Path

VERSION='8.0.61'
ROOT=Path(__file__).resolve().parents[1]

def main():
    os_name={'Windows':'windows','Linux':'linux'}[platform.system()]
    if platform.machine().lower() not in ('amd64','x86_64'):raise RuntimeError('Release builds currently require x86_64')
    ext='zip' if os_name=='windows' else 'tar.gz'
    name=f'CLIProxyAPI_{VERSION}_{os_name}_amd64.{ext}'
    base=f'https://github.com/router-for-me/CLIProxyAPI/releases/download/v{VERSION}/'
    def get(file):
        with urllib.request.urlopen(base+file,timeout=180) as r:return r.read()
    checks=get('checksums.txt').decode()
    expected=None
    for line in checks.splitlines():
        parts=line.split()
        if len(parts)==2 and parts[1].lstrip('*')==name:expected=parts[0]
    if not expected or not re.fullmatch('[a-fA-F0-9]{64}',expected):raise RuntimeError('No valid upstream checksum')
    data=get(name)
    if hashlib.sha256(data).hexdigest()!=expected.lower():raise RuntimeError('Core checksum mismatch')
    output=ROOT/'core';output.mkdir(exist_ok=True)
    binary='cli-proxy-api.exe' if os_name=='windows' else 'cli-proxy-api'
    wanted={binary,'LICENSE'}
    if ext=='zip':
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for entry in z.infolist():
                if Path(entry.filename).name in wanted:
                    (output/Path(entry.filename).name).write_bytes(z.read(entry))
    else:
        with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as z:
            for entry in z.getmembers():
                if entry.isfile() and Path(entry.name).name in wanted:
                    (output/Path(entry.name).name).write_bytes(z.extractfile(entry).read())
    if not all((output/f).exists() for f in wanted):raise RuntimeError('Incomplete core archive')
    (output/binary).chmod(0o755)
    print(f'Verified CLIProxyAPI {VERSION} for {os_name}')

if __name__=='__main__':main()
