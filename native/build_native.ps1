param(
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$nativeDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$rootDir = Split-Path -Parent $nativeDir
$buildDir = Join-Path $rootDir "build\native"
$outDll = Join-Path $nativeDir "rip_core_native.dll"

function Find-CommandPath([string]$name) {
    $cmd = Get-Command $name -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $knownDirs = @(
        "C:\Program Files\LLVM\bin",
        "C:\Program Files\CMake\bin"
    )
    foreach ($dir in $knownDirs) {
        $candidate = Join-Path $dir $name
        if (Test-Path -LiteralPath $candidate) { return $candidate }
        $candidateExe = Join-Path $dir "$name.exe"
        if (Test-Path -LiteralPath $candidateExe) { return $candidateExe }
    }
    return $null
}

$cmake = Find-CommandPath "cmake"
if ($cmake) {
    New-Item -ItemType Directory -Force -Path $buildDir | Out-Null
    & $cmake -S $nativeDir -B $buildDir -DCMAKE_BUILD_TYPE=$Configuration
    & $cmake --build $buildDir --config $Configuration
    $candidate = Get-ChildItem -Path $buildDir -Recurse -Filter "rip_core_native.dll" | Select-Object -First 1
    if ($candidate) {
        Copy-Item -LiteralPath $candidate.FullName -Destination $outDll -Force
        Write-Host "Built $outDll"
        exit 0
    }
}

$cl = Find-CommandPath "cl"
if ($cl) {
    Push-Location $nativeDir
    try {
        & $cl /nologo /std:c++17 /O2 /LD rip_core_native.cpp /Fe:rip_core_native.dll
        Write-Host "Built $outDll"
        exit 0
    } finally {
        Pop-Location
    }
}

$clang = Find-CommandPath "clang++"
if ($clang) {
    & $clang -std=c++17 -O3 -shared "-DRIP_CORE_API=__declspec(dllexport)" (Join-Path $nativeDir "rip_core_native.cpp") -o $outDll
    Write-Host "Built $outDll"
    exit 0
}

$gpp = Find-CommandPath "g++"
if ($gpp) {
    & $gpp -std=c++17 -O3 -shared (Join-Path $nativeDir "rip_core_native.cpp") -o $outDll
    Write-Host "Built $outDll"
    exit 0
}

throw "No C++ compiler found. Install Visual Studio Build Tools, LLVM clang, or MinGW-w64, then rerun native\build_native.ps1."