$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$distros = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object DistributionName -eq 'Ubuntu')
if ($distros.Count -ne 1) { throw 'Cannot locate Ubuntu WSL.' }
$base = [string]$distros[0].BasePath
if ($base -notmatch '(?i)([A-Z]):[\\/]') { throw 'Cannot locate Ubuntu backing drive.' }
if ((Get-Volume -DriveLetter $Matches[1]).SizeRemaining -lt 2GB) { throw 'Need 2 GiB real Windows space on the Ubuntu backing drive.' }
if ((Get-Volume -DriveLetter G).SizeRemaining -lt 18GB) { throw 'Need 18 GiB free on G: for a separate V4 IMG.' }
$folder = [IO.Path]::GetFullPath($PSScriptRoot)
if ($folder -notmatch '^[A-Za-z]:[\\/]') { throw 'Extract this package to a local Windows drive.' }
$linuxFolder = '/mnt/' + $folder.Substring(0,1).ToLowerInvariant() + '/' + $folder.Substring(3).Replace('\','/')
Write-Host 'Updating the verified unbooted WORK copy and exporting a NEW V4 IMG.'
Write-Host 'Existing IMG files, SD cards and running posts are not changed.'
& wsl.exe -d Ubuntu -u root --exec python3 ($linuxFolder + '/Rebuild-Application-V4.py')
if ($LASTEXITCODE -ne 0) { throw 'V4 build stopped. Send the output. Do not flash a partial image or retry blindly.' }
Write-Host 'Finished. The NEW V4 IMG can be selected in balenaEtcher.'
