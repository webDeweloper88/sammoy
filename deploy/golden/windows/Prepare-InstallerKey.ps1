$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
# Generate on the installer's PC. Only the public half enters the golden image.
$keygen = Get-Command ssh-keygen.exe -ErrorAction SilentlyContinue
if (-not $keygen) { throw 'Windows OpenSSH Client is missing. Install OpenSSH Client in Optional Features, then run again.' }
$keyDir = Join-Path $env:USERPROFILE '.ssh'
$key = Join-Path $keyDir 'labrix_installer_ed25519'
$public = $key + '.pub'
if ((Test-Path -LiteralPath $key) -xor (Test-Path -LiteralPath $public)) {
    throw 'An incomplete installer key already exists. Nothing overwritten; ask for help.'
}
if (-not (Test-Path -LiteralPath $key)) {
    New-Item -ItemType Directory -Path $keyDir -Force | Out-Null
    Write-Host 'Creating a NEW installer SSH key on this PC. Existing SSH keys are not changed.'
    Write-Host 'Choose a passphrase when asked, then repeat it. It will not be displayed.'
    & $keygen.Source -t ed25519 -f $key -C 'LABRIX-installer'
    if ($LASTEXITCODE -ne 0) { throw 'Key generation failed; do not send any private key.' }
}
if (-not ((Test-Path -LiteralPath $key -PathType Leaf) -and (Test-Path -LiteralPath $public -PathType Leaf))) {
    throw 'Key files are missing.'
}
$line = [IO.File]::ReadAllText($public).Trim()
if ($line -notmatch '^ssh-ed25519 [A-Za-z0-9+/]+={0,2}(?: [^\r\n]*)?$') {
    throw 'Unexpected public-key format. Nothing copied.'
}
& $keygen.Source -l -f $public
if ($LASTEXITCODE -ne 0) { throw 'Public-key validation failed.' }
Write-Host ''
Write-Host 'PUBLIC KEY - send only the following single line:'
Write-Host $line
Write-Host ''
Write-Host ('Private key stays on this PC: ' + $key)
Write-Host 'Never send the file without .pub or its contents. Keep the passphrase private.'
Write-Host 'No images, SD cards, posts or network settings were changed.'
