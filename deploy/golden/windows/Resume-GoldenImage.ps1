$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$original = 'G:\001_sammoy\LABRIX-New-Radxa\release.json'
if (-not (Test-Path -LiteralPath $original)) { throw 'Keep the original LABRIX-New-Radxa folder in G:\001_sammoy.' }
$distros = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object DistributionName -eq 'Ubuntu')
if ($distros.Count -ne 1) { throw 'Cannot locate Ubuntu.' }
$base = [string]$distros[0].BasePath
if ($base -notmatch '(?i)([A-Z]):\\') { throw 'Cannot locate Ubuntu backing drive.' }
if ((Get-Volume -DriveLetter $Matches[1]).SizeRemaining -lt 2GB) { throw 'Need 2 GiB real Windows free space on the Ubuntu backing drive. No image changed.' }
if ((Get-Volume -DriveLetter G).SizeRemaining -lt 18GB) { throw 'Need 18 GiB free on G: for the finished image.' }
$folder = [IO.Path]::GetFullPath($PSScriptRoot)
if ($folder -notmatch '^[A-Za-z]:[\\/]') { throw 'Extract the full recovery ZIP to a local drive.' }
$linuxFolder = '/mnt/' + $folder.Substring(0,1).ToLowerInvariant() + '/' + $folder.Substring(3).Replace('\','/')
Write-Host 'Continuing the interrupted image build. No SD card is read or written.'
& wsl.exe -d Ubuntu -u root --exec python3 ($linuxFolder + '/Resume-GoldenImage.py') --release /mnt/g/001_sammoy/LABRIX-New-Radxa --output /mnt/g/001_sammoy/LABRIX-CUBIE-A7A-GOLDEN-20261021.img
if ($LASTEXITCODE -ne 0) { throw 'Recovery stopped. Send this output; do not write an incomplete image.' }
Write-Host 'Finished. Use the saved .img in balenaEtcher. This script does not write any card.'
