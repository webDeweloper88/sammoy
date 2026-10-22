# Read-only preflight. Windows PowerShell 5.1 or PowerShell 7, Windows 11.
[CmdletBinding()]
param([string]$DestinationDirectory = 'G:\001_sammoy', [char]$TargetLetter = 'D')
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$drive = [IO.Path]::GetPathRoot($DestinationDirectory)
if ($drive -notmatch '^[A-Za-z]:\\$') { throw 'Use a local drive path such as G:\001_sammoy.' }
$destination = Get-Volume -DriveLetter $drive.Substring(0,1)
if ($destination.FileSystem -notin @('NTFS','exFAT')) { throw 'Destination must use NTFS or exFAT for a large image.' }
Write-Host "Destination: $DestinationDirectory"
Write-Host ('Free space: {0:N2} GiB; filesystem: {1}' -f ($destination.SizeRemaining / 1GB), $destination.FileSystem)
if ($destination.SizeRemaining -lt 66012053504) { throw 'Not enough space for the source card image plus 2 GiB.' }
Write-Host "`nPhysical disks (read-only listing):"
Get-Disk | Select-Object Number,FriendlyName,BusType,IsBoot,IsSystem,@{N='Bytes';E={$_.Size}},@{N='GiB';E={[math]::Round($_.Size/1GB,2)}} | Format-Table -AutoSize
Write-Host "Target card currently shown as ${TargetLetter}:"
$targetParts = @(Get-Partition -DriveLetter $TargetLetter -ErrorAction SilentlyContinue)
if ($targetParts.Count -eq 1) {
    $target = Get-Disk -Number $targetParts[0].DiskNumber
    $target | Select-Object Number,FriendlyName,BusType,Size | Format-List
    Write-Host 'This is the NEW card. Do not capture it as the source.'
} else { Write-Host 'Target letter not found or ambiguous; no changes made.' }
Write-Host "`nWSL status (optional for capture; needed later for Linux image work):"
if (Get-Command wsl.exe -ErrorAction SilentlyContinue) {
    & wsl.exe --list --verbose
    Write-Host 'The offline Linux preparation needs an installed WSL 2 distribution, not WSL 1.'
} else { Write-Host 'WSL is not installed. Capture can still be prepared; do not boot a raw clone yet.' }
Write-Host "`nNo disks, network settings or running posts were changed."
