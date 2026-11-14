$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')
python -m pip install -e . pyinstaller
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed' }

# Chocolatey can expose wrapper shims on PATH. A shim alone cannot be bundled;
# prefer the actual directory containing both media executables.
$candidates = [System.Collections.Generic.List[string]]::new()
if ($env:CLIPPER_FFMPEG_DIR) { $candidates.Add($env:CLIPPER_FFMPEG_DIR) }
$chocoTools = Join-Path $env:ProgramData 'chocolatey\lib\ffmpeg\tools'
if (Test-Path $chocoTools) {
    Get-ChildItem $chocoTools -Filter ffmpeg.exe -File -Recurse | ForEach-Object { $candidates.Add($_.DirectoryName) }
}
$command = Get-Command ffmpeg.exe -ErrorAction SilentlyContinue
if ($command -and $command.Source -notmatch 'chocolatey[\\/]bin') { $candidates.Add((Split-Path $command.Source)) }
$mediaDir = $candidates | Where-Object {
    (Test-Path (Join-Path $_ 'ffmpeg.exe')) -and (Test-Path (Join-Path $_ 'ffprobe.exe'))
} | Select-Object -First 1
if (-not $mediaDir) { throw 'A full FFmpeg build is required. Set CLIPPER_FFMPEG_DIR to the directory containing ffmpeg.exe and ffprobe.exe.' }

$assets = Join-Path (Get-Location).Path 'clipper/assets'
$argsList = @('--noconfirm', '--clean', '--windowed', '--name', 'Clipper', '--paths', (Get-Location).Path, '--add-data', "$assets;clipper/assets")
foreach ($file in @('ffmpeg.exe', 'ffprobe.exe')) {
    $argsList += @('--add-binary', "$(Join-Path $mediaDir $file);.")
}
Get-ChildItem $mediaDir -Filter '*.dll' -File | ForEach-Object { $argsList += @('--add-binary', "$($_.FullName);.") }
$argsList += 'scripts/launch.py'
python -m PyInstaller @argsList
if ($LASTEXITCODE -ne 0) { throw 'Build failed' }

Copy-Item 'WINDOWS-README.txt' 'dist/Clipper/CTI-ME.txt' -Force
$licenseDir = 'dist/Clipper/licence'
New-Item -ItemType Directory -Force -Path $licenseDir | Out-Null
Copy-Item 'third_party_licenses/GPL-3.txt','third_party_licenses/Qt.txt','third_party_licenses/PyQt6-sip.txt','third_party_licenses/Python.txt' $licenseDir -Force
$ffmpegLicense = Join-Path (Split-Path $mediaDir) 'LICENSE'
if (Test-Path $ffmpegLicense) {
    Copy-Item $ffmpegLicense (Join-Path $licenseDir 'FFmpeg.txt') -Force
} else {
    Write-Warning 'FFmpeg license was not found next to its binary directory; include the license and corresponding source for the supplied build before distribution.'
}
