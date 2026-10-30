<#
Escenario "casa" (ver app_obu/README.md, seccion "Escenario casa"): prueba
caminando con la tablet y GPS real. Levanta UNA RSU emulada (rsu_id 7, la
interseccion semaforizada de OSM que eligio generar_escenario_casa.py sobre
la ruta real) y el servidor central con registro_rsu_casa.json, cada uno en
su propia ventana de PowerShell.

Antes: generar registro_rsu_casa.json (una sola vez, desde la raiz del repo):

    python app_obu/pruebas/generar_escenario_casa.py --origen LAT,LON --destino LAT,LON

Correr DESDE E:\Tesis\ntcip_middleware (necesita servidor\main.py,
controller\controller_emulator.py y agent\rsu_middleware.py de ese
worktree -- es codigo identico al de esta rama app-obu, ver
app_obu/README.md):

    powershell -ExecutionPolicy Bypass -File E:\Tesis\ntcip_app\app_obu\pruebas\demo_casa.ps1

Para detener todo: detener_casa.ps1 (mismo directorio).

A diferencia de demo_hospital_nino.ps1, aqui la OBU es la tablet real: el
broker tiene que aceptar conexiones de fuera de la laptop (listener 1883
0.0.0.0 + regla de firewall, ver README "Probar en la tablet real"). Este
script lo comprueba y muestra las IP a poner en Ajustes de la app.

LIMITACION conocida (igual que demo_hospital_nino.ps1): solo detecta
procesos con RSU_ID 7 lanzados por ESTE script y choques de puerto; un
rsu_middleware.py con RSU_ID=7 lanzado a mano en otra terminal no se ve.
#>

$ErrorActionPreference = "Stop"

$RaizMiddleware = "E:\Tesis\ntcip_middleware"
$RegistroAbsoluto = "E:\Tesis\ntcip_app\app_obu\pruebas\registro_rsu_casa.json"
$DirPids = Join-Path $RaizMiddleware "resultados\casa"
$ArchivoPids = Join-Path $DirPids "pids.json"

Write-Host "=== Escenario casa: verificaciones previas ===" -ForegroundColor Cyan

if (-not (Test-Path (Join-Path $RaizMiddleware "servidor\main.py"))) {
    throw "No se encuentra servidor\main.py en $RaizMiddleware -- corre este script desde ese worktree (ver docstring)."
}
if (-not (Test-Path $RegistroAbsoluto)) {
    throw "No existe $RegistroAbsoluto -- genera primero el escenario con generar_escenario_casa.py (ver docstring)."
}
$registro = Get-Content $RegistroAbsoluto -Raw -Encoding utf8 | ConvertFrom-Json
$rsu = $registro.rsu[0]
$R = @{ id = [int]$rsu.rsu_id; interseccion = $rsu.interseccion_id; snmp = 1170 + [int]$rsu.rsu_id; ctrl = 9100 + [int]$rsu.rsu_id }
Write-Host "Registro: RSU $($R.id) en $($R.interseccion) ($($rsu.centro.lat), $($rsu.centro.lon))" -ForegroundColor Green

$mosq = Get-Service mosquitto -ErrorAction SilentlyContinue
if (-not $mosq -or $mosq.Status -ne "Running") {
    throw "Mosquitto no esta corriendo (Get-Service mosquitto). Arrancalo primero (docs/ARRANQUE_BROKER_LAPTOP.md, Paso 2)."
}
Write-Host "Mosquitto: Running" -ForegroundColor Green

# --- El broker escucha fuera de 127.0.0.1? (la tablet llega por LAN/Tailscale)
$escucha = Get-NetTCPConnection -LocalPort 1883 -State Listen -ErrorAction SilentlyContinue
if (-not ($escucha | Where-Object { $_.LocalAddress -in @("0.0.0.0", "::") })) {
    Write-Host "AVISO: Mosquitto solo escucha en $(($escucha.LocalAddress) -join ', ') -- la tablet NO podra conectarse." -ForegroundColor Yellow
    Write-Host "       Agrega 'listener 1883 0.0.0.0' + 'allow_anonymous true' a mosquitto.conf y reinicia el servicio." -ForegroundColor Yellow
}
$reglas = Get-NetFirewallRule -Direction Inbound -Enabled True -Action Allow -ErrorAction SilentlyContinue |
    Where-Object { ($_ | Get-NetFirewallPortFilter).LocalPort -contains "1883" }
if (-not $reglas) {
    Write-Host "AVISO: no hay regla de firewall de entrada para TCP 1883 -- ver README 'Probar en la tablet real'." -ForegroundColor Yellow
} else {
    Write-Host "Firewall 1883: $(($reglas.DisplayName) -join '; ')" -ForegroundColor Green
}

Write-Host "`nIP para 'Host del broker' en Ajustes de la app:" -ForegroundColor Cyan
Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    ForEach-Object {
        $tipo = if ($_.IPAddress -like "100.*") { "Tailscale (sirve fuera de casa, con el hotspot)" } else { "LAN (solo con la tablet en el Wi-Fi de casa)" }
        Write-Host "  $($_.IPAddress)  [$($_.InterfaceAlias)]  $tipo"
    }

# --- PID de una corrida anterior de ESTE script, todavia viva --------------
if (Test-Path $ArchivoPids) {
    $previos = Get-Content $ArchivoPids -Raw | ConvertFrom-Json
    $vivos = @($previos.pids | Where-Object { Get-Process -Id $_.pid -ErrorAction SilentlyContinue })
    if ($vivos.Count -gt 0) {
        $vivos | ForEach-Object { Write-Host "  PID $($_.pid) ($($_.rol)) sigue activo" -ForegroundColor Red }
        throw "Corre detener_casa.ps1 primero (mismo directorio) antes de volver a lanzar la demo."
    }
}

if (Get-NetUDPEndpoint -LocalPort $R.snmp -ErrorAction SilentlyContinue) {
    throw "Puerto SNMP $($R.snmp) ya en uso -- probablemente otro rsu_middleware.py con RSU_ID=$($R.id). Detenlo antes."
}
if (netstat -ano | Select-String ":$($R.ctrl)\s") {
    throw "Puerto de control $($R.ctrl) ya en uso -- probablemente otro controller_emulator.py con RSU_ID=$($R.id). Detenlo antes."
}
Write-Host "Puertos $($R.snmp) (SNMP) y $($R.ctrl) (control) libres." -ForegroundColor Green

New-Item -ItemType Directory -Force $DirPids | Out-Null
$pidsLanzados = @()

function Iniciar-Ventana($titulo, $comando) {
    Start-Process -FilePath "powershell.exe" `
        -ArgumentList "-NoExit", "-Command", "`$Host.UI.RawUI.WindowTitle = '$titulo'; $comando" `
        -WorkingDirectory $RaizMiddleware -PassThru
}

Write-Host "`n=== Levantando controlador + RSU $($R.id) ===" -ForegroundColor Cyan
$idr = $R.id
$cmdCtrl = "`$env:RSU_ID='$idr'; `$env:RSU_EVENTOS_DIR='resultados\casa\rsu$idr'; " +
           ".\.venv\Scripts\python.exe controller\controller_emulator.py --port $($R.ctrl)"
$pCtrl = Iniciar-Ventana "casa RSU $idr - controlador" $cmdCtrl
$pidsLanzados += @{ pid = $pCtrl.Id; rol = "controlador RSU $idr ($($R.interseccion))" }
Write-Host "  controlador en PID $($pCtrl.Id), puerto $($R.ctrl)"
Start-Sleep -Milliseconds 800

$cmdRsu = "`$env:RSU_ID='$idr'; `$env:RSU_EVENTOS_DIR='resultados\casa\rsu$idr'; " +
          "`$env:SNMP_PORT='$($R.snmp)'; `$env:CONTROLLER_PORT='$($R.ctrl)'; `$env:MQTT_BROKER_HOST='127.0.0.1'; " +
          ".\.venv\Scripts\python.exe agent\rsu_middleware.py"
$pRsu = Iniciar-Ventana "casa RSU $idr - middleware" $cmdRsu
$pidsLanzados += @{ pid = $pRsu.Id; rol = "middleware RSU $idr ($($R.interseccion))" }
Write-Host "  middleware en PID $($pRsu.Id), SNMP $($R.snmp)"
Start-Sleep -Milliseconds 800

Write-Host "`n=== Levantando servidor central ===" -ForegroundColor Cyan
$cmdSrv = "`$env:REGISTRO_RSU_PATH='$RegistroAbsoluto'; " +
          "Remove-Item Env:\RSU_ID,Env:\RSU_EVENTOS_DIR,Env:\SNMP_PORT,Env:\CONTROLLER_PORT -ErrorAction SilentlyContinue; " +
          ".\.venv\Scripts\python.exe servidor\main.py"
$pSrv = Iniciar-Ventana "casa - servidor central" $cmdSrv
$pidsLanzados += @{ pid = $pSrv.Id; rol = "servidor central" }
Write-Host "  servidor central en PID $($pSrv.Id)"

@{ pids = $pidsLanzados } | ConvertTo-Json | Set-Content -Encoding utf8 $ArchivoPids

Write-Host "`n=== Listo ===" -ForegroundColor Green
Write-Host "3 ventanas (controlador, middleware, servidor). PID guardados en $ArchivoPids."
Write-Host "En la tablet: selector 'GPS real', esperar 'GNSS listo', tocar el destino, 'Iniciar emergencia'."
Write-Host "Ensayo previo sin salir: selector 'Ruta emulada' con trayectoria_casa.csv (copiada a la tablet)."
Write-Host "Para detener todo: powershell -ExecutionPolicy Bypass -File E:\Tesis\ntcip_app\app_obu\pruebas\detener_casa.ps1"
