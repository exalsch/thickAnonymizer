#Requires -Version 5.1
<#
  Build the self-contained Windows exe.
      .\packaging\build.ps1
  Prints the resulting path, size and SHA256 so a shared copy can be verified.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$python = Join-Path $root 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    throw "No virtualenv at $python. Create one and run: pip install -e `".[dev]`""
}

if (-not ((Test-Path (Join-Path $root 'packaging\icon.ico')) -and (Test-Path (Join-Path $root 'packaging\splash.png')))) {
    Write-Host 'Generating icon and splash...'
    & $python (Join-Path $root 'packaging\make_icon.py')
}

Write-Host 'Cleaning previous build...'
foreach ($stale in @('build\thickanon', 'dist\thickAnonymizer.exe')) {
    $path = Join-Path $root $stale
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}

Write-Host 'Running PyInstaller (this takes several minutes)...'
& $python -m PyInstaller --noconfirm (Join-Path $root 'packaging\thickanon.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$exe = Join-Path $root 'dist\thickAnonymizer.exe'
if (-not (Test-Path $exe)) { throw "Build reported success but $exe is missing" }

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
$hash = (Get-FileHash $exe -Algorithm SHA256).Hash

Write-Host ''
Write-Host "Built:  $exe"
Write-Host "Size:   $sizeMb MB"
Write-Host "SHA256: $hash"
