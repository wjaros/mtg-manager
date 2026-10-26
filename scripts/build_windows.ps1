# Build "MTG Deck Manager" for Windows into dist\: a folder with "MTG Deck Manager.exe" and a zip of it.
# Requirements: uv, Node.js. Run from any directory:  powershell -File scripts\build_windows.ps1
# -ZipOnly zips the built folder again (CI, after the exe was signed).
param([switch]$ZipOnly)
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..").Path
$Version = (Select-String -Path "$Root\backend\mtgdm\__init__.py" -Pattern '__version__ = "(.+)"').Matches[0].Groups[1].Value

function Invoke-Step([string]$Name, [scriptblock]$Command) {
    Write-Host "==> $Name"
    & $Command
    # Native tools report failure only through the exit code.
    if ($LASTEXITCODE -ne 0) { throw "$Name failed with exit code $LASTEXITCODE" }
}

$AppDir = "$Root\dist\MTG Deck Manager"
$Exe = "$AppDir\MTG Deck Manager.exe"
$Zip = "$Root\dist\MTG-Deck-Manager-$Version-windows-x64.zip"

function Write-Zip {
    Write-Host "==> Zip"
    if (Test-Path $Zip) { Remove-Item $Zip }
    Compress-Archive -Path $AppDir -DestinationPath $Zip
    Write-Host ""
    Write-Host "App: $Exe"
    Write-Host "Zip: $Zip"
}

if ($ZipOnly) {
    Write-Zip
    exit 0
}

Push-Location "$Root\frontend"
try {
    Invoke-Step "Frontend dependencies" { npm ci --no-audit --no-fund }
    Invoke-Step "Frontend build" { npm run build }
} finally { Pop-Location }

Push-Location "$Root\backend"
try {
    Invoke-Step "Backend dependencies" { uv sync }
    # Minimal OpenCV (cached in build\opencv-slim): the PyPI wheel carries video and image codecs
    # the app never uses. Needs Visual Studio's C++ tools.
    Invoke-Step "Minimal OpenCV" { $script:Cv2Dir = (uv run python ..\scripts\build_opencv.py) }
    Invoke-Step "Third-party licenses" { uv run python ..\scripts\collect_licenses.py $script:Cv2Dir }
    Invoke-Step "Backend bundle (PyInstaller)" {
        $env:PYTHONPATH = $script:Cv2Dir
        try {
            uv run pyinstaller --noconfirm --clean --distpath "$Root\dist" --workpath "$Root\build\pyinstaller" "$Root\packaging\mtgdm.spec"
        } finally { Remove-Item Env:PYTHONPATH }
    }
} finally { Pop-Location }

# Code signing checks the exe's product name and version (packaging/signpath/).
$Info = (Get-Item $Exe).VersionInfo
if ($Info.ProductName -ne "MTG Deck Manager" -or $Info.ProductVersion -ne $Version) {
    throw "Exe version info is '$($Info.ProductName)' '$($Info.ProductVersion)', expected 'MTG Deck Manager' '$Version'"
}

Write-Zip
