<#
.SYNOPSIS
Un solo punto de entrada para la presentacion: verificar el banco, levantar
la demo, lanzar la OBU emulada y detener todo.

.DESCRIPTION
No reemplaza a ningun script: llama a scripts\demo\lanzar_rsus.ps1 y a
scripts\demo\detener_rsus.ps1 con los parametros del escenario elegido, y
antes revisa que este todo lo necesario. Ver docs\GUIA_COMANDOS.md.

Acciones:
  verificar   Revisa el banco y dice que falta. No levanta nada.
  iniciar     verificar + 1 controlador y 1 RSU por interseccion del
              escenario + servidor central + consola web (navegador).
  obu         Lanza la OBU emulada con la trayectoria del escenario.
  detener     Detiene todo lo que levanto "iniciar".

Escenarios (registro de RSU + trayectoria, en app_obu\pruebas\):
  hospital_nino   3 RSU (4, 5, 6) sobre la ruta PUCP -> Hospital del Nino  [por defecto]
  pucp            1 RSU (3), recorrido corto dentro del campus

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 verificar
powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 iniciar
powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 obu -Factor 4
powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 detener
#>

param(
    [Parameter(Position = 0)]
    [ValidateSet("verificar", "iniciar", "obu", "detener")]
    [string]$Accion = "verificar",
    [ValidateSet("hospital_nino", "pucp")]
    [string]$Escenario = "hospital_nino",
    [double]$Factor = 4,        # velocidad de la OBU emulada (1 = tiempo real)
    [switch]$ConPi,             # verificar tambien la Raspberry Pi (SSH alias "rsu")
    [switch]$ConTablet          # verificar tambien la tablet (adb)
)

# "Continue" a proposito: en Windows PowerShell 5, "Stop" convierte cualquier
# linea de stderr de ssh/adb/python en un error que corta el script. Los
# errores reales se cortan con throw.
$ErrorActionPreference = "Continue"
$Raiz = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Set-Location $Raiz
$Python = Join-Path $Raiz ".venv\Scripts\python.exe"
$Pruebas = Join-Path $Raiz "app_obu\pruebas"
$Registro = Join-Path $Pruebas "registro_rsu_$Escenario.json"
$Trayectoria = Join-Path $Pruebas "trayectoria_$Escenario.csv"

$script:fallas = 0
$script:avisos = 0
function Ok($msg)    { Write-Host "  [OK]    $msg" -ForegroundColor Green }
function Falla($msg, $solucion) {
    Write-Host "  [FALLA] $msg" -ForegroundColor Red
    Write-Host "          Que hacer: $solucion" -ForegroundColor Yellow
    $script:fallas++
}
function Aviso($msg, $solucion) {
    Write-Host "  [AVISO] $msg" -ForegroundColor Yellow
    Write-Host "          $solucion" -ForegroundColor DarkYellow
    $script:avisos++
}

function Verificar {
    Write-Host "`n=== Verificando el banco (escenario: $Escenario) ===" -ForegroundColor Cyan

    # 1. Entorno de Python
    if (Test-Path $Python) { Ok "Entorno virtual: .venv" }
    else { Falla "No existe .venv\Scripts\python.exe" "Instalar una vez (GUIA_COMANDOS.md, seccion 3.1)." ; return }

    $mods = & $Python -c "import importlib.util as u; print(','.join(m for m in ['paho','pysnmp','networkx','fastapi','uvicorn'] if u.find_spec(m) is None))" 2>$null
    if ([string]::IsNullOrWhiteSpace($mods)) { Ok "Librerias de Python instaladas" }
    else { Falla "Faltan librerias: $mods" ".venv\Scripts\python.exe -m pip install -r requirements.txt -r centro_control\requirements.txt" }

    # 2. Broker MQTT
    $mosq = Get-Service mosquitto -ErrorAction SilentlyContinue
    if (-not $mosq) { Falla "Mosquitto no esta instalado como servicio" "winget install EclipseFoundation.Mosquitto (docs\ARRANQUE_BROKER_LAPTOP.md, Paso 2)." }
    elseif ($mosq.Status -ne "Running") { Falla "Mosquitto esta detenido" "PowerShell como administrador: Start-Service mosquitto" }
    else {
        $escucha = Get-NetTCPConnection -LocalPort 1883 -State Listen -ErrorAction SilentlyContinue
        if ($escucha) { Ok "Mosquitto corriendo y escuchando en el puerto 1883" }
        else { Falla "Mosquitto corre pero no escucha en 1883" "Revisar mosquitto.conf (listener 1883 0.0.0.0) y Restart-Service mosquitto" }
    }

    # 3. Datos del escenario y del servidor
    if (Test-Path $Registro) { Ok "Registro de RSU: app_obu\pruebas\registro_rsu_$Escenario.json" }
    else { Falla "No se encuentra $Registro" "Revisar que app_obu\ este en esta copia del repositorio (git pull)." }
    if (Test-Path $Trayectoria) { Ok "Trayectoria: app_obu\pruebas\trayectoria_$Escenario.csv" }
    else { Falla "No se encuentra $Trayectoria" "Revisar que app_obu\ este en esta copia del repositorio (git pull)." }
    if (Test-Path (Join-Path $Raiz "data\grafo_san_miguel_real.graphml")) { Ok "Grafo vial cacheado (data\)" }
    else { Falla "Falta data\grafo_san_miguel_real.graphml" "python scripts\datos\regenerar_grafo.py (requiere osmnx e internet)." }

    # 4. Una corrida anterior todavia viva
    $actual = Join-Path $Raiz "resultados\demo\actual.json"
    if (Test-Path $actual) {
        $est = Get-Content $actual -Raw | ConvertFrom-Json
        $vivos = @()
        $pids = @()
        foreach ($r in $est.rsu) { $pids += $r.pid_controlador; $pids += $r.pid_middleware }
        if ($est.servidor) { $pids += $est.servidor.pid }
        if ($est.consola) { $pids += $est.consola.pid }
        foreach ($p in $pids) { if ($p -and (Get-Process -Id $p -ErrorAction SilentlyContinue)) { $vivos += $p } }
        if ($vivos.Count -gt 0) { Aviso "Hay procesos de una demo anterior todavia activos (PID $($vivos -join ', '))" "Si vas a iniciar de nuevo: presentacion.ps1 detener" }
    }

    # 5. Opcionales
    $ts = Get-Command tailscale -ErrorAction SilentlyContinue
    if ($ts) { Ok "Tailscale instalado (necesario solo para la Pi o la tablet fuera de casa)" }
    else { Aviso "Tailscale no esta en el PATH" "Solo hace falta para la RSU real o la tablet por Tailscale." }

    if ($ConTablet) {
        $adb = Get-Command adb -ErrorAction SilentlyContinue
        if (-not $adb) { Falla "adb no esta en el PATH" "Instalar Android Platform Tools o usar el adb de Android Studio." }
        else {
            $dev = (& adb devices) | Select-String "\tdevice$"
            if ($dev) { Ok "Tablet conectada por adb" }
            else { Falla "adb no ve ninguna tablet" "Conectar por USB, aceptar 'Permitir depuracion USB' en la tablet y repetir." }
        }
    }

    if ($ConPi) {
        & ssh -o ConnectTimeout=5 -o BatchMode=yes rsu true 2>$null
        if ($LASTEXITCODE -ne 0) { Falla "La Raspberry Pi no responde por SSH (alias rsu)" "Encenderla, revisar 'tailscale status' y docs\CONEXION_RASPBERRY.md." }
        else {
            $ag = (& ssh rsu "systemctl is-active rsu-agent rsu-controller") -join " "
            if ($ag -match "^active active$") { Ok "Pi: rsu-agent y rsu-controller activos" }
            else { Falla "Pi: servicios no activos ($ag)" "bash: scripts/pi.sh start controller && scripts/pi.sh start agent" }
        }
    }

    Write-Host ""
    if ($script:fallas -eq 0) { Write-Host "Resultado: listo ($script:avisos aviso(s))." -ForegroundColor Green }
    else { Write-Host "Resultado: $script:fallas falla(s). Corregir antes de iniciar." -ForegroundColor Red }
}

switch ($Accion) {
    "verificar" { Verificar }

    "iniciar" {
        Verificar
        if ($script:fallas -gt 0) { throw "No se inicia la demo: hay fallas (ver arriba)." }
        Write-Host "`n=== Levantando controladores, RSU, servidor central y consola ===" -ForegroundColor Cyan
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "lanzar_rsus.ps1") -Registro $Registro -ConServidor -ConConsola
        if ($LASTEXITCODE -ne 0) { throw "lanzar_rsus.ps1 termino con error (ver mensaje arriba)." }
        Write-Host "`n=== Listo ===" -ForegroundColor Green
        Write-Host "La consola se abre en http://127.0.0.1:8080/ (pantalla 'Mision (varias RSU)')."
        Write-Host "Siguiente paso, elegir UNO:"
        Write-Host "  a) OBU emulada:  powershell -ExecutionPolicy Bypass -File scripts\demo\presentacion.ps1 obu -Escenario $Escenario"
        Write-Host "  b) Tablet:       app > Ruta emulada > escenario > Iniciar emergencia (GUIA_COMANDOS.md, seccion 6)"
    }

    "obu" {
        if (-not (Test-Path $Trayectoria)) { throw "No se encuentra $Trayectoria" }
        Write-Host "`n=== OBU emulada: escenario $Escenario, factor $Factor ===" -ForegroundColor Cyan
        Write-Host "Arma la mision (MI), envia la posicion a 1 Hz (MP) y la cierra al final (MF). Ctrl+C para cortar."
        & $Python gateway\obu_emulada.py --broker-host 127.0.0.1 --factor $Factor --trayectoria $Trayectoria
    }

    "detener" {
        Write-Host "`n=== Deteniendo la demo ===" -ForegroundColor Cyan
        & powershell -ExecutionPolicy Bypass -File (Join-Path $PSScriptRoot "detener_rsus.ps1")
    }
}
