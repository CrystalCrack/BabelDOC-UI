param(
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
$RootPath = $Root.Path
$ReleaseDir = Join-Path $RootPath "releases"
$BuildDir = Join-Path $ReleaseDir "installer-build"
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
New-Item -ItemType Directory -Force -Path $BuildDir | Out-Null

$PayloadZip = Join-Path $BuildDir "BabelDOC-UI.zip"
$ExeName = "BabelDOC-UI-Setup-$Version"
$ExePath = Join-Path $ReleaseDir "$ExeName.exe"
$VenvPython = Join-Path $RootPath ".venv\Scripts\python.exe"
$Icon = Join-Path $RootPath "babeldoc\assets\ui\babeldoc-ui-icon.ico"
$InstallerScript = Join-Path $RootPath "scripts\windows_installer.py"

if (-not (Test-Path $VenvPython)) {
    throw "Virtual environment not found. Run scripts\setup_windows.ps1 first."
}

Write-Host "Building clean payload archive..."
Invoke-Checked -FilePath "git" -Arguments @(
    "-C",
    "$RootPath",
    "-c",
    "safe.directory=$GitSafeDirectory",
    "archive",
    "--format=zip",
    "--output=$PayloadZip",
    "--prefix=BabelDOC-UI/",
    "HEAD"
)

Write-Host "Checking PyInstaller..."
& $VenvPython -c "import PyInstaller" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing PyInstaller..."
    Invoke-Checked -FilePath $VenvPython -Arguments @(
        "-m",
        "pip",
        "install",
        "pyinstaller"
    )
}

if (Test-Path $ExePath) {
    Remove-Item -LiteralPath $ExePath -Force
}

Write-Host "Building single-file installer executable..."
$distPath = Join-Path $BuildDir "dist"
$workPath = Join-Path $BuildDir "build"
$specPath = $BuildDir
$addData = "$PayloadZip;."
$args = @(
    "-m",
    "PyInstaller",
    "--onefile",
    "--windowed",
    "--clean",
    "--name",
    $ExeName,
    "--distpath",
    $distPath,
    "--workpath",
    $workPath,
    "--specpath",
    $specPath,
    "--add-data",
    $addData
)

if (Test-Path $Icon) {
    $args += @("--icon", $Icon)
}

$args += $InstallerScript

Invoke-Checked -FilePath $VenvPython -Arguments $args

$BuiltExe = Join-Path $distPath "$ExeName.exe"
if (-not (Test-Path $BuiltExe)) {
    throw "PyInstaller did not produce the expected installer: $BuiltExe"
}

Copy-Item -LiteralPath $BuiltExe -Destination $ExePath -Force
$Output = Get-Item -LiteralPath $ExePath
Write-Host "Built installer: $($Output.FullName)"
Write-Host "Size: $([math]::Round($Output.Length / 1MB, 2)) MB"
