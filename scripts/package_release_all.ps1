<#
.SYNOPSIS
Build both the Windows MSI and Linux installer from one Windows workstation.

.DESCRIPTION
Run from an x64 Visual Studio Developer PowerShell with Docker Desktop set to
Linux containers. The Windows build uses the host's MSVC, WiX, Python and
portable ImageMagick. The Linux build runs in an Ubuntu 22.04 container.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$ImageMagickDir,
    [string]$DockerImage = "ashton-smokeview-linux-builder:ubuntu-22.04"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "Run this script on Windows from an x64 Visual Studio Developer PowerShell."
}

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$ImageMagickDir = (Resolve-Path -LiteralPath $ImageMagickDir).Path
if (-not (Test-Path -LiteralPath (Join-Path $ImageMagickDir "magick.exe"))) {
    throw "-ImageMagickDir must name the extracted portable folder containing magick.exe: $ImageMagickDir"
}

$Docker = Get-Command docker.exe -ErrorAction SilentlyContinue
if (-not $Docker) {
    throw "Docker Desktop was not found. Install it, start it, and select Linux containers."
}
$DockerOS = (& $Docker.Source info --format '{{.OSType}}' 2>&1 | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "Docker Desktop is not running: $DockerOS"
}
if ($DockerOS -ne "linux") {
    throw "Docker Desktop is using Windows containers. Switch it to Linux containers."
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$Command failed with exit code $LASTEXITCODE."
    }
}

$WindowsScript = Join-Path $PSScriptRoot "package_release_windows.ps1"
Write-Host "Building Windows MSI..."
& $WindowsScript -ImageMagickDir $ImageMagickDir

$Dockerfile = Join-Path $PSScriptRoot "Dockerfile.release-linux"
Write-Host "Preparing Ubuntu 22.04 Linux builder..."
Invoke-NativeCommand -Command $Docker.Source -Arguments @(
    "build", "--platform", "linux/amd64", "--file", $Dockerfile,
    "--tag", $DockerImage, $PSScriptRoot
)

# The same checkout is visible at /src. Docker Desktop maps this Windows path
# into its Linux VM; Linux and Windows use separate CMake build directories.
$Mount = "type=bind,source=$RepoRoot,target=/src"
$LinuxCommand = @'
set -Eeuo pipefail
git config --global --add safe.directory /src
bash scripts/package_release_linux.sh --build-dir cbuild/release-linux --output-dir dist
floor=$(objdump -T cbuild/release-linux/smokeview | grep -oE 'GLIBC_[0-9]+(\.[0-9]+)+' | cut -d_ -f2 | sort -uV | tail -1)
echo "Linux glibc floor: $floor"
dpkg --compare-versions "$floor" le 2.35
'@
Write-Host "Building Linux installer in Ubuntu 22.04..."
Invoke-NativeCommand -Command $Docker.Source -Arguments @(
    "run", "--rm", "--platform", "linux/amd64", "--mount", $Mount,
    "--workdir", "/src", $DockerImage, "bash", "-lc", $LinuxCommand
)

$CMakeContents = Get-Content -LiteralPath (Join-Path $RepoRoot "CMakeLists.txt") -Raw
$UpstreamVersion = [regex]::Match($CMakeContents, 'project\(smv .*VERSION ([0-9]+\.[0-9]+\.[0-9]+)').Groups[1].Value
$ReleaseName = [regex]::Match($CMakeContents, 'set\(ASHTON_RELEASE\s+"([^"]+)"\)').Groups[1].Value
if (-not $UpstreamVersion -or -not $ReleaseName) {
    throw "Could not determine the release version from CMakeLists.txt."
}
$Version = "$UpstreamVersion-$ReleaseName"
$Dist = Join-Path $RepoRoot "dist"
$Artifacts = @(
    (Join-Path $Dist "ashton-smokeview-v$Version-windows-x64.msi"),
    (Join-Path $Dist "ashton-smokeview-v$Version-linux-x64.sh")
)
foreach ($Artifact in $Artifacts) {
    $Checksum = "$Artifact.sha256"
    if (-not (Test-Path -LiteralPath $Artifact) -or -not (Test-Path -LiteralPath $Checksum)) {
        throw "Release output or checksum is missing: $Artifact"
    }
    $Expected = ((Get-Content -LiteralPath $Checksum -Raw).Trim() -split '\s+')[0].ToLowerInvariant()
    $Actual = (Get-FileHash -LiteralPath $Artifact -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($Expected -ne $Actual) {
        throw "SHA-256 checksum does not match: $Artifact"
    }
    Write-Host "Built $Artifact"
    Write-Host "SHA-256 $Actual"
}
