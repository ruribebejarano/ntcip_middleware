<#
.SYNOPSIS
Detiene lo que levanto scripts/demo/lanzar_rsus.ps1 (controladores, RSU y,
si se lanzaron, servidor central y consola), con sus procesos hijos.

.DESCRIPTION
Por defecto lee resultados/demo/actual.json (la ultima corrida). Con
-Estado <ruta a estado.json> detiene una corrida concreta; con -Todas,
todas las corridas de resultados/demo/*/estado.json que tengan algo vivo.
Solo detiene PID registrados por el lanzador: nunca procesos lanzados a mano.

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\demo\detener_rsus.ps1
#>

param(
    [string]$Estado = "",
    [switch]$Todas,
    [switch]$SinConsola     # deja la consola abierta (para revisar la linea de tiempo)
)

$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$DirDemo = Join-Path $Raiz "resultados\demo"
$Actual = Join-Path $DirDemo "actual.json"

function Detener-Arbol([int]$id, [string]$rol) {
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    if (-not $p) { Write-Host "  PID $id ($rol) ya no existe." -ForegroundColor DarkGray; return }
    # El python.exe de un venv es un lanzador: el interprete real es su hijo.
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $id" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
    Write-Host "  Detenido PID $id ($rol)" -ForegroundColor Green
}

$archivos = @()
if ($Todas) {
    if (Test-Path $DirDemo) {
        $archivos = @(Get-ChildItem $DirDemo -Directory | ForEach-Object { Join-Path $_.FullName "estado.json" } | Where-Object { Test-Path $_ })
    }
} elseif ($Estado) {
    $archivos = @((Resolve-Path $Estado).Path)
} elseif (Test-Path $Actual) {
    $archivos = @($Actual)
}
if ($archivos.Count -eq 0) {
    Write-Host "No hay corridas del lanzador que detener." -ForegroundColor Yellow
    exit 0
}

foreach ($f in $archivos) {
    $e = [System.IO.File]::ReadAllText($f) | ConvertFrom-Json
    Write-Host "=== $($e.dir) ===" -ForegroundColor Cyan
    if ($e.consola -and -not $SinConsola) { Detener-Arbol $e.consola.pid "consola" }
    if ($e.servidor) { Detener-Arbol $e.servidor.pid "servidor central" }
    foreach ($r in @($e.rsu)) {
        Detener-Arbol $r.pid_middleware "middleware RSU $($r.rsu_id)"
        Detener-Arbol $r.pid_controlador "controlador RSU $($r.rsu_id)"
    }
}
Write-Host "Listo. Los logs quedan en resultados\demo\<fecha>\."
