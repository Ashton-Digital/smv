<#
.SYNOPSIS
Build Smokeview and create a Windows MSI installer.

.DESCRIPTION
Requires Visual Studio 2022 with C++ build tools, CMake, WiX Toolset 3,
Python 3.10+ with PyInstaller, and a Windows ImageMagick directory.
#>
[CmdletBinding()]
param(
    [string]$Version,
    [string]$ConfigFile = "Build/for_bundle/smokeview.ini",
    [string]$BuildDir = "cbuild/release-windows",
    [string]$OutputDir = "dist",
    [string]$ImageMagickDir,
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if ($env:OS -ne "Windows_NT") {
    throw "This script must be run on Windows."
}

$RepoRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

function Get-RepoPath {
    param([Parameter(Mandatory = $true)][string]$Path)

    if ([IO.Path]::IsPathRooted($Path)) {
        return [IO.Path]::GetFullPath($Path)
    }
    return [IO.Path]::GetFullPath((Join-Path $RepoRoot $Path))
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

function Find-CMakeCommand {
    $Command = Get-Command cmake.exe -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }

    $Candidates = @()
    if ($env:ProgramFiles) {
        $Candidates += Join-Path $env:ProgramFiles "CMake/bin/cmake.exe"
    }

    $VsWhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio/Installer/vswhere.exe"
    if (Test-Path -LiteralPath $VsWhere) {
        $VsPath = & $VsWhere -latest -products * -property installationPath
        if ($VsPath) {
            $Candidates += Join-Path $VsPath "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"
        }
    }

    $Result = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($Result) { return $Result }

    throw "CMake was not found. Install the Visual Studio 'C++ CMake tools for Windows' component, then reopen PowerShell."
}

function Find-WixTool {
    param([Parameter(Mandatory = $true)][string]$Name)

    $Command = Get-Command "$Name.exe" -ErrorAction SilentlyContinue
    if ($Command) { return $Command.Source }

    $Candidates = @()
    if ($env:WIX) { $Candidates += Join-Path $env:WIX "bin/$Name.exe" }
    if (${env:ProgramFiles(x86)}) {
        $Candidates += Join-Path ${env:ProgramFiles(x86)} "WiX Toolset v3.11/bin/$Name.exe"
        $Candidates += Join-Path ${env:ProgramFiles(x86)} "WiX Toolset v3.14/bin/$Name.exe"
    }
    $Result = $Candidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
    if ($Result) { return $Result }

    throw "WiX Toolset 3 ($Name.exe) was not found. Install WiX Toolset 3 and add its bin directory to PATH."
}

$ConfigFile = Get-RepoPath $ConfigFile
$BuildDir = Get-RepoPath $BuildDir
$OutputDir = Get-RepoPath $OutputDir
if (-not $ImageMagickDir) {
    throw "Pass -ImageMagickDir PATH to the extracted official Windows portable Q16 x64 static build (the folder containing magick.exe)."
}
$ImageMagickDir = Get-RepoPath $ImageMagickDir
if (-not (Test-Path -LiteralPath (Join-Path $ImageMagickDir "magick.exe"))) {
    throw "ImageMagick directory does not contain magick.exe: $ImageMagickDir"
}

$PythonCommand = Get-Command py.exe -ErrorAction SilentlyContinue
$PythonPrefix = @("-3")
if (-not $PythonCommand) {
    $PythonCommand = Get-Command python.exe -ErrorAction SilentlyContinue
    $PythonPrefix = @()
}
if (-not $PythonCommand) {
    throw "Python 3.10 or newer is required on the build machine."
}
& $PythonCommand.Source @PythonPrefix -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)"
if ($LASTEXITCODE -ne 0) {
    throw "Python 3.10 or newer is required on the build machine."
}
& $PythonCommand.Source @PythonPrefix -c "import PySide6.QtWidgets"
if ($LASTEXITCODE -ne 0) {
    throw "PySide6 is required on the build machine. Install it with: py -3 -m pip install PySide6-Essentials"
}
$PythonVersion = (& $PythonCommand.Source @PythonPrefix -c "import sys; print(sys.version.split()[0])" | Out-String).Trim()
$PySideVersion = (& $PythonCommand.Source @PythonPrefix -c "import PySide6; print(PySide6.__version__)" | Out-String).Trim()
$PythonLicense = (& $PythonCommand.Source @PythonPrefix -c "import pathlib, sys; print(pathlib.Path(sys.base_prefix, 'LICENSE.txt'))" | Out-String).Trim()
if (-not (Test-Path -LiteralPath $PythonLicense)) {
    throw "Python's LICENSE.txt was not found beside the build interpreter: $PythonLicense"
}
$PyInstallerVersion = (& $PythonCommand.Source @PythonPrefix -m PyInstaller --version | Out-String).Trim()
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller is required on the build machine. Install it with: py -3 -m pip install pyinstaller"
}

. (Join-Path $PSScriptRoot "select_release_version.ps1")
$Version = Select-ReleaseVersion -RepoRoot $RepoRoot -Version $Version

$ObjectsFile = Join-Path $RepoRoot "Build/for_bundle/objects.svo"
$RootMarkerFile = Join-Path $RepoRoot "Build/for_bundle/.smokeview_bin"
$CaptureScript = Join-Path $RepoRoot "Utilities/Scripts/capture_result_slices.py"
$CaptureUiScript = Join-Path $RepoRoot "Utilities/Scripts/capture_slices_ui.pyw"
$CaptureUiCore = Join-Path $RepoRoot "Utilities/Scripts/capture_ui_core.py"
$PlaneScript = Join-Path $RepoRoot "Utilities/Scripts/smv_planes.py"
$CaptureLogo = Join-Path $RepoRoot "Utilities/Scripts/capture_logo.png"
$CaptureIcon = Join-Path $RepoRoot "Utilities/Scripts/capture_logo.ico"
$HelpFile = Join-Path $RepoRoot "Utilities/Scripts/smv_help_windows.txt"
$ColorbarsDir = Join-Path $RepoRoot "Build/for_bundle/colorbars"
$TexturesDir = Join-Path $RepoRoot "Build/for_bundle/textures"

foreach ($RequiredPath in @(
    $ConfigFile,
    $ObjectsFile,
    $RootMarkerFile,
    $CaptureScript,
    $CaptureUiScript,
    $CaptureUiCore,
    $PlaneScript,
    $CaptureLogo,
    $CaptureIcon,
    $HelpFile,
    $ColorbarsDir,
    $TexturesDir
)) {
    if (-not (Test-Path -LiteralPath $RequiredPath)) {
        throw "Required package input is missing: $RequiredPath"
    }
}

if (-not $SkipBuild) {
    $CMakeCommand = Find-CMakeCommand
}
$HeatCommand = Find-WixTool "heat"
$CandleCommand = Find-WixTool "candle"
$LightCommand = Find-WixTool "light"
if (-not $SkipBuild) {
    Invoke-NativeCommand -Command $CMakeCommand -Arguments @(
        "-S", $RepoRoot,
        "-B", $BuildDir,
        "-A", "x64",
        "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
        "-DBUILD_SHARED_LIBS=OFF",
        "-DVENDORED_UI_LIBS=ON",
        "-DVENDORED_LIBS=ON"
    )
    Invoke-NativeCommand -Command $CMakeCommand -Arguments @(
        "--build", $BuildDir,
        "--config", "Release",
        "--target", "smokeview",
        "--parallel"
    )
}

$BinaryCandidates = @(
    (Join-Path $BuildDir "Release/smokeview.exe"),
    (Join-Path $BuildDir "smokeview.exe")
)
$Binary = $BinaryCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $Binary) {
    throw "Release executable not found under $BuildDir."
}
$VersionOutput = (& $Binary "-version" 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0) {
    throw "Could not read the revision from the release executable."
}
$BinaryVersionMatch = [regex]::Match($VersionOutput, '(?m)^Revision\s*:\s*(\S+)\s*$')
if (-not $BinaryVersionMatch.Success) {
    throw "Could not read the revision from the release executable."
}
$BinaryVersion = $BinaryVersionMatch.Groups[1].Value
if ($BinaryVersion -ne $Version) {
    throw "Package version $Version does not match executable revision $BinaryVersion; rebuild after updating ASHTON_RELEASE in CMakeLists.txt."
}

$Architecture = "x64"
$PackageName = "ashton-smokeview-v$Version-windows-$Architecture"
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null

$StageRoot = Join-Path ([IO.Path]::GetTempPath()) ("smv-package-" + [guid]::NewGuid().ToString("N"))
$PackageDir = Join-Path $StageRoot $PackageName

try {
    New-Item -ItemType Directory -Force -Path $PackageDir | Out-Null
    $PyDist = Join-Path $StageRoot "python-dist"
    $PyWork = Join-Path $StageRoot "python-work"
    $PySpec = Join-Path $StageRoot "python-spec"
    foreach ($App in @(
        @{ Name = "capture_slices_ui"; Script = $CaptureUiScript; Mode = "--windowed" },
        @{ Name = "capture_result_slices"; Script = $CaptureScript; Mode = "--console" }
    )) {
        $PyArguments = $PythonPrefix + @(
            "-m", "PyInstaller", "--noconfirm", "--clean", "--onefile",
            $App.Mode, "--name", $App.Name, "--distpath", $PyDist,
            "--workpath", $PyWork, "--specpath", $PySpec
        )
        if ($App.Name -eq "capture_slices_ui") {
            $PyArguments += @("--icon", $CaptureIcon)
        }
        $PyArguments += $App.Script
        Invoke-NativeCommand -Command $PythonCommand.Source -Arguments $PyArguments
    }
    $UiBinary = Join-Path $PyDist "capture_slices_ui.exe"
    $CaptureBinary = Join-Path $PyDist "capture_result_slices.exe"
    foreach ($RequiredBinary in @($UiBinary, $CaptureBinary)) {
        if (-not (Test-Path -LiteralPath $RequiredBinary)) {
            throw "PyInstaller output is missing: $RequiredBinary"
        }
    }
    $UiSmoke = Start-Process -FilePath $UiBinary -ArgumentList "--smoke-test" -Wait -PassThru
    if ($UiSmoke.ExitCode -ne 0) {
        throw "Bundled capture window did not start (exit code $($UiSmoke.ExitCode))."
    }
    Copy-Item -LiteralPath $Binary -Destination (Join-Path $PackageDir "smokeview.exe")
    Copy-Item -LiteralPath $UiBinary -Destination (Join-Path $PackageDir "capture_slices_ui.exe")
    Copy-Item -LiteralPath $CaptureBinary -Destination (Join-Path $PackageDir "capture_result_slices.exe")
    Copy-Item -LiteralPath $PythonLicense -Destination (Join-Path $PackageDir "PYTHON-LICENSE.txt")
    Copy-Item -LiteralPath $ImageMagickDir -Destination (Join-Path $PackageDir "imagemagick") -Recurse
    $PackagedMagick = Join-Path $PackageDir "imagemagick/magick.exe"
    $MagickOutput = (& $PackagedMagick -version | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or -not $MagickOutput) {
        throw "Packaged ImageMagick did not run: $PackagedMagick"
    }
    $MagickVersion = ($MagickOutput -split '\r?\n')[0]
    @"
Python: $PythonVersion (embedded by PyInstaller $PyInstallerVersion)
PySide6: $PySideVersion
ImageMagick: $MagickVersion
ImageMagick executable SHA-256: $((Get-FileHash -LiteralPath $PackagedMagick -Algorithm SHA256).Hash.ToLowerInvariant())
"@ | Set-Content -LiteralPath (Join-Path $PackageDir "DEPENDENCIES.txt") -Encoding UTF8
    Copy-Item -LiteralPath $ConfigFile -Destination (Join-Path $PackageDir "smokeview.ini")
    Copy-Item -LiteralPath $RootMarkerFile -Destination (Join-Path $PackageDir ".smokeview_bin")
    Copy-Item -LiteralPath $CaptureScript -Destination (Join-Path $PackageDir "capture_result_slices.py")
    Copy-Item -LiteralPath $CaptureUiScript -Destination (Join-Path $PackageDir "capture_slices_ui.pyw")
    Copy-Item -LiteralPath $CaptureUiCore -Destination (Join-Path $PackageDir "capture_ui_core.py")
    Copy-Item -LiteralPath $PlaneScript -Destination (Join-Path $PackageDir "smv_planes.py")
    Copy-Item -LiteralPath $CaptureLogo -Destination (Join-Path $PackageDir "capture_logo.png")
    Copy-Item -LiteralPath $ObjectsFile -Destination (Join-Path $PackageDir "objects.svo")
    Copy-Item -LiteralPath $ColorbarsDir -Destination (Join-Path $PackageDir "colorbars") -Recurse
    Copy-Item -LiteralPath $TexturesDir -Destination (Join-Path $PackageDir "textures") -Recurse
    Copy-Item -LiteralPath $HelpFile -Destination (Join-Path $PackageDir "smvhelp.txt")

    @'
@echo off
setlocal

if "%~1"=="" (
    echo Usage: capture_result_slices.cmd C:\path\to\case.smv
    echo.
    echo You can also right-click an .smv file and select "Capture result slices".
    pause
    exit /b 2
)

set "CASE_FILE=%~f1"
if not exist "%CASE_FILE%" (
    echo Error: Smokeview case not found: %CASE_FILE%
    pause
    exit /b 2
)

"%~dp0capture_result_slices.exe" "%CASE_FILE%" --smokeview "%~dp0smokeview.exe" --overwrite

if errorlevel 1 (
    echo.
    echo Capture failed. Review the messages above.
    pause
    exit /b 1
)
endlocal
'@ | Set-Content -LiteralPath (Join-Path $PackageDir "capture_result_slices.cmd") -Encoding ASCII

    $Commit = (& git -C $RepoRoot rev-parse --short=12 HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { $Commit = "unknown" }
    $DirtyOutput = & git -C $RepoRoot status --porcelain --untracked-files=no
    $Dirty = if ($DirtyOutput) { "yes" } else { "no" }

    @"
Version: v$Version
Git commit: $Commit
Git working tree dirty: $Dirty
Build date: $([DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ"))
Platform: Windows $Architecture
Compiler/runtime: MSVC with static multithreaded runtime
"@ | Set-Content -LiteralPath (Join-Path $PackageDir "VERSION") -Encoding UTF8

    @"
Ashton Smokeview
================

Keep this directory together. Run Smokeview with an absolute path to a case:

  .\smokeview.exe C:\absolute\path\to\case.smv

The packaged smokeview.ini and objects.svo files are loaded from this directory.

Open Capture result slices from the Start menu to select one case or a folder,
choose slice types and times, and set an output location. The window and
capture engine include their Python runtime.
The window opens in dark mode. Use Advanced slice positions to scan cases and
capture only selected planes, such as Y=3 or Y=5.
Open Ashton Smokeview Help from the Start menu (or smvhelp.txt beside this
executable) for shortcuts and step-by-step capture instructions.

Capture every configured result-review slice with:

  .\capture_result_slices.cmd C:\absolute\path\to\case.smv

Alternatively, right-click an .smv file in File Explorer and select:

  Capture result slices

This opens the capture window with that case selected.

This starts a separate automated Smokeview process. An interactive Smokeview
window may remain open while capture runs.

The installed imagemagick folder supplies model cropping. The case's associated
slice and data files must remain beside the .smv file.

Contact the Ashton Digital internal support channel for help with this build.
"@ | Set-Content -LiteralPath (Join-Path $PackageDir "README.txt") -Encoding UTF8

    $InstallerPath = Join-Path $OutputDir "$PackageName.msi"
    $ChecksumPath = "$InstallerPath.sha256"
    if (Test-Path -LiteralPath $InstallerPath) {
        Remove-Item -LiteralPath $InstallerPath -Force
    }

    $WxsPath = Join-Path $StageRoot "installer.wxs"
    $HarvestPath = Join-Path $StageRoot "payload.wxs"
    $IconPath = Join-Path $RepoRoot "Build/for_bundle/icon.ico"
    $WxsTemplate = @'
<?xml version="1.0" encoding="UTF-8"?>
<Wix xmlns="http://schemas.microsoft.com/wix/2006/wi">
  <Product Id="*" Name="Ashton Smokeview @VERSION@" Language="1033"
           Version="@MSI_VERSION@" Manufacturer="Ashton Digital"
           UpgradeCode="1940D8A1-C842-442F-BF5D-00A570219BDB">
    <Package InstallerVersion="500" Compressed="yes" InstallScope="perMachine" InstallPrivileges="elevated" />
    <MajorUpgrade AllowSameVersionUpgrades="yes" DowngradeErrorMessage="A newer Ashton Smokeview is already installed." />
    <MediaTemplate EmbedCab="yes" />
    <Icon Id="SmokeviewIcon" SourceFile="@ICON@" />
    <Property Id="ARPPRODUCTICON" Value="SmokeviewIcon" />
    <Directory Id="TARGETDIR" Name="SourceDir">
      <Directory Id="ProgramFiles64Folder">
        <Directory Id="AshtonFolder" Name="Ashton Digital">
          <Directory Id="INSTALLDIR" Name="Smokeview" />
        </Directory>
      </Directory>
      <Directory Id="ProgramMenuFolder">
        <Directory Id="AshtonMenu" Name="Ashton Digital" />
      </Directory>
    </Directory>
    <DirectoryRef Id="INSTALLDIR">
      <Component Id="SmvAssociation" Guid="A7F23B24-5D06-48F4-A953-2611D789A743">
        <RegistryValue Root="HKLM" Key="Software\Classes\.smv" Type="string" Value="AshtonSmokeview.smv" KeyPath="yes" />
        <RegistryValue Root="HKLM" Key="Software\Classes\AshtonSmokeview.smv" Type="string" Value="Smokeview case" />
        <RegistryValue Root="HKLM" Key="Software\Classes\AshtonSmokeview.smv\DefaultIcon" Type="string" Value="[INSTALLDIR]smokeview.exe,0" />
        <RegistryValue Root="HKLM" Key="Software\Classes\AshtonSmokeview.smv\shell\open\command" Type="string" Value="&quot;[INSTALLDIR]smokeview.exe&quot; &quot;%1&quot;" />
        <RegistryValue Root="HKLM" Key="Software\Classes\AshtonSmokeview.smv\shell\capture" Type="string" Value="Capture result slices" />
        <RegistryValue Root="HKLM" Key="Software\Classes\AshtonSmokeview.smv\shell\capture" Name="Icon" Type="string" Value="[INSTALLDIR]smokeview.exe,0" />
        <RegistryValue Root="HKLM" Key="Software\Classes\AshtonSmokeview.smv\shell\capture\command" Type="string" Value="&quot;[INSTALLDIR]capture_slices_ui.exe&quot; &quot;%1&quot;" />
        <RemoveFolder Id="RemoveInstallDir" Directory="INSTALLDIR" On="uninstall" />
        <RemoveFolder Id="RemoveAshtonFolder" Directory="AshtonFolder" On="uninstall" />
      </Component>
    </DirectoryRef>
    <DirectoryRef Id="AshtonMenu">
      <Component Id="MenuShortcuts" Guid="7BA9925C-2052-4C4E-8B12-59149A43DE55">
        <Shortcut Id="CaptureUIShortcut" Name="Capture result slices" Target="[INSTALLDIR]capture_slices_ui.exe" />
        <Shortcut Id="SmokeviewHelpShortcut" Name="Ashton Smokeview Help" Target="[INSTALLDIR]smvhelp.txt" />
        <Shortcut Id="SmokeviewShortcut" Name="Ashton Smokeview" Target="[INSTALLDIR]smokeview.exe" WorkingDirectory="INSTALLDIR" />
        <RemoveFolder Id="RemoveAshtonMenu" On="uninstall" />
        <RegistryValue Root="HKCU" Key="Software\Ashton Digital\Smokeview" Name="MenuInstalled" Type="integer" Value="1" KeyPath="yes" />
      </Component>
    </DirectoryRef>
    <Feature Id="MainFeature" Title="Ashton Smokeview" Level="1">
      <ComponentGroupRef Id="PayloadFiles" />
      <ComponentRef Id="SmvAssociation" />
      <ComponentRef Id="MenuShortcuts" />
    </Feature>
  </Product>
</Wix>
'@
    $MsiVersion = [regex]::Match($Version, '^[0-9]+\.[0-9]+\.[0-9]+').Value
    if (-not $MsiVersion) { throw "MSI requires a numeric upstream version: $Version" }
    $WxsContents = $WxsTemplate.Replace("@VERSION@", $Version)
    $WxsContents = $WxsContents.Replace("@MSI_VERSION@", $MsiVersion)
    $WxsContents = $WxsContents.Replace("@ICON@", [System.Security.SecurityElement]::Escape($IconPath))
    $WxsContents | Set-Content -LiteralPath $WxsPath -Encoding UTF8

    Invoke-NativeCommand -Command $HeatCommand -Arguments @(
        "dir", $PackageDir, "-cg", "PayloadFiles", "-dr", "INSTALLDIR",
        "-srd", "-sreg", "-sfrag", "-gg", "-var", "var.PayloadDir",
        "-out", $HarvestPath
    )
    $HarvestContents = Get-Content -LiteralPath $HarvestPath -Raw
    foreach ($RequiredPayloadFile in @(
        "smokeview.exe", "smokeview.ini", "objects.svo", ".smokeview_bin",
        "capture_slices_ui.exe", "capture_slices_ui.pyw",
        "capture_ui_core.py",
        "capture_result_slices.exe", "capture_result_slices.py",
        "capture_result_slices.cmd", "smv_planes.py", "capture_logo.png",
        "smvhelp.txt", "magick.exe",
        "PYTHON-LICENSE.txt", "DEPENDENCIES.txt"
    )) {
        if ($HarvestContents -notmatch [regex]::Escape($RequiredPayloadFile)) {
            throw "WiX payload does not include $RequiredPayloadFile."
        }
    }
    Invoke-NativeCommand -Command $CandleCommand -Arguments @(
        "-arch", "x64", "-dPayloadDir=$PackageDir", "-out", (Join-Path $StageRoot "installer.wixobj"), $WxsPath
    )
    Invoke-NativeCommand -Command $CandleCommand -Arguments @(
        "-arch", "x64", "-dPayloadDir=$PackageDir", "-out", (Join-Path $StageRoot "payload.wixobj"), $HarvestPath
    )
    Invoke-NativeCommand -Command $LightCommand -Arguments @(
        "-out", $InstallerPath,
        (Join-Path $StageRoot "installer.wixobj"),
        (Join-Path $StageRoot "payload.wixobj")
    )

    $Hash = (Get-FileHash -LiteralPath $InstallerPath -Algorithm SHA256).Hash.ToLowerInvariant()
    "$Hash  $([IO.Path]::GetFileName($InstallerPath))" |
        Set-Content -LiteralPath $ChecksumPath -Encoding ASCII

    Write-Host "Created $InstallerPath"
    Write-Host "Created $ChecksumPath"
}
finally {
    if (Test-Path -LiteralPath $StageRoot) {
        Remove-Item -LiteralPath $StageRoot -Recurse -Force
    }
}
