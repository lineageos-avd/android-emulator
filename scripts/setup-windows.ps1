#requires -Version 7.0
<#
Install the VS 2022 17.4 toolset and ATL used with the pinned Google Clang 17 compiler.
Run before msvc-dev-cmd (toolset: 14.34). After source checkout, pass -Source
to verify the complete compiler/STL/linker combination with a native executable.
#>
[CmdletBinding()]
param(
    [string] $Source,
    [switch] $VerifyOnly
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
if (-not $IsWindows) { throw 'This setup requires Windows.' }

$toolsetFamily = '14.34'
$component = 'Microsoft.VisualStudio.Component.VC.14.34.17.4.x86.x64'
$atlComponent = 'Microsoft.VisualStudio.Component.VC.14.34.17.4.ATL'
$installerDirectory = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer'
$vswhere = Join-Path $installerDirectory 'vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere -PathType Leaf)) {
    throw 'Visual Studio Installer/vswhere is required; use the windows-2022 builder.'
}

$instances = @(& $vswhere -products '*' -version '[17.0,18.0)' -requires Microsoft.VisualStudio.Workload.NativeDesktop -latest -format json -utf8 | ConvertFrom-Json)
if ($LASTEXITCODE -ne 0 -or $instances.Count -ne 1) {
    throw 'Cannot locate a VS 2022 installation with the Native Desktop workload.'
}
$installation = [string] $instances[0].installationPath
$toolsRoot = Join-Path $installation 'VC\Tools\MSVC'
$vcvars = Join-Path $installation 'VC\Auxiliary\Build\vcvars64.bat'

function Find-PinnedToolset {
    if (Test-Path -LiteralPath $toolsRoot -PathType Container) {
        return Get-ChildItem -LiteralPath $toolsRoot -Directory |
            Where-Object { $_.Name.StartsWith("$toolsetFamily.") -and (Test-Path -LiteralPath (Join-Path $_.FullName 'bin\Hostx64\x64\cl.exe')) } |
            Sort-Object { [version] $_.Name } -Descending |
            Select-Object -First 1
    }
    return $null
}

function Test-PinnedAtl($candidate) {
    return $null -ne $candidate -and
        (Test-Path -LiteralPath (Join-Path $candidate.FullName 'atlmfc\include\atlbase.h')) -and
        (Test-Path -LiteralPath (Join-Path $candidate.FullName 'atlmfc\lib\x64\atls.lib'))
}

$toolset = Find-PinnedToolset
if ($null -eq $toolset -or -not (Test-PinnedAtl $toolset)) {
    if ($VerifyOnly) { throw "MSVC $toolsetFamily with matching ATL is missing; run setup-windows.ps1 first." }
    $installer = Join-Path $installerDirectory 'setup.exe'
    if (-not (Test-Path -LiteralPath $installer -PathType Leaf)) { throw 'Visual Studio Installer setup.exe is missing.' }
    Write-Host "Installing $component and $atlComponent into $installation"
    # Use the existing signed Microsoft installer. This adds the old toolset
    # side-by-side; it does not replace or downgrade the host Visual Studio IDE.
    $installerArguments = @('modify', '--installPath', "`"$installation`"", '--channelId', 'VisualStudio.17.Release', '--add', $component, '--add', $atlComponent, '--quiet', '--norestart', '--nocache')
    $process = Start-Process -FilePath $installer -ArgumentList $installerArguments -WorkingDirectory $env:TEMP -Wait -PassThru
    if ($process.ExitCode -notin @(0, 3010)) {
        throw "Visual Studio component installation failed with exit code $($process.ExitCode); see dd_setup logs in $env:TEMP."
    }
    $toolset = Find-PinnedToolset
    if ($null -eq $toolset -or -not (Test-PinnedAtl $toolset)) { throw "Installer did not provide the required $toolsetFamily toolset and ATL libraries." }
}
if (-not (Test-Path -LiteralPath $vcvars -PathType Leaf)) { throw "Missing developer environment script: $vcvars" }

$env:EMULATOR_MSVC_TOOLSET = $toolsetFamily
$env:EMULATOR_MSVC_FULL_VERSION = $toolset.Name
if ($env:GITHUB_ENV) {
    "EMULATOR_MSVC_TOOLSET=$toolsetFamily" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
    "EMULATOR_MSVC_FULL_VERSION=$($toolset.Name)" | Out-File -FilePath $env:GITHUB_ENV -Encoding utf8 -Append
}
Write-Host "Pinned MSVC: $($toolset.FullName)"
Write-Host "Upstream vcvars selector: -vcvars_ver=$toolsetFamily"

if ($Source) {
    $sourceRoot = (Resolve-Path -LiteralPath $Source).Path
    $clang = Join-Path $sourceRoot 'prebuilts\clang\host\windows-x86\clang-r487747c\bin\clang-cl.exe'
    if (-not (Test-Path -LiteralPath $clang -PathType Leaf)) { throw "Pinned Clang compiler is missing: $clang" }
    $compilerVersion = (& $clang --version 2>&1 | Out-String).Trim()
    if ($LASTEXITCODE -ne 0 -or $compilerVersion -notmatch 'clang version 17\.0\.2') {
        throw "Unexpected compiler in the pinned toolchain: $compilerVersion"
    }
    $probeDirectory = Join-Path $env:TEMP ('emulator-stl-probe-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $probeDirectory | Out-Null
    $probeSource = Join-Path $probeDirectory 'probe.cpp'
    $probeExe = Join-Path $probeDirectory 'probe.exe'
    $probeBatch = Join-Path $probeDirectory 'probe.cmd'
    @'
#include <filesystem>
#include <atlbase.h>
#include <iostream>
#include <memory>
#include <string>
#include <vector>
int main() {
    ATL::CComPtr<IUnknown> unknown;
    std::vector<std::string> values = {"Google Clang", "MSVC 14.34"};
    auto count = std::make_unique<std::size_t>(values.size());
    std::filesystem::path path = std::filesystem::path("toolchain") / "probe";
    std::cout << values[0] << " + " << values[1] << ": C++17 STL/link/runtime OK; "
              << "_MSVC_STL_UPDATE=" << _MSVC_STL_UPDATE << "\n";
    return *count == 2 && path.filename() == "probe" && !unknown ? 0 : 1;
}
'@ | Set-Content -LiteralPath $probeSource -Encoding utf8
    @"
@echo off
call "$vcvars" -vcvars_ver=$toolsetFamily
if errorlevel 1 exit /b 1
echo Effective MSVC: %VCToolsVersion%
"$clang" /nologo /std:c++17 /EHsc /MD "$probeSource" /Fe:"$probeExe"
if errorlevel 1 exit /b 1
"$probeExe"
exit /b %errorlevel%
"@ | Set-Content -LiteralPath $probeBatch -Encoding ascii
    Push-Location $probeDirectory
    try {
        & $env:ComSpec /d /c $probeBatch
        if ($LASTEXITCODE -ne 0) { throw "Pinned compiler/STL/linker probe failed with exit code $LASTEXITCODE." }
    } finally {
        Pop-Location
    }
    Write-Host $compilerVersion
}
