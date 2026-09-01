# Combine-Split Tool  v1
# ============================================================
# Standalone extraction of the Combine-Files workflow from
# Combine-Files-COMBINED-v12-FULL-HYBRID.ps1
#
# Features preserved (modes 1-8 of the original combine workflow):
#   1) Single combined file
#   2) Split by number of files per output
#   3) Split by number of lines per output
#   4) Split into a fixed number of parts
#   5) Split by number of tokens per output (sentence-safe approximate chunking)
#   6) Output filenames only (optionally grouped by subdirectory or file type)
#   7) JSON merge mode (valid JSON output)
#   8) JSON-aware text splitter (text output)
#
# Windows compatible — no external dependencies required.
# Designed to parse and chunk the github_export/ output produced by
# Package 1 (github_extractor_v2.py + platform_extractor.py).

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Web

# ============================================================
#  DIALOG HELPERS
# ============================================================

function Show-OpenFileDialog {
    param(
        [string]$Title = "Select files",
        [string]$InitialDirectory = [Environment]::GetFolderPath('Desktop'),
        [string]$Filter = "All files (*.*)|*.*",
        [bool]$Multiselect = $true
    )

    $allFiles = @()
    $currentDir = $InitialDirectory

    while ($true) {
        $ofd = New-Object System.Windows.Forms.OpenFileDialog
        $ofd.Title = $Title
        $ofd.InitialDirectory = $currentDir
        $ofd.Multiselect = $Multiselect
        $ofd.Filter = $Filter
        $ofd.RestoreDirectory = $true

        $dialogResult = $ofd.ShowDialog()
        if ($dialogResult -eq [System.Windows.Forms.DialogResult]::OK) {
            foreach ($f in $ofd.FileNames) {
                if (-not ($allFiles -contains $f)) { $allFiles += $f }
            }

            if ($ofd.FileNames.Count -gt 0) {
                $currentDir = Split-Path -Parent $ofd.FileNames[-1]
            }

            if (-not $Multiselect) { break }

            $more = [System.Windows.Forms.MessageBox]::Show(
                "Files added: $($allFiles.Count)`n`nSelect more files from other folders/subfolders?",
                "Select more files?",
                [System.Windows.Forms.MessageBoxButtons]::YesNo,
                [System.Windows.Forms.MessageBoxIcon]::Question
            )
            if ($more -ne [System.Windows.Forms.DialogResult]::Yes) { break }
        } else {
            break
        }
    }

    return $allFiles | Sort-Object
}

function Show-FolderBrowserDialog {
    param(
        [string]$Description = "Select a folder to include (recursively)",
        [string]$InitialDirectory = [Environment]::GetFolderPath('Desktop')
    )
    $fbd = New-Object System.Windows.Forms.FolderBrowserDialog
    $fbd.Description = $Description
    $fbd.SelectedPath = $InitialDirectory
    if ($fbd.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { return $fbd.SelectedPath }
    return $null
}

function Show-SaveFileDialog {
    param(
        [string]$Title = "Save output as",
        [string]$InitialDirectory = [Environment]::GetFolderPath('Desktop'),
        [string]$DefaultName = "Output.txt",
        [string]$Filter = "Text files (*.txt)|*.txt|JSON files (*.json)|*.json|All files (*.*)|*.*"
    )
    $sfd = New-Object System.Windows.Forms.SaveFileDialog
    $sfd.Title = $Title
    $sfd.InitialDirectory = $InitialDirectory
    $sfd.FileName = $DefaultName
    $sfd.Filter = $Filter
    if ($sfd.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { return $sfd.FileName }
    return $null
}

# ============================================================
#  COMMON HELPERS
# ============================================================

function Get-CommonPath {
    param([string[]]$Paths)
    if (-not $Paths -or $Paths.Count -eq 0) { return $null }
    $splitPaths = $Paths | ForEach-Object { ($_ -replace '/','\').TrimEnd('\') -split '\\' }
    $minLen = ($splitPaths | ForEach-Object { $_.Count } | Measure-Object -Minimum).Minimum
    $common = @()
    for ($i = 0; $i -lt $minLen; $i++) {
        $part = $splitPaths[0][$i]
        $mismatch = $false
        foreach ($p in $splitPaths) {
            if ($p[$i] -ne $part) { $mismatch = $true; break }
        }
        if ($mismatch) { break }
        $common += $part
    }
    if ($common.Count -eq 0) { return $null }
    return ($common -join '\')
}

function Sanitize-FileName {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) { return "HtmlBatch_" }
    $invalid = [System.IO.Path]::GetInvalidFileNameChars()
    foreach ($ch in $invalid) { $Name = $Name.Replace($ch, '_') }
    return $Name.Trim()
}

function Detect-Encoding {
    param([string]$FilePath)

    # Read up to the first 4 bytes to check for BOM
    $result = @{
        Path = $FilePath
        BOMHex = ""
        Guess = ""
    }

    try {
        $fs = [System.IO.File]::Open($FilePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        $bytes = New-Object byte[] 4
        $read = $fs.Read($bytes, 0, 4)
        $fs.Close()
        $bomHex = ($bytes[0..($read-1)] | ForEach-Object { "{0:X2}" -f $_ }) -join " "
        $result.BOMHex = if ($bomHex) { $bomHex } else { "<none>" }

        # Check for known BOMs
        switch -regex ($bomHex) {
            '^EF BB BF' { $result.Guess = 'UTF-8 with BOM'; return $result }
            '^FF FE 00 00' { $result.Guess = 'UTF-32 LE (BOM)'; return $result }
            '^00 00 FE FF' { $result.Guess = 'UTF-32 BE (BOM)'; return $result }
            '^FF FE' { $result.Guess = 'UTF-16 LE (BOM)'; return $result }
            '^FE FF' { $result.Guess = 'UTF-16 BE (BOM)'; return $result }
        }

        # No known BOM: attempt to read as UTF-8 (no BOM)
        try {
            $content = Get-Content -LiteralPath $FilePath -Raw -Encoding UTF8 -ErrorAction Stop
            # if there are many NULs it's probably binary
            if ($content -match "`0") {
                $result.Guess = 'Binary/Unknown'
            } else {
                $result.Guess = 'UTF-8 (no BOM) or valid UTF-8'
            }
            return $result
        } catch {
            # Try Default (ANSI / Windows-1252)
            try {
                $content2 = Get-Content -LiteralPath $FilePath -Raw -Encoding Default -ErrorAction Stop
                if ($content2 -match "`0") { $result.Guess = 'Binary/Unknown' } else { $result.Guess = 'ANSI / Default (Windows-1252) or similar' }
                return $result
            } catch {
                $result.Guess = 'Binary/Unknown (could not read as UTF-8 or Default)'
                return $result
            }
        }

    } catch {
        $result.BOMHex = "<error reading>"
        $result.Guess = "Error: $($_.Exception.Message)"
        return $result
    }
}



function Sanitize-FileNamePart {
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) { return "CombinedBatch_" }

    $invalid = [System.IO.Path]::GetInvalidFileNameChars()
    foreach ($ch in $invalid) {
        $Name = $Name.Replace($ch, '_')
    }

    return $Name.Trim()
}

# ============================================================
#  TOKEN APPROXIMATION  (same method as Combine-Files.ps1)
# ============================================================

function Get-ApproxTokenCount {
    param([string[]]$Lines)
    if (-not $Lines -or $Lines.Count -eq 0) { return 0 }
    $Lines = @($Lines | Where-Object { $_ -ne $null })
    if ($Lines.Count -eq 0) { return 0 }
    $text = $Lines -join "`n"
    if ([string]::IsNullOrWhiteSpace($text)) { return 0 }
    return ([regex]::Matches($text, '\w+|[^\s\w]')).Count
}

# ============================================================
#  COMBINE-SPECIFIC HELPERS
# ============================================================

function Get-FileSectionLines {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][int]$Counter
    )

    $lines = New-Object System.Collections.Generic.List[string]

    $item = Get-Item -LiteralPath $FilePath -ErrorAction SilentlyContinue
    $size = if ($item) { $item.Length } else { 0 }
    $mtime = if ($item) { $item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') } else { "Unknown" }

    [void]$lines.Add("")
    [void]$lines.Add("===== File ${Counter}: ${FilePath} =====")
    [void]$lines.Add("Size: ${size} bytes    Last modified: ${mtime}")
    [void]$lines.Add("----- Begin Content -----")

    $processedAsText = $false
    try {
        $isBinary = $false
        try {
            $fs = [System.IO.File]::Open($FilePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
            $bytes = New-Object byte[] 4096
            $read = $fs.Read($bytes, 0, 4096)
            $fs.Close()
            for ($i = 0; $i -lt $read; $i++) {
                if ($bytes[$i] -eq 0) { $isBinary = $true; break }
            }
        } catch {
            $isBinary = $true
        }

        if (-not $isBinary) {
            try {
                $lineNo = 0
                Get-Content -LiteralPath $FilePath -Encoding UTF8 -ErrorAction Stop | ForEach-Object {
                    $lineNo++
                    [void]$lines.Add(("{0:d5}: {1}" -f $lineNo, $_))
                }
                $processedAsText = $true
            } catch {
                $lineNo = 0
                Get-Content -LiteralPath $FilePath -Encoding Default -ErrorAction Stop | ForEach-Object {
                    $lineNo++
                    [void]$lines.Add(("{0:d5}: {1}" -f $lineNo, $_))
                }
                $processedAsText = $true
            }
        }
    } catch {
        # fall through to Base64
    }

    if (-not $processedAsText) {
        try {
            $bytes = [System.IO.File]::ReadAllBytes($FilePath)
            [void]$lines.Add("NOTE: Binary or unreadable as UTF-8/ANSI text. Including as Base64.")
            $b64 = [Convert]::ToBase64String($bytes)
            $pos = 0
            while ($pos -lt $b64.Length) {
                $chunk = $b64.Substring($pos, [Math]::Min(76, $b64.Length - $pos))
                [void]$lines.Add($chunk)
                $pos += $chunk.Length
            }
        } catch {
            [void]$lines.Add("ERROR: Could not read file to include its contents. ($($_.Exception.Message))")
        }
    }

    [void]$lines.Add("----- End Content -----")
    [void]$lines.Add("")

    return ,$lines.ToArray()
}

function Get-SectionLineCount {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][int]$Counter
    )
    return (Get-FileSectionLines -FilePath $FilePath -Counter $Counter).Count
}
function Get-SectionTokenCount {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][int]$Counter
    )
    return (Get-ApproxTokenCount -Lines (Get-FileSectionLines -FilePath $FilePath -Counter $Counter))
}

function Get-BatchGroups {
    param(
        [Parameter(Mandatory=$true)][string[]]$Files,
        [Parameter(Mandatory=$true)][string]$Mode,
        [int]$FilesPerBatch = 30,
        [int]$LinesPerBatch = 200,
        [int]$PartCount = 20,
        [int]$TokensPerBatch = 8000
    )

    $groups = New-Object System.Collections.Generic.List[object]

    switch ($Mode) {
        'Single' {
            [void]$groups.Add(@($Files))
        }
        'Files' {
            if ($FilesPerBatch -lt 1) { $FilesPerBatch = 1 }
            for ($i = 0; $i -lt $Files.Count; $i += $FilesPerBatch) {
                $end = [Math]::Min($i + $FilesPerBatch - 1, $Files.Count - 1)
                [void]$groups.Add(@($Files[$i..$end]))
            }
        }
        'Parts' {
            if ($PartCount -lt 1) { $PartCount = 1 }
            if ($PartCount -gt $Files.Count) { $PartCount = $Files.Count }
            $filesPerPart = [Math]::Ceiling($Files.Count / $PartCount)
            for ($i = 0; $i -lt $Files.Count; $i += $filesPerPart) {
                $end = [Math]::Min($i + $filesPerPart - 1, $Files.Count - 1)
                [void]$groups.Add(@($Files[$i..$end]))
            }
        }
        'Lines' {
            if ($LinesPerBatch -lt 1) { $LinesPerBatch = 1 }
            $current = New-Object System.Collections.Generic.List[string]
            $currentLines = 0
            for ($i = 0; $i -lt $Files.Count; $i++) {
                $f = $Files[$i]
                $sectionLines = Get-SectionLineCount -FilePath $f -Counter ($i + 1)

                if ($current.Count -gt 0 -and ($currentLines + $sectionLines) -gt $LinesPerBatch) {
                    [void]$groups.Add(@($current.ToArray()))
                    $current.Clear()
                    $currentLines = 0
                }

                [void]$current.Add($f)
                $currentLines += $sectionLines
            }

            if ($current.Count -gt 0) {
                [void]$groups.Add(@($current.ToArray()))
            }
        }
        'Tokens' {
            if ($TokensPerBatch -lt 1) { $TokensPerBatch = 1 }
            $current = New-Object System.Collections.Generic.List[string]
            $currentTokens = 0
            for ($i = 0; $i -lt $Files.Count; $i++) {
                $f = $Files[$i]
                $sectionTokens = Get-SectionTokenCount -FilePath $f -Counter ($i + 1)

                if ($current.Count -gt 0 -and ($currentTokens + $sectionTokens) -gt $TokensPerBatch) {
                    [void]$groups.Add(@($current.ToArray()))
                    $current.Clear()
                    $currentTokens = 0
                }

                [void]$current.Add($f)
                $currentTokens += $sectionTokens
            }

            if ($current.Count -gt 0) {
                [void]$groups.Add(@($current.ToArray()))
            }
        }
        default {
            [void]$groups.Add(@($Files))
        }
    }

    return ,$groups.ToArray()
}

function Build-HeaderLines {
    param(
        [string]$TreeText,
        [bool]$EnableDiag,
        [object[]]$Diagnostics = @(),
        [int]$BatchNumber = 1,
        [int]$TotalBatches = 1,
        [string]$BatchDescription = "Single file"
    )

    $headerLines = @()
    $headerLines += "Combined on: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
    if ($TotalBatches -gt 1) {
        $headerLines += "Batch: $BatchNumber of $TotalBatches"
        $headerLines += "Batch mode: $BatchDescription"
    }
    $headerLines += ""
    $headerLines += "--- Directory tree ---"
    $headerLines += $TreeText
    $headerLines += ""
    if ($EnableDiag -and $Diagnostics -and $Diagnostics.Count -gt 0) {
        $headerLines += "--- Encoding diagnostics ---"
        $headerLines += "Path | BOM (hex) | Guess"
        $headerLines += "-----|----------|------"
        foreach ($d in $Diagnostics) {
            $headerLines += ("{0} | {1} | {2}" -f $d.Path, $d.BOMHex, $d.Guess)
        }
        $headerLines += ""
    }
    $headerLines += "--- File contents follow ---"
    return $headerLines
}

function Write-CombinedBatch {
    param(
        [Parameter(Mandatory=$true)][string[]]$BatchFiles,
        [Parameter(Mandatory=$true)][string]$OutPath,
        [Parameter(Mandatory=$true)][string]$TreeText,
        [Parameter(Mandatory=$true)][bool]$EnableDiag,
        [object[]]$Diagnostics = @(),
        [int]$BatchNumber = 1,
        [int]$TotalBatches = 1,
        [string]$BatchDescription = "Single file"
    )

    $headerLines = Build-HeaderLines -TreeText $TreeText -EnableDiag $EnableDiag -Diagnostics $Diagnostics -BatchNumber $BatchNumber -TotalBatches $TotalBatches -BatchDescription $BatchDescription
    Set-Content -Path $OutPath -Value ($headerLines -join "`r`n") -Encoding UTF8

    $counter = 0
    foreach ($f in $BatchFiles) {
        $counter++
        Write-Host "[$counter / $($BatchFiles.Count)]: Adding $f"
        $section = Get-FileSectionLines -FilePath $f -Counter $counter
        $section | Add-Content -Path $OutPath -Encoding UTF8
    }
}


function Get-ReadableContentLines {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][int]$Counter
    )

    $lines = New-Object System.Collections.Generic.List[string]

    $processedAsText = $false
    try {
        $isBinary = $false
        try {
            $fs = [System.IO.File]::Open($FilePath, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
            $bytes = New-Object byte[] 4096
            $read = $fs.Read($bytes, 0, 4096)
            $fs.Close()
            for ($i = 0; $i -lt $read; $i++) {
                if ($bytes[$i] -eq 0) { $isBinary = $true; break }
            }
        } catch {
            $isBinary = $true
        }

        if (-not $isBinary) {
            try {
                Get-Content -LiteralPath $FilePath -Encoding UTF8 -ErrorAction Stop | ForEach-Object {
                    [void]$lines.Add($_)
                }
                $processedAsText = $true
            } catch {
                Get-Content -LiteralPath $FilePath -Encoding Default -ErrorAction Stop | ForEach-Object {
                    [void]$lines.Add($_)
                }
                $processedAsText = $true
            }
        }
    } catch {
        # fall through to Base64
    }

    if (-not $processedAsText) {
        try {
            $bytes = [System.IO.File]::ReadAllBytes($FilePath)
            [void]$lines.Add("NOTE: Binary or unreadable as UTF-8/ANSI text. Including as Base64.")
            $b64 = [Convert]::ToBase64String($bytes)
            $pos = 0
            while ($pos -lt $b64.Length) {
                $chunk = $b64.Substring($pos, [Math]::Min(76, $b64.Length - $pos))
                [void]$lines.Add($chunk)
                $pos += $chunk.Length
            }
        } catch {
            [void]$lines.Add("ERROR: Could not read file to include its contents. ($($_.Exception.Message))")
        }
    }

    return ,$lines.ToArray()
}

function Build-TokenAwareSectionLines {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][int]$Counter,
        [AllowEmptyCollection()][AllowEmptyString()][Parameter(Mandatory=$false)][string[]]$ContentLines = @(),
        [int]$ChunkNumber = 1,
        [int]$ChunkCount = 1,
        [string]$ChunkingLabel = "sentence-safe token chunks",
        [AllowEmptyCollection()][AllowEmptyString()][string[]]$ExtraMetaLines = @()
    )

    $lines = New-Object System.Collections.Generic.List[string]

    $item = Get-Item -LiteralPath $FilePath -ErrorAction SilentlyContinue
    $size = if ($item) { $item.Length } else { 0 }
    $mtime = if ($item) { $item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') } else { "Unknown" }

    [void]$lines.Add("")
    [void]$lines.Add("===== File ${Counter}: ${FilePath} =====")
    [void]$lines.Add("Size: ${size} bytes    Last modified: ${mtime}")
    if ($ChunkCount -gt 1) {
        [void]$lines.Add("Chunk: ${ChunkNumber} of ${ChunkCount}")
        [void]$lines.Add("Chunking: ${ChunkingLabel}")
    }
    if ($ExtraMetaLines -and $ExtraMetaLines.Count -gt 0) {
        foreach ($meta in $ExtraMetaLines) {
            if ($meta -ne $null -and -not [string]::IsNullOrWhiteSpace([string]$meta)) {
                [void]$lines.Add([string]$meta)
            }
        }
    }
    [void]$lines.Add("----- Begin Content -----")

    $lineNo = 0
    if ($ContentLines -and $ContentLines.Count -gt 0) {
        foreach ($contentLine in $ContentLines) {
            if ($contentLine -eq $null) { continue }
            $lineNo++
            [void]$lines.Add(("{0:d5}: {1}" -f $lineNo, $contentLine))
        }
    }

    [void]$lines.Add("----- End Content -----")
    [void]$lines.Add("")

    return ,$lines.ToArray()
}

function Split-LongTextIntoWordChunks {
    param(
        [Parameter(Mandatory=$true)][string]$Text,
        [Parameter(Mandatory=$true)][int]$MaxTokens
    )

    $chunks = New-Object System.Collections.Generic.List[string]
    $currentWords = New-Object System.Collections.Generic.List[string]

    $words = $Text -split '\s+' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) }
    foreach ($word in $words) {
        $candidate = if ($currentWords.Count -gt 0) { (($currentWords.ToArray() + $word) -join ' ') } else { $word }
        if ($currentWords.Count -gt 0 -and (Get-ApproxTokenCount -Lines @($candidate)) -gt $MaxTokens) {
            [void]$chunks.Add(($currentWords.ToArray() -join ' '))
            $currentWords.Clear()
        }
        [void]$currentWords.Add($word)
    }

    if ($currentWords.Count -gt 0) {
        [void]$chunks.Add(($currentWords.ToArray() -join ' '))
    }

    return ,$chunks.ToArray()
}

function Convert-ToSentenceAwareUnits {
    param(
        [AllowEmptyCollection()][AllowEmptyString()][string[]]$Lines,
        [Parameter(Mandatory=$true)][int]$MaxTokens
    )

    $units = New-Object System.Collections.Generic.List[string]

    foreach ($line in $Lines) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            [void]$units.Add("")
            continue
        }

        if ((Get-ApproxTokenCount -Lines @($line)) -le $MaxTokens) {
            [void]$units.Add($line)
            continue
        }

        $trimmed = $line.Trim()
        $sentences = [regex]::Split($trimmed, '(?<=[.!?])\s+')
        if ($sentences.Count -gt 1) {
            foreach ($sentence in $sentences) {
                if ([string]::IsNullOrWhiteSpace($sentence)) { continue }
                if ((Get-ApproxTokenCount -Lines @($sentence)) -le $MaxTokens) {
                    [void]$units.Add($sentence)
                } else {
                    $wordChunks = Split-LongTextIntoWordChunks -Text $sentence -MaxTokens $MaxTokens
                    foreach ($chunk in $wordChunks) {
                        [void]$units.Add($chunk)
                    }
                }
            }
        } else {
            $wordChunks = Split-LongTextIntoWordChunks -Text $trimmed -MaxTokens $MaxTokens
            foreach ($chunk in $wordChunks) {
                [void]$units.Add($chunk)
            }
        }
    }

    return ,$units.ToArray()
}

function Convert-ToJsonAwareUnits {
    param(
        [AllowEmptyCollection()][AllowEmptyString()][string[]]$Lines,
        [Parameter(Mandatory=$true)][int]$MaxTokens
    )

    $units = New-Object System.Collections.Generic.List[string]

    foreach ($line in $Lines) {
        if ([string]::IsNullOrWhiteSpace($line)) {
            [void]$units.Add("")
            continue
        }

        if ((Get-ApproxTokenCount -Lines @($line)) -le $MaxTokens) {
            [void]$units.Add($line)
            continue
        }

        $wordChunks = Split-LongTextIntoWordChunks -Text $line.Trim() -MaxTokens $MaxTokens
        foreach ($chunk in $wordChunks) {
            [void]$units.Add($chunk)
        }
    }

    return ,$units.ToArray()
}

function Pack-UnitsIntoTokenChunks {
    param(
        [AllowEmptyCollection()][AllowEmptyString()][string[]]$Units,
        [Parameter(Mandatory=$true)][int]$MaxTokens
    )

    $chunks = New-Object System.Collections.Generic.List[object]
    $current = New-Object System.Collections.Generic.List[string]
    $currentTokens = 0

    foreach ($unit in $Units) {
        if ([string]::IsNullOrWhiteSpace($unit)) {
            if ($current.Count -gt 0) {
                [void]$current.Add("")
            }
            continue
        }

        $unitTokens = Get-ApproxTokenCount -Lines @($unit)
        if ($current.Count -gt 0 -and ($currentTokens + $unitTokens) -gt $MaxTokens) {
            [void]$chunks.Add(@($current.ToArray()))
            $current.Clear()
            $currentTokens = 0
        }

        [void]$current.Add($unit)
        $currentTokens += $unitTokens
    }

    if ($current.Count -gt 0) {
        [void]$chunks.Add(@($current.ToArray()))
    }

    return ,$chunks.ToArray()
}

function Get-TokenAwareSectionItems {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][int]$Counter,
        [Parameter(Mandatory=$true)][int]$MaxTokens
    )

    $contentLines = Get-ReadableContentLines -FilePath $FilePath -Counter $Counter

    $item = Get-Item -LiteralPath $FilePath -ErrorAction SilentlyContinue
    $size = if ($item) { $item.Length } else { 0 }
    $mtime = if ($item) { $item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') } else { "Unknown" }

    $baseHeader = @(
        "",
        "===== File ${Counter}: ${FilePath} =====",
        ("Size: {0} bytes    Last modified: {1}" -f $size, $mtime),
        "----- Begin Content -----",
        "----- End Content -----",
        ""
    )

    $headerReserve = (Get-ApproxTokenCount -Lines $baseHeader) + 30
    $contentBudget = [Math]::Max(1, $MaxTokens - $headerReserve)

    $units = Convert-ToSentenceAwareUnits -Lines $contentLines -MaxTokens $contentBudget
    $chunkBodies = Pack-UnitsIntoTokenChunks -Units $units -MaxTokens $contentBudget
    if (-not $chunkBodies -or $chunkBodies.Count -eq 0) {
        $chunkBodies = @(@())
    }

    $items = New-Object System.Collections.Generic.List[object]
    $chunkCount = $chunkBodies.Count
    for ($i = 0; $i -lt $chunkCount; $i++) {
        $chunkNumber = $i + 1
        # Guard: ensure we always pass a proper string[] (never $null or empty string coercion)
        $chunkContent = if ($chunkBodies[$i] -and $chunkBodies[$i].Count -gt 0) {
            [string[]]@($chunkBodies[$i] | Where-Object { $_ -ne $null })
        } else {
            [string[]]@()
        }
        $sectionLines = Build-TokenAwareSectionLines -FilePath $FilePath -Counter $Counter -ContentLines $chunkContent -ChunkNumber $chunkNumber -ChunkCount $chunkCount
        $sectionTokens = Get-ApproxTokenCount -Lines $sectionLines
        [void]$items.Add([pscustomobject]@{
            FilePath = $FilePath
            Counter = $Counter
            ChunkNumber = $chunkNumber
            ChunkCount = $chunkCount
            Lines = $sectionLines
            TokenCount = $sectionTokens
        })
    }

    return ,$items.ToArray()
}

function Get-TokenAwareBatchGroups {
    param(
        [Parameter(Mandatory=$true)][string[]]$Files,
        [Parameter(Mandatory=$true)][int]$TokensPerBatch
    )

    if ($TokensPerBatch -lt 1) { $TokensPerBatch = 1 }

    $groups = New-Object System.Collections.Generic.List[object]
    $current = New-Object System.Collections.Generic.List[object]
    $currentTokens = 0
    $totalFiles = $Files.Count

    Write-Host ""
    Write-Host "Analysing $totalFiles file(s) for token-aware chunking. Please wait..." -ForegroundColor Cyan

    for ($i = 0; $i -lt $Files.Count; $i++) {
        $f = $Files[$i]
        $pct = [int](($i / $totalFiles) * 100)
        Write-Host ("  [{0,3}%] ({1}/{2}) {3}" -f $pct, ($i+1), $totalFiles, (Split-Path -Leaf $f)) -ForegroundColor DarkGray

        $sectionItems = Get-TokenAwareSectionItems -FilePath $f -Counter ($i + 1) -MaxTokens $TokensPerBatch

        foreach ($item in $sectionItems) {
            if ($current.Count -gt 0 -and ($currentTokens + $item.TokenCount) -gt $TokensPerBatch) {
                [void]$groups.Add(@($current.ToArray()))
                Write-Host ("  --> Batch {0} sealed ({1} tokens)" -f $groups.Count, $currentTokens) -ForegroundColor Yellow
                $current.Clear()
                $currentTokens = 0
            }

            [void]$current.Add($item)
            $currentTokens += $item.TokenCount
        }
    }

    if ($current.Count -gt 0) {
        [void]$groups.Add(@($current.ToArray()))
        Write-Host ("  --> Batch {0} sealed ({1} tokens)" -f $groups.Count, $currentTokens) -ForegroundColor Yellow
    }

    Write-Host "Analysis complete. $($groups.Count) batch(es) planned." -ForegroundColor Cyan
    Write-Host ""

    return ,$groups.ToArray()
}

function Write-TokenAwareBatch {
    param(
        [Parameter(Mandatory=$true)][object[]]$BatchItems,
        [Parameter(Mandatory=$true)][string]$OutPath,
        [Parameter(Mandatory=$true)][string]$TreeText,
        [Parameter(Mandatory=$true)][bool]$EnableDiag,
        [object[]]$Diagnostics = @(),
        [int]$BatchNumber = 1,
        [int]$TotalBatches = 1,
        [string]$BatchDescription = "Single file"
    )

    $headerLines = Build-HeaderLines -TreeText $TreeText -EnableDiag $EnableDiag -Diagnostics $Diagnostics -BatchNumber $BatchNumber -TotalBatches $TotalBatches -BatchDescription $BatchDescription
    Set-Content -Path $OutPath -Value ($headerLines -join "`r`n") -Encoding UTF8

    $counter = 0
    foreach ($item in $BatchItems) {
        $counter++
        Write-Host "[$counter / $($BatchItems.Count)]: Adding $($item.FilePath) (chunk $($item.ChunkNumber) of $($item.ChunkCount))"
        $item.Lines | Add-Content -Path $OutPath -Encoding UTF8
    }
}


function Get-JsonItemSummary {
    param([Parameter(Mandatory=$false)]$Value)

    if ($null -eq $Value) { return 'Null' }

    $summaryParts = New-Object System.Collections.Generic.List[string]
    $candidateNames = @('uuid', 'name', 'title', 'id', 'created_at', 'updated_at', 'type', 'role', 'sender')

    try {
        if ($Value -is [pscustomobject] -or $Value -is [hashtable] -or $Value -is [System.Collections.IDictionary]) {
            foreach ($key in $candidateNames) {
                $prop = $null
                try {
                    if ($Value.PSObject.Properties.Name -contains $key) {
                        $prop = $Value.$key
                    } elseif ($Value.ContainsKey($key)) {
                        $prop = $Value[$key]
                    }
                } catch {
                    # ignore
                }
                if ($null -ne $prop -and -not [string]::IsNullOrWhiteSpace([string]$prop)) {
                    [void]$summaryParts.Add(("{0}={1}" -f $key, $prop))
                }
            }
        }
    } catch {
        # ignore
    }

    if ($summaryParts.Count -gt 0) {
        return ($summaryParts -join '; ')
    }

    try {
        return $Value.GetType().Name
    } catch {
        return 'JSON value'
    }
}

function Get-JsonTextAwareSectionItems {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][int]$Counter,
        [Parameter(Mandatory=$true)][int]$MaxTokens
    )

    $items = New-Object System.Collections.Generic.List[object]

    $rawText = $null
    try {
        $rawText = Get-Content -LiteralPath $FilePath -Raw -Encoding UTF8 -ErrorAction Stop
    } catch {
        try {
            $rawText = Get-Content -LiteralPath $FilePath -Raw -Encoding Default -ErrorAction Stop
        } catch {
            return @(Get-TokenAwareSectionItems -FilePath $FilePath -Counter $Counter -MaxTokens $MaxTokens)
        }
    }

    if ([string]::IsNullOrWhiteSpace($rawText)) {
        return @(Get-TokenAwareSectionItems -FilePath $FilePath -Counter $Counter -MaxTokens $MaxTokens)
    }

    try {
        $jsonRoot = $rawText | ConvertFrom-Json -ErrorAction Stop
    } catch {
        return @(Get-TokenAwareSectionItems -FilePath $FilePath -Counter $Counter -MaxTokens $MaxTokens)
    }

    $rootKind = Get-JsonRootKind -Value $jsonRoot
    $sourceItems = @()
    if ($rootKind -eq 'Array') {
        $sourceItems = @($jsonRoot)
    } else {
        $sourceItems = @($jsonRoot)
    }

    $itemCount = if ($rootKind -eq 'Array') { $sourceItems.Count } else { 1 }
    if ($itemCount -lt 1) { $itemCount = 1 }

    for ($idx = 0; $idx -lt $sourceItems.Count; $idx++) {
        $sourceItem = $sourceItems[$idx]
        $summary = Get-JsonItemSummary -Value $sourceItem

        try {
            $itemText = $sourceItem | ConvertTo-Json -Depth 100
        } catch {
            $itemText = [string]$sourceItem
        }
        if ([string]::IsNullOrWhiteSpace($itemText)) {
            $itemText = [string]$sourceItem
        }

        $contentLines = @($itemText -split "`r?`n")
        $metaLines = @(
            ("JSON root kind: {0}" -f $rootKind)
        )
        if ($rootKind -eq 'Array') {
            $metaLines += ("JSON item: {0} of {1}" -f ($idx + 1), $itemCount)
        } else {
            $metaLines += "JSON document root"
        }
        if (-not [string]::IsNullOrWhiteSpace($summary)) {
            $metaLines += ("JSON item summary: {0}" -f $summary)
        }

        $jsonFileItem = Get-Item -LiteralPath $FilePath -ErrorAction SilentlyContinue
        $jsonSize = if ($jsonFileItem) { $jsonFileItem.Length } else { 0 }
        $jsonMtime = if ($jsonFileItem) { $jsonFileItem.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') } else { "Unknown" }

        $baseHeader = @(
            "",
            ("===== File {0}: {1} =====" -f $Counter, $FilePath),
            ("Size: {0} bytes    Last modified: {1}" -f $jsonSize, $jsonMtime)
        ) + $metaLines + @("----- Begin Content -----", "----- End Content -----", "")
        $headerReserve = (Get-ApproxTokenCount -Lines $baseHeader) + 30
        $contentBudget = [Math]::Max(1, $MaxTokens - $headerReserve)

        $units = Convert-ToJsonAwareUnits -Lines $contentLines -MaxTokens $contentBudget
        $chunkBodies = Pack-UnitsIntoTokenChunks -Units $units -MaxTokens $contentBudget
        if (-not $chunkBodies -or $chunkBodies.Count -eq 0) {
            $chunkBodies = @(@())
        }

        $chunkCount = $chunkBodies.Count
        for ($i = 0; $i -lt $chunkCount; $i++) {
            $chunkContent = if ($chunkBodies[$i] -and $chunkBodies[$i].Count -gt 0) {
                [string[]]@($chunkBodies[$i] | Where-Object { $_ -ne $null })
            } else {
                [string[]]@()
            }
            $sectionLines = Build-TokenAwareSectionLines -FilePath $FilePath -Counter $Counter -ContentLines $chunkContent -ChunkNumber ($i + 1) -ChunkCount $chunkCount -ChunkingLabel 'JSON-aware token chunks' -ExtraMetaLines $metaLines
            $sectionTokens = Get-ApproxTokenCount -Lines $sectionLines
            [void]$items.Add([pscustomobject]@{
                FilePath = $FilePath
                Counter = $Counter
                ChunkNumber = ($i + 1)
                ChunkCount = $chunkCount
                Lines = $sectionLines
                TokenCount = $sectionTokens
            })
        }
    }

    return ,$items.ToArray()
}

function Get-JsonTextAwareBatchGroups {
    param(
        [Parameter(Mandatory=$true)][string[]]$Files,
        [Parameter(Mandatory=$true)][int]$TokensPerBatch
    )

    if ($TokensPerBatch -lt 1) { $TokensPerBatch = 1 }

    $groups = New-Object System.Collections.Generic.List[object]
    $current = New-Object System.Collections.Generic.List[object]
    $currentTokens = 0
    $totalFiles = $Files.Count

    Write-Host ""
    Write-Host "Analysing $totalFiles file(s) for JSON-aware token chunking. Please wait..." -ForegroundColor Cyan

    for ($i = 0; $i -lt $Files.Count; $i++) {
        $f = $Files[$i]
        $pct = [int](($i / [Math]::Max(1, $totalFiles)) * 100)
        Write-Host (("  [{0,3}%] ({1}/{2}) {3}" -f $pct, ($i + 1), $totalFiles, (Split-Path -Leaf $f))) -ForegroundColor DarkGray

        $sectionItems = Get-JsonTextAwareSectionItems -FilePath $f -Counter ($i + 1) -MaxTokens $TokensPerBatch

        foreach ($item in $sectionItems) {
            if ($current.Count -gt 0 -and ($currentTokens + $item.TokenCount) -gt $TokensPerBatch) {
                [void]$groups.Add(@($current.ToArray()))
                Write-Host (("  --> Batch {0} sealed ({1} tokens)" -f $groups.Count, $currentTokens)) -ForegroundColor Yellow
                $current.Clear()
                $currentTokens = 0
            }

            [void]$current.Add($item)
            $currentTokens += $item.TokenCount
        }
    }

    if ($current.Count -gt 0) {
        [void]$groups.Add(@($current.ToArray()))
        Write-Host (("  --> Batch {0} sealed ({1} tokens)" -f $groups.Count, $currentTokens)) -ForegroundColor Yellow
    }

    Write-Host "Analysis complete. $($groups.Count) batch(es) planned." -ForegroundColor Cyan
    Write-Host ""

    return ,$groups.ToArray()
}

function Get-JsonRootKind {
    param([Parameter(Mandatory=$false)]$Value)

    if ($null -eq $Value) { return 'Null' }

    if ($Value -is [string] -or $Value -is [char] -or $Value -is [bool] -or
        $Value -is [byte] -or $Value -is [sbyte] -or
        $Value -is [int16] -or $Value -is [int32] -or $Value -is [int64] -or
        $Value -is [uint16] -or $Value -is [uint32] -or $Value -is [uint64] -or
        $Value -is [single] -or $Value -is [double] -or $Value -is [decimal]) {
        return 'Primitive'
    }

    if ($Value -is [pscustomobject] -or $Value -is [hashtable] -or $Value -is [System.Collections.IDictionary]) {
        return 'Object'
    }

    if (($Value -is [System.Collections.IEnumerable]) -and -not ($Value -is [string])) {
        return 'Array'
    }

    return 'Primitive'
}

function Read-TextFileRaw {
    param([Parameter(Mandatory=$true)][string]$FilePath)

    try {
        return [pscustomobject]@{
            Success = $true
            Encoding = 'UTF8'
            Text = (Get-Content -LiteralPath $FilePath -Raw -Encoding UTF8 -ErrorAction Stop)
            Error = $null
        }
    } catch {
        $utf8Error = $_.Exception.Message
        try {
            return [pscustomobject]@{
                Success = $true
                Encoding = 'Default'
                Text = (Get-Content -LiteralPath $FilePath -Raw -Encoding Default -ErrorAction Stop)
                Error = $null
            }
        } catch {
            return [pscustomobject]@{
                Success = $false
                Encoding = $null
                Text = $null
                Error = $_.Exception.Message
            }
        }
    }
}

function Read-JsonFileRecord {
    param([Parameter(Mandatory=$true)][string]$FilePath)

    $item = Get-Item -LiteralPath $FilePath -ErrorAction SilentlyContinue
    $size = if ($item) { $item.Length } else { 0 }
    $mtime = if ($item) { $item.LastWriteTime.ToString('yyyy-MM-dd HH:mm:ss') } else { "Unknown" }

    $read = Read-TextFileRaw -FilePath $FilePath
    if (-not $read.Success) {
        return [pscustomobject]@{
            FilePath = $FilePath
            FileName = [System.IO.Path]::GetFileName($FilePath)
            Size = $size
            LastModified = $mtime
            Encoding = $null
            ParseStatus = 'ReadError'
            RootType = 'Invalid'
            ItemCount = 1
            ErrorMessage = $read.Error
            Content = [pscustomobject]@{
                sourceFile = $FilePath
                fileName = [System.IO.Path]::GetFileName($FilePath)
                parseStatus = 'ReadError'
                error = $read.Error
            }
        }
    }

    $parsed = $null
    $parseStatus = 'Parsed'
    $rootType = 'Unknown'
    $errorMessage = $null

    try {
        $parsed = $read.Text | ConvertFrom-Json -Depth 100 -ErrorAction Stop
        $rootType = Get-JsonRootKind -Value $parsed
    } catch {
        $parseStatus = 'ParseError'
        $rootType = 'Invalid'
        $errorMessage = $_.Exception.Message
    }

    if ($parseStatus -eq 'Parsed') {
        $itemCount = if ($rootType -eq 'Array') { @($parsed).Count } else { 1 }
        return [pscustomobject]@{
            FilePath = $FilePath
            FileName = [System.IO.Path]::GetFileName($FilePath)
            Size = $size
            LastModified = $mtime
            Encoding = $read.Encoding
            ParseStatus = $parseStatus
            RootType = $rootType
            ItemCount = $itemCount
            ErrorMessage = $null
            Content = $parsed
        }
    }

    return [pscustomobject]@{
        FilePath = $FilePath
        FileName = [System.IO.Path]::GetFileName($FilePath)
        Size = $size
        LastModified = $mtime
        Encoding = $read.Encoding
        ParseStatus = $parseStatus
        RootType = $rootType
        ItemCount = 1
        ErrorMessage = $errorMessage
        Content = [pscustomobject]@{
            sourceFile = $FilePath
            fileName = [System.IO.Path]::GetFileName($FilePath)
            parseStatus = $parseStatus
            error = $errorMessage
            rawText = $read.Text
        }
    }
}

function Get-JsonMergedPayload {
    param(
        [Parameter(Mandatory=$true)][string[]]$Files,
        [Parameter(Mandatory=$true)][string]$TreeText,
        [Parameter(Mandatory=$true)][bool]$EnableDiag,
        [object[]]$Diagnostics = @(),
        [int]$BatchNumber = 1,
        [int]$TotalBatches = 1,
        [string]$BatchDescription = "Single file",
        [object[]]$MergedItemsOverride = $null
    )

    $records = New-Object System.Collections.Generic.List[object]
    $mergedItems = New-Object System.Collections.Generic.List[object]
    $mergeNotes = New-Object System.Collections.Generic.List[string]

    foreach ($f in $Files) {
        $record = Read-JsonFileRecord -FilePath $f
        [void]$records.Add($record)

        if ($record.ParseStatus -eq 'Parsed' -and $record.RootType -eq 'Array') {
            foreach ($item in @($record.Content)) {
                [void]$mergedItems.Add($item)
            }
        } else {
            [void]$mergedItems.Add([pscustomobject]@{
                sourceFile = $record.FilePath
                fileName = $record.FileName
                sizeBytes = $record.Size
                lastModified = $record.LastModified
                parseStatus = $record.ParseStatus
                rootType = $record.RootType
                content = $record.Content
            })
        }
    }

    if ($MergedItemsOverride -ne $null) {
        $mergedItems = New-Object System.Collections.Generic.List[object]
        foreach ($item in $MergedItemsOverride) {
            [void]$mergedItems.Add($item)
        }
    }

    $sourceFiles = foreach ($record in @($records.ToArray())) {
        [pscustomobject]@{
            filePath = $record.FilePath
            fileName = $record.FileName
            sizeBytes = $record.Size
            lastModified = $record.LastModified
            encoding = $record.Encoding
            parseStatus = $record.ParseStatus
            rootType = $record.RootType
            itemCount = $record.ItemCount
            errorMessage = $record.ErrorMessage
        }
    }

    if ($records.Count -eq 0) {
        [void]$mergeNotes.Add('No input files were provided.')
    } else {
        [void]$mergeNotes.Add('Array roots were flattened into mergedItems; non-array roots were wrapped per source file.')
    }

    $mergedItemsArray = @($mergedItems.ToArray())
    $mergeNotesArray = @($mergeNotes.ToArray())

    return [pscustomobject]@{
        combinedOn = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
        outputKind = 'JsonMerge'
        batchNumber = $BatchNumber
        totalBatches = $TotalBatches
        batchDescription = $BatchDescription
        sourceCount = $Files.Count
        sourceFiles = @($sourceFiles)
        mergedItemCount = $mergedItemsArray.Count
        mergedItems = @($mergedItemsArray)
        mergeNotes = @($mergeNotesArray)
        directoryTree = $TreeText
        encodingDiagnostics = if ($EnableDiag) { @($Diagnostics) } else { @() }
    }
}

function Get-JsonBatchGroups {
    param(
        [Parameter(Mandatory=$true)][object[]]$Items,
        [ValidateSet('Items','Parts')]
        [string]$Mode = 'Items',
        [int]$ItemsPerBatch = 50,
        [int]$PartCount = 10
    )

    $groups = New-Object System.Collections.Generic.List[object]
    if (-not $Items -or $Items.Count -eq 0) { return @() }

    switch ($Mode) {
        'Items' {
            if ($ItemsPerBatch -lt 1) { $ItemsPerBatch = 1 }
            for ($i = 0; $i -lt $Items.Count; $i += $ItemsPerBatch) {
                $end = [Math]::Min($i + $ItemsPerBatch - 1, $Items.Count - 1)
                [void]$groups.Add(@($Items[$i..$end]))
            }
        }
        'Parts' {
            if ($PartCount -lt 1) { $PartCount = 1 }
            if ($PartCount -gt $Items.Count) { $PartCount = $Items.Count }
            $itemsPerPart = [Math]::Ceiling($Items.Count / $PartCount)
            for ($i = 0; $i -lt $Items.Count; $i += $itemsPerPart) {
                $end = [Math]::Min($i + $itemsPerPart - 1, $Items.Count - 1)
                [void]$groups.Add(@($Items[$i..$end]))
            }
        }
    }

    return ,$groups.ToArray()
}

function Resolve-RelativePath {
    param(
        [Parameter(Mandatory=$true)][string]$PathValue,
        [string]$RootPath
    )

    $fullPath = [System.IO.Path]::GetFullPath($PathValue)

    if ([string]::IsNullOrWhiteSpace($RootPath)) {
        return $fullPath
    }

    try {
        $rootFull = [System.IO.Path]::GetFullPath($RootPath).TrimEnd('\')
        if ($fullPath.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            $relative = $fullPath.Substring($rootFull.Length).TrimStart('\')
            if ([string]::IsNullOrWhiteSpace($relative)) {
                return $fullPath
            }
            return $relative
        }
    } catch {
        # Fallback to full path below
    }

    return $fullPath
}

function Build-FilenameListLines {
    param(
        [Parameter(Mandatory=$true)][string[]]$Files,
        [string]$RootPath,
        [ValidateSet('NamesOnly','RelativePaths','GroupedByDirectory','GroupedByFileType')]
        [string]$ListingMode = 'NamesOnly'
    )

    $lines = New-Object System.Collections.Generic.List[string]
    [void]$lines.Add("Filename list generated on: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    [void]$lines.Add("Source file count: $($Files.Count)")
    if (-not [string]::IsNullOrWhiteSpace($RootPath)) {
        [void]$lines.Add("Root path: $RootPath")
    }
    [void]$lines.Add("Listing mode: $ListingMode")
    [void]$lines.Add("")

    switch ($ListingMode) {
        'NamesOnly' {
            foreach ($f in $Files) {
                $name = [System.IO.Path]::GetFileName($f)
                if ([string]::IsNullOrWhiteSpace($name)) { $name = $f }
                [void]$lines.Add($name)
            }
        }
        'RelativePaths' {
            foreach ($f in $Files) {
                [void]$lines.Add((Resolve-RelativePath -PathValue $f -RootPath $RootPath))
            }
        }
        'GroupedByDirectory' {
            $grouped = @{}
            foreach ($f in $Files) {
                $dir = Split-Path -Parent $f
                if ([string]::IsNullOrWhiteSpace($dir)) { $dir = '.' }
                $displayDir = Resolve-RelativePath -PathValue $dir -RootPath $RootPath
                if ([string]::IsNullOrWhiteSpace($displayDir)) { $displayDir = '.' }

                if (-not $grouped.ContainsKey($displayDir)) {
                    $grouped[$displayDir] = New-Object System.Collections.Generic.List[string]
                }
                $leaf = [System.IO.Path]::GetFileName($f)
                if ([string]::IsNullOrWhiteSpace($leaf)) { $leaf = $f }
                [void]$grouped[$displayDir].Add($leaf)
            }

            foreach ($dirName in ($grouped.Keys | Sort-Object)) {
                [void]$lines.Add("[$dirName]")
                foreach ($fileName in ($grouped[$dirName] | Sort-Object)) {
                    [void]$lines.Add("  $fileName")
                }
                [void]$lines.Add("")
            }
        }
        'GroupedByFileType' {
            $grouped = @{}
            foreach ($f in $Files) {
                $type = Get-FileTypeLabel -FilePath $f
                if (-not $grouped.ContainsKey($type)) {
                    $grouped[$type] = New-Object System.Collections.Generic.List[string]
                }

                if ([string]::IsNullOrWhiteSpace($RootPath)) {
                    $display = [System.IO.Path]::GetFileName($f)
                    if ([string]::IsNullOrWhiteSpace($display)) { $display = $f }
                } else {
                    $display = Resolve-RelativePath -PathValue $f -RootPath $RootPath
                }

                [void]$grouped[$type].Add($display)
            }

            foreach ($typeName in ($grouped.Keys | Sort-Object)) {
                [void]$lines.Add("[$typeName]")
                foreach ($fileName in ($grouped[$typeName] | Sort-Object)) {
                    [void]$lines.Add("  $fileName")
                }
                [void]$lines.Add("")
            }
        }
    }

    return ,$lines.ToArray()
}

function Write-FilenameListOutput {
    param(
        [Parameter(Mandatory=$true)][string[]]$Files,
        [Parameter(Mandatory=$true)][string]$OutPath,
        [string]$RootPath,
        [ValidateSet('NamesOnly','RelativePaths','GroupedByDirectory','GroupedByFileType')]
        [string]$ListingMode = 'NamesOnly'
    )

    $lines = Build-FilenameListLines -Files $Files -RootPath $RootPath -ListingMode $ListingMode
    Set-Content -Path $OutPath -Value ($lines -join "`r`n") -Encoding UTF8
}



function Get-FileTypeLabel {
    param([Parameter(Mandatory=$true)][string]$FilePath)

    $ext = [System.IO.Path]::GetExtension($FilePath)
    if ([string]::IsNullOrWhiteSpace($ext)) {
        return '[no extension]'
    }
    return $ext.ToLowerInvariant()
}

function Get-FileTypeInventory {
    param([Parameter(Mandatory=$true)][string[]]$Files)

    $groups = $Files | ForEach-Object {
        [pscustomobject]@{
            FilePath = $_
            FileType = Get-FileTypeLabel -FilePath $_
        }
    } | Group-Object FileType | ForEach-Object {
        [pscustomobject]@{
            FileType = $_.Name
            Count    = $_.Count
        }
    }

    return @($groups | Sort-Object -Property @{Expression='Count';Descending=$true}, @{Expression='FileType';Descending=$false})
}

function Select-FilesByFileType {
    param([Parameter(Mandatory=$true)][string[]]$Files)

    $inventory = Get-FileTypeInventory -Files $Files
    if (-not $inventory -or $inventory.Count -le 1) {
        return $Files
    }

    Write-Host ""
    Write-Host "Discovered file types:"
    for ($i = 0; $i -lt $inventory.Count; $i++) {
        $item = $inventory[$i]
        Write-Host ("  {0}) {1} ({2} files)" -f ($i + 1), $item.FileType, $item.Count)
    }

    $choice = Read-Host "Enter numbers or ranges to include (example 1,3,5-7). Enter A for all (default A)"
    if ([string]::IsNullOrWhiteSpace($choice) -or $choice.Trim().ToUpperInvariant() -eq 'A') {
        return $Files
    }

    $selectedIndexes = New-Object System.Collections.Generic.HashSet[int]
    foreach ($part in ($choice -split '[,; ]+')) {
        if ([string]::IsNullOrWhiteSpace($part)) { continue }
        if ($part -match '^(\d+)-(\d+)$') {
            $start = [int]$matches[1]
            $end = [int]$matches[2]
            if ($start -gt $end) { $tmp = $start; $start = $end; $end = $tmp }
            for ($n = $start; $n -le $end; $n++) {
                if ($n -ge 1 -and $n -le $inventory.Count) { [void]$selectedIndexes.Add($n) }
            }
        } elseif ($part -match '^\d+$') {
            $n = [int]$part
            if ($n -ge 1 -and $n -le $inventory.Count) { [void]$selectedIndexes.Add($n) }
        }
    }

    if ($selectedIndexes.Count -eq 0) {
        return $Files
    }

    $selectedTypes = foreach ($idx in ($selectedIndexes | Sort-Object)) {
        $inventory[$idx - 1].FileType
    }

    $filtered = foreach ($f in $Files) {
        if ($selectedTypes -contains (Get-FileTypeLabel -FilePath $f)) {
            $f
        }
    }

    return @($filtered)
}

# ============================================================
#  COMBINE WORKFLOW
# ============================================================

function Invoke-CombineFilesWorkflow {
    Write-Host ""
    Write-Host "Combine Files -> Text / JSON output with optional batching and encoding diagnostic" -ForegroundColor Cyan
    Write-Host "Choose mode:"
    Write-Host "  1) Select specific files (multi-select and iterative navigation)"
    Write-Host "  2) Select a folder (include all files recursively)"
    Write-Host "  3) Exit"
    $mode = Read-Host "Enter 1, 2 or 3 (default 1)"
    if ($mode -eq '3') { return }
    if ($mode -ne '2') { $mode = '1' }

    Write-Host ""
    Write-Host ">>> A dialog box is about to appear. Check your taskbar if you don't see it. <<<" -ForegroundColor Magenta
    $diagAnswer = [System.Windows.Forms.MessageBox]::Show(
        "Enable encoding diagnostic mode? (This writes a diagnostic table to the combined file(s) and prints info to console.)",
        "Encoding Diagnostic",
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question
    )
    $enableDiag = ($diagAnswer -eq [System.Windows.Forms.DialogResult]::Yes)

    $files = @()
    $rootForTree = $null

    if ($mode -eq '1') {
        $sel = Show-OpenFileDialog -Title "Select files to include" -Filter "All files (*.*)|*.*" -Multiselect $true
        if (-not $sel -or $sel.Count -eq 0) { Write-Host "No files selected. Exiting."; return }
        $files = $sel
        $common = Get-CommonPath -Paths $files
        if ($common) { $rootForTree = $common } else { $rootForTree = $null }
    } else {
        $folder = Show-FolderBrowserDialog
        if (-not $folder) { Write-Host "No folder selected. Exiting."; return }
        $files = Get-ChildItem -LiteralPath $folder -File -Recurse -ErrorAction SilentlyContinue | Sort-Object FullName | Select-Object -ExpandProperty FullName
        if (-not $files -or $files.Count -eq 0) { Write-Host "No files found in folder. Exiting."; return }
        $rootForTree = $folder

        Write-Host ""
        Write-Host "Folder scan found these file types:"
        $inventory = Get-FileTypeInventory -Files $files
        for ($i = 0; $i -lt $inventory.Count; $i++) {
            $item = $inventory[$i]
            Write-Host ("  {0}) {1} ({2} files)" -f ($i + 1), $item.FileType, $item.Count)
        }

        $filterAnswer = Read-Host "Filter by file type before output? (Y/n default Y)"
        if ($filterAnswer -notin @('n','N','no','NO')) {
            $filtered = Select-FilesByFileType -Files $files
            if ($filtered -and $filtered.Count -gt 0) {
                $files = $filtered | Sort-Object
                Write-Host ("Keeping {0} files after file-type filtering." -f $files.Count)
            } else {
                Write-Host "No files matched the selected file types. Exiting."
                return
            }
        }
    }

    Write-Host ""
    Write-Host "Output mode:"
    Write-Host "  1) Single combined file"
    Write-Host "  2) Split by number of files per output"
    Write-Host "  3) Split by number of lines per output"
    Write-Host "  4) Split into a fixed number of parts"
    Write-Host "  5) Split by number of tokens per output (sentence-safe approximate chunking)"
    Write-Host "  6) Output filenames only (optionally grouped by subdirectory or file type)"
    Write-Host "  7) JSON merge mode (valid JSON output)"
    Write-Host "  8) JSON-aware text splitter (text output)"
    $outputMode = Read-Host "Enter 1, 2, 3, 4, 5, 6, 7, or 8 (default 1)"
    if ($outputMode -notin @('2','3','4','5','6','7','8')) { $outputMode = '1' }

    $treeText = ""
    if ($rootForTree) {
        try {
            $treeText = (& tree "$rootForTree" /A /F 2>$null) | Out-String
        } catch {
            $treeText = "Unable to generate tree via 'tree.exe' for $rootForTree."
        }
    } else {
        $parents = $files | ForEach-Object { Split-Path -Parent $_ } | Sort-Object -Unique
        foreach ($p in $parents) {
            $treeText += "Directory tree for: $p`r`n"
            try {
                $treeText += ((& tree "$p" /A /F 2>$null) | Out-String)
            } catch {
                $treeText += "Unable to generate tree via 'tree.exe' for $p.`r`n"
            }
            $treeText += "`r`n"
        }
    }

    $diagnostics = @()
    if ($enableDiag) {
        Write-Host "Running encoding diagnostics for $($files.Count) files..."
        foreach ($f in $files) {
            $d = Detect-Encoding -FilePath $f
            $diagnostics += $d
            Write-Host ("{0}  | BOM: {1}  | Guess: {2}" -f $d.Path, $d.BOMHex, $d.Guess)
        }
    }

    if ($outputMode -eq '6') {
        Write-Host ""
        Write-Host "Filename list mode:"
        Write-Host "  1) File names only"
        Write-Host "  2) Relative paths from the selected root"
        Write-Host "  3) Grouped by subdirectory"
        Write-Host "  4) Grouped by file type"
        $listMode = Read-Host "Enter 1, 2, 3, or 4 (default 2)"
        switch ($listMode) {
            '1' { $listMode = 'NamesOnly' }
            '3' { $listMode = 'GroupedByDirectory' }
            '4' { $listMode = 'GroupedByFileType' }
            default { $listMode = 'RelativePaths' }
        }

        Write-Host ""
        Write-Host ">>> A save file dialog is about to appear. Check your taskbar if you don't see it. <<<" -ForegroundColor Magenta
        $outPath = Show-SaveFileDialog -Title "Save filename list as" -DefaultName "Filenames.txt" -Filter "Text files (*.txt)|*.txt|All files (*.*)|*.*"
        if (-not $outPath) { Write-Host "No output file selected. Exiting."; return }

        Write-FilenameListOutput -Files $files -OutPath $outPath -RootPath $rootForTree -ListingMode $listMode

        Write-Host ""
        Write-Host "Done. Wrote $($files.Count) filename entries to:" -ForegroundColor Green
        Write-Host "  $outPath" -ForegroundColor Yellow
        return
    }

    if ($outputMode -eq '7') {
        Write-Host ""
        Write-Host "JSON merge mode:"
        Write-Host "  1) Single combined JSON file"
        Write-Host "  2) Split by number of merged items per output"
        Write-Host "  3) Split into a fixed number of parts"
        $jsonOutputMode = Read-Host "Enter 1, 2, or 3 (default 1)"
        if ($jsonOutputMode -notin @('2','3')) { $jsonOutputMode = '1' }

        $jsonPayload = Get-JsonMergedPayload -Files $files -TreeText $treeText -EnableDiag $enableDiag -Diagnostics $diagnostics -BatchNumber 1 -TotalBatches 1 -BatchDescription "Single merged JSON document"

        if ($jsonOutputMode -eq '1') {
            Write-Host ""
            Write-Host ">>> A save file dialog is about to appear. Check your taskbar if you don't see it. <<<" -ForegroundColor Magenta
            $outPath = Show-SaveFileDialog -Title "Save merged JSON as" -DefaultName "Combined.json" -Filter "JSON files (*.json)|*.json|All files (*.*)|*.*"
            if (-not $outPath) { Write-Host "No output file selected. Exiting."; return }

            $json = $jsonPayload | ConvertTo-Json -Depth 100
            Set-Content -Path $outPath -Value $json -Encoding UTF8

            Write-Host ""
            Write-Host "Done. Merged $($files.Count) JSON file(s) into:" -ForegroundColor Green
            Write-Host "  $outPath" -ForegroundColor Yellow
            if ($enableDiag) {
                Write-Host "Encoding diagnostic included in the JSON metadata."
            }
            return
        }

        if ($jsonOutputMode -eq '2') {
            $itemsPerBatch = Read-Host "How many merged items per output file? (default 50)"
            if ([string]::IsNullOrWhiteSpace($itemsPerBatch)) { $itemsPerBatch = 50 }
            $itemsPerBatch = [int]$itemsPerBatch
            $jsonGroups = Get-JsonBatchGroups -Items $jsonPayload.mergedItems -Mode 'Items' -ItemsPerBatch $itemsPerBatch
            $jsonBatchDescription = "Every $itemsPerBatch merged items"
        } else {
            $partCount = Read-Host "How many output parts do you want? (default 10)"
            if ([string]::IsNullOrWhiteSpace($partCount)) { $partCount = 10 }
            $partCount = [int]$partCount
            $jsonGroups = Get-JsonBatchGroups -Items $jsonPayload.mergedItems -Mode 'Parts' -PartCount $partCount
            $jsonBatchDescription = "$partCount total JSON parts"
        }

        if (-not $jsonGroups -or $jsonGroups.Count -eq 0) {
            Write-Host "No JSON output batches were created. Exiting."
            return
        }

        Write-Host ""
        Write-Host ">>> A folder selection dialog is about to appear. Check your taskbar if you don't see it. <<<" -ForegroundColor Magenta
        $outDir = Show-FolderBrowserDialog -Description "Select a folder to save the JSON batch files"
        if (-not $outDir) { Write-Host "No output folder selected. Exiting."; return }

        $prefix = Read-Host "Output filename prefix (default CombinedJSON_)"
        if ([string]::IsNullOrWhiteSpace($prefix)) { $prefix = "CombinedJSON_" }
        $prefix = Sanitize-FileNamePart -Name $prefix

        for ($i = 0; $i -lt $jsonGroups.Count; $i++) {
            $batchNumber = $i + 1
            $outName = "{0}{1}.json" -f $prefix, $batchNumber.ToString("D3")
            $outPath = Join-Path -Path $outDir -ChildPath $outName

            Write-Host ""
            Write-Host "Writing JSON batch $batchNumber of $($jsonGroups.Count): $outPath" -ForegroundColor Cyan

            $batchItems = @($jsonGroups[$i])
            $payload = [pscustomobject]@{
                combinedOn = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
                outputKind = 'JsonMerge'
                batchNumber = $batchNumber
                totalBatches = $jsonGroups.Count
                batchDescription = $jsonBatchDescription
                sourceCount = $jsonPayload.sourceCount
                sourceFiles = $jsonPayload.sourceFiles
                mergedItemCount = $batchItems.Count
                mergedItems = @($batchItems)
                mergeNotes = $jsonPayload.mergeNotes
                directoryTree = $treeText
                encodingDiagnostics = if ($enableDiag) { @($diagnostics) } else { @() }
            }

            $json = $payload | ConvertTo-Json -Depth 100
            Set-Content -Path $outPath -Value $json -Encoding UTF8
        }

        Write-Host ""
        Write-Host "Done. Created $($jsonGroups.Count) JSON batch file(s) in:" -ForegroundColor Green
        Write-Host "  $outDir" -ForegroundColor Yellow
        if ($enableDiag) {
            Write-Host "Encoding diagnostic included in the JSON metadata."
        }
        return
    }

    $batchGroups = @()
    $batchDescription = "Single file"

    if ($outputMode -eq '1') {
        $batchGroups = Get-BatchGroups -Files $files -Mode 'Single'
    } elseif ($outputMode -eq '2') {
        $filesPerBatch = Read-Host "How many files per output file? (default 30)"
        if ([string]::IsNullOrWhiteSpace($filesPerBatch)) { $filesPerBatch = 30 }
        $filesPerBatch = [int]$filesPerBatch
        $batchDescription = "Every $filesPerBatch files"
        $batchGroups = Get-BatchGroups -Files $files -Mode 'Files' -FilesPerBatch $filesPerBatch
    } elseif ($outputMode -eq '3') {
        $linesPerBatch = Read-Host "How many output lines per output file? (default 200)"
        if ([string]::IsNullOrWhiteSpace($linesPerBatch)) { $linesPerBatch = 200 }
        $linesPerBatch = [int]$linesPerBatch
        $batchDescription = "Every $linesPerBatch output lines"
        $batchGroups = Get-BatchGroups -Files $files -Mode 'Lines' -LinesPerBatch $linesPerBatch
    } elseif ($outputMode -eq '4') {
        $partCount = Read-Host "How many output parts do you want? (default 20)"
        if ([string]::IsNullOrWhiteSpace($partCount)) { $partCount = 20 }
        $partCount = [int]$partCount
        $batchDescription = "$partCount total parts"
        $batchGroups = Get-BatchGroups -Files $files -Mode 'Parts' -PartCount $partCount
    } elseif ($outputMode -eq '8') {
        $tokensPerBatch = Read-Host "How many tokens per output file? (default 8000)"
        if ([string]::IsNullOrWhiteSpace($tokensPerBatch)) { $tokensPerBatch = 8000 }
        $tokensPerBatch = [int]$tokensPerBatch
        $batchDescription = "About $tokensPerBatch tokens per output (JSON-aware text chunks)"
        $batchGroups = Get-JsonTextAwareBatchGroups -Files $files -TokensPerBatch $tokensPerBatch
    } else {
        $tokensPerBatch = Read-Host "How many tokens per output file? (default 8000)"
        if ([string]::IsNullOrWhiteSpace($tokensPerBatch)) { $tokensPerBatch = 8000 }
        $tokensPerBatch = [int]$tokensPerBatch
        $batchDescription = "About $tokensPerBatch tokens per output (sentence-safe approximate chunking)"
        $batchGroups = Get-TokenAwareBatchGroups -Files $files -TokensPerBatch $tokensPerBatch
    }

    if (-not $batchGroups -or $batchGroups.Count -eq 0) {
        Write-Host "No output batches were created. Exiting."
        return
    }

    if ($batchGroups.Count -eq 1 -and $outputMode -eq '1') {
        $outPath = Show-SaveFileDialog -Title "Save combined file as" -DefaultName "Combined.txt" -Filter "Text files (*.txt)|*.txt|JSON files (*.json)|*.json|All files (*.*)|*.*"
        if (-not $outPath) { Write-Host "No output file selected. Exiting."; return }

        Write-CombinedBatch -BatchFiles $batchGroups[0] -OutPath $outPath -TreeText $treeText -EnableDiag $enableDiag -Diagnostics $diagnostics -BatchNumber 1 -TotalBatches 1 -BatchDescription $batchDescription

        Write-Host ""
        Write-Host "Done. Combined $($files.Count) files into:" -ForegroundColor Green
        Write-Host "  $outPath" -ForegroundColor Yellow
    } else {
        Write-Host ""
        Write-Host ">>> A folder selection dialog is about to appear. Check your taskbar if you don't see it. <<<" -ForegroundColor Magenta
        $outDir = Show-FolderBrowserDialog -Description "Select a folder to save the batched combined files"
        if (-not $outDir) { Write-Host "No output folder selected. Exiting."; return }

        $prefix = Read-Host "Output filename prefix (default CombinedBatch_)"
        if ([string]::IsNullOrWhiteSpace($prefix)) { $prefix = "CombinedBatch_" }
        $prefix = Sanitize-FileNamePart -Name $prefix

        for ($i = 0; $i -lt $batchGroups.Count; $i++) {
            $batchNumber = $i + 1
            $outName = "{0}{1}.txt" -f $prefix, $batchNumber.ToString("D3")
            $outPath = Join-Path -Path $outDir -ChildPath $outName

            Write-Host ""
            Write-Host "Writing batch $batchNumber of $($batchGroups.Count): $outPath" -ForegroundColor Cyan
            if ($outputMode -eq '5' -or $outputMode -eq '8') {
                Write-TokenAwareBatch -BatchItems $batchGroups[$i] -OutPath $outPath -TreeText $treeText -EnableDiag $enableDiag -Diagnostics $diagnostics -BatchNumber $batchNumber -TotalBatches $batchGroups.Count -BatchDescription $batchDescription
            } else {
                Write-CombinedBatch -BatchFiles $batchGroups[$i] -OutPath $outPath -TreeText $treeText -EnableDiag $enableDiag -Diagnostics $diagnostics -BatchNumber $batchNumber -TotalBatches $batchGroups.Count -BatchDescription $batchDescription
            }
        }

        Write-Host ""
        Write-Host "Done. Created $($batchGroups.Count) batched file(s) in:" -ForegroundColor Green
        Write-Host "  $outDir" -ForegroundColor Yellow
    }

    Write-Host ""
    if ($enableDiag) {
        Write-Host "Encoding diagnostic included in the header of the combined file(s)."
    }
}

# ============================================================
#  ENTRY POINT
# ============================================================

# When this script is dot-sourced by an orchestrator (e.g. the Combined_Tool
# menu), it must NOT auto-run. Set $__CombineTool_SuppressAutoRun = $true
# in the caller before dot-sourcing to suppress the auto-launch below.

if (-not $__CombineTool_SuppressAutoRun) {
    Write-Host ""
    Write-Host "Combine & Split Tool  v1" -ForegroundColor Cyan
    Write-Host "Combine files / folders into text / JSON outputs with batching and diagnostics." -ForegroundColor Cyan
    Write-Host "Designed to parse and chunk the github_export/ output produced by Package 1." -ForegroundColor Cyan
    Write-Host ""

    Invoke-CombineFilesWorkflow
}