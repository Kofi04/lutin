<#
.SYNOPSIS
    Creates (or removes) the Little Wizard shortcuts.

.DESCRIPTION
    Puts a clickable icon on the Desktop and in the Start Menu, pointing at the
    GUI launcher that `pip install -e .` generated in the virtualenv. The
    shortcut carries the generated app.ico, so it shows the avatar rather than
    a generic Python icon.

    A .lnk can only be written through the Windows shell COM object, which is
    why this is a PowerShell script rather than part of the Python package.

.PARAMETER Remove
    Delete the shortcuts instead of creating them.

.PARAMETER DesktopOnly
    Skip the Start Menu entry.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\shortcut.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\shortcut.ps1 -Remove
#>

[CmdletBinding()]
param(
    [switch]$Remove,
    [switch]$DesktopOnly
)

$ErrorActionPreference = 'Stop'

$projectRoot = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $projectRoot '.venv\Scripts\wizard.exe'
$icon = Join-Path $projectRoot 'src\wizard\app.ico'

$shortcutName = 'LittleWizard.lnk'
$targets = @(Join-Path ([Environment]::GetFolderPath('Desktop')) $shortcutName)
if (-not $DesktopOnly) {
    $targets += Join-Path ([Environment]::GetFolderPath('Programs')) $shortcutName
}

if ($Remove) {
    foreach ($path in $targets) {
        if (Test-Path $path) {
            Remove-Item $path -Force
            Write-Host "removed  $path"
        }
        else {
            Write-Host "absent   $path"
        }
    }
    exit 0
}

if (-not (Test-Path $launcher)) {
    Write-Error @"
Launcher not found: $launcher

Create the virtualenv and install the package first:
    py -3.14 -m venv .venv
    .venv\Scripts\python.exe -m pip install -e ".[dev]"
"@
}

if (-not (Test-Path $icon)) {
    Write-Warning "Icon missing ($icon). Regenerate it with: .venv\Scripts\python.exe tools\make_icon.py"
    $icon = $null
}

$shell = New-Object -ComObject WScript.Shell
foreach ($path in $targets) {
    $parent = Split-Path -Parent $path
    if (-not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }

    $link = $shell.CreateShortcut($path)
    $link.TargetPath = $launcher
    $link.WorkingDirectory = $projectRoot
    $link.Description = 'Un petit compagnon de bureau posé sur votre barre des tâches'
    if ($icon) {
        # ",0" selects the first icon group in the file.
        $link.IconLocation = "$icon,0"
    }
    $link.Save()
    Write-Host "created  $path"
}

[System.Runtime.InteropServices.Marshal]::ReleaseComObject($shell) | Out-Null

Write-Host ''
Write-Host 'Double-click "Little Wizard" on the Desktop, or search for it in the Start Menu.'
Write-Host 'To pin it to the taskbar: right-click the Start Menu entry -> More -> Pin to taskbar.'
