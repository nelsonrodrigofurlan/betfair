# Cria atalho na área de trabalho para disparar atualização remota segura.
param(
    [string]$AppUrl = "",
    [string]$Secret = "",
    [string]$Comp = "WC"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$ConfigDir = Join-Path $env:USERPROFILE ".palpitaria"
$ConfigPath = Join-Path $ConfigDir "launcher.json"
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$Launcher = Join-Path $RepoRoot "scripts\palpitaria_atualizar.py"
$Desktop = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = Join-Path $Desktop "Palpitaria - Atualizar.lnk"

if (-not (Test-Path $Python)) {
    Write-Host "Python do venv não encontrado: $Python" -ForegroundColor Red
    exit 1
}

if (-not $AppUrl) {
    $AppUrl = Read-Host "URL do Cloud Run (ex: https://palpitaria-xxxxx.run.app)"
}
$AppUrl = $AppUrl.TrimEnd("/")

if (-not $Secret) {
    $bytes = New-Object byte[] 48
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $Secret = [Convert]::ToBase64String($bytes)
    Write-Host ""
    Write-Host "Secret gerado (copie para Cloud Run -> PIPELINE_TRIGGER_SECRET):" -ForegroundColor Yellow
    Write-Host $Secret
    Write-Host ""
}

New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
$config = @{
    app_url = $AppUrl
    secret  = $Secret
    comp    = $Comp
} | ConvertTo-Json
Set-Content -Path $ConfigPath -Value $config -Encoding UTF8

$WshShell = New-Object -ComObject WScript.Shell
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $Python
$Shortcut.Arguments = "`"$Launcher`""
$Shortcut.WorkingDirectory = $RepoRoot
$IconIco = Join-Path $RepoRoot "src\palpitaria\static\assets\launcher.ico"
$IconPng = Join-Path $RepoRoot "src\palpitaria\static\assets\logo.png"
$IconPath = if (Test-Path $IconIco) { $IconIco } else { $IconPng }
$Shortcut.IconLocation = "$IconPath,0"
$Shortcut.Description = "Dispara atualização diária segura no Palpitaria FC (Cloud Run)"
$Shortcut.Save()

Write-Host "Atalho criado: $ShortcutPath" -ForegroundColor Green
Write-Host "Config local: $ConfigPath"
Write-Host ""
Write-Host "No Google Cloud Run, adicione a variável:" -ForegroundColor Cyan
Write-Host "PIPELINE_TRIGGER_SECRET = (mesmo valor do secret acima)"
Write-Host "APP_URL = $AppUrl"
