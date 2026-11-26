<#
Builds the two EV3 programs and optionally uploads them to the brick.

  .\build.ps1                          build
  .\build.ps1 -Ev3Ip <brick address>         build + upload

Uses the leJOS libraries in lib\ (taken from the brick's SD image) unless -LejosHome
points elsewhere. Output: out\powershock-wifi.jar (DS4Receiver), out\powershock-bt.jar
(DS4Drive). On the brick they appear under Programs in the leJOS menu.
#>
param(
    [string]$LejosHome = $(if ($env:EV3_HOME) { $env:EV3_HOME } else { Join-Path $PSScriptRoot 'lib' }),
    [string]$Ev3Ip,
    [string]$Jdk
)
$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot

# One version for the whole app (see CHANGELOG.md); stamped into every jar.
$version = (Get-Content (Join-Path $root 'VERSION') -Raw).Trim()
if ($version -notmatch '^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?$') { throw "VERSION must look like 1.2.3, not '$version'" }

if (-not (Test-Path $LejosHome)) { throw "leJOS folder not found: $LejosHome" }
$ev3classes = Get-ChildItem $LejosHome -Recurse -Filter 'ev3classes.jar' | Select-Object -First 1
$jna = Get-ChildItem $LejosHome -Recurse -Filter 'jna*.jar' | Where-Object Name -notmatch 'platform' | Select-Object -First 1
if (-not $ev3classes) { throw "ev3classes.jar not found under $LejosHome" }
if (-not $jna) { throw "jna jar not found under $LejosHome" }

if (-not $Jdk) {
    if ($env:JAVA_HOME) { $Jdk = $env:JAVA_HOME }
    else {
        $found = Get-ChildItem "$env:USERPROFILE\.jdks" -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending | Select-Object -First 1
        if ($found) { $Jdk = $found.FullName }
    }
}
$javac = Join-Path $Jdk 'bin\javac.exe'
$jar = Join-Path $Jdk 'bin\jar.exe'
if (-not (Test-Path $javac)) { throw "javac not found; pass -Jdk <folder>" }

# The brick runs Java 7 (ejre 7u60). JDK 19 and older can target 7 directly. Newer JDKs
# compile against the brick's own Java 7 class library (lib/rt7.jar, so any Java 8+ API
# is a compile error) as Java 8 bytecode, then the class-file version is lowered to 7.
# That is safe because the code uses no Java 8 language features (no lambdas).
$rt7 = Join-Path $root 'lib/rt7.jar'
$ErrorActionPreference = 'Continue'
& $javac --release 7 -version 2>&1 | Out-Null
$direct7 = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = 'Stop'
if ($direct7) {
    $targetArgs = @('--release', '7')
} elseif (Test-Path $rt7) {
    $targetArgs = @('-source', '8', '-target', '8', '-bootclasspath', $rt7)
} else {
    throw "This JDK can't target Java 7 and lib/rt7.jar is missing. Use JDK 17 (-Jdk <folder>)."
}

$classes = Join-Path $root 'out\classes'
Remove-Item (Join-Path $root 'out') -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $classes | Out-Null

$sources = Get-ChildItem (Join-Path $root 'ev3\src') -Recurse -Filter *.java | ForEach-Object FullName
& $javac @targetArgs -proc:none -Xlint:-options -encoding UTF-8 -cp "$($ev3classes.FullName);$($jna.FullName)" -d $classes $sources
if ($LASTEXITCODE -ne 0) { throw "compile failed" }
if (-not $direct7) {
    Get-ChildItem $classes -Recurse -Filter *.class | ForEach-Object {
        $b = [IO.File]::ReadAllBytes($_.FullName)
        if ($b[7] -ne 52) { throw "unexpected class version in $($_.Name)" }
        $b[7] = 51
        [IO.File]::WriteAllBytes($_.FullName, $b)
    }
}

# The programs read their version from this file (Version.java) and report it to the console.
[IO.File]::WriteAllText((Join-Path $classes 'powershock/version.txt'), "$version`n")

# Paths of the libraries on the brick.
$brickCp = '/home/root/lejos/lib/ev3classes.jar /home/root/lejos/libjna/usr/share/java/jna.jar'
$jars = @{ 'powershock-wifi.jar' = 'powershock.DS4Receiver'; 'powershock-bt.jar' = 'powershock.DS4Drive'; 'powershock-ports.jar' = 'powershock.PortProbe' }
foreach ($name in $jars.Keys) {
    $manifest = Join-Path $root "out\$name.mf"
    "Main-Class: $($jars[$name])`r`nClass-Path: $brickCp`r`nImplementation-Title: PowerShock`r`nImplementation-Version: $version`r`n" | Out-File $manifest -Encoding ascii
    & $jar cfm (Join-Path $root "out\$name") $manifest -C $classes .
    if ($LASTEXITCODE -ne 0) { throw "jar failed for $name" }
    Write-Host "built out\$name $version (Java 7)"
}

if ($Ev3Ip) {
    # Upload over SSH with the same legacy settings the console uses (pc/ev3_brick.py):
    # leJOS's dropbear 0.51 needs old algorithms, and its scp is unreliable.
    & python (Join-Path $root 'pc/ev3_brick.py') upload $Ev3Ip
    if ($LASTEXITCODE -ne 0) { throw "upload failed" }
}
