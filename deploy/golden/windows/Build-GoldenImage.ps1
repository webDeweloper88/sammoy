param([string]$OutputImage = '/mnt/g/001_sammoy/LABRIX-CUBIE-A7A-GOLDEN-V2-20261021.img')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$distros = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object DistributionName -eq 'Ubuntu')
if ($distros.Count -ne 1) { throw 'Cannot locate Ubuntu.' }
$base = [string]$distros[0].BasePath
if ($base -notmatch '(?i)([A-Z]):\\') { throw 'Cannot locate Ubuntu backing drive.' }
if ((Get-Volume -DriveLetter $Matches[1]).SizeRemaining -lt 24GB) { throw 'Need 24 GiB free on the Windows drive holding Ubuntu for safe image finalization.' }
if ((Get-Volume -DriveLetter G).SizeRemaining -lt 18GB) { throw 'Need 18 GiB free on G: for the finished image.' }
$folder = [IO.Path]::GetFullPath($PSScriptRoot)
if ($folder -notmatch '^[A-Za-z]:[\\/]') { throw 'Extract to a local Windows drive.' }
$linuxFolder = '/mnt/' + $folder.Substring(0,1).ToLowerInvariant() + '/' + $folder.Substring(3).Replace('\','/')
Write-Host 'Building a READY-TO-FLASH .img from the separate verified working copy.'
Write-Host 'Original image and running posts are not changed. No SD card is written by this step.'
& wsl.exe -d Ubuntu -u root --exec python3 ($linuxFolder + '/Build-GoldenImage.py') --release $linuxFolder --output $OutputImage
if ($LASTEXITCODE -ne 0) { throw 'Image build stopped. Do not write a partial image; send the error text.' }
Write-Host 'Finished. Open the saved .img in balenaEtcher and select the NEW card. This script does not write a card.'
