param(
    [string]$GameDir = "E:\Games\NoSleepForKanameDate",
    [switch]$Restore,
    [string]$NuGetPackagesDir = "$env:USERPROFILE\.nuget\packages"
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectFile = Join-Path $scriptDir "NSFKD_KRINPUT.csproj"
$outDir = Join-Path $scriptDir "bin\Release\net6.0"
$dllPath = Join-Path $outDir "NSFKD_KRINPUT.dll"
$pdbPath = Join-Path $outDir "NSFKD_KRINPUT.pdb"
$keymapPath = Join-Path $scriptDir "NSFKD_KRINPUT_Keymap.json"
$spriteDir = Join-Path $scriptDir "NSFKD_KRINPUT_Sprite"
$modsDir = Join-Path $GameDir "Mods"
$modsSpriteDir = Join-Path $modsDir "NSFKD_KRINPUT_Sprite"

if (-not (Test-Path $projectFile)) {
    throw "Project file not found: $projectFile"
}

$dotnetHome = Join-Path $scriptDir ".dotnet-home"
New-Item -ItemType Directory -Force -Path $dotnetHome | Out-Null
$env:DOTNET_CLI_HOME = $dotnetHome
if (Test-Path $NuGetPackagesDir) {
    $env:NUGET_PACKAGES = $NuGetPackagesDir
}

if ($Restore.IsPresent) {
    & dotnet restore $projectFile --ignore-failed-sources -p:NuGetAudit=false
    if ($LASTEXITCODE -ne 0) {
        throw "dotnet restore failed with exit code $LASTEXITCODE"
    }
}

$buildArgs = @(
    "build", $projectFile,
    "-c", "Release",
    "-p:GameDir=$GameDir",
    "-p:NuGetAudit=false"
)

if (-not $Restore.IsPresent) {
    $buildArgs += "--no-restore"
}

& dotnet @buildArgs
if ($LASTEXITCODE -ne 0) {
    throw "dotnet build failed with exit code $LASTEXITCODE"
}

if (-not (Test-Path $dllPath)) {
    throw "Build output not found: $dllPath"
}

New-Item -ItemType Directory -Force -Path $modsDir | Out-Null
Copy-Item -Force $dllPath (Join-Path $modsDir "NSFKD_KRINPUT.dll")
if (Test-Path $pdbPath) {
    Copy-Item -Force $pdbPath (Join-Path $modsDir "NSFKD_KRINPUT.pdb")
}
if (Test-Path $keymapPath) {
    Copy-Item -Force $keymapPath (Join-Path $modsDir "NSFKD_KRINPUT_Keymap.json")
}
if (Test-Path $spriteDir) {
    if (Test-Path $modsSpriteDir) {
        Remove-Item -LiteralPath $modsSpriteDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $modsSpriteDir | Out-Null
    Get-ChildItem -LiteralPath $spriteDir -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $modsSpriteDir -Recurse -Force
    }
}

Write-Host "Build complete. Copied to: $modsDir"
if (-not $Restore.IsPresent) {
    Write-Host "Restore mode: cache-only (--no-restore)"
}
