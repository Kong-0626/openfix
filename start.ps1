param(
    [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$bundledPython = Join-Path $root "runtime\python312\python.exe"

function Test-OpenFixPython {
    param([string]$Executable, [string[]]$Prefix = @())
    try {
        $version = & $Executable @Prefix -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($LASTEXITCODE -eq 0 -and $version) {
            $parts = $version.Trim().Split(".")
            return ([int]$parts[0] -gt 3) -or ([int]$parts[0] -eq 3 -and [int]$parts[1] -ge 10)
        }
    } catch {
        return $false
    }
    return $false
}

$python = $null
$pythonPrefix = @()

if ($env:OPENFIX_PYTHON -and (Test-Path -LiteralPath $env:OPENFIX_PYTHON)) {
    $python = $env:OPENFIX_PYTHON
} elseif (Test-Path -LiteralPath $bundledPython) {
    $python = $bundledPython
} else {
    foreach ($candidate in @("python", "python3")) {
        if (Get-Command $candidate -ErrorAction SilentlyContinue) {
            if (Test-OpenFixPython -Executable $candidate) {
                $python = $candidate
                break
            }
        }
    }
    if (-not $python -and (Get-Command "py" -ErrorAction SilentlyContinue)) {
        if (Test-OpenFixPython -Executable "py" -Prefix @("-3")) {
            $python = "py"
            $pythonPrefix = @("-3")
        }
    }
}

if (-not $python) {
    Write-Host "OpenFix requires Python 3.10 or newer." -ForegroundColor Red
    Write-Host "Set OPENFIX_PYTHON or use the bundled runtime/python312 directory."
    exit 1
}

$env:PYTHONUTF8 = "1"
$env:OPENFIX_QUIET = "0"

Write-Host ""
Write-Host "OpenFix - Industrial Maintenance Evidence Agent" -ForegroundColor Green
Write-Host "Open: http://127.0.0.1:$Port"
Write-Host "Press Ctrl+C to stop."
Write-Host ""

Push-Location $root
try {
    & $python @pythonPrefix app.py --host 127.0.0.1 --port $Port
} finally {
    Pop-Location
}
