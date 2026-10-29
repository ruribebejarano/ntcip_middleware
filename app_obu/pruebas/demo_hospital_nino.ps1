<#
Escenario "hospital_nino" (ver app_obu/README.md, seccion "Escenario
Hospital del Nino"): levanta 3 RSU emuladas (rsu_id 4, 5, 6 -- OSM-PUCP-07,
OSM-PUCP-03, OSM-PUCP-08, las unicas intersecciones de
osm/salida_osm/candidatas_pucp.csv que caen sobre la ruta real calculada
por servidor/rutas.py) y el servidor central con
registro_rsu_hospital_nino.json, cada una en su propia ventana de
PowerShell.

Correr DESDE E:\Tesis\ntcip_middleware (necesita servidor\main.py,
controller\controller_emulator.py y agent\rsu_middleware.py de ese
worktree -- es codigo identico al de esta rama app-obu, ver
app_obu/README.md):

    powershell -ExecutionPolicy Bypass -File E:\Tesis\ntcip_app\app_obu\pruebas\demo_hospital_nino.ps1

Para detener todo: detener_hospital_nino.ps1 (mismo directorio).

LIMITACION conocida: la comprobacion de "no hay otro rsu_middleware.py con
estos RSU_ID" solo detecta procesos lanzados por ESTE script (via el
archivo de PID de abajo) y choques de puerto SNMP/control -- no puede leer
las variables de entorno de un proceso de rsu_middleware.py lanzado por otra
sesion/terminal con estos mismos RSU_ID. Si se sabe que hay otra sesion con
RSU_ID 4, 5 o 6 corriendo fuera de este script, detenerla a mano antes.
#>

$ErrorActionPreference = "Stop"

$RaizMiddleware = "E:\Tesis\ntcip_middleware"
$RegistroAbsoluto = "E:\Tesis\ntcip_app\app_obu\pruebas\registro_rsu_hospital_nino.json"
$DirPids = Join-Path $RaizMiddleware "resultados\hospital_nino"
$ArchivoPids = Join-Path $DirPids "pids.json"

$RSUS = @(
    @{ id = 4; interseccion = "OSM-PUCP-07"; snmp = 1174; ctrl = 9104 },
    @{ id = 5; interseccion = "OSM-PUCP-03"; snmp = 1175; ctrl = 9105 },
    @{ id = 6; interseccion = "OSM-PUCP-08"; snmp = 1176; ctrl = 9106 }
)

Write-Host "=== Escenario hospital_nino: verificaciones previas ===" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $RaizMiddleware "servidor\main.py"))) {
    throw "No se encuentra servidor\main.py en $RaizMiddleware -- corre este script desde ese worktree (ver docstring)."
}

$mosq = Get-Service mosquitto -ErrorAction SilentlyContinue
if (-not $mosq -or $mosq.Status -ne "Running") {
    throw "Mosquitto no esta corriendo (Get-Service mosquitto). Arrancalo primero (docs/ARRANQUE_BROKER_LAPTOP.md, Paso 2)."
}
Write-Host "Mosquitto: Running" -ForegroundColor Green

# --- PID de una corrida anterior de ESTE script, todavia viva --------------
if (Test-Path $ArchivoPids) {
    $previos = Get-Content $ArchivoPids -Raw | ConvertFrom-Json
    $vivos = @()
    foreach ($p in $previos.pids) {
        if (Get-Process -Id $p.pid -ErrorAction SilentlyContinue) { $vivos += $p }
    }
    if ($vivos.Count -gt 0) {
        Write-Host "Ya hay procesos de una corrida anterior de este script todavia activos:" -ForegroundColor Red
        $vivos | ForEach-Object { Write-Host "  PID $($_.pid) ($($_.rol))" }
        throw "Corre detener_hospital_nino.ps1 primero (mismo directorio) antes de volver a lanzar la demo."
    }
}

# --- Puertos SNMP/control de este escenario, ya ocupados? ------------------
$ocupados = @()
foreach ($r in $RSUS) {
    $udp = Get-NetUDPEndpoint -LocalPort $r.snmp -ErrorAction SilentlyContinue
    if ($udp) { $ocupados += "RSU_ID=$($r.id): puerto SNMP $($r.snmp) ya esta en uso" }
    $tcp = netstat -ano | Select-String ":$($r.ctrl)\s"
    if ($tcp) { $ocupados += "RSU_ID=$($r.id): puerto de control $($r.ctrl) ya esta en uso" }
}
if ($ocupados.Count -gt 0) {
    $ocupados | ForEach-Object { Write-Host $_ -ForegroundColor Red }
    throw "Hay puertos de este escenario ya ocupados -- probablemente otro rsu_middleware.py/controller_emulator.py con alguno de estos RSU_ID (4, 5 o 6) ya esta corriendo en otra ventana/sesion. Detenlo a mano (ver limitacion en el docstring) antes de reintentar."
}
Write-Host "Puertos 1174-1176 (SNMP) y 9104-9106 (control) libres." -ForegroundColor Green

New-Item -ItemType Directory -Force $DirPids | Out-Null
$pidsLanzados = @()

function Iniciar-Ventana($titulo, $comando) {
    $p = Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = '$titulo'; $comando" `
        -WorkingDirectory $RaizMiddleware -PassThru
    return $p
}

Write-Host "`n=== Levantando controlador + RSU por cada interseccion ===" -ForegroundColor Cyan
foreach ($r in $RSUS) {
    $idr = $r.id
    $titCtrl = "hospital_nino RSU $idr - controlador"
    $cmdCtrl = "`$env:RSU_ID='$idr'; `$env:RSU_EVENTOS_DIR='resultados\hospital_nino\rsu$idr'; " +
               ".\.venv\Scripts\python.exe controller\controller_emulator.py --port $($r.ctrl)"
    $pCtrl = Iniciar-Ventana $titCtrl $cmdCtrl
    $pidsLanzados += @{ pid = $pCtrl.Id; rol = "controlador RSU $idr ($($r.interseccion))" }
    Write-Host "  RSU $idr ($($r.interseccion)): controlador en PID $($pCtrl.Id), puerto $($r.ctrl)"
    Start-Sleep -Milliseconds 800

    $titRsu = "hospital_nino RSU $idr - middleware"
    $cmdRsu = "`$env:RSU_ID='$idr'; `$env:RSU_EVENTOS_DIR='resultados\hospital_nino\rsu$idr'; " +
              "`$env:SNMP_PORT='$($r.snmp)'; `$env:CONTROLLER_PORT='$($r.ctrl)'; `$env:MQTT_BROKER_HOST='127.0.0.1'; " +
              ".\.venv\Scripts\python.exe agent\rsu_middleware.py"
    $pRsu = Iniciar-Ventana $titRsu $cmdRsu
    $pidsLanzados += @{ pid = $pRsu.Id; rol = "middleware RSU $idr ($($r.interseccion))" }
    Write-Host "  RSU $idr ($($r.interseccion)): middleware en PID $($pRsu.Id), SNMP $($r.snmp)"
    Start-Sleep -Milliseconds 800
}

Write-Host "`n=== Levantando servidor central ===" -ForegroundColor Cyan
$cmdSrv = "`$env:REGISTRO_RSU_PATH='$RegistroAbsoluto'; " +
          "Remove-Item Env:\RSU_ID,Env:\RSU_EVENTOS_DIR,Env:\SNMP_PORT,Env:\CONTROLLER_PORT -ErrorAction SilentlyContinue; " +
          ".\.venv\Scripts\python.exe servidor\main.py"
$pSrv = Iniciar-Ventana "hospital_nino - servidor central" $cmdSrv
$pidsLanzados += @{ pid = $pSrv.Id; rol = "servidor central" }
Write-Host "  servidor central en PID $($pSrv.Id)"

@{ pids = $pidsLanzados } | ConvertTo-Json | Set-Content -Encoding utf8 $ArchivoPids

Write-Host "`n=== Listo ===" -ForegroundColor Green
Write-Host "6 ventanas abiertas (3 RSU x 2 procesos) + 1 servidor. PID guardados en $ArchivoPids."
Write-Host "Para probar: gateway\obu_emulada.py --broker-host 127.0.0.1 --trayectoria `"E:\Tesis\ntcip_app\app_obu\pruebas\trayectoria_hospital_nino.csv`""
Write-Host "Para detener todo: powershell -ExecutionPolicy Bypass -File E:\Tesis\ntcip_app\app_obu\pruebas\detener_hospital_nino.ps1"
