<#
Build the Lute3 Windows desktop version.

Outputs (in dist\):
  Lute3\                         one-folder app (Lute3.exe)
  Lute3-<ver>-portable.zip       portable version (data stored beside exe)
  Lute3-<ver>-setup.exe          installer (only if Inno Setup 6 is installed)

Usage, from the repo root:
  powershell -ExecutionPolicy Bypass -File windows\build.ps1
  powershell -ExecutionPolicy Bypass -File windows\build.ps1 -SkipInstall
#>
param(
    [string]$Python = ".venv\Scripts\python.exe",
    [switch]$SkipInstall,
    [switch]$SkipDeps
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Test-Path $Python)) {
    Write-Host "Creating venv .venv ..."
    python -m venv .venv
    $Python = ".venv\Scripts\python.exe"
}

if (-not $SkipDeps) {
    Write-Host "Installing dependencies ..."
    & $Python -m pip install --upgrade pip
    & $Python -m pip install .
    & $Python -m pip install -r windows\requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

$Version = (& $Python -c "import lute; print(lute.__version__)").Trim()
Write-Host "Building Lute3 $Version ..."

& $Python -m PyInstaller --noconfirm --clean --distpath dist --workpath build windows\lute3.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Portable zip: Lute3\ folder + portable.txt marker.
$Stage = "build\portable"
if (Test-Path $Stage) { Remove-Item $Stage -Recurse -Force }
New-Item -ItemType Directory -Force $Stage | Out-Null
Copy-Item dist\Lute3 "$Stage\Lute3" -Recurse
Copy-Item windows\portable.txt "$Stage\Lute3\portable.txt"
$Zip = "dist\Lute3-$Version-portable.zip"
if (Test-Path $Zip) { Remove-Item $Zip -Force }
Compress-Archive -Path "$Stage\Lute3" -DestinationPath $Zip
Write-Host "Portable: $Zip"

if ($SkipInstall) { return }

$IsccCandidates = @(
    (Get-Command iscc.exe -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source),
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $IsccCandidates) {
    Write-Warning "Inno Setup 6 not found; skipping installer. Install it with: winget install JRSoftware.InnoSetup"
    return
}
& $IsccCandidates[0] "/DAppVersion=$Version" windows\lute3.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
Write-Host "Installer: dist\Lute3-$Version-setup.exe"
