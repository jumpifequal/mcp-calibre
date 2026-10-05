<#
.SYNOPSIS
  Setup wizard for calibre-mcp (WinForms). It only collects choices and then runs the existing
  install.ps1 unchanged, streaming and colouring its output.

.DESCRIPTION
  * Pre-flight checks: Python, install.ps1 / calibre_mcp.py, venv, OneDrive placement, Tesseract, ebook-convert.
  * Parameters are introspected from install.ps1 itself: an option is offered only if the installer
    exposes it, so the wizard keeps working when install.ps1 gains or loses switches.
  * Arguments are quoted with the CommandLineToArgvW rules (a path ending in a backslash, e.g.
    "C:\Lib\", can no longer swallow the following parameters).
  * Optional post-steps: desktop shortcut for the console, seeding the console profile.

.PARAMETER SelfTest
  Runs the non-GUI unit tests (argument quoting, argument building) and exits.

.EXAMPLE
  powershell -NoProfile -ExecutionPolicy Bypass -STA -File .\setup-wizard.ps1
#>
[CmdletBinding()]
param([switch]$SelfTest)

$ErrorActionPreference = 'Stop'
$script:Here = $PSScriptRoot
if (-not $script:Here) { $script:Here = Split-Path -Parent $MyInvocation.MyCommand.Path }
# Root = the folder that holds install.ps1: this folder, or its parent when the wizard lives in <root>\gui
$script:Root = $script:Here
if (-not (Test-Path -LiteralPath (Join-Path $script:Here 'install.ps1'))) {
    $parent = Split-Path -Parent $script:Here
    if ($parent -and (Test-Path -LiteralPath (Join-Path $parent 'install.ps1'))) { $script:Root = $parent }
}
$script:InstallPs1 = Join-Path $script:Root 'install.ps1'
$script:ServerPy   = Join-Path $script:Root 'calibre_mcp.py'
$script:ConsolePy  = Join-Path $script:Here 'calibre_mcp_console.py'
if (-not (Test-Path -LiteralPath $script:ConsolePy)) { $script:ConsolePy = Join-Path $script:Root 'gui\calibre_mcp_console.py' }
$script:VenvPy     = Join-Path $script:Root '.venv\Scripts\python.exe'
$script:VenvPyw    = Join-Path $script:Root '.venv\Scripts\pythonw.exe'
$script:IconIco     = Join-Path $script:Root 'presentation\icon\favicon.ico'

# ---------------------------------------------------------------------------------------------
# Pure helpers (unit-tested by -SelfTest)
# ---------------------------------------------------------------------------------------------
function ConvertTo-QuotedArg {
    # CommandLineToArgvW-compatible quoting of one argument.
    param([AllowEmptyString()][string]$Arg)
    if ($Arg.Length -gt 0 -and $Arg -notmatch '[\s"]') { return $Arg }
    $sb = New-Object System.Text.StringBuilder
    [void]$sb.Append('"')
    $bs = 0
    foreach ($ch in $Arg.ToCharArray()) {
        if ($ch -eq [char]92) { $bs++ }
        elseif ($ch -eq [char]34) {
            [void]$sb.Append([char]92, ($bs * 2 + 1)); [void]$sb.Append([char]34); $bs = 0
        }
        else {
            if ($bs -gt 0) { [void]$sb.Append([char]92, $bs); $bs = 0 }
            [void]$sb.Append($ch)
        }
    }
    if ($bs -gt 0) { [void]$sb.Append([char]92, ($bs * 2)) }
    [void]$sb.Append('"')
    return $sb.ToString()
}

function Split-WinArgs {
    # Reference parser for the Windows argument rules, used only to verify ConvertTo-QuotedArg.
    param([string]$Line)
    $out = New-Object System.Collections.Generic.List[string]
    $cur = New-Object System.Text.StringBuilder
    $inQ = $false; $has = $false; $i = 0; $n = $Line.Length
    while ($i -lt $n) {
        $c = $Line[$i]
        if ($c -eq [char]92) {
            $j = $i; while ($j -lt $n -and $Line[$j] -eq [char]92) { $j++ }
            $count = $j - $i
            if ($j -lt $n -and $Line[$j] -eq [char]34) {
                [void]$cur.Append([char]92, [int][math]::Floor($count / 2)); $has = $true
                if ($count % 2 -eq 1) { [void]$cur.Append([char]34); $i = $j + 1 }
                else { $inQ = -not $inQ; $i = $j + 1 }
            } else { [void]$cur.Append([char]92, $count); $has = $true; $i = $j }
            continue
        }
        if ($c -eq [char]34) { $inQ = -not $inQ; $has = $true; $i++; continue }
        if (([char]::IsWhiteSpace($c)) -and -not $inQ) {
            if ($has) { $out.Add($cur.ToString()); [void]$cur.Clear(); $has = $false }
            $i++; continue
        }
        [void]$cur.Append($c); $has = $true; $i++
    }
    if ($has) { $out.Add($cur.ToString()) }
    return ,$out.ToArray()
}

function Get-InstallArgumentList {
    # Maps wizard choices to install.ps1 parameters, but only those install.ps1 actually declares.
    param([hashtable]$Opt, [string[]]$Supported)
    $has = { param($n) $Supported -contains $n }
    $a = New-Object System.Collections.Generic.List[string]
    if ($Opt.Library -and (& $has 'Library')) { $a.Add('-Library'); $a.Add([string]$Opt.Library) }
    if ($Opt.Pdf -and (& $has 'Pdf')) { $a.Add('-Pdf'); $a.Add([string]$Opt.Pdf) }
    foreach ($sw in 'Register', 'SkipSync', 'NoSemantic', 'NoOcr') {
        if ($Opt[$sw] -and (& $has $sw)) { $a.Add('-' + $sw) }
    }
    if ($Opt.OcrLangs -and (& $has 'OcrLangs')) { $a.Add('-OcrLangs'); $a.Add([string]$Opt.OcrLangs) }
    return ,$a.ToArray()
}

function Format-CleanLibraryPath {
    param([string]$Path)
    if (-not $Path) { return '' }
    $p = $Path.Trim().Trim('"').Trim()
    while ($p.Length -gt 3 -and ($p.EndsWith('\') -or $p.EndsWith('/'))) { $p = $p.Substring(0, $p.Length - 1) }
    return $p
}

if ($SelfTest) {
    $fail = 0
    function Assert-Eq($name, $got, $want) {
        if ($got -ceq $want) { Write-Host "ok    $name" } else { Write-Host "FAIL  $name : got [$got] want [$want]"; $script:fail++ }
    }
    $samples = @(
        'plain', 'with space', 'C:\Users\x\My Lib\', 'C:\Users\x\Lib\', 'C:\a b\c\\', 'say "hi"', 'trail\\"q',
        '', 'a\b', '\\server\share\dir with space\', 'x"y"z', '"', '\"', 'tab	inside')
    foreach ($s in $samples) {
        $q = ConvertTo-QuotedArg $s
        $back = Split-WinArgs $q
        Assert-Eq "roundtrip [$s] -> [$q]" (($back.Count -eq 1) -and ($back[0] -ceq $s)) $true
    }
    # the exact failure that motivated the wizard: a trailing backslash must not swallow the next parameter
    $line = (@('-Library', 'C:\Users\x\Calibre Library\', '-Pdf', 'pymupdf', '-Register') | ForEach-Object { ConvertTo-QuotedArg $_ }) -join ' '
    $parts = Split-WinArgs $line
    Assert-Eq 'trailing backslash keeps 5 args' $parts.Count 5
    Assert-Eq 'trailing backslash value' $parts[1] 'C:\Users\x\Calibre Library\'
    Assert-Eq 'Register survives' $parts[4] '-Register'
    $sup = @('Library', 'Pdf', 'Register', 'SkipSync', 'NoSemantic')
    $al = Get-InstallArgumentList -Opt @{ Library = 'C:\L'; Pdf = 'pypdf'; Register = $true; SkipSync = $false; NoSemantic = $true; NoOcr = $true; OcrLangs = 'eng' } -Supported $sup
    Assert-Eq 'unsupported params dropped' ($al -join ' ') '-Library C:\L -Pdf pypdf -Register -NoSemantic'
    $al2 = Get-InstallArgumentList -Opt @{ Pdf = 'none'; NoOcr = $true; OcrLangs = 'ita,eng' } -Supported ($sup + 'NoOcr' + 'OcrLangs')
    Assert-Eq 'all supported' ($al2 -join ' ') '-Pdf none -NoOcr -OcrLangs ita,eng'
    $al3 = Get-InstallArgumentList -Opt @{} -Supported $sup
    Assert-Eq 'empty -> empty array (not null)' (($al3 -is [array]) -and ($al3.Count -eq 0)) $true
    Assert-Eq 'clean path strips slash+quotes' (Format-CleanLibraryPath ' "D:\Books\Lib\" ') 'D:\Books\Lib'
    Assert-Eq 'clean path keeps drive root' (Format-CleanLibraryPath 'D:\') 'D:\'
    Assert-Eq 'install.ps1 resolved from this location' (Test-Path -LiteralPath $script:InstallPs1) $true
    Assert-Eq 'calibre_mcp.py resolved from this location' (Test-Path -LiteralPath $script:ServerPy) $true
    if ($fail) { Write-Host "$fail FAILED"; exit 1 } else { Write-Host 'all tests passed'; exit 0 }
}

# ---------------------------------------------------------------------------------------------
# Environment probes
# ---------------------------------------------------------------------------------------------
function Get-InstallerParameters {
    if (-not (Test-Path -LiteralPath $script:InstallPs1)) { return @() }
    try { return @((Get-Command -Name $script:InstallPs1 -ErrorAction Stop).Parameters.Keys) } catch { return @() }
}

function Get-PythonInfo {
    $cands = New-Object System.Collections.Generic.List[object]
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) { $cands.Add(@($py.Source, '-3')) }
    $p = Get-Command python -ErrorAction SilentlyContinue
    if ($p) { $cands.Add(@($p.Source)) }
    foreach ($c in $cands) {
        try {
            $exe = $c[0]; $pre = @(); if ($c.Count -gt 1) { $pre = @($c[1..($c.Count - 1)]) }
            $code = "import sys,struct;print('%d.%d|%d|%s' % (sys.version_info[0], sys.version_info[1], struct.calcsize('P')*8, sys.executable))"
            $out = & $exe @pre -c $code 2>$null
            if ($LASTEXITCODE -eq 0 -and $out) {
                $f = ([string]($out | Select-Object -First 1)).Split('|')
                return [pscustomobject]@{ Version = [version]$f[0]; Bits = [int]$f[1]; Path = $f[2]; Store = ($f[2] -like '*\WindowsApps\*' -or $f[2] -like '*\PythonSoftwareFoundation*') }
            }
        } catch { }
    }
    return $null
}

function Test-OneDrivePath {
    param([string]$Path)
    foreach ($root in @($env:OneDrive, $env:OneDriveCommercial, $env:OneDriveConsumer) | Where-Object { $_ }) {
        if ($Path.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { return $true }
    }
    return $false
}

function Get-DetectedLibrary {
    $cfg = Join-Path $env:APPDATA 'calibre\global.py.json'
    try {
        if (Test-Path -LiteralPath $cfg) {
            $j = Get-Content -LiteralPath $cfg -Raw -Encoding UTF8 | ConvertFrom-Json
            if ($j.library_path -and (Test-Path -LiteralPath (Join-Path $j.library_path 'metadata.db'))) { return [string]$j.library_path }
        }
    } catch { }
    return ''
}

function Get-PreflightChecks {
    $r = New-Object System.Collections.Generic.List[object]
    $add = { param($s, $n, $d, $blocks) $r.Add([pscustomobject]@{ Status = $s; Name = $n; Detail = $d; Blocks = [bool]$blocks }) }
    if (Test-Path -LiteralPath $script:InstallPs1) {
        $np = (Get-InstallerParameters | Where-Object { $_ -notin [System.Management.Automation.PSCmdlet]::CommonParameters -and $_ -notin [System.Management.Automation.PSCmdlet]::OptionalCommonParameters }).Count
        & $add 'ok' 'install.ps1' "found, $np parameters detected" $false
    } else { & $add 'fail' 'install.ps1' "not found in the install folder ($script:Root)" $true }
    if (Test-Path -LiteralPath $script:ServerPy) { & $add 'ok' 'calibre_mcp.py' 'found' $false }
    else { & $add 'fail' 'calibre_mcp.py' 'not found in the install folder' $true }
    $pi = Get-PythonInfo
    if (-not $pi) { & $add 'fail' 'Python' 'not found. Install Python 3.10+ from python.org (3.12+ recommended).' $true }
    elseif ($pi.Version -lt [version]'3.10') { & $add 'fail' 'Python' ("{0} found at {1}: 3.10 or newer required" -f $pi.Version, $pi.Path) $true }
    else {
        $note = ''
        if ($pi.Bits -ne 64) { $note += ' | 32-bit: semantic search will be skipped' }
        if ($pi.Store) { $note += ' | Store/WindowsApps build: python.org build recommended' }
        if ($pi.Version -lt [version]'3.12') { $note += ' | 3.12+ gives a smaller full-text index' }
        $st = 'ok'; if ($note) { $st = 'warn' }
        & $add $st 'Python' ("{0}, {1}-bit, {2}{3}" -f $pi.Version, $pi.Bits, $pi.Path, $note) $false
    }
    if (Test-Path -LiteralPath $script:VenvPy) { & $add 'ok' 'Virtual env' '.venv exists: it will be reused and updated' $false }
    else { & $add 'ok' 'Virtual env' '.venv will be created' $false }
    $inLib = Test-Path -LiteralPath (Join-Path $script:Root '..\metadata.db')
    if ((Test-OneDrivePath $script:Root) -or $inLib) {
        & $add 'warn' 'Install location' 'inside OneDrive and/or inside the Calibre library: the .venv (thousands of files) gets synced. Prefer e.g. C:\Tools\calibre-mcp-win' $false
    } else { & $add 'ok' 'Install location' $script:Root $false }
    $tess = Get-Command tesseract -ErrorAction SilentlyContinue
    if (-not $tess -and (Test-Path -LiteralPath (Join-Path $env:ProgramFiles 'Tesseract-OCR\tesseract.exe'))) { $tess = $true }
    $wg = Get-Command winget -ErrorAction SilentlyContinue
    if ($tess) { & $add 'ok' 'Tesseract (OCR)' 'found' $false }
    elseif ($wg) { & $add 'warn' 'Tesseract (OCR)' 'not found: install.ps1 can install it with winget' $false }
    else { & $add 'warn' 'Tesseract (OCR)' 'not found and winget unavailable: OCR of scanned PDFs will need a manual install' $false }
    $ec = Get-Command ebook-convert -ErrorAction SilentlyContinue
    if (-not $ec -and (Test-Path -LiteralPath (Join-Path $env:ProgramFiles 'Calibre2\ebook-convert.exe'))) { $ec = $true }
    if ($ec) { & $add 'ok' 'Calibre ebook-convert' 'found' $false }
    else { & $add 'warn' 'Calibre ebook-convert' 'not found: LIT/MOBI and similar will not be readable until set (CALIBRE_EBOOK_CONVERT)' $false }
    return ,$r.ToArray()
}

# ---------------------------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------------------------
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[System.Windows.Forms.Application]::EnableVisualStyles()

function Get-Color([string]$Hex) { return [System.Drawing.ColorTranslator]::FromHtml($Hex) }
$cDark = Get-Color '#12161c'; $cAccent = Get-Color '#3ba99c'; $cMuted = Get-Color '#8793a3'; $cText = Get-Color '#1c2530'
$cOk = Get-Color '#1f8f5f'; $cWarn = Get-Color '#b7791f'; $cErr = Get-Color '#c0392b'; $cBg = Get-Color '#f5f7fa'
$cLogBg = Get-Color '#0d1117'; $cLogFg = Get-Color '#d7dde5'; $cLogMuted = Get-Color '#6b7686'
$fUi = New-Object System.Drawing.Font('Segoe UI', 9.5)
$fBold = New-Object System.Drawing.Font('Segoe UI', 9.5, [System.Drawing.FontStyle]::Bold)
$fTitle = New-Object System.Drawing.Font('Segoe UI', 17, [System.Drawing.FontStyle]::Bold)
$fMono = New-Object System.Drawing.Font('Consolas', 9.5)
$glyph = @{ ok = [string][char]0x2714; warn = [string][char]0x26A0; fail = [string][char]0x2716 }

function New-Label([string]$Text, [int]$X, [int]$Y, [int]$W, [int]$H, $Font = $null, $Color = $null) {
    $l = New-Object System.Windows.Forms.Label
    $l.Text = $Text; $l.Location = New-Object System.Drawing.Point($X, $Y); $l.Size = New-Object System.Drawing.Size($W, $H)
    if ($Font) { $l.Font = $Font }; if ($Color) { $l.ForeColor = $Color } else { $l.ForeColor = $cText }
    return $l
}
function New-Button([string]$Text, [int]$X, [int]$Y, [int]$W = 96, [int]$H = 32) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $Text; $b.Location = New-Object System.Drawing.Point($X, $Y); $b.Size = New-Object System.Drawing.Size($W, $H)
    $b.FlatStyle = 'Flat'; $b.FlatAppearance.BorderColor = Get-Color '#c9d1da'; $b.BackColor = [System.Drawing.Color]::White; $b.ForeColor = $cText
    $b.UseVisualStyleBackColor = $false
    return $b
}
function Set-Primary($b) { $b.BackColor = $cAccent; $b.ForeColor = [System.Drawing.Color]::White; $b.FlatAppearance.BorderColor = $cAccent; $b.Font = $fBold }
function New-Check([string]$Text, [int]$X, [int]$Y, [int]$W = 600, [bool]$On = $true) {
    $c = New-Object System.Windows.Forms.CheckBox
    $c.Text = $Text; $c.Location = New-Object System.Drawing.Point($X, $Y); $c.Size = New-Object System.Drawing.Size($W, 24); $c.Checked = $On; $c.ForeColor = $cText
    return $c
}

$script:Supported = Get-InstallerParameters
$script:Steps = @('Checks', 'Library', 'Components', 'Integration', 'Install')
$script:Page = 0
$script:Running = $false
$script:Done = $false
$script:Ok = $false
$script:Proc = $null
$script:S = @{ Out = @{ Reader = $null; Task = $null; Eof = $false }; Err = @{ Reader = $null; Task = $null; Eof = $false } }

$form = New-Object System.Windows.Forms.Form
$form.Text = 'calibre-mcp setup'
$form.ClientSize = New-Object System.Drawing.Size(920, 640)
$form.StartPosition = 'CenterScreen'; $form.FormBorderStyle = 'FixedDialog'; $form.MaximizeBox = $false
$form.Font = $fUi; $form.BackColor = $cBg
if (Test-Path -LiteralPath $script:IconIco) { try { $form.Icon = New-Object System.Drawing.Icon($script:IconIco) } catch { } }

# sidebar
$side = New-Object System.Windows.Forms.Panel
$side.Location = New-Object System.Drawing.Point(0, 0); $side.Size = New-Object System.Drawing.Size(220, 640); $side.BackColor = $cDark
$form.Controls.Add($side)
$side.Controls.Add((New-Label 'calibre-mcp' 24 26 180 34 $fTitle ([System.Drawing.Color]::White)))
$side.Controls.Add((New-Label 'setup wizard' 26 62 180 22 $fUi $cMuted))
$script:StepLabels = @()
for ($i = 0; $i -lt $script:Steps.Count; $i++) {
    $l = New-Label ("{0}   {1}" -f ($i + 1), $script:Steps[$i]) 26 (130 + 44 * $i) 180 28 $fUi $cMuted
    $side.Controls.Add($l); $script:StepLabels += $l
}

# header
$lblTitle = New-Label '' 252 22 640 34 (New-Object System.Drawing.Font('Segoe UI', 15, [System.Drawing.FontStyle]::Bold)) $cText
$lblSub = New-Label '' 254 58 640 38 $fUi $cMuted
$form.Controls.Add($lblTitle); $form.Controls.Add($lblSub)

# page container
$host1 = New-Object System.Windows.Forms.Panel
$host1.Location = New-Object System.Drawing.Point(252, 104); $host1.Size = New-Object System.Drawing.Size(640, 470)
$form.Controls.Add($host1)
$script:Pages = @()
for ($i = 0; $i -lt 5; $i++) {
    $pn = New-Object System.Windows.Forms.Panel
    $pn.Dock = 'Fill'; $pn.Visible = $false; $pn.BackColor = $cBg
    $host1.Controls.Add($pn); $script:Pages += $pn
}

# bottom bar
$btnBack = New-Button 'Back' 520 590
$btnNext = New-Button 'Next' 626 590; Set-Primary $btnNext
$btnInstall = New-Button 'Install' 626 590; Set-Primary $btnInstall; $btnInstall.Visible = $false
$btnCancel = New-Button 'Cancel' 790 590
$btnConsole = New-Button 'Open console' 252 590 130 32; $btnConsole.Visible = $false
$form.Controls.AddRange(@($btnBack, $btnNext, $btnInstall, $btnCancel, $btnConsole))
$form.CancelButton = $btnCancel

# ---- page 0: checks
$p0 = $script:Pages[0]
$lv = New-Object System.Windows.Forms.ListView
$lv.View = 'Details'; $lv.FullRowSelect = $true; $lv.HideSelection = $true; $lv.BorderStyle = 'FixedSingle'
$lv.Location = New-Object System.Drawing.Point(0, 0); $lv.Size = New-Object System.Drawing.Size(640, 380)
[void]$lv.Columns.Add('', 34); [void]$lv.Columns.Add('Check', 170); [void]$lv.Columns.Add('Result', 420)
$p0.Controls.Add($lv)
$btnRecheck = New-Button 'Re-check' 0 392 96 30
$p0.Controls.Add($btnRecheck)
$lblChecksNote = New-Label '' 110 398 520 40 $fUi $cMuted
$p0.Controls.Add($lblChecksNote)
$script:ChecksBlock = $false
function Update-Checks {
    $lv.Items.Clear(); $script:ChecksBlock = $false
    foreach ($c in (Get-PreflightChecks)) {
        $it = New-Object System.Windows.Forms.ListViewItem($glyph[$c.Status])
        [void]$it.SubItems.Add($c.Name); [void]$it.SubItems.Add($c.Detail)
        switch ($c.Status) { 'ok' { $it.ForeColor = $cOk } 'warn' { $it.ForeColor = $cWarn } 'fail' { $it.ForeColor = $cErr } }
        [void]$lv.Items.Add($it)
        if ($c.Blocks) { $script:ChecksBlock = $true }
    }
    if ($script:ChecksBlock) { $lblChecksNote.Text = 'Blocking problem found: fix it and press Re-check.'; $lblChecksNote.ForeColor = $cErr }
    else { $lblChecksNote.Text = 'Warnings do not block the installation.'; $lblChecksNote.ForeColor = $cMuted }
    Update-Nav
}
$btnRecheck.Add_Click({ Update-Checks })

# ---- page 1: library
$p1 = $script:Pages[1]
$chkLib = New-Check 'Set the Calibre library folder explicitly' 0 4 620 $true
$p1.Controls.Add($chkLib)
$txtLib = New-Object System.Windows.Forms.TextBox
$txtLib.Location = New-Object System.Drawing.Point(0, 40); $txtLib.Size = New-Object System.Drawing.Size(470, 26)
$p1.Controls.Add($txtLib)
$btnBrowse = New-Button 'Browse...' 480 38 76 30
$btnDetect = New-Button 'Detect' 562 38 76 30
$p1.Controls.AddRange(@($btnBrowse, $btnDetect))
$lblLibState = New-Label '' 0 78 636 60 $fUi $cMuted
$p1.Controls.Add($lblLibState)
$p1.Controls.Add((New-Label 'If left unchecked, the server finds the library at runtime from Calibre''s own settings (or ~\Calibre Library).' 0 150 636 40 $fUi $cMuted))
$p1.Controls.Add((New-Label 'The folder must contain metadata.db. Do not worry about a trailing backslash: the wizard removes it and quotes the path safely.' 0 192 636 40 $fUi $cMuted))
function Test-LibraryPage {
    # returns $true when the page is valid; updates the status label
    if (-not $chkLib.Checked) { $lblLibState.Text = 'Auto-detect at runtime.'; $lblLibState.ForeColor = $cMuted; return $true }
    $p = Format-CleanLibraryPath $txtLib.Text
    if (-not $p) { $lblLibState.Text = 'Enter the library folder or untick the option.'; $lblLibState.ForeColor = $cErr; return $false }
    if ($p.IndexOfAny([System.IO.Path]::GetInvalidPathChars()) -ge 0) { $lblLibState.Text = 'The path contains invalid characters.'; $lblLibState.ForeColor = $cErr; return $false }
    if (-not (Test-Path -LiteralPath (Join-Path $p 'metadata.db'))) { $lblLibState.Text = 'metadata.db not found in this folder.'; $lblLibState.ForeColor = $cErr; return $false }
    $msg = 'Valid Calibre library.'; $col = $cOk
    if (Test-OneDrivePath $p) { $msg += ' It is inside OneDrive: set the folder to "Always keep on this device", otherwise reading a book forces a download.'; $col = $cWarn }
    $lblLibState.Text = $msg; $lblLibState.ForeColor = $col
    return $true
}
$chkLib.Add_CheckedChanged({ $txtLib.Enabled = $chkLib.Checked; $btnBrowse.Enabled = $chkLib.Checked; $btnDetect.Enabled = $chkLib.Checked; [void](Test-LibraryPage); Update-Nav })
$txtLib.Add_TextChanged({ [void](Test-LibraryPage); Update-Nav })
$btnBrowse.Add_Click({
    $d = New-Object System.Windows.Forms.FolderBrowserDialog
    $d.Description = 'Select the Calibre library folder (contains metadata.db)'
    if ($txtLib.Text -and (Test-Path -LiteralPath (Format-CleanLibraryPath $txtLib.Text))) { $d.SelectedPath = Format-CleanLibraryPath $txtLib.Text }
    if ($d.ShowDialog() -eq 'OK') { $txtLib.Text = $d.SelectedPath }
})
$btnDetect.Add_Click({
    $d = Get-DetectedLibrary
    if ($d) { $txtLib.Text = $d } else { $lblLibState.Text = 'No library found in Calibre''s configuration.'; $lblLibState.ForeColor = $cWarn }
})

# ---- page 2: components
$p2 = $script:Pages[2]
$gb = New-Object System.Windows.Forms.GroupBox
$gb.Text = 'PDF backend'; $gb.Location = New-Object System.Drawing.Point(0, 0); $gb.Size = New-Object System.Drawing.Size(636, 112)
$p2.Controls.Add($gb)
$rbMu = New-Object System.Windows.Forms.RadioButton; $rbMu.Text = 'PyMuPDF: fast (AGPL-3.0)'; $rbMu.Location = New-Object System.Drawing.Point(14, 24); $rbMu.Size = New-Object System.Drawing.Size(580, 22); $rbMu.Checked = $true
$rbPy = New-Object System.Windows.Forms.RadioButton; $rbPy.Text = 'pypdf: slower (BSD)'; $rbPy.Location = New-Object System.Drawing.Point(14, 50); $rbPy.Size = New-Object System.Drawing.Size(580, 22)
$rbNo = New-Object System.Windows.Forms.RadioButton; $rbNo.Text = 'None (only PDFs already indexed by Calibre; no page-range reading)'; $rbNo.Location = New-Object System.Drawing.Point(14, 76); $rbNo.Size = New-Object System.Drawing.Size(600, 22)
$gb.Controls.AddRange(@($rbMu, $rbPy, $rbNo))
$chkSem = New-Check 'Semantic search dependencies (numpy, fastembed; the multilingual model is downloaded once)' 0 128 636 $true
$chkOcr = New-Check 'OCR for scanned PDFs (Tesseract; installed with winget when missing)' 0 160 636 $true
$p2.Controls.Add((New-Label 'OCR languages' 24 196 110 22 $fUi $cText))
$txtOcr = New-Object System.Windows.Forms.TextBox; $txtOcr.Text = 'ita,eng'; $txtOcr.Location = New-Object System.Drawing.Point(140, 192); $txtOcr.Size = New-Object System.Drawing.Size(160, 26)
$p2.Controls.AddRange(@($chkSem, $chkOcr, $txtOcr))
$chkSync = New-Check 'Build the full-text index now (can take a while on large libraries)' 0 232 636 $true
$p2.Controls.Add($chkSync)
$lblComp = New-Label '' 0 276 636 80 $fUi $cMuted
$p2.Controls.Add($lblComp)
$chkOcr.Add_CheckedChanged({ $txtOcr.Enabled = ($chkOcr.Checked -and ($script:Supported -contains 'OcrLangs')) })
$unsupported = @()
foreach ($pair in @(@('NoSemantic', $chkSem), @('NoOcr', $chkOcr), @('SkipSync', $chkSync))) {
    if (-not ($script:Supported -contains $pair[0])) { $pair[1].Enabled = $false; $unsupported += $pair[0] }
}
if (-not ($script:Supported -contains 'Pdf')) { $gb.Enabled = $false; $unsupported += 'Pdf' }
if (-not ($script:Supported -contains 'OcrLangs')) { $txtOcr.Enabled = $false; $unsupported += 'OcrLangs' }
if ($unsupported.Count) { $lblComp.Text = 'This install.ps1 does not expose: ' + ($unsupported -join ', ') + '. Those options are disabled (the installer applies its own defaults).' }

# ---- page 3: integration
$p3 = $script:Pages[3]
$chkReg = New-Check 'Register the server in Claude Desktop (stdio; claude_desktop_config.json is backed up first)' 0 4 636 $true
$chkSeed = New-Check 'Seed the console profile with the library path (only if the console has no profile yet)' 0 36 636 $true
$chkShort = New-Check 'Create a desktop shortcut for the console' 0 68 636 $true
$chkLaunch = New-Check 'Open the console when setup finishes' 0 100 636 $true
$p3.Controls.AddRange(@($chkReg, $chkSeed, $chkShort, $chkLaunch))
$p3.Controls.Add((New-Label 'The console launches and supervises the server over HTTP transport (token generated and stored with DPAPI). Claude Desktop keeps using its own stdio instance; both can coexist.' 0 146 636 64 $fUi $cMuted))
if (-not ($script:Supported -contains 'Register')) { $chkReg.Enabled = $false; $chkReg.Checked = $false }
if (-not (Test-Path -LiteralPath $script:ConsolePy)) {
    foreach ($c in @($chkSeed, $chkShort, $chkLaunch)) { $c.Enabled = $false; $c.Checked = $false }
    $p3.Controls.Add((New-Label 'calibre_mcp_console.py not found (expected in gui\): console options disabled.' 0 214 636 24 $fUi $cWarn))
}

# ---- page 4: install
$p4 = $script:Pages[4]
$p4.Controls.Add((New-Label 'Command that will run' 0 0 300 20 $fBold $cText))
$txtCmd = New-Object System.Windows.Forms.TextBox
$txtCmd.Multiline = $true; $txtCmd.ReadOnly = $true; $txtCmd.ScrollBars = 'Vertical'; $txtCmd.Font = $fMono
$txtCmd.Location = New-Object System.Drawing.Point(0, 24); $txtCmd.Size = New-Object System.Drawing.Size(636, 64)
$p4.Controls.Add($txtCmd)
$btnCopyCmd = New-Button 'Copy command' 520 92 116 26
$p4.Controls.Add($btnCopyCmd)
$btnCopyCmd.Add_Click({ [System.Windows.Forms.Clipboard]::SetText($txtCmd.Text) })
$rtb = New-Object System.Windows.Forms.RichTextBox
$rtb.ReadOnly = $true; $rtb.BackColor = $cLogBg; $rtb.ForeColor = $cLogFg; $rtb.Font = $fMono; $rtb.BorderStyle = 'None'; $rtb.WordWrap = $false
$rtb.Location = New-Object System.Drawing.Point(0, 124); $rtb.Size = New-Object System.Drawing.Size(636, 296); $rtb.ScrollBars = 'Both'
$p4.Controls.Add($rtb)
$prog = New-Object System.Windows.Forms.ProgressBar
$prog.Location = New-Object System.Drawing.Point(0, 428); $prog.Size = New-Object System.Drawing.Size(300, 10); $prog.Style = 'Continuous'
$p4.Controls.Add($prog)
$lblRun = New-Label '' 0 442 636 24 $fBold $cText
$p4.Controls.Add($lblRun)

# ---------------------------------------------------------------------------------------------
# State -> options
# ---------------------------------------------------------------------------------------------
function Get-WizardOptions {
    $pdf = 'pymupdf'; if ($rbPy.Checked) { $pdf = 'pypdf' } elseif ($rbNo.Checked) { $pdf = 'none' }
    $lib = ''; if ($chkLib.Checked) { $lib = Format-CleanLibraryPath $txtLib.Text }
    return @{
        Library = $lib; Pdf = $pdf; Register = $chkReg.Checked; SkipSync = (-not $chkSync.Checked)
        NoSemantic = (-not $chkSem.Checked); NoOcr = (-not $chkOcr.Checked); OcrLangs = $(if ($chkOcr.Checked) { $txtOcr.Text.Trim() } else { '' })
    }
}
function Get-HostExe {
    $ps = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (Test-Path -LiteralPath $ps) { return $ps }
    return (Get-Process -Id $PID).Path
}
function Get-InstallCommand {
    $args1 = Get-InstallArgumentList -Opt (Get-WizardOptions) -Supported $script:Supported
    $all = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $script:InstallPs1) + @($args1)
    return [pscustomobject]@{ Exe = (Get-HostExe); ArgString = (($all | ForEach-Object { ConvertTo-QuotedArg $_ }) -join ' ') }
}

# ---------------------------------------------------------------------------------------------
# Navigation
# ---------------------------------------------------------------------------------------------
$script:Titles = @(
    @('Pre-flight checks', 'Verifying that this machine and the install folder are ready.'),
    @('Calibre library', 'Where the Calibre library lives. The server opens it read-only.'),
    @('Components', 'Choose what install.ps1 installs. Defaults suit most setups.'),
    @('Integration', 'How the server is hooked up and how you will manage it afterwards.'),
    @('Review and install', 'install.ps1 runs unchanged with the arguments below. Its output streams here.')
)
function Update-Nav {
    $p = $script:Page
    $btnBack.Enabled = ($p -gt 0 -and -not $script:Running -and -not $script:Done)
    $btnNext.Visible = ($p -lt 4); $btnInstall.Visible = ($p -eq 4 -and -not $script:Done)
    $ok = $true
    if ($p -eq 0) { $ok = -not $script:ChecksBlock }
    if ($p -eq 1) { $ok = [bool](Test-LibraryPage) }
    $btnNext.Enabled = $ok
    $btnInstall.Enabled = (-not $script:Running -and -not $script:Done -and -not $script:ChecksBlock)
    if ($script:Done) { $btnCancel.Text = 'Close' } elseif ($script:Running) { $btnCancel.Text = 'Stop' } else { $btnCancel.Text = 'Cancel' }
}
function Show-Page([int]$i) {
    $script:Page = $i
    for ($k = 0; $k -lt $script:Pages.Count; $k++) { $script:Pages[$k].Visible = ($k -eq $i) }
    for ($k = 0; $k -lt $script:StepLabels.Count; $k++) {
        if ($k -eq $i) { $script:StepLabels[$k].ForeColor = [System.Drawing.Color]::White; $script:StepLabels[$k].Font = $fBold }
        else { $script:StepLabels[$k].ForeColor = $cMuted; $script:StepLabels[$k].Font = $fUi }
    }
    $lblTitle.Text = $script:Titles[$i][0]; $lblSub.Text = $script:Titles[$i][1]
    if ($i -eq 4 -and -not $script:Running -and -not $script:Done) {
        $c = Get-InstallCommand
        $txtCmd.Text = ('"{0}" {1}' -f $c.Exe, $c.ArgString)
    }
    Update-Nav
}
$btnNext.Add_Click({ if ($script:Page -lt 4) { Show-Page ($script:Page + 1) } })
$btnBack.Add_Click({ if ($script:Page -gt 0) { Show-Page ($script:Page - 1) } })

# ---------------------------------------------------------------------------------------------
# Running install.ps1 (async line pump on a UI timer: no event runspaces, no cross-thread UI calls)
# ---------------------------------------------------------------------------------------------
function Add-LogLine([string]$Text, [bool]$IsErr) {
    $col = $cLogFg
    if ($Text -match '^\s*\[\+\]') { $col = Get-Color '#4cc38a' }
    elseif ($Text -match '^\s*(WARNING|WARN)\b') { $col = Get-Color '#e5b34a' }
    elseif ($Text -match '^\s*\[notice\]') { $col = $cLogMuted }
    elseif ($Text -match '^\s*(\[!\]|ERROR|Exception|At line:|\+ CategoryInfo|\+ FullyQualifiedErrorId)' -or $IsErr) { $col = Get-Color '#ef6b6b' }
    $rtb.SelectionStart = $rtb.TextLength; $rtb.SelectionLength = 0; $rtb.SelectionColor = $col
    $rtb.AppendText($Text + "`r`n"); $rtb.SelectionColor = $rtb.ForeColor
    $rtb.SelectionStart = $rtb.TextLength; $rtb.ScrollToCaret()
}
function Pump-Stream([string]$Which) {
    $st = $script:S[$Which]
    while (-not $st.Eof -and $st.Task -ne $null -and $st.Task.IsCompleted) {
        try { $line = $st.Task.Result } catch { $st.Eof = $true; break }
        if ($null -eq $line) { $st.Eof = $true; break }
        Add-LogLine $line ($Which -eq 'Err')
        $st.Task = $st.Reader.ReadLineAsync()
    }
}
function Add-PostSteps {
    $o = Get-WizardOptions
    if (-not (Test-Path -LiteralPath $script:VenvPy)) { return }
    if ($chkShort.Checked) {
        try {
            $exe = $script:VenvPyw; if (-not (Test-Path -LiteralPath $exe)) { $exe = $script:VenvPy }
            $ws = New-Object -ComObject WScript.Shell
            $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'calibre-mcp console.lnk'))
            $lnk.TargetPath = $exe; $lnk.Arguments = '"' + $script:ConsolePy + '"'; $lnk.WorkingDirectory = $script:Root
            $lnk.Description = 'calibre-mcp console'
            if (Test-Path -LiteralPath $script:IconIco) { $lnk.IconLocation = $script:IconIco }
            $lnk.Save()
            Add-LogLine '[+] Desktop shortcut created: calibre-mcp console' $false
        } catch { Add-LogLine ('WARNING: shortcut not created: ' + $_.Exception.Message) $false }
    }
    if ($chkSeed.Checked -and $o.Library) {
        try {
            $cfg = Join-Path $env:LOCALAPPDATA 'calibre-mcp-console\profiles.json'
            if (-not (Test-Path -LiteralPath $cfg)) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $cfg) | Out-Null
                $obj = @{ active = 'Default'; profiles = @{ Default = @{ env = @{ CALIBRE_LIBRARY = $o.Library } } } }
                [System.IO.File]::WriteAllText($cfg, ($obj | ConvertTo-Json -Depth 6), (New-Object System.Text.UTF8Encoding($false)))
                Add-LogLine '[+] Console profile seeded with the library path' $false
            } else { Add-LogLine '[+] Console profile already exists: left untouched' $false }
        } catch { Add-LogLine ('WARNING: console profile not seeded: ' + $_.Exception.Message) $false }
    }
}
function Open-Console {
    $exe = $script:VenvPyw
    if (-not (Test-Path -LiteralPath $exe)) { $exe = $script:VenvPy }
    if (-not (Test-Path -LiteralPath $exe)) { $c = Get-Command pythonw -ErrorAction SilentlyContinue; if ($c) { $exe = $c.Source } }
    if ($exe -and (Test-Path -LiteralPath $script:ConsolePy)) {
        Start-Process -FilePath $exe -ArgumentList ('"' + $script:ConsolePy + '"') -WorkingDirectory $script:Root
    }
}
function Complete-Run {
    $timer.Stop(); $prog.Style = 'Continuous'; $prog.Value = 0
    $script:Running = $false; $script:Done = $true
    $code = $script:Proc.ExitCode
    $script:Ok = ($code -eq 0)
    if ($script:Ok) {
        Add-PostSteps
        $lblRun.Text = 'Setup completed successfully.'; $lblRun.ForeColor = $cOk
        $btnConsole.Visible = (Test-Path -LiteralPath $script:ConsolePy)
        if ($chkLaunch.Checked) { Open-Console }
    } else {
        $lblRun.Text = "install.ps1 exited with code $code. Review the log above."; $lblRun.ForeColor = $cErr
    }
    Update-Nav
}
$timer = New-Object System.Windows.Forms.Timer
$timer.Interval = 80
$timer.Add_Tick({
    Pump-Stream 'Out'; Pump-Stream 'Err'
    if ($script:S.Out.Eof -and $script:S.Err.Eof -and $script:Proc.HasExited) { Complete-Run }
})
$btnInstall.Add_Click({
    $c = Get-InstallCommand
    $rtb.Clear(); $lblRun.Text = 'Running...'; $lblRun.ForeColor = $cText
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $c.Exe; $psi.Arguments = $c.ArgString; $psi.WorkingDirectory = $script:Root
    $psi.UseShellExecute = $false; $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true; $psi.RedirectStandardError = $true
    $psi.StandardOutputEncoding = [System.Text.Encoding]::UTF8; $psi.StandardErrorEncoding = [System.Text.Encoding]::UTF8
    Add-LogLine ('> ' + $c.Exe + ' ' + $c.ArgString) $false
    try { $script:Proc = [System.Diagnostics.Process]::Start($psi) }
    catch { Add-LogLine ('ERROR: cannot start: ' + $_.Exception.Message) $true; return }
    foreach ($w in 'Out', 'Err') { $script:S[$w].Eof = $false }
    $script:S.Out.Reader = $script:Proc.StandardOutput; $script:S.Err.Reader = $script:Proc.StandardError
    $script:S.Out.Task = $script:S.Out.Reader.ReadLineAsync(); $script:S.Err.Task = $script:S.Err.Reader.ReadLineAsync()
    $script:Running = $true; $prog.Style = 'Marquee'; $timer.Start(); Update-Nav
})
$btnCancel.Add_Click({
    if ($script:Running -and $script:Proc -and -not $script:Proc.HasExited) {
        if ([System.Windows.Forms.MessageBox]::Show('Stop the installation now? A partial install can be completed by running the wizard again.', 'calibre-mcp setup', 'YesNo', 'Question') -eq 'Yes') {
            try { & taskkill.exe /T /F /PID $script:Proc.Id 2>&1 | Out-Null } catch { try { $script:Proc.Kill() } catch { } }
            Add-LogLine 'Installation stopped by user.' $true
        }
        return
    }
    $form.Close()
})
$btnConsole.Add_Click({ Open-Console })
$form.Add_FormClosing({
    if ($script:Running -and $script:Proc -and -not $script:Proc.HasExited) {
        $_.Cancel = $true
        [System.Windows.Forms.MessageBox]::Show('Installation in progress. Use Stop first.', 'calibre-mcp setup') | Out-Null
    }
})

# ---------------------------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------------------------
$detected = Get-DetectedLibrary
if ($detected) { $txtLib.Text = $detected }
$txtLib.Enabled = $chkLib.Checked; $btnBrowse.Enabled = $chkLib.Checked; $btnDetect.Enabled = $chkLib.Checked
Update-Checks
Show-Page 0
[void]$form.ShowDialog()
