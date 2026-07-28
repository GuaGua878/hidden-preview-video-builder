param(
    [string]$Version = "0.1.0",
    [string]$FFmpegDir,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$releaseRoot = Join-Path $projectRoot "release"
$artifactStem = "HiddenPreviewBuilder-v$Version-windows-x64-full-portable"
$archiveName = "$artifactStem.zip"
$archivePath = Join-Path $releaseRoot $archiveName
$archiveHashPath = Join-Path $releaseRoot "$archiveName.sha256.txt"
$manifestPath = Join-Path $releaseRoot "$artifactStem.manifest.json"
$exePath = Join-Path $projectRoot "dist\HiddenPreviewBuilder.exe"

function Find-FFmpegBinDirectory {
    param([string]$RequestedDirectory)

    $candidates = @()
    if (-not [string]::IsNullOrWhiteSpace($RequestedDirectory)) {
        $candidates += $RequestedDirectory
    }
    if (-not [string]::IsNullOrWhiteSpace(
        $env:HIDDEN_PREVIEW_FFMPEG_DIR
    )) {
        $candidates += $env:HIDDEN_PREVIEW_FFMPEG_DIR
    }
    foreach ($commandName in @("ffmpeg.exe", "ffprobe.exe")) {
        $commands = Get-Command `
            -Name $commandName `
            -CommandType Application `
            -All `
            -ErrorAction SilentlyContinue
        foreach ($command in $commands) {
            $candidates += Split-Path -Parent $command.Source
        }
    }
    if (-not [string]::IsNullOrWhiteSpace($env:PATH)) {
        $separator = [regex]::Escape(
            [string][System.IO.Path]::PathSeparator
        )
        $candidates += $env:PATH -split $separator
    }

    $seen = @{}
    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        $cleaned = $candidate.Trim().Trim('"')
        if (-not (Test-Path -LiteralPath $cleaned -PathType Container)) {
            continue
        }
        $resolved = (Resolve-Path -LiteralPath $cleaned).Path
        $key = $resolved.ToLowerInvariant()
        if ($seen.ContainsKey($key)) {
            continue
        }
        $seen[$key] = $true
        if (
            (Test-Path -LiteralPath (Join-Path $resolved "ffmpeg.exe")) -and
            (Test-Path -LiteralPath (Join-Path $resolved "ffprobe.exe"))
        ) {
            return $resolved
        }
    }

    throw (
        "Could not find one directory containing both ffmpeg.exe and " +
        "ffprobe.exe. Use -FFmpegDir or HIDDEN_PREVIEW_FFMPEG_DIR."
    )
}

foreach ($target in @($archivePath, $archiveHashPath, $manifestPath)) {
    if (Test-Path -LiteralPath $target) {
        throw "Release target already exists; refusing to overwrite: $target"
    }
}

$ffmpegBinDir = Find-FFmpegBinDirectory -RequestedDirectory $FFmpegDir

if (-not $SkipBuild) {
    $hadConfiguredFFmpeg = Test-Path Env:HIDDEN_PREVIEW_FFMPEG_DIR
    $previousConfiguredFFmpeg = $env:HIDDEN_PREVIEW_FFMPEG_DIR
    try {
        $env:HIDDEN_PREVIEW_FFMPEG_DIR = $ffmpegBinDir
        & (Join-Path $projectRoot "build.ps1")
        if ($LASTEXITCODE -ne 0) {
            throw "Build failed; release packaging stopped."
        }
    } finally {
        if ($hadConfiguredFFmpeg) {
            $env:HIDDEN_PREVIEW_FFMPEG_DIR = $previousConfiguredFFmpeg
        } else {
            Remove-Item Env:HIDDEN_PREVIEW_FFMPEG_DIR -ErrorAction SilentlyContinue
        }
    }
}

if (-not (Test-Path -LiteralPath $exePath)) {
    throw "Packaged EXE not found: $exePath"
}

$exeItem = Get-Item -LiteralPath $exePath
$versionInfo = $exeItem.VersionInfo
if ($versionInfo.ProductVersion -ne $Version) {
    throw "EXE product version is '$($versionInfo.ProductVersion)', expected '$Version'."
}
if ($versionInfo.CompanyName -ne "教主") {
    throw "EXE publisher metadata is '$($versionInfo.CompanyName)', expected '教主'."
}

$ffmpegPath = Join-Path $ffmpegBinDir "ffmpeg.exe"
$ffprobePath = Join-Path $ffmpegBinDir "ffprobe.exe"
$ffmpegRoot = Split-Path -Parent $ffmpegBinDir
$ffmpegLicensePath = Join-Path $ffmpegRoot "LICENSE"
$ffmpegReadmePath = Join-Path $ffmpegRoot "README.txt"
foreach ($requiredPath in @($ffmpegLicensePath, $ffmpegReadmePath)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Required FFmpeg distribution file not found: $requiredPath"
    }
}

$ffmpegVersionOutput = (& $ffmpegPath -version 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect bundled ffmpeg.exe."
}
$ffprobeVersionOutput = (& $ffprobePath -version 2>&1) -join "`n"
if ($LASTEXITCODE -ne 0) {
    throw "Could not inspect bundled ffprobe.exe."
}
foreach ($requiredFlag in @(
    "--enable-gpl",
    "--enable-version3",
    "--enable-static",
    "--enable-libx264"
)) {
    if (-not $ffmpegVersionOutput.Contains($requiredFlag)) {
        throw "FFmpeg build is missing required flag: $requiredFlag"
    }
}

$ffmpegVersionLine = (
    $ffmpegVersionOutput -split "\r?\n" |
        Select-Object -First 1
).Trim()
$ffprobeVersionLine = (
    $ffprobeVersionOutput -split "\r?\n" |
        Select-Object -First 1
).Trim()
$configurationLine = (
    $ffmpegVersionOutput -split "\r?\n" |
        Where-Object { $_ -like "configuration:*" } |
        Select-Object -First 1
).Trim()
$ffmpegReadme = Get-Content -Raw -LiteralPath $ffmpegReadmePath
$licenseMatch = [regex]::Match(
    $ffmpegReadme,
    "(?m)^License:\s*(.+?)\s*$"
)
$sourceMatch = [regex]::Match(
    $ffmpegReadme,
    "(?m)^Source Code:\s*(\S+)\s*$"
)
if (-not $licenseMatch.Success -or -not $sourceMatch.Success) {
    throw "FFmpeg README.txt does not contain parseable license/source metadata."
}
$ffmpegLicenseName = $licenseMatch.Groups[1].Value.Trim()
$ffmpegSourceUrl = $sourceMatch.Groups[1].Value.Trim()
if ($ffmpegLicenseName -ne "GPL v3") {
    throw "Expected a GPL v3 FFmpeg build, found '$ffmpegLicenseName'."
}

$tempBase = Join-Path ([System.IO.Path]::GetTempPath()) "hidden-preview-builder-release"
New-Item -ItemType Directory -Path $tempBase -Force | Out-Null
$runTemp = Join-Path $tempBase ([guid]::NewGuid().ToString("N"))
$staging = Join-Path $runTemp $artifactStem
$tempArchive = Join-Path $runTemp $archiveName
New-Item -ItemType Directory -Path $staging -Force | Out-Null

try {
    Copy-Item -LiteralPath $exePath -Destination $staging
    Copy-Item -LiteralPath $ffmpegPath -Destination $staging
    Copy-Item -LiteralPath $ffprobePath -Destination $staging
    foreach ($document in @(
        "QUICKSTART.zh-CN.md",
        "README.md",
        "LICENSE",
        "THIRD_PARTY_NOTICES.md"
    )) {
        Copy-Item `
            -LiteralPath (Join-Path $projectRoot $document) `
            -Destination $staging
    }

    $ffmpegNoticeDir = Join-Path $staging "third-party\ffmpeg"
    New-Item -ItemType Directory -Path $ffmpegNoticeDir -Force |
        Out-Null
    Copy-Item `
        -LiteralPath $ffmpegLicensePath `
        -Destination (Join-Path $ffmpegNoticeDir "LICENSE-GPLv3.txt")
    Copy-Item `
        -LiteralPath $ffmpegReadmePath `
        -Destination (Join-Path $ffmpegNoticeDir "README-build.txt")
    @(
        "Bundled component: FFmpeg and ffprobe"
        "Build: $ffmpegVersionLine"
        "License: $ffmpegLicenseName"
        "Corresponding upstream source: $ffmpegSourceUrl"
        "Build distributor: https://www.gyan.dev/ffmpeg/builds/"
        ""
        "See LICENSE-GPLv3.txt and README-build.txt in this directory."
        "The project MIT License does not apply to these FFmpeg binaries."
    ) | Set-Content `
        -LiteralPath (Join-Path $ffmpegNoticeDir "SOURCE.txt") `
        -Encoding utf8

    $exeHash = Get-FileHash -LiteralPath (Join-Path $staging "HiddenPreviewBuilder.exe") -Algorithm SHA256
    $ffmpegHash = Get-FileHash -LiteralPath (Join-Path $staging "ffmpeg.exe") -Algorithm SHA256
    $ffprobeHash = Get-FileHash -LiteralPath (Join-Path $staging "ffprobe.exe") -Algorithm SHA256
    @(
        "$($exeHash.Hash) *HiddenPreviewBuilder.exe"
        "$($ffmpegHash.Hash) *ffmpeg.exe"
        "$($ffprobeHash.Hash) *ffprobe.exe"
    ) |
        Set-Content -LiteralPath (Join-Path $staging "SHA256SUMS.txt") -Encoding ascii

    $selfTestReportPath = Join-Path $staging ".portable-self-test.json"
    $selfTestArguments = (
        '--self-test-report "{0}"' -f $selfTestReportPath
    )
    $selfTestProcess = Start-Process `
        -FilePath (Join-Path $staging "HiddenPreviewBuilder.exe") `
        -ArgumentList $selfTestArguments `
        -WindowStyle Hidden `
        -Wait `
        -PassThru
    if ($selfTestProcess.ExitCode -ne 0) {
        throw (
            "Full-portable EXE self-test failed with exit code " +
            "$($selfTestProcess.ExitCode)."
        )
    }
    if (-not (Test-Path -LiteralPath $selfTestReportPath)) {
        throw "Full-portable EXE did not create its self-test report."
    }
    $selfTest = Get-Content -Raw -LiteralPath $selfTestReportPath |
        ConvertFrom-Json
    $expectedFFmpeg = (Resolve-Path -LiteralPath (
        Join-Path $staging "ffmpeg.exe"
    )).Path
    $expectedFFprobe = (Resolve-Path -LiteralPath (
        Join-Path $staging "ffprobe.exe"
    )).Path
    if (
        $selfTest.status -ne "PASS" -or
        -not [string]::Equals(
            $selfTest.ffmpeg,
            $expectedFFmpeg,
            [System.StringComparison]::OrdinalIgnoreCase
        ) -or
        -not [string]::Equals(
            $selfTest.ffprobe,
            $expectedFFprobe,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        throw "Full-portable EXE did not resolve the bundled media tools."
    }
    Remove-Item -LiteralPath $selfTestReportPath -Force

    Compress-Archive `
        -Path (Join-Path $staging "*") `
        -DestinationPath $tempArchive `
        -CompressionLevel Optimal

    New-Item -ItemType Directory -Path $releaseRoot -Force | Out-Null
    Move-Item -LiteralPath $tempArchive -Destination $archivePath
    $archiveHash = Get-FileHash -LiteralPath $archivePath -Algorithm SHA256
    "$($archiveHash.Hash) *$archiveName" |
        Set-Content -LiteralPath $archiveHashPath -Encoding ascii

    $signature = Get-AuthenticodeSignature -LiteralPath $exePath
    $manifest = [ordered]@{
        schema = "hidden-preview-builder-release-v2"
        created_utc = [DateTime]::UtcNow.ToString("o")
        product = "Hidden Preview Builder"
        version = $Version
        publisher = "教主"
        platform = "windows-x64"
        package_variant = "full-portable"
        default_release_asset = $true
        asset = $archiveName
        asset_bytes = (Get-Item -LiteralPath $archivePath).Length
        asset_sha256 = $archiveHash.Hash
        executable = "HiddenPreviewBuilder.exe"
        executable_bytes = $exeItem.Length
        executable_sha256 = $exeHash.Hash
        executable_company_name = $versionInfo.CompanyName
        executable_product_version = $versionInfo.ProductVersion
        authenticode_status = $signature.Status.ToString()
        portable_self_test = "PASS"
        media_tools_resolved_from = "archive-root"
        ffmpeg_bundled = $true
        ffmpeg = [ordered]@{
            executable = "ffmpeg.exe"
            bytes = (Get-Item -LiteralPath $ffmpegPath).Length
            sha256 = $ffmpegHash.Hash
            version = $ffmpegVersionLine
            configuration = $configurationLine
            license = $ffmpegLicenseName
            source = $ffmpegSourceUrl
            license_file = "third-party/ffmpeg/LICENSE-GPLv3.txt"
            build_readme = "third-party/ffmpeg/README-build.txt"
            source_notice = "third-party/ffmpeg/SOURCE.txt"
        }
        ffprobe = [ordered]@{
            executable = "ffprobe.exe"
            bytes = (Get-Item -LiteralPath $ffprobePath).Length
            sha256 = $ffprobeHash.Hash
            version = $ffprobeVersionLine
        }
    }
    $manifest |
        ConvertTo-Json -Depth 6 |
        Set-Content -LiteralPath $manifestPath -Encoding utf8
} finally {
    if (Test-Path -LiteralPath $runTemp) {
        $resolvedTempBase = (Resolve-Path -LiteralPath $tempBase).Path.TrimEnd("\")
        $resolvedRunTemp = (Resolve-Path -LiteralPath $runTemp).Path
        if ($resolvedRunTemp.StartsWith(
            $resolvedTempBase + "\",
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            Remove-Item -LiteralPath $resolvedRunTemp -Recurse -Force
        } else {
            throw "Refusing to clean unexpected staging directory: $resolvedRunTemp"
        }
    }
}

[pscustomobject]@{
    Archive = $archivePath
    ArchiveSHA256 = $archiveHash.Hash
    Manifest = $manifestPath
    Publisher = $versionInfo.CompanyName
    Version = $versionInfo.ProductVersion
    Signature = $signature.Status.ToString()
    Variant = "full-portable"
    FFmpeg = $ffmpegVersionLine
}
