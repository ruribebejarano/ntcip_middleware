"""Pruebas de scripts/analisis/leyenda_tabla.py (título corto y nota al pie)."""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "scripts" / "analisis"))

from leyenda_tabla import CORTAS, formalizar  # noqa: E402

TABLA = r"""\begin{table}[H]
\centering
\caption{Tasa de entrega por tipo de mensaje y enlace. Entre paréntesis, la cota inferior. Elaboración propia.}
\label{tab:entrega}
\begin{tabular}{lr}
a & b \\
\end{tabular}
\end{table}
"""


def test_titulo_corto_y_nota_al_pie():
    t = formalizar(TABLA)
    assert "\\caption{" + CORTAS["tab:entrega"] + "}" in t
    assert "\\textit{Nota:} Entre paréntesis, la cota inferior. Elaboración propia." in t
    assert t.index("\\end{tabular}") < t.index("Nota:") < t.index("\\end{table}")


def test_es_idempotente():
    una = formalizar(TABLA)
    assert formalizar(una) == una


def test_etiqueta_desconocida_no_cambia():
    otra = TABLA.replace("tab:entrega", "tab:otra")
    assert formalizar(otra) == otra


def test_tabla_con_resizebox():
    t = TABLA.replace("\\begin{tabular}", "\\resizebox{\\textwidth}{!}{%\n\\begin{tabular}").replace(
        "\\end{tabular}", "\\end{tabular}}")
    f = formalizar(t)
    assert f.index("\\end{tabular}}") < f.index("Nota:")
