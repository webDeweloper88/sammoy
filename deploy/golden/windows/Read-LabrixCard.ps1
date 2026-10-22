# Capture an OFFLINE source SD card. Opens PhysicalDrive with FileAccess.Read only.
# This script never formats a card and contains no raw disk write operation.
#Requires -RunAsAdministrator
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][ValidateRange(0,255)][int]$SourceDiskNumber,
    [string]$DestinationDirectory = 'G:\001_sammoy'
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$reference = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'source-reference.json') -Raw | ConvertFrom-Json
$disk = Get-Disk -Number $SourceDiskNumber
if ($disk.IsBoot -or $disk.IsSystem) { throw 'Refusing the Windows system/boot disk.' }
if ($disk.BusType -notin @('USB','SD','MMC')) { throw 'Source must be a removable USB/SD/MMC card reader.' }
if ([long]$disk.Size -ne [long]$reference.disk_bytes) { throw 'Disk capacity does not match the SOURCE card on post 2. Check disk selection.' }
$parts = @(Get-Partition -DiskNumber $SourceDiskNumber | Sort-Object Offset)
if ($parts.Count -ne 3) { throw 'Source must have the three Radxa partitions. The blank NEW card is not a source.' }
for ($i=0; $i -lt 3; $i++) {
    if ([long]$parts[$i].Offset -ne [long]$reference.partitions[$i].offset_bytes -or [long]$parts[$i].Size -ne [long]$reference.partitions[$i].size_bytes) {
        throw 'Partition layout differs from the inspected post 2 source. Capture refused.'
    }
}
$root = [IO.Path]::GetPathRoot($DestinationDirectory)
if ($root -notmatch '^[A-Za-z]:\\$') { throw 'Destination must be a local drive path.' }
$letter = $root.Substring(0,1)
$destinationDisk = Get-Partition -DriveLetter $letter | Get-Disk
if ($destinationDisk.Number -eq $SourceDiskNumber) { throw 'Cannot store an image on its own source disk.' }
$volume = Get-Volume -DriveLetter $letter
if ($volume.FileSystem -notin @('NTFS','exFAT')) { throw 'Destination must be NTFS or exFAT.' }
if ($volume.SizeRemaining -lt ([long]$disk.Size + 2GB)) { throw 'Insufficient destination space.' }
$disk | Select-Object Number,FriendlyName,BusType,Size,SerialNumber | Format-List
Write-Host 'Source card must be removed from the POWERED-OFF second Radxa.'
Write-Host 'Keep the new third-post card separate. Do not format Linux partitions when Windows asks.'
$answer = Read-Host "Type READ SOURCE $SourceDiskNumber to capture this card"
if ($answer -cne "READ SOURCE $SourceDiskNumber") { throw 'Cancelled; no image written.' }
New-Item -ItemType Directory -Force -Path $DestinationDirectory | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$final = Join-Path $DestinationDirectory "LABRIX-SOURCE-POST2-$stamp.img"
$partial = "$final.partial"
if ((Test-Path -LiteralPath $final) -or (Test-Path -LiteralPath $partial)) { throw 'Destination exists; refusing overwrite.' }
$source = $null; $output = $null
try {
    $source = [IO.FileStream]::new("\\.\PhysicalDrive$SourceDiskNumber",[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
    $output = [IO.FileStream]::new($partial,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None,4194304)
    $buffer = New-Object byte[] 4194304
    [long]$copied=0
    $timer=[Diagnostics.Stopwatch]::StartNew(); [long]$nextReport=0
    while ($copied -lt [long]$disk.Size) {
        $wanted=[int][Math]::Min([long]$buffer.Length,([long]$disk.Size-$copied))
        $n=$source.Read($buffer,0,$wanted)
        if ($n -le 0) { throw "Source ended early at $copied bytes." }
        $output.Write($buffer,0,$n); $copied += $n
        if ($timer.ElapsedMilliseconds -ge $nextReport) {
            Write-Progress -Activity 'Reading source SD card (read-only)' -Status ('{0:N2} / {1:N2} GiB' -f ($copied/1GB),($disk.Size/1GB)) -PercentComplete ([int](100*$copied/$disk.Size))
            $nextReport=$timer.ElapsedMilliseconds+1000
        }
    }
    $output.Flush($true)
} finally {
    if ($null -ne $output) { $output.Dispose() }
    if ($null -ne $source) { $source.Dispose() }
    Write-Progress -Activity 'Reading source SD card (read-only)' -Completed
}
if ((Get-Item -LiteralPath $partial).Length -ne [long]$disk.Size) { throw 'Image size mismatch. Partial image is not usable.' }
Move-Item -LiteralPath $partial -Destination $final
Write-Host 'Calculating SHA-256 of the complete image...'
$hash=Get-FileHash -LiteralPath $final -Algorithm SHA256
[IO.File]::WriteAllText("$final.sha256",$hash.Hash.ToLowerInvariant()+'  '+[IO.Path]::GetFileName($final)+[Environment]::NewLine,[Text.Encoding]::ASCII)
@{format=1;state='PRIVATE_RAW_SOURCE_NOT_GOLDEN';bytes=[long]$disk.Size;sha256=$hash.Hash.ToLowerInvariant();captured_at=(Get-Date).ToString('o');source_post=2;source_disk_number=$SourceDiskNumber;source_model=$disk.FriendlyName} | ConvertTo-Json | Set-Content -LiteralPath "$final.json" -Encoding UTF8
Write-Host "Saved: $final"
Write-Host "SHA-256: $($hash.Hash)"
Write-Host 'This is the private ORIGINAL copy. It still contains source-post credentials and data.'
Write-Host 'Do not write it directly to post 3. The offline cleaning/shrinking step comes next.'
