# Build the portable ORION release: PyInstaller -> self-test of the built app -> zip.
# usage (from the repo root):  powershell -ExecutionPolicy Bypass -File packaging\build.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root ".venv\Scripts\python.exe"

& $py -m PyInstaller packaging\orion.spec --noconfirm --distpath dist --workpath build
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

# Self-test the BUILT app from a copy, with Python removed from PATH (as on a PC without Python).
$test = Join-Path $env:TEMP "orion-release-test"
if (Test-Path $test) { Remove-Item -Recurse -Force $test }
Copy-Item -Recurse dist\ORION $test
$savedPath = $env:PATH
$env:PATH = ($env:PATH -split ';' | Where-Object { $_ -notmatch 'python|\.venv|WindowsApps' }) -join ';'
$p = Start-Process -FilePath "$test\ORION.exe" -ArgumentList "--selftest" -Wait -PassThru
$env:PATH = $savedPath
Copy-Item "$test\selftest.json" dist\selftest.json
Remove-Item -Recurse -Force $test
if ($p.ExitCode -ne 0) { throw "self-test of the built app failed; see dist\selftest.json" }

$version = (Select-String -Path pyproject.toml -Pattern '^version = "(.+)"').Matches[0].Groups[1].Value
$zip = "dist\ORION-$version-win64.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path dist\ORION -DestinationPath $zip
Write-Host "release: $zip ($([math]::Round((Get-Item $zip).Length / 1MB)) MB); self-test passed"
