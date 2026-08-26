Write-Host "Starting autonomous Cursor loop..." -ForegroundColor Cyan

# Locate native CLI agent binary to bypass Electron GUI launcher
$agentCmd = Get-Command "agent" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
if (-not $agentCmd) {
    $agentCmd = Get-Command "cursor-agent" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source
}
if (-not $agentCmd -and (Test-Path "$env:LOCALAPPDATA\cursor-agent\agent.cmd")) {
    $agentCmd = "$env:LOCALAPPDATA\cursor-agent\agent.cmd"
}
if (-not $agentCmd) {
    $agentCmd = "agent"
}

while (Select-String -Path "tasks.md" -Pattern "- \[ \]") {
    Write-Host "------------------------------------------------------" -ForegroundColor Yellow
    Write-Host "Starting new task iteration..." -ForegroundColor Yellow
    Write-Host "------------------------------------------------------" -ForegroundColor Yellow

    $promptText = Get-Content -Path "PROMPT_LOOP.md" -Raw
    & $agentCmd -p "$promptText" --force

    Start-Sleep -Seconds 3
}

Write-Host "All tasks in tasks.md completed and deployed!" -ForegroundColor Green
