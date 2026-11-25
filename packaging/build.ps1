#Requires -Version 5.1
<#
  Build the self-contained Windows app (one-dir: a folder with the exe).
      .\packaging\build.ps1
      .\packaging\build.ps1 -OutDir C:\temp\try   # build somewhere other than dist\
      .\packaging\build.ps1 -NoZip                # skip the zip for sharing
  Produces <OutDir>\thickAnonymizer\thickAnonymizer.exe and, unless -NoZip,
  <OutDir>\thickAnonymizer.zip. Prints sizes and the zip's SHA256 so a shared
  copy can be verified.
#>
[CmdletBinding()]
param(
    [string]$OutDir,
    [switch]$NoZip
)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not $OutDir) { $OutDir = Join-Path $root 'dist' }

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
# corrupt exe, so that clean is deliberate. The output folder is left alone:
# the user's existing working app must survive both the minutes this takes
# and a failed build.
$buildDir = Join-Path $root 'build'
if (Test-Path $buildDir) { Remove-Item -Recurse -Force $buildDir }

$staging = Join-Path $root 'build\staging'

Write-Host 'Running PyInstaller (this takes several minutes)...'
& $python -m PyInstaller --noconfirm --distpath $staging (Join-Path $root 'packaging\thickanon.spec')
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$stagedDir = Join-Path $staging 'thickAnonymizer'
$staged = Join-Path $stagedDir 'thickAnonymizer.exe'
if (-not (Test-Path $staged)) { throw "Build reported success but $staged is missing" }

Write-Host 'Checking the bundled Visual C++ runtime...'
# onnxruntime crashes with an access violation on a Visual C++ runtime older
# than 14.40, and --help does not load onnxruntime, so the smoke test below
# cannot see it. The spec takes the runtime from System32; this proves it.
$minVc = [version]'14.40.0.0'
foreach ($name in 'msvcp140.dll', 'vcruntime140.dll') {
    $dll = Join-Path $stagedDir "_internal\$name"
    if (-not (Test-Path $dll)) { continue }
    $vi = (Get-Item $dll).VersionInfo
    $ver = [version]::new($vi.FileMajorPart, $vi.FileMinorPart, $vi.FileBuildPart, $vi.FilePrivatePart)
    if ($ver -lt $minVc) {
        throw ("The build bundled $name $ver, older than $minVc. GLiNER would crash. " +
               "Install the latest Visual C++ Redistributable (x64) and build again.")
    }
    Write-Host "  $name $ver"
}

Write-Host 'Smoke-testing the exe...'
# An exe can build cleanly and still be unable to start, for instance when a
# DLL is missing from the folder. Sizes and hashes mean nothing if the app
# cannot run, so prove it before reporting them.
$smokeOut = & $staged --help 2>&1
$smokeCode = $LASTEXITCODE
if ($smokeCode -ne 0) {
    Write-Host ($smokeOut | Out-String)
    throw "The exe was built but failed to run (exit code $smokeCode). Delete build\ and try again."
}
if (($smokeOut | Out-String) -notmatch 'usage: thickanon') {
    Write-Host ($smokeOut | Out-String)
    throw "The exe ran but did not print the expected CLI usage. The build is not trustworthy."
}
Write-Host '  CLI responds correctly.'

Write-Host 'Promoting the verified build...'
if (-not (Test-Path $OutDir)) { New-Item -ItemType Directory -Path $OutDir | Out-Null }
$app = Join-Path $OutDir 'thickAnonymizer'
$previous = Join-Path $OutDir 'thickAnonymizer.previous'
# The staged app has already proved it runs. The previous one is moved aside,
# not deleted, so a failed move can put it back. Until the new folder is in
# place the user's old app is untouched.
if (Test-Path $previous) { Remove-Item -Recurse -Force $previous }
if (Test-Path $app) {
    try {
        Rename-Item -Path $app -NewName 'thickAnonymizer.previous'
    } catch {
        throw ("Built and verified, but could not move the previous app aside: " +
               "$($_.Exception.Message). Close thickAnonymizer if it is running. " +
               "The new build is waiting at $stagedDir.")
    }
}
try {
    Move-Item -Path $stagedDir -Destination $app
} catch {
    if (Test-Path $previous) { Rename-Item -Path $previous -NewName 'thickAnonymizer' }
    throw ("Built and verified, but could not move it to $app : $($_.Exception.Message). " +
           "The previous app is back in place.")
}
if (Test-Path $previous) { Remove-Item -Recurse -Force $previous }

$exe = Join-Path $app 'thickAnonymizer.exe'
$folderMb = [math]::Round(((Get-ChildItem $app -Recurse -File | Measure-Object Length -Sum).Sum) / 1MB, 1)

Write-Host ''
Write-Host "Built:  $exe"
Write-Host "Folder: $folderMb MB"

$legacy = Join-Path $OutDir 'thickAnonymizer.exe'
if (Test-Path $legacy) {
    Write-Host "Note:   $legacy is the old one-file build. It still works; delete it when the new app is fine."
}

if (-not $NoZip) {
    Write-Host 'Zipping for sharing...'
    $zip = Join-Path $OutDir 'thickAnonymizer.zip'
    if (Test-Path $zip) { Remove-Item -Force $zip }
    Compress-Archive -Path $app -DestinationPath $zip -CompressionLevel Optimal
    $zipMb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
    # Windows PowerShell 5.1 does not ship Get-FileHash on every host, and the
    # script declares #Requires -Version 5.1, so compute the digest with .NET.
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $stream = [System.IO.File]::OpenRead($zip)
    try {
        $hash = [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-', '')
    } finally {
        $stream.Dispose()
        $sha.Dispose()
    }
    Write-Host "Zip:    $zip"
    Write-Host "Size:   $zipMb MB"
    Write-Host "SHA256: $hash"
}
