# Local publishing helpers are deliberately gitignored; this test needs that local script.
$ErrorActionPreference = 'Stop'
$source = Join-Path $PSScriptRoot '../scripts/publish-to-github.ps1'
if (-not (Test-Path $source)) { Write-Host 'SKIP: local publishing helper not installed'; exit 0 }
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Resolve-Path $source), [ref]$tokens, [ref]$parseErrors)
if ($parseErrors.Count) { throw ($parseErrors | Out-String) }
foreach ($functionName in 'Get-ReleaseInfo', 'Step') {
    $definition = $ast.Find({ param($node)
        $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -eq $functionName
    }, $true)
    . ([scriptblock]::Create($definition.Extent.Text))
}
$text = Get-Content $source -Raw
$releaseBlock = [scriptblock]::Create($text.Substring($text.IndexOf('# --- release:')))

# Native calls are recorded, never executed: no Git state or GitHub releases are changed.
function gh {
    if ($script:scenario -eq 'api-error') { $global:LASTEXITCODE = 1; return 'HTTP 503' }
    if ($script:scenario -eq 'missing') {
        $global:LASTEXITCODE = 1; return 'gh: Not Found (HTTP 404)'
    }
    $global:LASTEXITCODE = 0
    $assets = if ($script:scenario -eq 'complete') { @(@{name=$assetName}) }
              elseif ($script:scenario -eq 'other-asset') { @(@{name='other.zip'}) }
              else { @() }
    @{assets=$assets} | ConvertTo-Json -Depth 4 -Compress
}
function Invoke-Native {
    $script:calls.Add(($args -join ' '))
    if ($args[0] -eq 'git' -and $args[1] -eq 'archive') {
        [IO.File]::WriteAllText($zip, 'test archive')
    }
}
function Get-Native { return 'v5.4.0' }
function Assert([bool]$condition, [string]$message) { if (-not $condition) { throw $message } }

$repo = 'example/test'; $version = 'v5.4.1'
$Name = 'mcp-calibre-test-' + [guid]::NewGuid().ToString('N')
$assetName = "$Name-5.4.1.zip"
foreach ($case in @(
    @{scenario='missing'; tag=$false; create=$true; upload=$false},
    @{scenario='missing'; tag=$true; create=$true; upload=$false},
    @{scenario='missing-zip'; tag=$true; create=$false; upload=$true},
    @{scenario='other-asset'; tag=$true; create=$false; upload=$true},
    @{scenario='complete'; tag=$true; create=$false; upload=$false},
    @{scenario='api-error'; tag=$true; create=$false; upload=$false}
)) {
    $script:scenario = $case.scenario; $tagExists = $case.tag; $changes = $null
    $script:calls = [Collections.Generic.List[string]]::new()
    $failed = $false
    try { & $releaseBlock } catch {
        if ($case.scenario -ne 'api-error') { throw }
        $failed = $true
    } finally {
        Remove-Item -LiteralPath (Join-Path ([IO.Path]::GetTempPath()) $assetName) -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath (Join-Path ([IO.Path]::GetTempPath()) "$Name-notes.md") -ErrorAction SilentlyContinue
    }
    $commands = $script:calls -join "`n"
    Assert (($commands -match 'gh release create') -eq $case.create) 'Incorrect release creation'
    Assert (($commands -match 'gh release upload') -eq $case.upload) 'Incorrect asset upload'
    Assert (($commands -match 'git tag -a') -eq ($case.create -and -not $case.tag)) 'Existing tag recreated'
    if ($case.scenario -in 'complete','api-error') {
        Assert ($script:calls.Count -eq 0) 'Unexpected mutation for complete release or API error'
    } else {
        Assert ($commands -match 'git push origin v5.4.1') 'Tag not pushed before release/asset'
        Assert ($commands -match 'git archive .* v5.4.1') 'Archive not built from version tag'
    }
    Assert ($failed -eq ($case.scenario -eq 'api-error')) 'API error treated as missing release'
    Write-Host "PASS $($case.scenario), existing tag=$tagExists"
}
