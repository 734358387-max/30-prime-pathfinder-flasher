[CmdletBinding()]
param()

$exePath = "c:\Users\29493\.gemini\antigravity\playground\prime-pathfinder\擎天柱30车厢编程软件v1.1.2\擎天柱30车厢编程软件v1.1.2\擎天柱30车厢编程软件v1.1.2.exe"

# Resolve path just in case
$exePath = Resolve-Path $exePath

# Load by bytes to bypass URI restrictions
$bytes = [System.IO.File]::ReadAllBytes($exePath)
$assembly = [System.Reflection.Assembly]::Load($bytes)

foreach ($type in $assembly.GetTypes()) {
    Write-Output "TYPE: $($type.FullName)"
    foreach ($method in $type.GetMethods([System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::NonPublic -bor [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::Static)) {
        if ($method.Name -match "USB|Connect|Hid|Match|ToUSB|Write|Report|Worker|Make|Translate") {
            Write-Output "  METHOD: $($method.Name)"
        }
    }
}
