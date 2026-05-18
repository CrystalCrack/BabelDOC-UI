param(
    [string]$Version = "",
    [string]$InnoSetupUrl = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_2/innosetup-6.7.2.exe"
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$RootPath = $Root.Path
$ReleaseDir = Join-Path $RootPath "releases"
$BuildDir = Join-Path $ReleaseDir "inno-build"
$PayloadDir = Join-Path $BuildDir "payload"
$SourceDir = Join-Path $PayloadDir "BabelDOC-UI"
$ToolsDir = Join-Path $ReleaseDir "inno-tools"
$InnoDir = Join-Path $ToolsDir "Inno Setup 6"
$Iscc = Join-Path $InnoDir "ISCC.exe"
$GitSafeDirectory = $RootPath.Replace('\', '/')
$env:GIT_CONFIG_GLOBAL = "NUL"

function Invoke-Checked {
    param(
        [Parameter(Mandatory = $true)]
        [string]$FilePath,
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
    }
}

function Find-Iscc {
    $cmd = Get-Command iscc.exe -ErrorAction SilentlyContinue
    if ($cmd) {
        return $cmd.Source
    }
    $common = @(
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
    )
    foreach ($candidate in $common) {
        if ($candidate -and (Test-Path $candidate)) {
            return $candidate
        }
    }
    if (Test-Path $Iscc) {
        return $Iscc
    }
    return $null
}

function Ensure-InnoSetup {
    $found = Find-Iscc
    if ($found) {
        return $found
    }

    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    $installer = Join-Path $ToolsDir "innosetup.exe"
    if (-not (Test-Path $installer)) {
        Write-Host "Downloading Inno Setup compiler..."
        Invoke-WebRequest -Uri $InnoSetupUrl -OutFile $installer
    }

    Write-Host "Installing local Inno Setup compiler..."
    Invoke-Checked -FilePath $installer -Arguments @(
        "/VERYSILENT",
        "/SUPPRESSMSGBOXES",
        "/NORESTART",
        "/CURRENTUSER",
        "/DIR=$InnoDir"
    )

    Start-Sleep -Seconds 2
    if (-not (Test-Path $Iscc)) {
        $found = Get-ChildItem -Path $ToolsDir -Recurse -Filter ISCC.exe -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($found) {
            return $found.FullName
        }
        throw "ISCC.exe was not found after installing Inno Setup."
    }
    return $Iscc
}

if (-not $Version) {
    $Version = (
        & git -C $RootPath -c "safe.directory=$GitSafeDirectory" rev-parse --short HEAD
    ).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $Version) {
        throw "Could not resolve the current git revision."
    }
}

New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
Remove-Item -LiteralPath $BuildDir -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $PayloadDir | Out-Null

$archive = Join-Path $BuildDir "payload.zip"
Write-Host "Creating clean source payload..."
Invoke-Checked -FilePath "git" -Arguments @(
    "-C",
    "$RootPath",
    "-c",
    "safe.directory=$GitSafeDirectory",
    "archive",
    "--format=zip",
    "--output=$archive",
    "--prefix=BabelDOC-UI/",
    "HEAD"
)
Expand-Archive -LiteralPath $archive -DestinationPath $PayloadDir -Force

$compiler = Ensure-InnoSetup
$iss = Join-Path $RootPath "installer\BabelDOC-UI.iss"

Write-Host "Building Inno Setup installer..."
Invoke-Checked -FilePath $compiler -Arguments @(
    "/Qp",
    "/DBuildVersion=$Version",
    "/DSourceDir=$SourceDir",
    "/DOutputDir=$ReleaseDir",
    $iss
)

$output = Join-Path $ReleaseDir "BabelDOC-UI-Inno-Setup-$Version.exe"
if (-not (Test-Path $output)) {
    throw "Inno Setup did not produce the expected installer: $output"
}

$file = Get-Item -LiteralPath $output
Write-Host "Built installer: $($file.FullName)"
Write-Host "Size: $([math]::Round($file.Length / 1MB, 2)) MB"
