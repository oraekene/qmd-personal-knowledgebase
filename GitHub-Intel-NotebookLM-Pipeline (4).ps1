# GitHub Intel → NotebookLM Pipeline  v1
# ============================================================
# Single entry point that wires together:
#   • Package 1 — GitHub & platform extraction (Python)
#   • Package 2 — Combine / split workflow (PowerShell)
#
# Folder layout assumed (sibling to this script):
#   ..\Package1_GitHub_Extraction\github_extractor_v2.py
#   ..\Package1_GitHub_Extraction\platform_extractor.py
#   ..\Package2_PowerShell_CombineSplit\Combine-Split-Tool.ps1
#
# Workflow:
#   1) Run extraction (GitHub / platform / both) -> produces github_export/
#   2) Run combine/split on github_export/        -> produces NotebookLM chunks
#
# Requirements: Windows PowerShell 5.1+ (or PowerShell 7+), Python 3.8+ in PATH.

Add-Type -AssemblyName System.Windows.Forms

# ── Paths ────────────────────────────────────────────────────────────────────
$script:ToolRoot          = Split-Path -Parent $PSCommandPath
$script:ParentRoot        = Split-Path -Parent $script:ToolRoot
$script:Package1Dir       = Join-Path $script:ParentRoot 'Package1_GitHub_Extraction'
$script:Package2Dir       = Join-Path $script:ParentRoot 'Package2_PowerShell_CombineSplit'
$script:GitHubExtractor   = Join-Path $script:Package1Dir 'github_extractor_v2.py'
$script:PlatformExtractor = Join-Path $script:Package1Dir 'platform_extractor.py'
$script:CombineTool       = Join-Path $script:Package2Dir 'Combine-Split-Tool.ps1'
$script:ExportDir         = Join-Path $script:ToolRoot 'github_export'
$script:OutputDir         = Join-Path $script:ToolRoot 'notebooklm_chunks'
$script:IncludeCodeFiles  = $false
# Shared code-extension list + size cap, used by BOTH the discovery/estimate
# code and the actual extraction call, so the [10] toggle and Test-RepoCodeExtracted
# stay in sync with what actually gets sent to github_extractor_v2.py.
$script:CodeExtensions    = @('.py','.js','.ts','.jsx','.tsx','.rb','.go','.rs','.java','.c','.cpp','.h','.cs',
                              '.sh','.bash','.zsh','.ps1','.bat','.cmd')
$script:MaxTextFileBytes  = 500000   # must match MAX_TEXT_FILE_BYTES in github_extractor_v2.py

# ── Verify Package 1 + Package 2 exist ───────────────────────────────────────
$missing = @()
if (-not (Test-Path $script:GitHubExtractor))   { $missing += "  - $script:GitHubExtractor" }
if (-not (Test-Path $script:PlatformExtractor)) { $missing += "  - $script:PlatformExtractor" }
if (-not (Test-Path $script:CombineTool))       { $missing += "  - $script:CombineTool" }
if ($missing.Count -gt 0) {
    Write-Host ""
    Write-Host "ERROR: required package files not found:" -ForegroundColor Red
    $missing | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    Write-Host ""
    Write-Host "Expected layout (Combined_Tool/ is this script's folder):" -ForegroundColor Yellow
    Write-Host "  ..\Package1_GitHub_Extraction\github_extractor_v2.py"  -ForegroundColor Yellow
    Write-Host "  ..\Package1_GitHub_Extraction\platform_extractor.py"   -ForegroundColor Yellow
    Write-Host "  ..\Package2_PowerShell_CombineSplit\Combine-Split-Tool.ps1" -ForegroundColor Yellow
    Write-Host ""
    exit 1
}

# ── Locate Python ────────────────────────────────────────────────────────────
function Get-PythonCommand {
    $candidates = @('python', 'python3', 'py')
    foreach ($c in $candidates) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) {
            try {
                $ver = & $cmd --version 2>&1
                if ($ver -match 'Python\s+(\d+)\.(\d+)') {
                    $major = [int]$Matches[1]; $minor = [int]$Matches[2]
                    if ($major -ge 3 -and $minor -ge 8) {
                        return @{ Command = $cmd.Source; Version = $ver }
                    }
                }
            } catch { }
        }
    }
    return $null
}

# ── Load Package 2 as a library (suppress its auto-run) ─────────────────────
$script:__CombineTool_SuppressAutoRun = $true
. $script:CombineTool
if (-not (Get-Command Invoke-CombineFilesWorkflow -ErrorAction SilentlyContinue)) {
    Write-Host "ERROR: failed to load Invoke-CombineFilesWorkflow from Package 2." -ForegroundColor Red
    exit 1
}

# ── Helpers ──────────────────────────────────────────────────────────────────
function Show-Banner {
    Clear-Host
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host "  GitHub Intel  ->  NotebookLM Pipeline  v1"                 -ForegroundColor Cyan
    Write-Host "  Extraction + Combine/Split, all in one menu."              -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Show-Menu {
    $codeLabel = if ($script:IncludeCodeFiles) { "ON" } else { "OFF" }
    $codeColor = if ($script:IncludeCodeFiles) { "Green" } else { "DarkGray" }
    Write-Host "  [1]  Extract GitHub repos  (select sources: trending, collections, owned, forked, starred)" -ForegroundColor White
    Write-Host "  [2]  Extract platform repos  (HN, npm, PyPI, Reddit, ...)"                         -ForegroundColor White
    Write-Host "  [3]  Extract GitHub + platforms  (select sources + platforms)"                     -ForegroundColor White
    Write-Host "  [4]  Run combine/split on github_export/  (Package 2)"                            -ForegroundColor White
    Write-Host "  [5]  FULL PIPELINE: select sources + extract  ->  combine/split"                  -ForegroundColor Green
    Write-Host "  [6]  Set GitHub token (saved to memory for this session)"                         -ForegroundColor White
    Write-Host "  [7]  Open output folder  (github_export/)"                                        -ForegroundColor White
    Write-Host "  [8]  Install Python dependencies  (PyGithub, requests, optional scrapling)"       -ForegroundColor White
    Write-Host "  [9]  SELECT & EXTRACT repo   (search by partial name, pick one, incremental by default)" -ForegroundColor Green
    Write-Host "  [10] Toggle code file inclusion  (currently: $codeLabel)"                         -ForegroundColor $codeColor
    Write-Host "  [11] FORCE re-extract all  (ignore existing data, re-download everything)"        -ForegroundColor Yellow
    Write-Host "  [q]  Quit"                                                                       -ForegroundColor White
    Write-Host ""
}

function Read-Choice {
    param([string]$Prompt)
    Write-Host -NoNewline ("  " + $Prompt + ": ") -ForegroundColor Yellow
    return (Read-Host).Trim().ToLower()
}

function Ensure-ExportDir {
    if (-not (Test-Path $script:ExportDir)) {
        New-Item -ItemType Directory -Path $script:ExportDir -Force | Out-Null
    }
}

function Run-PythonScript {
    param(
        [string]$ScriptPath,
        [string[]]$Arguments
    )
    $py = Get-PythonCommand
    if (-not $py) {
        Write-Host ""
        Write-Host "ERROR: Python 3.8+ not found in PATH." -ForegroundColor Red
        Write-Host "Install Python from https://www.python.org/downloads/" -ForegroundColor Yellow
        Write-Host "Then re-run this menu option." -ForegroundColor Yellow
        return $false
    }
    Write-Host ""
    Write-Host "Using: $($py.Command) ($($py.Version))" -ForegroundColor DarkCyan
    Write-Host "Running: $ScriptPath $($Arguments -join ' ')" -ForegroundColor DarkCyan
    Write-Host ("-" * 60) -ForegroundColor DarkGray
    # Force UTF-8 for Python output so emoji and non-ASCII chars in the
    # extractors' messages (e.g. the scrapling/BS4 fallback warning) don't
    # crash on Windows consoles using cp1252.
    $env:PYTHONIOENCODING = 'utf-8'
    $env:PYTHONUTF8 = '1'
    Push-Location (Split-Path -Parent $ScriptPath)
    try {
        & $py.Command $ScriptPath @Arguments
        $exitCode = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    Write-Host ("-" * 60) -ForegroundColor DarkGray
    if ($exitCode -ne 0 -and $null -ne $exitCode) {
        Write-Host "Script exited with code $exitCode" -ForegroundColor Yellow
    } else {
        Write-Host "Done." -ForegroundColor Green
    }
    return $true
}

function Invoke-GitHubExtractor {
    Ensure-ExportDir
    $args = @('--output', $script:ExportDir)
    if ($script:GitHubToken) { $args += @('--token', $script:GitHubToken) }
    if ($script:IncludeCodeFiles) { $args += @('--text-extensions', ($script:CodeExtensions -join ',')) }
    Run-PythonScript -ScriptPath $script:GitHubExtractor -Arguments $args
}

function Invoke-PlatformExtractor {
    Ensure-ExportDir
    $args = @('--output', $script:ExportDir)
    Run-PythonScript -ScriptPath $script:PlatformExtractor -Arguments $args
}

function Install-PythonDeps {
    $py = Get-PythonCommand
    if (-not $py) {
        Write-Host ""
        Write-Host "ERROR: Python 3.8+ not found in PATH." -ForegroundColor Red
        Write-Host "Install Python from https://www.python.org/downloads/" -ForegroundColor Yellow
        return
    }
    Write-Host ""
    Write-Host "Installing: PyGithub requests beautifulsoup4 (and optional scrapling)..." -ForegroundColor Cyan
    & $py.Command -m pip install --upgrade PyGithub requests beautifulsoup4
    if ($LASTEXITCODE -eq 0) {
        Write-Host ""
        $ans = Read-Host "Also install scrapling (HTML scraping with stealth)?  [y/N]"
        if ($ans -match '^y') {
            & $py.Command -m pip install --upgrade scrapling
            if ($LASTEXITCODE -eq 0) {
                Write-Host "Running 'scrapling install' (downloads Camoufox browser)..." -ForegroundColor Cyan
                & $py.Command -m scrapling install
            }
        }
        Write-Host "Done." -ForegroundColor Green
    } else {
        Write-Host "pip install failed (exit $LASTEXITCODE)." -ForegroundColor Red
    }
}

function Invoke-BothExtractors {
    Invoke-GitHubExtractor
    Write-Host ""
    Write-Host "Now running platform extractor..." -ForegroundColor Cyan
    Invoke-PlatformExtractor
}

function Invoke-CombineSplit {
    if (-not (Test-Path $script:ExportDir)) {
        Write-Host ""
        Write-Host "ERROR: $script:ExportDir does not exist yet." -ForegroundColor Red
        Write-Host "Run option [1], [2] or [3] first to populate it." -ForegroundColor Yellow
        return
    }
    $fileCount = (Get-ChildItem -Path $script:ExportDir -Recurse -File -ErrorAction SilentlyContinue).Count
    if ($fileCount -eq 0) {
        Write-Host ""
        Write-Host "WARNING: $script:ExportDir is empty. Nothing to combine." -ForegroundColor Yellow
        return
    }
    Write-Host ""
    Write-Host "Loaded $($fileCount) file(s) available under $script:ExportDir" -ForegroundColor DarkCyan
    Write-Host "Launching combine/split workflow (Package 2)..." -ForegroundColor Cyan
    Write-Host ""
    Invoke-CombineFilesWorkflow
}

function Invoke-FullPipeline {
    Invoke-BothExtractors
    Write-Host ""
    Write-Host "Press any key to continue to combine/split..." -ForegroundColor Cyan
    $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
    Invoke-CombineSplit
}

# ── Interactive Repo Selection ───────────────────────────────────────────────

function Invoke-SourceSelection {
    Write-Host ""
    Write-Host "  ── Select sources to discover ──" -ForegroundColor Cyan
    Write-Host "  [1] Trending     (GitHub trending repos)"         -ForegroundColor White
    Write-Host "  [2] Collections  (GitHub curated collections)"   -ForegroundColor White
    Write-Host "  [3] Owned        (your own repos)"               -ForegroundColor White
    Write-Host "  [4] Forked       (your forks)"                   -ForegroundColor White
    Write-Host "  [5] Starred      (repos you starred)"            -ForegroundColor White
    Write-Host "  [a] All sources"                                 -ForegroundColor Green
    Write-Host ""
    $input = Read-Host "  Pick sources (comma-separated, e.g. 1,3,5 or 'a' for all)"
    $input = $input.Trim().ToLower()
    if ($input -eq 'a' -or $input -eq 'all' -or $input -eq '') {
        return @{ Trending = $true; Collections = $true; Owned = $true; Forked = $true; Starred = $true }
    }
    $sources = @{ Trending = $false; Collections = $false; Owned = $false; Forked = $false; Starred = $false }
    $parts = $input -split ','
    foreach ($part in $parts) {
        $part = $part.Trim()
        switch ($part) {
            '1' { $sources.Trending = $true }
            '2' { $sources.Collections = $true }
            '3' { $sources.Owned = $true }
            '4' { $sources.Forked = $true }
            '5' { $sources.Starred = $true }
        }
    }
    $selected = ($sources.Keys | Where-Object { $sources[$_] }) -join ', '
    Write-Host "  Selected: $selected" -ForegroundColor Green
    return $sources
}

function Invoke-GitHubRepoDiscovery {
    param(
        [switch]$IncludeTrending,
        [switch]$IncludeCollections,
        [switch]$IncludeOwned,
        [switch]$IncludeForked,
        [switch]$IncludeStarred,
        [switch]$IncludePlatforms
    )
    $repos = @()
    # Trending discovery
    if ($IncludeTrending) {
        Write-Host "  [Discovery] Fetching trending repos..." -ForegroundColor Cyan
        $py = Get-PythonCommand
        if ($py) {
            $env:PYTHONIOENCODING = 'utf-8'
            $env:PYTHONUTF8 = '1'
            Push-Location (Split-Path -Parent $script:GitHubExtractor)
            try {
                & $py.Command $script:GitHubExtractor --sources trending --output $script:ExportDir --trending-langs python 2>&1 | Out-Null
            } finally { Pop-Location }
        }
        $trendingDir = Join-Path $script:ExportDir '_trending'
        if (Test-Path $trendingDir) {
            Get-ChildItem -Path $trendingDir -Filter '*.json' | ForEach-Object {
                try {
                    $data = Get-Content $_.FullName -Raw | ConvertFrom-Json
                    foreach ($item in $data) {
                        $owner = ''; $name = ''
                        if ($item.url -match 'github\.com/([^/]+)/([^/]+)') {
                            $owner = $Matches[1]; $name = $Matches[2]
                        } elseif ($item.name -match '([^/]+)/(.+)') {
                            $owner = $Matches[1]; $name = $Matches[2]
                        }
                        if ($owner -and $name) {
                            $repos += [PSCustomObject]@{
                                Source      = 'trending'
                                Owner       = $owner
                                Name        = $name
                                Description = if ($item.description) { $item.description } else { '' }
                                Stars       = if ($item.stars) { $item.stars } else { 0 }
                                SizeKB      = 0
                                FileCount   = 0
                                Url         = if ($item.url) { $item.url } else { "https://github.com/$owner/$name" }
                            }
                        }
                    }
                } catch { }
            }
        }
    }
    # Collections discovery
    if ($IncludeCollections) {
        Write-Host "  [Discovery] Fetching GitHub collections..." -ForegroundColor Cyan
        $py = Get-PythonCommand
        if ($py) {
            $env:PYTHONIOENCODING = 'utf-8'
            $env:PYTHONUTF8 = '1'
            Push-Location (Split-Path -Parent $script:GitHubExtractor)
            try {
                & $py.Command $script:GitHubExtractor --sources collections --collections-full --output $script:ExportDir 2>&1 | Out-Null
            } finally { Pop-Location }
        }
        $collectionsDir = Join-Path $script:ExportDir '_collections'
        if (Test-Path $collectionsDir) {
            Get-ChildItem -Path $collectionsDir -Filter '*.json' | Where-Object { $_.Name -ne '_index.json' } | ForEach-Object {
                try {
                    $data = Get-Content $_.FullName -Raw | ConvertFrom-Json
                    if ($data.repos) {
                        foreach ($repo in $data.repos) {
                            $owner = ''; $repoName = ''
                            if ($repo.url -match 'github\.com/([^/]+)/([^/]+)') {
                                $owner = $Matches[1]; $repoName = $Matches[2]
                            }
                            if ($owner -and $repoName) {
                                $repos += [PSCustomObject]@{
                                    Source      = "collection:$($data.name)"
                                    Owner       = $owner
                                    Name        = $repoName
                                    Description = if ($repo.description) { $repo.description } else { '' }
                                    Stars       = if ($repo.stars) { $repo.stars } else { 0 }
                                    SizeKB      = 0
                                    FileCount   = 0
                                    Url         = $repo.url
                                }
                            }
                        }
                    }
                } catch { }
            }
        }
    }
    # Owned / Forked / Starred  (via the authenticated GitHub REST API)
    if ($IncludeOwned -or $IncludeForked -or $IncludeStarred) {
        Write-Host "  [Discovery] Fetching your owned, forked & starred repos..." -ForegroundColor Cyan
        if (-not $script:GitHubToken) {
            Write-Host "  ⚠ GitHub token not set. Skipping. Use option [6] to set a token." -ForegroundColor Yellow
        } else {
            $headers = @{ Authorization = "token $($script:GitHubToken)"; 'User-Agent' = 'GitHub-Intel-Pipeline' }
            # Owned + forked repos
            if ($IncludeOwned -or $IncludeForked) {
                try {
                    $page = 1
                    do {
                        $apiUrl = "https://api.github.com/user/repos?per_page=100&page=$page&sort=updated&type=all"
                        $resp = Invoke-RestMethod -Uri $apiUrl -Headers $headers -ErrorAction Stop
                        foreach ($r in $resp) {
                            $isFork = $r.fork
                            $source = if ($isFork) { 'forked' } else { 'owned' }
                            $include = ($isFork -and $IncludeForked) -or (-not $isFork -and $IncludeOwned)
                            if ($include) {
                                $repos += [PSCustomObject]@{
                                    Source      = $source
                                    Owner       = $r.owner.login
                                    Name        = $r.name
                                    Description = if ($r.description) { $r.description } else { '' }
                                    Stars       = $r.stargazers_count
                                    SizeKB      = $r.size
                                    FileCount   = 0
                                    Url         = $r.html_url
                                }
                            }
                        }
                        $page++
                    } while ($resp.Count -eq 100)
                } catch {
                    Write-Host "  ⚠ Error fetching owned repos: $($_.Exception.Message)" -ForegroundColor Yellow
                }
            }
            # Starred repos
            if ($IncludeStarred) {
                try {
                    $page = 1
                    do {
                        $apiUrl = "https://api.github.com/user/starred?per_page=100&page=$page"
                        $resp = Invoke-RestMethod -Uri $apiUrl -Headers $headers -ErrorAction Stop
                        foreach ($r in $resp) {
                            $repos += [PSCustomObject]@{
                                Source      = 'starred'
                                Owner       = $r.owner.login
                                Name        = $r.name
                                Description = if ($r.description) { $r.description } else { '' }
                                Stars       = $r.stargazers_count
                                SizeKB      = $r.size
                                FileCount   = 0
                                Url         = $r.html_url
                            }
                        }
                        $page++
                    } while ($resp.Count -eq 100)
                } catch {
                    Write-Host "  ⚠ Error fetching starred repos: $($_.Exception.Message)" -ForegroundColor Yellow
                }
            }
        }
    }
    # External platforms (HN, npm, PyPI, Reddit, crates.io, arXiv, HF, dev.to, ...)
    # This is a SEPARATE discovery pipeline (platform_extractor.py) from GitHub's own
    # trending/collections/owned/forked/starred above. It writes repo *references* to
    # github_export\_external_sources\{source}\forward\*.json; we read those back in
    # here so they show up in the normal repo picker like any other source, and can
    # then be fully extracted (metadata/tree/text+code files) the same way.
    if ($IncludePlatforms) {
        Write-Host "  [Discovery] Running platform extractor (HN, npm, PyPI, Reddit, ...)..." -ForegroundColor Cyan
        Ensure-ExportDir
        $null = Invoke-PlatformExtractor
        $extDir = Join-Path $script:ExportDir '_external_sources'
        if (Test-Path $extDir) {
            Get-ChildItem -Path $extDir -Directory -ErrorAction SilentlyContinue | ForEach-Object {
                $sourceName = $_.Name
                $forwardDir = Join-Path $_.FullName 'forward'
                if (Test-Path $forwardDir) {
                    Get-ChildItem -Path $forwardDir -Filter '*.json' -ErrorAction SilentlyContinue | ForEach-Object {
                        try {
                            $items = Get-Content $_.FullName -Raw | ConvertFrom-Json
                            foreach ($item in $items) {
                                if (-not $item.github_repo) { continue }
                                $parts = $item.github_repo -split '/', 2
                                if ($parts.Count -ne 2 -or -not $parts[0] -or -not $parts[1]) { continue }
                                $repos += [PSCustomObject]@{
                                    Source      = "platform:$sourceName"
                                    Owner       = $parts[0]
                                    Name        = $parts[1]
                                    Description = if ($item.description) { $item.description } elseif ($item.title) { $item.title } else { '' }
                                    Stars       = if ($item.score) { [int]$item.score } else { 0 }
                                    SizeKB      = 0
                                    FileCount   = 0
                                    Url         = if ($item.source_url) { $item.source_url } else { "https://github.com/$($item.github_repo)" }
                                }
                            }
                        } catch { }
                    }
                }
            }
        } else {
            Write-Host "  ⚠ No _external_sources output found — check platform_extractor.py's own dependencies/config." -ForegroundColor Yellow
        }
    }
    # Enrich repos with size + file count from GitHub API (all repos)
    $toEnrich = $repos | Where-Object { $_.SizeKB -eq 0 -or $_.FileCount -eq 0 }
    if ($toEnrich.Count -gt 0 -and $script:GitHubToken) {
        Write-Host "  [Discovery] Enriching repo sizes + file counts (GitHub API)..." -ForegroundColor DarkCyan
        $headers = @{ Authorization = "token $($script:GitHubToken)"; 'User-Agent' = 'GitHub-Intel-Pipeline' }
        # Base extensions matching Python script's DEFAULT_TEXT_EXTENSIONS (25)
        $baseExts = @('.md','.markdown','.rst','.txt','.adoc','.asciidoc','.textile','.rdoc','.pod','.wiki',
                      '.yaml','.yml','.toml','.ini','.cfg','.conf','.json','.csv','.tsv','.xml',
                      '.html','.htm','.tex','.graphql','.proto')
        # Extra code extensions — only included when $script:IncludeCodeFiles = $true
        # (shared with the actual extraction call — see $script:CodeExtensions above)
        $extractableExts = if ($script:IncludeCodeFiles) { $baseExts + $script:CodeExtensions } else { $baseExts }
        $extractableNames = @('readme','license','licence','changelog','changes','history','contributing',
                              'authors','maintainers','notice','todo','install','news','dockerfile','makefile',
                              'procfile','vagrantfile','gemfile','pipfile','requirements.txt','requirements-dev.txt',
                              '.gitignore','.gitattributes','.editorconfig','.npmrc','package.json','composer.json',
                              'cargo.toml','go.mod','pyproject.toml','setup.cfg','pipfile.lock','poetry.lock','gemfile.lock')
        foreach ($r in $toEnrich) {
            try {
                # Fetch repo metadata for size
                $apiUrl = "https://api.github.com/repos/$($r.Owner)/$($r.Name)"
                $resp = Invoke-RestMethod -Uri $apiUrl -Headers $headers -ErrorAction Stop
                $r.SizeKB = $resp.size
                $defaultBranch = $resp.default_branch
                # Fetch tree for file count (extractable files only)
                if ($defaultBranch) {
                    $treeUrl = "https://api.github.com/repos/$($r.Owner)/$($r.Name)/git/trees/$($defaultBranch)?recursive=1"
                    $treeResp = Invoke-RestMethod -Uri $treeUrl -Headers $headers -ErrorAction SilentlyContinue
                    if ($treeResp.tree) {
                        $count = 0
                        foreach ($item in $treeResp.tree) {
                            if ($item.type -ne 'blob') { continue }
                            $path = $item.path.ToLower()
                            $ext = [System.IO.Path]::GetExtension($path)
                            $fname = [System.IO.Path]::GetFileName($path)
                            if ($extractableExts -contains $ext -or $extractableNames -contains $fname) {
                                $count++
                            }
                        }
                        $r.FileCount = $count
                    }
                }
            } catch { }
        }
    }
    # Deduplicate by owner/name
    $seen = @{}
    $unique = @()
    foreach ($r in $repos) {
        $key = "$($r.Owner)/$($r.Name)".ToLower()
        if (-not $seen.ContainsKey($key)) {
            $seen[$key] = $true
            $unique += $r
        }
    }
    return $unique
}

function Format-SizeKB {
    param([int]$KB)
    if ($KB -ge 1024) { return "{0:N1} MB" -f ($KB / 1024) }
    return "$KB KB"
}

function Test-RepoExtracted {
    param([string]$Owner, [string]$Name)
    # Python script creates: github_export/{owner}__{repo}/metadata.json
    $repoDir = Join-Path $script:ExportDir "$($Owner)__$($Name)"
    $metaFile = Join-Path $repoDir 'metadata.json'
    return (Test-Path $metaFile)
}

function Test-RepoCodeExtracted {
    # Returns $true only if EVERY code file the repo's own directory_tree.json
    # says exists (and is small enough to have been fetched) is actually present
    # on disk under text_files\. This is checked straight off the filesystem
    # rather than text_files\_index.json, because an incremental run's index
    # only lists that run's changed files, not the full accumulated set.
    param([string]$Owner, [string]$Name)
    $repoDir  = Join-Path $script:ExportDir "$($Owner)__$($Name)"
    $treeFile = Join-Path $repoDir 'directory_tree.json'
    $tfDir    = Join-Path $repoDir 'text_files'
    if (-not (Test-Path $treeFile)) { return $false }
    try {
        $tree = Get-Content $treeFile -Raw | ConvertFrom-Json
    } catch { return $false }
    if (-not $tree) { return $false }

    $expectedCode = @($tree | Where-Object {
        $_.type -eq 'blob' -and
        ($_.size -le $script:MaxTextFileBytes) -and
        ($script:CodeExtensions -contains [System.IO.Path]::GetExtension($_.path).ToLower())
    })
    if ($expectedCode.Count -eq 0) { return $false }   # no (fetchable) code files in this repo at all
    if (-not (Test-Path $tfDir)) { return $false }

    $onDisk = @{}
    Get-ChildItem -Path $tfDir -File -ErrorAction SilentlyContinue | ForEach-Object { $onDisk[$_.Name] = $true }

    foreach ($item in $expectedCode) {
        $safeName = $item.path -replace '/', '__'
        if (-not $onDisk.ContainsKey($safeName)) { return $false }
    }
    return $true
}

function Invoke-RepoSelection {
    param([array]$Repos)
    if ($Repos.Count -eq 0) {
        Write-Host "  No repos discovered." -ForegroundColor Yellow
        return @()
    }
    Write-Host ""
    Write-Host "  Discovered $($Repos.Count) repo(s):" -ForegroundColor Cyan
    Write-Host ""
    # Group by source
    $grouped = $Repos | Group-Object Source
    $idx = 0
    foreach ($group in $grouped) {
        Write-Host "  ── $($group.Name) ($($group.Count)) ──" -ForegroundColor DarkCyan
        foreach ($r in $group.Group) {
            $idx++
            $sizeStr = if ($r.SizeKB -gt 0) { "  $(Format-SizeKB $r.SizeKB)" } else { '' }
            $fileStr = if ($r.FileCount -gt 0) { "  $($r.FileCount) files" } else { '' }
            $starStr = if ($r.Stars -gt 0) { " ⭐$($r.Stars)" } else { '' }
            $extracted = Test-RepoExtracted -Owner $r.Owner -Name $r.Name
            $codeDone  = $extracted -and (Test-RepoCodeExtracted -Owner $r.Owner -Name $r.Name)
            $statusStr = if ($extracted) { "  [EXTRACTED]" } else { '' }
            $statusColor = if ($extracted) { "DarkGreen" } else { "White" }
            $descStr = if ($r.Description) { " - $($r.Description.Substring(0, [Math]::Min(35, $r.Description.Length)))" } else { '' }
            Write-Host ("  [{0,3}] {1,-35}{2,-12}{3,-12}{4}" -f $idx, "$($r.Owner)/$($r.Name)", $sizeStr, $fileStr, $starStr) -ForegroundColor White -NoNewline
            if ($extracted) {
                Write-Host ("{0}" -f $statusStr) -ForegroundColor $statusColor -NoNewline
            }
            if ($codeDone) {
                Write-Host "  [CODE]" -ForegroundColor Magenta -NoNewline
            }
            Write-Host ("{0}" -f $descStr) -ForegroundColor DarkGray
        }
    }
    Write-Host ""
    Write-Host "  Enter repo numbers to KEEP (comma-separated, ranges with -, or 'all'/'none'):" -ForegroundColor Yellow
    Write-Host "  Examples: 1,3,5-10   or   all   or   none" -ForegroundColor DarkGray
    Write-Host ""
    $input = Read-Host "  Your selection"
    $input = $input.Trim().ToLower()
    if ($input -eq 'all' -or $input -eq '') {
        Write-Host "  Keeping all $($Repos.Count) repos." -ForegroundColor Green
        return $Repos
    }
    if ($input -eq 'none') {
        Write-Host "  Skipping all repos." -ForegroundColor Yellow
        return @()
    }
    # Parse selection: "1,3,5-10" -> @(1,3,5,6,7,8,9,10)
    $selectedIndices = @()
    $parts = $input -split ','
    foreach ($part in $parts) {
        $part = $part.Trim()
        if ($part -match '^(\d+)-(\d+)$') {
            $start = [int]$Matches[1]; $end = [int]$Matches[2]
            for ($i = $start; $i -le $end; $i++) { $selectedIndices += $i }
        } elseif ($part -match '^\d+$') {
            $selectedIndices += [int]$part
        }
    }
    # Filter repos by selected indices (1-based)
    $selected = @()
    foreach ($i in $selectedIndices) {
        if ($i -ge 1 -and $i -le $Repos.Count) {
            $selected += $Repos[$i - 1]
        }
    }
    # Deduplicate
    $seen = @(); $unique = @()
    foreach ($r in $selected) {
        $key = "$($r.Owner)/$($r.Name)".ToLower()
        if ($seen -notcontains $key) { $seen += $key; $unique += $r }
    }
    Write-Host "  Selected $($unique.Count) repo(s) for extraction." -ForegroundColor Green
    return $unique
}

function Invoke-SelectedExtraction {
    param(
        [array]$Repos,
        [switch]$RunCombine,
        [switch]$Force
    )
    if ($Repos.Count -eq 0) {
        Write-Host "  No repos selected. Nothing to extract." -ForegroundColor Yellow
        return
    }
    Ensure-ExportDir
    $py = Get-PythonCommand
    if (-not $py) {
        Write-Host "  ERROR: Python 3.8+ not found." -ForegroundColor Red
        return
    }
    Write-Host ""
    if ($Force) {
        Write-Host "  Force mode: re-extracting all repos (ignoring existing data)" -ForegroundColor Yellow
    } else {
        Write-Host "  Incremental mode: only fetch new/changed files for already-extracted repos" -ForegroundColor DarkCyan
    }
    Write-Host ""
    $total = $Repos.Count
    $current = 0
    $success = 0
    $failed = 0
    $incremental = 0
    foreach ($r in $Repos) {
        $current++
        $pct = [Math]::Round(($current / $total) * 100)
        $extracted = Test-RepoExtracted -Owner $r.Owner -Name $r.Name
        if ($extracted -and -not $Force) {
            Write-Host "  [$current/$total] ($pct%) $($r.Owner)/$($r.Name)" -ForegroundColor White -NoNewline
            Write-Host "  [INCREMENTAL]" -ForegroundColor DarkCyan
            $incremental++
        } elseif ($extracted -and $Force) {
            Write-Host "  [$current/$total] ($pct%) $($r.Owner)/$($r.Name)" -ForegroundColor White -NoNewline
            Write-Host "  [RE-EXTRACT]" -ForegroundColor Yellow
        } else {
            Write-Host "  [$current/$total] ($pct%) $($r.Owner)/$($r.Name)" -ForegroundColor White
        }
        $repoArgs = @('--repo', "$($r.Owner)/$($r.Name)", '--output', $script:ExportDir, '--skip-issues', '--rate-limit', '4600')
        if ($extracted -and -not $Force) {
            # Incremental: only fetch new/changed files
            $repoArgs += '--incremental'
        }
        if ($script:IncludeCodeFiles) {
            # This is what actually makes code files (not just docs/config) get downloaded.
            # See github_extractor_v2.py's --text-extensions flag.
            $repoArgs += @('--text-extensions', ($script:CodeExtensions -join ','))
        }
        if ($script:GitHubToken) { $repoArgs += @('--token', $script:GitHubToken) }
        $env:PYTHONIOENCODING = 'utf-8'
        $env:PYTHONUTF8 = '1'
        Push-Location (Split-Path -Parent $script:GitHubExtractor)
        try {
            & $py.Command $script:GitHubExtractor @repoArgs
            if ($LASTEXITCODE -eq 0 -or $LASTEXITCODE -eq $null) {
                $success++
                Write-Host "  ✓ Done" -ForegroundColor Green
            } else {
                $failed++
                Write-Host "  ✗ Failed (exit $LASTEXITCODE)" -ForegroundColor Red
            }
        } catch {
            $failed++
            Write-Host "  ✗ Error: $($_.Exception.Message)" -ForegroundColor Red
        } finally { Pop-Location }
        Write-Host ""
    }
    Write-Host "  Extraction complete: $success extracted, $incremental incremental, $failed failed (out of $total)." -ForegroundColor Cyan
    if ($RunCombine) {
        Write-Host ""
        Write-Host "  Press any key to continue to combine/split..." -ForegroundColor Cyan
        $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        Invoke-CombineSplit
    }
}

# ── Command [9]: standalone 2-step "search then pick" repo selection ────────
function Invoke-FuzzyRepoSearch {
    # Step 1: user types a partial name / letters / words.
    # Step 2: we show the closest-matching repos, numbered; user picks ONE.
    # Returns a single repo object, or $null if the user cancels.
    while ($true) {
        Write-Host ""
        Write-Host "  ── SELECT & EXTRACT: find a repo ──" -ForegroundColor Cyan
        Write-Host "  Type part of a repo name — letters, a partial word, whatever you remember." -ForegroundColor DarkGray
        Write-Host "  Tip: type it as 'owner/repo' for an exact, direct match instead of a search." -ForegroundColor DarkGray
        $query = (Read-Host "  Search (or 'q' to cancel)").Trim()
        if ($query -eq '' -or $query.ToLower() -eq 'q') {
            Write-Host "  Cancelled." -ForegroundColor Yellow
            return $null
        }

        $headers = @{ 'User-Agent' = 'GitHub-Intel-Pipeline' }
        if ($script:GitHubToken) { $headers['Authorization'] = "token $($script:GitHubToken)" }
        if (-not $script:GitHubToken) {
            Write-Host "  ⚠ No GitHub token set (option [6]) — searching unauthenticated (low rate limit)." -ForegroundColor Yellow
        }

        $candidates = @()

        # Exact 'owner/repo' typed in -> try a direct lookup first, skips search entirely.
        if ($query -match '^([^/\s]+)/([^/\s]+)$') {
            $owner = $Matches[1]; $name = $Matches[2]
            try {
                $r = Invoke-RestMethod -Uri "https://api.github.com/repos/$owner/$name" -Headers $headers -ErrorAction Stop
                $candidates += [PSCustomObject]@{
                    Source = 'direct'; Owner = $r.owner.login; Name = $r.name
                    Description = if ($r.description) { $r.description } else { '' }
                    Stars = $r.stargazers_count; SizeKB = $r.size; FileCount = 0; Url = $r.html_url
                }
            } catch {
                Write-Host "  '$query' isn't a repo that exists directly — falling back to a name search." -ForegroundColor DarkGray
            }
        }

        # Otherwise (or if the direct lookup missed): fuzzy search by name via GitHub's search API.
        if ($candidates.Count -eq 0) {
            $encoded = [uri]::EscapeDataString("$query in:name")
            try {
                $resp = Invoke-RestMethod -Uri "https://api.github.com/search/repositories?q=$encoded&per_page=25" -Headers $headers -ErrorAction Stop
                foreach ($r in $resp.items) {
                    $candidates += [PSCustomObject]@{
                        Source = 'search'; Owner = $r.owner.login; Name = $r.name
                        Description = if ($r.description) { $r.description } else { '' }
                        Stars = $r.stargazers_count; SizeKB = $r.size; FileCount = 0; Url = $r.html_url
                    }
                }
            } catch {
                Write-Host "  ⚠ Search failed: $($_.Exception.Message)" -ForegroundColor Red
            }
        }

        if ($candidates.Count -eq 0) {
            Write-Host "  No repos found matching '$query'. Try again." -ForegroundColor Yellow
            continue
        }

        Write-Host ""
        Write-Host "  Found $($candidates.Count) match(es) for '$query':" -ForegroundColor Cyan
        Write-Host ""
        $i = 0
        foreach ($r in $candidates) {
            $i++
            $extracted = Test-RepoExtracted -Owner $r.Owner -Name $r.Name
            $codeDone  = $extracted -and (Test-RepoCodeExtracted -Owner $r.Owner -Name $r.Name)
            $starStr = if ($r.Stars -gt 0) { " ⭐$($r.Stars)" } else { '' }
            $descStr = if ($r.Description) { " - $($r.Description.Substring(0, [Math]::Min(55, $r.Description.Length)))" } else { '' }
            Write-Host ("  [{0,2}] {1,-40}{2}" -f $i, "$($r.Owner)/$($r.Name)", $starStr) -ForegroundColor White -NoNewline
            if ($extracted) { Write-Host "  [EXTRACTED]" -ForegroundColor DarkGreen -NoNewline }
            if ($codeDone)  { Write-Host "  [CODE]" -ForegroundColor Magenta -NoNewline }
            Write-Host $descStr -ForegroundColor DarkGray
        }
        Write-Host ""
        $pick = (Read-Host "  Number to select  ('s' = search again, 'q' = cancel)").Trim().ToLower()
        if ($pick -eq 'q') { return $null }
        if ($pick -eq 's' -or $pick -eq '') { continue }
        if ($pick -match '^\d+$' -and [int]$pick -ge 1 -and [int]$pick -le $candidates.Count) {
            return $candidates[[int]$pick - 1]
        }
        Write-Host "  Invalid selection." -ForegroundColor Red
    }
}

# ── Main loop ────────────────────────────────────────────────────────────────
Show-Banner
Write-Host "  Export dir:  $script:ExportDir" -ForegroundColor DarkGray
Write-Host "  Chunks dir:  $script:OutputDir  (Package 2 will ask for an output dir)" -ForegroundColor DarkGray
Write-Host ""

while ($true) {
    Show-Menu
    $choice = Read-Choice "Pick an option"
    switch ($choice) {
        '1' {
            # GitHub extractor: user selects sources
            $sources = Invoke-SourceSelection
            $repos = Invoke-GitHubRepoDiscovery -IncludeTrending:$sources.Trending -IncludeCollections:$sources.Collections -IncludeOwned:$sources.Owned -IncludeForked:$sources.Forked -IncludeStarred:$sources.Starred
            $selected = Invoke-RepoSelection -Repos $repos
            Invoke-SelectedExtraction -Repos $selected
            Write-Host ""; Write-Host "Press any key..." -ForegroundColor DarkGray; $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        }
        '2' {
            # Platforms: discover + select + extract
            $repos = Invoke-GitHubRepoDiscovery -IncludePlatforms
            $selected = Invoke-RepoSelection -Repos $repos
            Invoke-SelectedExtraction -Repos $selected
            Write-Host ""; Write-Host "Press any key..." -ForegroundColor DarkGray; $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        }
        '3' {
            # GitHub sources + platforms
            $sources = Invoke-SourceSelection
            $repos = Invoke-GitHubRepoDiscovery -IncludeTrending:$sources.Trending -IncludeCollections:$sources.Collections -IncludeOwned:$sources.Owned -IncludeForked:$sources.Forked -IncludeStarred:$sources.Starred -IncludePlatforms
            $selected = Invoke-RepoSelection -Repos $repos
            Invoke-SelectedExtraction -Repos $selected
            Write-Host ""; Write-Host "Press any key..." -ForegroundColor DarkGray; $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        }
        '4' { Invoke-CombineSplit }
        '5' {
            # Full pipeline: select sources + extract + combine
            $sources = Invoke-SourceSelection
            $repos = Invoke-GitHubRepoDiscovery -IncludeTrending:$sources.Trending -IncludeCollections:$sources.Collections -IncludeOwned:$sources.Owned -IncludeForked:$sources.Forked -IncludeStarred:$sources.Starred -IncludePlatforms
            $selected = Invoke-RepoSelection -Repos $repos
            Invoke-SelectedExtraction -Repos $selected -RunCombine
        }
        '6' {
            $tok = Read-Host "  Paste your GitHub token (hidden with Read-Host -AsSecureString not used here for simplicity)"
            if ($tok) { $script:GitHubToken = $tok.Trim(); Write-Host "  Token saved for this session." -ForegroundColor Green }
        }
        '7' {
            Ensure-ExportDir
            Start-Process explorer.exe $script:ExportDir
        }
        '8' { Install-PythonDeps; Write-Host ""; Write-Host "Press any key..." -ForegroundColor DarkGray; $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown') }
        '9' {
            # Standalone: 2-step search-by-partial-name, pick one, extract just that repo (incremental by default)
            $picked = Invoke-FuzzyRepoSearch
            if ($picked) {
                Invoke-SelectedExtraction -Repos @($picked)
            }
            Write-Host ""; Write-Host "Press any key..." -ForegroundColor DarkGray; $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        }
        '10' {
            $script:IncludeCodeFiles = -not $script:IncludeCodeFiles
            if ($script:IncludeCodeFiles) {
                Write-Host "  Code files INCLUDED ($($script:CodeExtensions -join ', '))" -ForegroundColor Green
                Write-Host "  Every extraction from now on passes --text-extensions to github_extractor_v2.py," -ForegroundColor DarkGray
                Write-Host "  so source code gets downloaded in full, not just docs/config." -ForegroundColor DarkGray
            } else {
                Write-Host "  Code files EXCLUDED (default: text/config/doc only, per DEFAULT_TEXT_EXTENSIONS)" -ForegroundColor DarkGray
            }
            Write-Host ""; Write-Host "Press any key..." -ForegroundColor DarkGray; $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        }
        '11' {
            # Force re-extract: select sources + extract with --force (ignores existing data)
            $sources = Invoke-SourceSelection
            $repos = Invoke-GitHubRepoDiscovery -IncludeTrending:$sources.Trending -IncludeCollections:$sources.Collections -IncludeOwned:$sources.Owned -IncludeForked:$sources.Forked -IncludeStarred:$sources.Starred
            $selected = Invoke-RepoSelection -Repos $repos
            Invoke-SelectedExtraction -Repos $selected -Force
            Write-Host ""; Write-Host "Press any key..." -ForegroundColor DarkGray; $null = $Host.UI.RawUI.ReadKey('NoEcho,IncludeKeyDown')
        }
        'q' { Write-Host "Bye." -ForegroundColor Cyan; break }
        default { Write-Host "  Unknown option." -ForegroundColor Yellow }
    }
    if ($choice -eq 'q') { break }
    Show-Banner
}




