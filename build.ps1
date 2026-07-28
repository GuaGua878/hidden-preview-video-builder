param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$venvDir = Join-Path $projectRoot ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$exePath = Join-Path $projectRoot "dist\HiddenPreviewBuilder.exe"

if (-not (Test-Path -LiteralPath $venvPython)) {
    & $Python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Could not create the build virtual environment."
    }
}

& $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot "requirements-dev.txt")
if ($LASTEXITCODE -ne 0) {
    throw "Could not install build dependencies."
}

& $venvPython -m pip install --disable-pip-version-check -e $projectRoot
if ($LASTEXITCODE -ne 0) {
    throw "Could not install the project into the build environment."
}

& $venvPython -m unittest discover -s (Join-Path $projectRoot "tests") -v
if ($LASTEXITCODE -ne 0) {
    throw "Tests failed; EXE build stopped."
}

Push-Location $projectRoot
try {
    & $venvPython -m PyInstaller `
        --noconfirm `
        --clean `
        --onefile `
        --windowed `
        --name HiddenPreviewBuilder `
        --version-file (Join-Path $projectRoot "version_info.txt") `
        --paths (Join-Path $projectRoot "src") `
        (Join-Path $projectRoot "src\hidden_preview_builder\app.py")
    if ($LASTEXITCODE -ne 0) {
        throw "PyInstaller failed."
    }
} finally {
    Pop-Location
}

if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Expected EXE was not created: $exePath"
}

$process = Start-Process `
    -FilePath $exePath `
    -ArgumentList "--self-test" `
    -WindowStyle Hidden `
    -Wait `
    -PassThru
if ($process.ExitCode -ne 0) {
    throw "Packaged EXE self-test failed with exit code $($process.ExitCode)."
}

Write-Output $exePath
