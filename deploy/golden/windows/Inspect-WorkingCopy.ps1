$ErrorActionPreference='Stop'
Set-StrictMode -Version Latest
$script=[IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'Inspect-WorkingCopy.py'))
if ($script -notmatch '^[A-Za-z]:[\\/]') { throw 'Extract to a local Windows drive.' }
$linuxScript='/mnt/'+$script.Substring(0,1).ToLowerInvariant()+'/'+$script.Substring(3).Replace('\','/')
& wsl.exe -d Ubuntu -u root --exec test -f $linuxScript
if ($LASTEXITCODE -ne 0) { throw 'Cannot read inspection helper from Ubuntu.' }
& wsl.exe -d Ubuntu -u root --exec python3 $linuxScript
if ($LASTEXITCODE -ne 0) { throw 'Inspection did not complete. Do not clean or resize; send this error.' }
