"""scripts/analisis/consumo_datos.py: contadores de usb0 desde el texto de
'scripts/pi.sh red estado' (formato real de una corrida pi-lan)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "analisis"))
from consumo_datos import consumo_corrida, contadores_usb0  # noqa: E402


def _estado(rx: int, tx: int) -> str:
    return (
        "=== tailscale status ===\n"
        "100.121.77.97  laptopricardoub  x  windows  active; direct 1.2.3.4:41641, tx 50388 rx 38596\n\n"
        "=== contadores usb0 ===\n"
        "7: usb0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc fq_codel state UNKNOWN\n"
        "    link/ether 22:89:84:6a:96:ab brd ff:ff:ff:ff:ff:ff\n"
        "    RX:  bytes packets errors dropped  missed   mcast           \n"
        f"        {rx}    1337      2       0       0       0 \n"
        "    TX:  bytes packets errors dropped carrier collsns           \n"
        f"        {tx}     657      0       0       0       0 \n"
    )


def test_lee_rx_tx_de_usb0_y_no_los_de_tailscale():
    assert contadores_usb0(_estado(195447, 108124)) == (195447, 108124)


def test_sin_seccion_usb0_devuelve_none():
    assert contadores_usb0("=== contadores usb0 ===\n(usb0 no existe)\n") is None
    assert contadores_usb0(None) is None


def test_consumo_es_la_diferencia_fin_menos_inicio():
    cfg = {"config": "pi-4g", "estado_red_inicio": _estado(1_000_000, 500_000),
           "estado_red_fin": _estado(3_000_000, 1_500_000),
           "chrony_sincronizado_por_repeticion": {"rep_01": True, "rep_02": True}}
    res = consumo_corrida(cfg)
    assert res["estado"] == "ok"
    assert res["total_bytes"] == 3_000_000
    assert res["total_mb"] == 3.0
    assert res["mb_por_repeticion"] == 1.5


def test_contador_reiniciado_no_se_reporta_como_consumo():
    cfg = {"estado_red_inicio": _estado(5_000_000, 5_000_000), "estado_red_fin": _estado(10, 10)}
    assert "reiniciado" in consumo_corrida(cfg)["estado"]
