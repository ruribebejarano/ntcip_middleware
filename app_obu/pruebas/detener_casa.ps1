<#
Detiene todos los procesos levantados por demo_casa.ps1 (lee
E:\Tesis\ntcip_middleware\resultados\casa\pids.json) -- la
RSU (controlador + middleware) y el servidor central, cada uno con sus
procesos hijos (python.exe dentro de la ventana de PowerShell que abrio
Start-Process).

Uso (desde cualquier carpeta):

    powershell -ExecutionPolicy Bypass -File E:\Tesis\ntcip_app\app_obu\pruebas\detener_casa.ps1
#>

$ArchivoPids = "E:\Tesis\ntcip_middleware\resultados\casa\pids.json"

if (-not (Test-Path $ArchivoPids)) {
    Write-Host "No hay $ArchivoPids -- no hay nada que detener (o ya se detuvo antes)." -ForegroundColor Yellow
    exit 0
}

$datos = Get-Content $ArchivoPids -Raw | ConvertFrom-Json
$detenidos = 0
foreach ($p in $datos.pids) {
    $procesoVentana = Get-Process -Id $p.pid -ErrorAction SilentlyContinue
    if (-not $procesoVentana) {
        Write-Host "PID $($p.pid) ($($p.rol)) ya no existe." -ForegroundColor DarkGray
        continue
    }
    # Procesos python.exe hijos de esta ventana de PowerShell (el intérprete
    # real corriendo controller_emulator.py / rsu_middleware.py / main.py).
    Get-CimInstance Win32_Process -Filter "ParentProcessId = $($p.pid)" -ErrorAction SilentlyContinue |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Stop-Process -Id $p.pid -Force -ErrorAction SilentlyContinue
    Write-Host "Detenido PID $($p.pid) ($($p.rol))" -ForegroundColor Green
    $detenidos++
}

Remove-Item $ArchivoPids -Force
Write-Host "`n$detenidos proceso(s) detenido(s). $ArchivoPids eliminado."
