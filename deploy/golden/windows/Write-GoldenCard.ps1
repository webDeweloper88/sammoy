$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
trap { Write-Host $_ -ForegroundColor Red; Read-Host 'Stopped. Send the error text; press Enter to close'; exit 1 }
$admin = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $admin.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Start-Process -FilePath 'powershell.exe' -Verb RunAs -Wait -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-File',('"' + $PSCommandPath + '"'))
    exit
}
$image = 'G:\001_sammoy\LABRIX-CUBIE-A7A-GOLDEN-20261021.img'
if (-not (Test-Path -LiteralPath $image -PathType Leaf)) { throw 'Finished image not found. Run 06-BUILD-IMAGE.cmd first.' }
$report = Get-Content -LiteralPath ($image + '.json') -Raw | ConvertFrom-Json
if ($report.state -ne 'GOLDEN_CANDIDATE_READY_TO_FLASH' -or -not $report.sanitized -or -not $report.shrunk -or -not $report.free_blocks_zeroed) { throw 'Image is not ready to flash.' }
$file = Get-Item -LiteralPath $image
if ($file.Length -ne $report.bytes -or $file.Length % 512 -ne 0) { throw 'Image size mismatch.' }
Write-Host 'Checking the complete image SHA-256 before selecting a card...'
$expected = (Get-FileHash -LiteralPath $image -Algorithm SHA256).Hash.ToLowerInvariant()
if ($expected -ne $report.sha256) { throw 'Image SHA-256 mismatch. No disk changed.' }
Get-Disk | Select-Object Number,FriendlyName,BusType,IsBoot,IsSystem,Size | Format-Table -AutoSize
Write-Host 'Insert only the NEW third-post microSD. All contents of the selected card will be replaced.'
$chosen = Read-Host 'Enter its physical disk Number (not a drive letter)'
[int]$number = 0
if (-not [int]::TryParse($chosen,[ref]$number)) { throw 'Invalid disk number; no disk changed.' }
$disk = Get-Disk -Number $number
if ($disk.IsBoot -or $disk.IsSystem -or [string]$disk.BusType -notin @('USB','SD','MMC') -or $disk.Size -lt $file.Length -or $disk.Size -lt 60000000000 -or $disk.Size -gt 70000000000) { throw 'Target must be the new removable 64-GB card. No disk changed.' }
$parts = @(Get-Partition -DiskNumber $number -ErrorAction SilentlyContinue)
if (@($parts | Where-Object { $_.Offset -eq 348127232 -and $_.Size -eq 63516425728 }).Count -gt 0) { throw 'This resembles the ORIGINAL post-2 source card. Refusing to erase it.' }
$disk | Select-Object Number,FriendlyName,SerialNumber,BusType,Size | Format-List
$confirmation = Read-Host ('Type WRITE NEW ' + $number + ' to erase ONLY this NEW card and write the golden image')
if ($confirmation -cne ('WRITE NEW ' + $number)) { throw 'Cancelled; no disk changed.' }
# Recheck the device immediately before the irreversible operation.
$again = Get-Disk -Number $number
if ($again.UniqueId -ne $disk.UniqueId -or $again.Size -ne $disk.Size -or $again.IsBoot -or $again.IsSystem) { throw 'Target changed; no disk changed.' }
if ($again.IsReadOnly) { throw 'Card is read-only. Unlock the adapter and retry.' }
Clear-Disk -Number $number -RemoveData -RemoveOEM -Confirm:$false
$raw = '\\.\PhysicalDrive' + $number
$source = $null; $target = $null
try {
    $source = [IO.File]::Open($image,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $target = [IO.File]::Open($raw,[IO.FileMode]::Open,[IO.FileAccess]::ReadWrite,[IO.FileShare]::ReadWrite)
    $buffer = New-Object byte[] (4MB)
    [long]$done = 0
    while (($count = $source.Read($buffer,0,$buffer.Length)) -gt 0) {
        $target.Write($buffer,0,$count); $done += $count
        Write-Progress -Activity 'Writing NEW third-post card' -Status ('{0:N2} / {1:N2} GiB' -f ($done/1GB),($file.Length/1GB)) -PercentComplete ([int](100*$done/$file.Length))
    }
    $target.Flush($true)
    Write-Progress -Activity 'Writing NEW third-post card' -Completed
} finally {
    if ($source) { $source.Dispose() }
    if ($target) { $target.Dispose() }
}
Write-Host 'Reading back and verifying EVERY written byte...'
$reader = $null; $hash = [Security.Cryptography.SHA256]::Create()
try {
    $reader = [IO.File]::Open($raw,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite)
    $buffer = New-Object byte[] (4MB)
    [long]$remaining = $file.Length
    while ($remaining -gt 0) {
        $count = $reader.Read($buffer,0,[int][Math]::Min($remaining,$buffer.Length))
        if ($count -eq 0) { throw 'Card read-back ended early.' }
        $null = $hash.TransformBlock($buffer,0,$count,$buffer,0)
        $remaining -= $count
        Write-Progress -Activity 'Verifying NEW card' -PercentComplete ([int](100*($file.Length-$remaining)/$file.Length))
    }
    $null = $hash.TransformFinalBlock((New-Object byte[] 0),0,0)
    $actual = [BitConverter]::ToString($hash.Hash).Replace('-','').ToLowerInvariant()
    if ($actual -ne $expected) { throw 'Card read-back SHA-256 mismatch. Do not boot; check card/reader.' }
} finally {
    if ($reader) { $reader.Dispose() }
    $hash.Dispose()
    Write-Progress -Activity 'Verifying NEW card' -Completed
}
Write-Host 'CARD VERIFIED. Eject safely, insert into the POWERED-OFF NEW Radxa, then power it on.'
Write-Host 'First boot loads offline images, opens /install and expands the filesystem to the card capacity.'
Write-Host 'If Windows asks to format a Linux partition, CANCEL. Keep the original post-2 card separate.'
Read-Host 'Press Enter to close'
