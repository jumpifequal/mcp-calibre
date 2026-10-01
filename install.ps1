<#
.SYNOPSIS
  Installs calibre-mcp on Windows: venv, dependencies, index build, optional Claude Desktop registration.

.PARAMETER Library
  Calibre library folder. If omitted: auto-detected from %APPDATA%\calibre\global.py.json.
  Do NOT end the path with a backslash inside quotes ("C:\path\" breaks Windows argument parsing).

.PARAMETER Pdf
  pymupdf (fast, AGPL-3.0) | pypdf (slow, BSD) | none. Only needed for PDFs NOT yet indexed by Calibre
  and for page-range reading (calibre_read_section).

.PARAMETER Register
  Adds/updates the "calibre" entry in %APPDATA%\Claude\claude_desktop_config.json (with backup).

.PARAMETER SkipSync
  Skip the initial full-text index build.

.PARAMETER NoSemantic
  Skip the semantic-search dependencies (requirements-semantic.txt: numpy, fastembed, ~28 packages) and the
  model download (~220 MB, once, into %LOCALAPPDATA%\calibre-mcp\models). Both happen by default; the index
  itself is always built later, explicitly:
  .venv\Scripts\python.exe calibre_mcp.py --build-embeddings
  (-Semantic is still accepted for backward compatibility and has no effect.)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File .\install.ps1 -Library "D:\Books\Calibre Library" -Pdf pymupdf -Register
#>
[CmdletBinding()]
param(
    [string]$Library,
    [ValidateSet('pymupdf', 'pypdf', 'none')][string]$Pdf = 'pymupdf',
    [switch]$Register,
    [switch]$SkipSync,
    [switch]$NoSemantic,
    [switch]$Semantic   # deprecated: semantic deps are now the default
)
$ErrorActionPreference = 'Stop'

function Test-OneDrivePath([string]$p) {
    foreach ($root in @($env:OneDrive, $env:OneDriveCommercial, $env:OneDriveConsumer) | Where-Object { $_ }) {
        if ($p.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

$here   = Split-Path -Parent $MyInvocation.MyCommand.Path
$server = Join-Path $here 'calibre_mcp.py'
$venv   = Join-Path $here '.venv'
$py     = Join-Path $venv 'Scripts\python.exe'

if ((Test-OneDrivePath $here) -or (Test-Path -LiteralPath (Join-Path $here '..\metadata.db'))) {
    Write-Warning ("The repo is inside OneDrive and/or inside the Calibre library: the .venv (thousands of files) " +
                   "will be synced and Calibre will report an extra folder. Recommended: move it, e.g. C:\Tools\mcp-calibre")
}

# --- Python >= 3.10 (3.12+ recommended: SQLite >= 3.43 -> contentless index, ~1/3 of the disk space)
$launcher = Get-Command py -ErrorAction SilentlyContinue
if ($launcher) { $pyExe = 'py'; $pyPre = @('-3') } else { $pyExe = 'python'; $pyPre = @() }
$ver = & $pyExe @pyPre -c "import sys;print('%d.%d'%sys.version_info[:2])"
if ([version]$ver -lt [version]'3.10') { throw "Python >= 3.10 required (found $ver). Install from python.org (not the Microsoft Store)." }
Write-Host "[+] Python $ver"

if (-not (Test-Path $py)) {
    & $pyExe @pyPre -m venv $venv
    Write-Host "[+] venv created: $venv"
}
& $py -m pip install --disable-pip-version-check -q --upgrade pip
& $py -m pip install --disable-pip-version-check -q -r (Join-Path $here 'requirements.txt')
if ($Pdf -ne 'none') { & $py -m pip install --disable-pip-version-check -q $Pdf }
if (-not $NoSemantic) {
    # Non-blocking: a failure here must not break the core install.
    $bits = & $py -c "import struct;print(struct.calcsize('P')*8)"
    if ($bits -ne '64') {
        Write-Warning "Semantic search skipped: it needs 64-bit Python (found $bits-bit; onnxruntime has no 32-bit wheels)."
    } else {
        & $py -m pip install --disable-pip-version-check -q -r (Join-Path $here 'requirements-semantic.txt')
        if ($LASTEXITCODE -eq 0) {
            Write-Host "[+] Semantic search deps installed"
            Write-Host "[*] Downloading the embedding model (~220 MB, once) into $env:LOCALAPPDATA\calibre-mcp\models ..."
            & $py $server --download-model
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[+] Model ready: semantic search runs fully on this machine from now on"
            } else {
                Write-Warning "Model download failed (network/proxy? set HTTPS_PROXY). Core server is fine; retry with: $py $server --download-model"
            }
            Write-Host "    Build the index when ready (CPU heavy, resumable): $py $server --build-embeddings --max-books 50"
        } else {
            Write-Warning "Semantic search deps failed to install; core server is fine. Retry: $py -m pip install -r requirements-semantic.txt"
        }
    }
}
Write-Host "[+] Dependencies installed (PDF backend: $Pdf)"

$envVars = @{}
if ($Library) {
    # Classic Windows pitfall: "C:\path\" -> the trailing \" is parsed as an escaped quote and the
    # following arguments (-Pdf, -Register) end up inside -Library.
    if ($Library.Contains('"')) {
        throw ("-Library contains a quote: the path probably ends with '\' before the closing quote and " +
               "swallowed the other parameters. Remove the trailing backslash and run again. Received: $Library")
    }
    $Library = $Library.Trim().TrimEnd('\', '/')
    if ($Library.IndexOfAny([IO.Path]::GetInvalidPathChars()) -ge 0) { throw "Invalid characters in path: $Library" }
    if (-not (Test-Path -LiteralPath (Join-Path $Library 'metadata.db'))) { throw "metadata.db not found in '$Library'" }
    if (Test-OneDrivePath $Library) {
        Write-Warning ("Library is in a OneDrive folder: set it to 'Always keep on this device', " +
                       "otherwise on-demand EPUB/PDF reading forces file downloads.")
    }
    $envVars['CALIBRE_LIBRARY'] = (Resolve-Path -LiteralPath $Library).Path
    $env:CALIBRE_LIBRARY = $envVars['CALIBRE_LIBRARY']
}

& $py $server --status
if (-not $SkipSync) {
    Write-Host "[*] Building/refreshing the full-text index (first run: ~30-60 s per GB of text)..."
    & $py $server --sync
}

$entry = [ordered]@{ command = $py; args = @($server) }
if ($envVars.Count) { $entry['env'] = $envVars }

if ($Register) {
    $cfgDir  = Join-Path $env:APPDATA 'Claude'
    $cfgPath = Join-Path $cfgDir 'claude_desktop_config.json'
    New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
    $cfg = if (Test-Path $cfgPath) {
        Copy-Item $cfgPath "$cfgPath.bak-$(Get-Date -Format yyyyMMddHHmmss)"
        Get-Content $cfgPath -Raw | ConvertFrom-Json
    } else { [pscustomobject]@{} }
    if (-not $cfg.PSObject.Properties['mcpServers']) { $cfg | Add-Member mcpServers ([pscustomobject]@{}) }
    $cfg.mcpServers | Add-Member -Force calibre ([pscustomobject]$entry)
    # UTF-8 without BOM: Windows PowerShell 5.1 with -Encoding utf8 writes a BOM
    [IO.File]::WriteAllText($cfgPath, ($cfg | ConvertTo-Json -Depth 20), (New-Object Text.UTF8Encoding $false))
    Write-Host "[+] Registered in $cfgPath (backup created). Fully restart Claude Desktop (quit from the tray)."
} else {
    Write-Host "`n[i] Add this to %APPDATA%\Claude\claude_desktop_config.json:"
    @{ mcpServers = @{ calibre = $entry } } | ConvertTo-Json -Depth 20
}
