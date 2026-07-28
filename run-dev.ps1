$ErrorActionPreference = "Stop"
$sourceDir = Join-Path $PSScriptRoot "src"
Push-Location $sourceDir
try {
    python -m hidden_preview_builder
} finally {
    Pop-Location
}
