# Rebuilds the marketing brochure from the newest raw PDF in .\source
#   .\build-brochure.ps1            build and open the PDF
#   .\build-brochure.ps1 -Setup     install dependencies first (one-time)
#   .\build-brochure.ps1 -Preview   also write page images to output\preview
param([switch]$Setup, [switch]$Preview, [switch]$NoOpen)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$env:PYTHONIOENCODING = "utf-8"

if ($Setup) {
    python -m pip install -r brochure\requirements.txt
    python -m playwright install chromium
}

$buildArgs = @("brochure\build.py")
if ($Preview) { $buildArgs += "--preview" }
python @buildArgs
if ($LASTEXITCODE -ne 0) { throw "Brochure build failed" }

if (-not $NoOpen) {
    $pdf = Get-ChildItem output\*.pdf | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($pdf) { Start-Process $pdf.FullName }
}
