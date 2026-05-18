param(
    [switch]$SkipWarmup,
    [switch]$NoPythonInstall,
    [switch]$NoShortcuts
)

$ErrorActionPreference = "Stop"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

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

function Find-Python {
    $candidates = @(
        "py -3.12",
        "py -3.11",
        "py -3.10",
        "python"
    )

    foreach ($candidate in $candidates) {
        $parts = $candidate.Split(" ")
        $exe = $parts[0]
        $args = @()
        if ($parts.Length -gt 1) {
            $args = $parts[1..($parts.Length - 1)]
        }
        try {
            $version = & $exe @args -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
            if ($LASTEXITCODE -eq 0 -and $version -match "^(3\.10|3\.11|3\.12|3\.13)$") {
                return @{ Exe = $exe; Args = $args }
            }
        }
        catch {
            continue
        }
    }
    return $null
}

function Install-Python {
    if ($NoPythonInstall) {
        throw "Python 3.10-3.13 was not found. Install Python first, then rerun this script."
    }

    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if (-not $winget) {
        throw "Python 3.10-3.13 was not found, and winget is unavailable. Install Python 3.12 manually, then rerun this script."
    }

    Write-Host "Python 3.10-3.13 was not found. Installing Python 3.12 with winget..."
    Invoke-Checked -FilePath "winget" -Arguments @(
        "install",
        "--id",
        "Python.Python.3.12",
        "--exact",
        "--source",
        "winget",
        "--accept-package-agreements",
        "--accept-source-agreements"
    )

    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("PATH", "User")
    $python = Find-Python
    if (-not $python) {
        throw "Python installation completed, but Python is still not visible in PATH. Open a new PowerShell window and rerun this script."
    }
    return $python
}

function New-BabelDocShortcut {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ShortcutPath
    )

    $Launcher = Join-Path $Root ".venv\Scripts\pythonw.exe"
    $Arguments = "-m babeldoc.ui_app"
    if (-not (Test-Path $Launcher)) {
        $Launcher = Join-Path $Root "run_babeldoc_ui.bat"
        $Arguments = ""
    }
    $Icon = Join-Path $Root "babeldoc\assets\ui\babeldoc-ui-icon.ico"
    $ShortcutFolder = Split-Path -Parent $ShortcutPath
    New-Item -ItemType Directory -Force -Path $ShortcutFolder | Out-Null

    $Shell = New-Object -ComObject WScript.Shell
    $Shortcut = $Shell.CreateShortcut($ShortcutPath)
    $Shortcut.TargetPath = $Launcher
    $Shortcut.Arguments = $Arguments
    $Shortcut.WorkingDirectory = $Root
    $Shortcut.Description = "BabelDOC UI"
    if (Test-Path $Icon) {
        $Shortcut.IconLocation = "$Icon,0"
    }
    $Shortcut.Save()
}

Write-Host "BabelDOC Windows setup"
Write-Host "Workspace: $Root"

$Python = Find-Python
if (-not $Python) {
    $Python = Install-Python
}
Write-Host "Using Python command: $($Python.Exe) $($Python.Args -join ' ')"

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    Invoke-Checked -FilePath $Python.Exe -Arguments @($Python.Args + @("-m", "venv", ".venv"))
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"

Write-Host "Upgrading pip..."
Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "--upgrade", "pip")

Write-Host "Installing BabelDOC and dependencies..."
Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "-e", ".")

Write-Host "Installing Windows runtime helpers..."
Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "msvc-runtime", "tkinterdnd2")

Write-Host "Pinning a Windows-tested onnxruntime/numpy combination..."
Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "pip", "install", "--force-reinstall", "onnxruntime==1.20.1", "numpy>=2.0.2,<2.3")

Write-Host "Checking imports..."
Invoke-Checked -FilePath $VenvPython -Arguments @("-c", "import tkinter, tkinterdnd2, numpy, cv2, onnxruntime, openai; print('OK', numpy.__version__, cv2.__version__, onnxruntime.__version__, openai.__version__)")

if (-not $SkipWarmup) {
    Write-Host "Warming up BabelDOC assets. This may download fonts and the layout model..."
    $env:HOME = Join-Path $env:APPDATA "BabelDOC\home"
    $env:USERPROFILE = $env:HOME
    New-Item -ItemType Directory -Force -Path $env:HOME | Out-Null
    Invoke-Checked -FilePath $VenvPython -Arguments @("-m", "babeldoc.main", "--warmup")
}

if (-not $NoShortcuts) {
    Write-Host "Creating desktop and Start Menu shortcuts..."
    $Desktop = [Environment]::GetFolderPath("Desktop")
    $Programs = [Environment]::GetFolderPath("Programs")
    New-BabelDocShortcut -ShortcutPath (Join-Path $Desktop "BabelDOC UI.lnk")
    New-BabelDocShortcut -ShortcutPath (Join-Path $Programs "BabelDOC UI\BabelDOC UI.lnk")
}

Write-Host ""
Write-Host "Setup complete."
if (-not $NoShortcuts) {
    Write-Host "Launch BabelDOC UI from the desktop or Start Menu shortcut."
}
Write-Host "You can also launch it with: .\run_babeldoc_ui.bat"
