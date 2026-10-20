"""Pruebas de consola/backend/registro_comandos.py: que cada registrar()
persista una linea JSON en resultados/consola/registro_comandos.jsonl
(nunca se sobrescribe), que listar() filtre por canal/texto, y que al
reiniciar el proceso se recarguen las entradas existentes del archivo."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from consola.backend.registro_comandos import RegistroComandos  # noqa: E402


def test_registrar_persiste_una_linea_jsonl(tmp_path):
    ruta = tmp_path / "registro_comandos.jsonl"
    r = RegistroComandos(ruta)
    r.registrar("Consola", "RSU 1 (rsu-01:1161)", "SNMPv3", {"accion": "WALK", "oid": "1.3.6.1.4.1.1206.4.2.1.1"},
               {"red": False, "green": True})

    lineas = ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 1
    entrada = json.loads(lineas[0])
    assert entrada["origen"] == "Consola"
    assert entrada["canal"] == "SNMPv3"
    assert entrada["resultado"]["green"] is True


def test_registrar_nunca_sobrescribe_y_numera_en_orden(tmp_path):
    ruta = tmp_path / "registro_comandos.jsonl"
    r = RegistroComandos(ruta)
    for i in range(5):
        r.registrar("Consola", "destino", "SSH", f"comando {i}")
    lineas = ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == 5
    numeros = [json.loads(l)["n"] for l in lineas]
    assert numeros == sorted(numeros) == list(range(1, 6))


def test_canal_invalido_rechazado(tmp_path):
    r = RegistroComandos(tmp_path / "registro_comandos.jsonl")
    with pytest.raises(ValueError):
        r.registrar("Consola", "destino", "canal-que-no-existe", "x")


def test_listar_filtra_por_canal_y_texto(tmp_path):
    r = RegistroComandos(tmp_path / "registro_comandos.jsonl")
    r.registrar("OBU", "RSU 1", "MQTT", {"tema": "rsu/1/solicitudes"}, id_solicitud="req-1")
    r.registrar("Consola", "RSU 1", "SNMPv3", {"oid": "1.3.6.1.4.1.1206.4.2.1.1"})
    r.registrar("Consola", "RSU (SSH)", "SSH", "tail -n 500 eventos_rsu_1.csv")

    assert len(r.listar()) == 3
    assert len(r.listar(canal="MQTT")) == 1
    assert len(r.listar(texto="req-1")) == 1
    assert len(r.listar(canal="SSH", texto="eventos_rsu")) == 1
    assert len(r.listar(canal="MQTT", texto="no-existe")) == 0


def test_listar_devuelve_mas_reciente_primero(tmp_path):
    r = RegistroComandos(tmp_path / "registro_comandos.jsonl")
    r.registrar("Consola", "d", "SSH", "primero")
    r.registrar("Consola", "d", "SSH", "segundo")
    filas = r.listar()
    assert filas[0]["comando"] == "segundo"
    assert filas[1]["comando"] == "primero"


def test_recarga_desde_archivo_al_reiniciar(tmp_path):
    ruta = tmp_path / "registro_comandos.jsonl"
    r1 = RegistroComandos(ruta)
    r1.registrar("Consola", "d", "SSH", "antes de reiniciar")

    r2 = RegistroComandos(ruta)  # simula reiniciar el proceso de la consola
    assert len(r2.listar()) == 1
    r2.registrar("Consola", "d", "SSH", "despues de reiniciar")
    assert len(r2.listar()) == 2
    # el numero sigue despues del ultimo leido, no se reinicia en 1
    assert [f["n"] for f in r2.listar()][::-1] == [1, 2]
