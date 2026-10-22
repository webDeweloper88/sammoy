$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$distros = @(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object DistributionName -eq 'Ubuntu')
if ($distros.Count -ne 1) { throw 'Cannot locate Ubuntu.' }
$base = [string]$distros[0].BasePath
if ($base -notmatch '(?i)([A-Z]):\\') { throw 'Cannot locate Ubuntu backing drive.' }
if ((Get-Volume -DriveLetter $Matches[1]).SizeRemaining -lt 2GB) { throw 'Need 2 GiB free on the Ubuntu backing drive.' }
if ((Get-Volume -DriveLetter G).SizeRemaining -lt 18GB) { throw 'Need 18 GiB free on G: for the separate new IMG.' }
$folder = [IO.Path]::GetFullPath($PSScriptRoot)
if ($folder -notmatch '^[A-Za-z]:[\\/]') { throw 'Extract to a local Windows drive.' }
$linuxFolder = '/mnt/' + $folder.Substring(0,1).ToLowerInvariant() + '/' + $folder.Substring(3).Replace('\','/')
Write-Host 'Revising only the uninitialized private V2 copy. Original and old IMG are preserved.'
Write-Host 'No SD card is read or written. Keep this window open until IMAGE READY TO FLASH.'
& wsl.exe -d Ubuntu -u root --exec python3 ($linuxFolder + '/Rebuild-Defaults.py')
if ($LASTEXITCODE -ne 0) { throw 'Rebuild stopped. Send the output; do not flash a partial image or retry blindly.' }
Write-Host 'Finished. Use the NEW V2-LABRIX IMG in balenaEtcher on the test card.'
