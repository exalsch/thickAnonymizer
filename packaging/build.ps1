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
# Remove the trees wholesale. A partial clean let stale intermediates from an
# interrupted build survive and silently produce a corrupt one-file exe whose
# bootloader never extracted.
foreach ($stale in @('build', 'dist')) {
    $path = Join-Path $root $stale
    if (Test-Path $path) { Remove-Item -Recurse -Force $path }
}

Write-Host 'Running PyInstaller (this takes several minutes)...'
& $python -m PyInstaller --noconfirm (Join-Path $root 'packaging\thickanon.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$exe = Join-Path $root 'dist\thickAnonymizer.exe'
if (-not (Test-Path $exe)) { throw "Build reported success but $exe is missing" }

Write-Host 'Smoke-testing the exe...'
# A one-file exe can build cleanly and still be unable to start, for instance
# when stale intermediates leave the archive unembedded. Size and SHA256 mean
# nothing if the binary cannot run, so prove it before reporting them.
$smokeOut = & $exe --help 2>&1
$smokeCode = $LASTEXITCODE
if ($smokeCode -ne 0) {
    Write-Host ($smokeOut | Out-String)
    throw "The exe was built but failed to run (exit code $smokeCode). Delete build\ and dist\ and try again."
}
if (($smokeOut | Out-String) -notmatch 'usage: thickanon') {
    Write-Host ($smokeOut | Out-String)
    throw "The exe ran but did not print the expected CLI usage. The build is not trustworthy."
}
Write-Host '  CLI responds correctly.'

$sizeMb = [math]::Round((Get-Item $exe).Length / 1MB, 1)
# Windows PowerShell 5.1 does not ship Get-FileHash on every host, and the
# script declares #Requires -Version 5.1, so compute the digest with .NET.
$sha = [System.Security.Cryptography.SHA256]::Create()
$stream = [System.IO.File]::OpenRead($exe)
try {
    $hash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '')
} finally {
    $stream.Dispose()
    $sha.Dispose()
}

Write-Host ''
Write-Host "Built:  $exe"
Write-Host "Size:   $sizeMb MB"
Write-Host "SHA256: $hash"
