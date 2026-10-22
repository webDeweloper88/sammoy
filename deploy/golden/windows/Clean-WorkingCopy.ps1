$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$distros = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object DistributionName -eq 'Ubuntu')
if ($distros.Count -ne 1) { throw 'Cannot locate Ubuntu WSL distribution.' }
$base = [string]$distros[0].BasePath
if ($base -notmatch '(?i)([A-Z]):\\') { throw 'Cannot locate Ubuntu backing drive.' }
$backing = Get-Volume -DriveLetter $Matches[1]
if ($backing.SizeRemaining -lt 6GB) { throw 'Need at least 6 GiB free on the Windows drive holding Ubuntu.' }
$folder = [IO.Path]::GetFullPath($PSScriptRoot)
if ($folder -notmatch '^[A-Za-z]:[\\/]') { throw 'Extract to a local Windows drive.' }
$linuxFolder = '/mnt/' + $folder.Substring(0,1).ToLowerInvariant() + '/' + $folder.Substring(3).Replace('\','/')
& wsl.exe -d Ubuntu -u root --exec test -f ($linuxFolder + '/release.json')
if ($LASTEXITCODE -ne 0) { throw 'Release not found. Extract the complete package first.' }
Write-Host 'Only the separate WORK image will be cleaned. Original image and all SD cards stay untouched.'
& wsl.exe -d Ubuntu -u root --exec python3 ($linuxFolder + '/Clean-WorkingCopy.py') --release $linuxFolder
if ($LASTEXITCODE -ne 0) { throw 'Cleaning stopped. Do not retry or boot this copy; send the error text.' }
