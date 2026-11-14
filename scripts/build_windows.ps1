$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
python scripts/download_core.py
if ($LASTEXITCODE -ne 0) { throw 'Core download failed' }
python -m pip install -r requirements.txt pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }
python -m PyInstaller --noconfirm --clean --windowed --name QingzhouAIStation --hidden-import capability_window --hidden-import capability_tester --copy-metadata aiohttp --copy-metadata PyYAML --icon assets/icon.ico --add-data "assets;assets" --add-data "core;core" --add-data "THIRD_PARTY_LICENSES.txt;." app.py
if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
Copy-Item README.md dist/QingzhouAIStation/
$pythonLicense = Join-Path (python -c "import sys; print(sys.base_prefix)") 'LICENSE.txt'
if (Test-Path $pythonLicense) { Copy-Item $pythonLicense dist/QingzhouAIStation/PYTHON-LICENSE.txt }
Compress-Archive -Path dist/QingzhouAIStation -DestinationPath dist/qingzhou-ai-station-0.3.0-windows-x64.zip -Force
$iscc = 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe'
if (!(Test-Path $iscc)) {
  choco install innosetup -y --no-progress
  if ($LASTEXITCODE -ne 0) { throw 'Inno Setup installation failed' }
}
& $iscc scripts/windows-installer.iss
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
