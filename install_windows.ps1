<#
  RL PCB installer for Windows.
  Run from the rlpcb folder in PowerShell:
      powershell -ExecutionPolicy Bypass -File .\install_windows.ps1
  Options:
      -Python C:\Path\to\python.exe   use a specific Python 3.10+
      -Port 8765                      chat panel port
      -SkipClaudeDesktop              don't register the MCP server with Claude Desktop
      -SeedCorpus                     download & index the curated open-hardware designs (a few minutes)
#>
param(
  [string]$Python = "",
  [int]$Port = 8765,
  [switch]$SkipClaudeDesktop,
  [switch]$SeedCorpus
)
$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "RL PCB installer - repo: $Repo" -ForegroundColor Cyan

# ---------------------------------------------------------------- 1. Python
function Test-Py($p) {
  try { $v = & $p -c "import sys;print(sys.version_info[:2]>=(3,10))" 2>$null; return ($v -eq "True") } catch { return $false }
}
if (-not $Python) {
  foreach ($cand in @("py -3.13", "py -3.12", "py -3.11", "py -3.10", "python")) {
    try {
      $exe = Invoke-Expression "$cand -c `"import sys;print(sys.executable)`"" 2>$null
      if ($exe -and (Test-Py $exe)) { $Python = $exe.Trim(); break }
    } catch {}
  }
}
if (-not $Python -or -not (Test-Py $Python)) {
  Write-Host "Python 3.10+ not found. Install it from https://www.python.org/downloads/ (tick 'Add to PATH') and re-run." -ForegroundColor Red
  exit 1
}
Write-Host "Using Python: $Python"

# ---------------------------------------------------------------- 2. virtual environment
$Venv = Join-Path $Repo ".venv"
if (-not (Test-Path (Join-Path $Venv "Scripts\python.exe"))) {
  & $Python -m venv $Venv
}
$VPy = Join-Path $Venv "Scripts\python.exe"
& $VPy -m pip install --upgrade pip --quiet
& $VPy -m pip install -r (Join-Path $Repo "requirements.txt") --quiet
& $VPy -m pip install -e $Repo --quiet
Write-Host "Python environment ready." -ForegroundColor Green

# ---------------------------------------------------------------- 3. launcher config
$RlHome = Join-Path $env:USERPROFILE ".rlpcb"
New-Item -ItemType Directory -Force -Path $RlHome | Out-Null
function Write-Utf8NoBom($Path, $Text) { [System.IO.File]::WriteAllText($Path, $Text, (New-Object System.Text.UTF8Encoding $false)) }
$launcher = @{ python = $VPy; repo = $Repo; port = $Port } | ConvertTo-Json
Write-Utf8NoBom (Join-Path $RlHome "launcher.json") $launcher

# ---------------------------------------------------------------- 3b. pre-built reference corpus (136 open designs)
$CorpusDir = Join-Path $RlHome "corpus"
New-Item -ItemType Directory -Force -Path $CorpusDir | Out-Null
$SeedDb = Join-Path $Repo "seed\corpus.db"
if ((Test-Path $SeedDb) -and -not (Test-Path (Join-Path $CorpusDir "corpus.db"))) {
  Copy-Item $SeedDb (Join-Path $CorpusDir "corpus.db")
  Write-Host "Installed the pre-built reference-design corpus."
}

# ---------------------------------------------------------------- 4. library index + knowledge base
Write-Host "Indexing your KiCad symbol and footprint libraries (1-3 minutes the first time)..."
Push-Location $Repo
& $VPy -m rlpcb index
& $VPy -m rlpcb tool list_knowledge "{}" | Out-Null
Pop-Location

# ---------------------------------------------------------------- 5. KiCad plugins
$Docs = [Environment]::GetFolderPath("MyDocuments")
$versions = @()
foreach ($v in @("10.0", "9.0", "8.0", "7.0")) {
  if ((Test-Path (Join-Path $Docs "KiCad\$v")) -or (Test-Path "C:\Program Files\KiCad\$v")) { $versions += $v }
}
if ($versions.Count -eq 0) { $versions = @("9.0") }
foreach ($v in $versions) {
  $base = Join-Path $Docs "KiCad\$v"
  # KiCad 9+/10: IPC-API plugin (toolbar button in PCB and - on KiCad 10 - schematic editors)
  if ([double]$v -ge 9.0) {
    $ipc = Join-Path $base "plugins\org.rlpcb.copilot"
    New-Item -ItemType Directory -Force -Path $ipc | Out-Null
    Copy-Item -Force (Join-Path $Repo "kicad_plugin\ipc\*") $ipc
    Copy-Item -Force (Join-Path $Repo "kicad_plugin\launcher_common.py") $ipc
    Write-Utf8NoBom (Join-Path $ipc "requirements.txt") "kicad-python>=0.3`n"
    Write-Host "Installed IPC plugin for KiCad $v -> $ipc"
  }
  # KiCad 7-10: classic PCB-editor action plugin
  $swig = Join-Path $base "scripting\plugins\rlpcb_copilot"
  New-Item -ItemType Directory -Force -Path $swig | Out-Null
  Copy-Item -Force (Join-Path $Repo "kicad_plugin\action\*") $swig
  Copy-Item -Force (Join-Path $Repo "kicad_plugin\launcher_common.py") $swig
  Write-Host "Installed PCB action plugin for KiCad $v -> $swig"
}

# ---------------------------------------------------------------- 6. Claude Desktop (works with a Pro/Max subscription)
if (-not $SkipClaudeDesktop) {
  $cfgPaths = @((Join-Path $env:APPDATA "Claude\claude_desktop_config.json"))
  Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA "Packages") -Filter "Claude_*" -Directory -ErrorAction SilentlyContinue |
    ForEach-Object { $cfgPaths += (Join-Path $_.FullName "LocalCache\Roaming\Claude\claude_desktop_config.json") }
  $done = $false
  foreach ($cfgPath in $cfgPaths) {
    $dir = Split-Path $cfgPath
    if (-not (Test-Path $dir)) { continue }
    $cfg = [ordered]@{}
    if (Test-Path $cfgPath) {
      Copy-Item $cfgPath "$cfgPath.bak-rlpcb" -Force
      $raw = [System.IO.File]::ReadAllText($cfgPath)
      if ($raw.Trim()) {
        $obj = $raw | ConvertFrom-Json
        foreach ($p in $obj.PSObject.Properties) { $cfg[$p.Name] = $p.Value }
      }
    }
    $servers = [ordered]@{}
    if ($cfg.Contains("mcpServers") -and $cfg["mcpServers"]) {
      foreach ($p in $cfg["mcpServers"].PSObject.Properties) { $servers[$p.Name] = $p.Value }
    }
    $servers["rlpcb"] = [ordered]@{ command = $VPy; args = @("-m", "rlpcb.agent.mcp_server"); env = @{ PYTHONPATH = $Repo } }
    $cfg["mcpServers"] = $servers
    Write-Utf8NoBom $cfgPath ($cfg | ConvertTo-Json -Depth 20)
    Write-Host "Registered RL PCB with Claude Desktop: $cfgPath" -ForegroundColor Green
    $done = $true
  }
  if (-not $done) {
    Write-Host "Claude Desktop config folder not found. Install Claude Desktop, then re-run, or add this to claude_desktop_config.json:" -ForegroundColor Yellow
    Write-Host "  `"rlpcb`": { `"command`": `"$($VPy -replace '\\','\\')`", `"args`": [`"-m`", `"rlpcb.agent.mcp_server`"] }"
  }
}

# ---------------------------------------------------------------- 7. Desktop shortcut for the chat panel
try {
  $ws = New-Object -ComObject WScript.Shell
  $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "RL PCB Copilot.lnk"))
  $lnk.TargetPath = (Join-Path $Venv "Scripts\pythonw.exe")
  $lnk.Arguments = "-m rlpcb serve --open"
  $lnk.WorkingDirectory = $Repo
  $lnk.IconLocation = "shell32.dll,43"
  $lnk.Save()
  Write-Host "Created desktop shortcut 'RL PCB Copilot'."
} catch { Write-Host "Could not create desktop shortcut: $_" -ForegroundColor Yellow }

# ---------------------------------------------------------------- 8. optional corpus
if ($SeedCorpus) {
  Write-Host "Downloading and indexing the curated reference designs (needs git)..."
  Push-Location $Repo
  & $VPy -m rlpcb corpus seed
  Pop-Location
}

Write-Host ""
Push-Location $Repo
& $VPy -m rlpcb doctor
Pop-Location
Write-Host ""
Write-Host "Done. Next steps:" -ForegroundColor Cyan
Write-Host "  1. Restart Claude Desktop - you'll see the 'rlpcb' tools (hammer icon). Say: 'Open my KiCad project at ... and help me design ...'"
Write-Host "  2. In KiCad 9/10: Preferences > Plugins > enable 'KiCad API'. Restart KiCad; the RL PCB button appears in the toolbar."
Write-Host "  3. Or double-click 'RL PCB Copilot' on the desktop for the chat panel (needs an API key or a local model)."
