# Register QMD collections (silos 1:1) including wiki — for #20
# Per spec.md:82-86 + qmd.index.yml.example. Requires `qmd` binary.
# Usage: .\scripts\register_qmd_collections.ps1
$root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Set-Location $root

function Add-Collection($name, $path) {
  if (Test-Path $path) {
    Write-Host "→ qmd collection add $path --name $name"
    & qmd collection add $path --name $name
    if ($LASTEXITCODE -ne 0) { Write-Host "  (warn: add $name failed, continuing)" -ForegroundColor Yellow }
  } else {
    Write-Host "  (skip $name: $path missing — will be indexed once created)" -ForegroundColor Yellow
    Write-Host "  To register later: qmd collection add $path --name $name"
  }
}

Add-Collection github corpus/github
Add-Collection chats corpus/chats
Add-Collection twitter corpus/twitter
Add-Collection notes corpus/notes
Add-Collection pdfs corpus/pdfs
Add-Collection web corpus/web
Add-Collection wiki corpus/wiki

Write-Host 'Done. Verify: qmd ls; qmd query --collection wiki "nebula"'
Write-Host 'Or copy qmd.index.yml.example to ~/.config/qmd/index.yml / .qmd/index.yml'
