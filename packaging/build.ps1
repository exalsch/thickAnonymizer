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
# Only `build` is removed. Stale intermediates there once silently produced a
# corrupt one-file exe, so that clean is deliberate. `dist` is left alone: the
# user's existing working exe must survive both the ten minutes this takes and
# a failed build.
$buildDir = Join-Path $root 'build'
if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }

$staging = Join-Path $root 'build\staging'
if (Test-Path $staging) { Remove-Item -Recurse -Force $staging }

Write-Host 'Running PyInstaller (this takes several minutes)...'
& $python -m PyInstaller --noconfirm --distpath $staging (Join-Path $root 'packaging\thickanon.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$staged = Join-Path $staging 'thickAnonymizer.exe'
if (-not (Test-Path $staged)) { throw "Build reported success but $staged is missing" }

Write-Host 'Smoke-testing the exe...'
# A one-file exe can build cleanly and still be unable to start, for instance
# when stale intermediates leave the archive unembedded. Size and SHA256 mean
# nothing if the binary cannot run, so prove it before reporting them.
$smokeOut = & $staged --help 2>&1
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

Write-Host 'Promoting the verified exe...'
$distDir = Join-Path $root 'dist'
if (-not (Test-Path $distDir)) { New-Item -ItemType Directory -Path $distDir | Out-Null }
$exe = Join-Path $distDir 'thickAnonymizer.exe'
# The staged exe has already proved it runs, so replacing the previous one is
# safe. Until this line the user's old exe is untouched.
try {
    Move-Item -Force -Path $staged -Destination $exe
} catch {
    throw ("Built and verified, but could not replace $exe : $($_.Exception.Message). " +
           "Close thickAnonymizer if it is running. The new exe is waiting at $staged.")
}

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
