[CmdletBinding()]
param([string]$SourceImage = 'G:\001_sammoy\LABRIX-SOURCE-POST2-20261021-121320.img')
$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
if (-not (Test-Path -LiteralPath $SourceImage -PathType Leaf)) { throw 'Original image not found.' }
$source=Get-Item -LiteralPath $SourceImage
if ($source.Length -ne 63864569856) { throw 'Original image size mismatch.' }
if (-not (Test-Path -LiteralPath "$SourceImage.sha256")) { throw 'SHA-256 sidecar missing.' }
$distros=@(Get-ChildItem 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Lxss' | ForEach-Object { Get-ItemProperty $_.PSPath } | Where-Object DistributionName -eq 'Ubuntu')
if ($distros.Count -ne 1) { throw 'Cannot locate the installed Ubuntu distribution.' }
$base=[string]$distros[0].BasePath
if ($base -notmatch '(?i)([A-Z]):\\') { throw 'Cannot determine the physical drive holding Ubuntu. Report this result.' }
$backingLetter=$Matches[1]
$backing=Get-Volume -DriveLetter $backingLetter
Write-Host "Ubuntu backing drive: ${backingLetter}:"
Write-Host ('Free: {0:N2} GiB; checking measured sparse data plus build reserve in Ubuntu.' -f ($backing.SizeRemaining/1GB))
if ($backing.SizeRemaining -lt 24GB) { throw 'Need at least 24 GiB build reserve before inspecting the source.' }
# Use known /mnt/<drive> mounts and direct exec. Legacy wsl.exe command
# forwarding stripped backslashes from Windows paths passed to wslpath.
function Convert-LabrixWslPath([string]$WindowsPath) {
    $full=[IO.Path]::GetFullPath($WindowsPath)
    if ($full -notmatch '^[A-Za-z]:[\\/]') { throw 'Use a local Windows drive path.' }
    $drive=$full.Substring(0,1).ToLowerInvariant()
    $tail=$full.Substring(3).Replace('\','/')
    return '/mnt/'+$drive+'/'+$tail
}
$script=Join-Path $PSScriptRoot 'Create-WorkingCopy.py'
$linuxScript=Convert-LabrixWslPath $script
$linuxSource=Convert-LabrixWslPath $source.FullName
& wsl.exe -d Ubuntu -u root --exec test -f $linuxScript
if ($LASTEXITCODE -ne 0) { throw 'Helper not found under /mnt/<drive>. Extract the whole ZIP or report the WSL mount configuration.' }
& wsl.exe -d Ubuntu -u root --exec test -r $linuxSource
if ($LASTEXITCODE -ne 0) { throw 'Original image is not readable in Ubuntu. No copy started.' }
Write-Host 'Checking source SHA-256, then creating a separate copy inside Ubuntu.'
Write-Host 'The original image on G: is opened read-only. No SD card is written.'
$linuxScript = $linuxScript.Trim()
$linuxSource = $linuxSource.Trim()
& wsl.exe -d Ubuntu -u root --exec python3 $linuxScript --source $linuxSource --backing-free-bytes ([long](Get-Volume -DriveLetter $backingLetter).SizeRemaining)
if ($LASTEXITCODE -ne 0) { throw 'Working-copy preparation did not finish. Original was not modified; send the error text.' }
