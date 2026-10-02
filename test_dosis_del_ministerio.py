"""
test_dosis_del_ministerio.py - Un 0 del MAPA no es una dosis de cero.

Lo que esto cierra
------------------
Cuando un uso no tiene horquilla, el Ministerio pone la cifra en uno de los dos
campos y manda **0** en el otro. Ese 0 significa «no hay segundo extremo», no
«dosis cero».

Medido el 02/10/2026 sobre los 62.648 usos del registro:

    los dos con valor   49.863   79,6 %
    Dosis_Max = 0        8.803   14,1 %
    Dosis_Min = 0        2.491    4,0 %
    los dos a 0          1.491    2,4 %

Guardarlo tal cual convierte un hueco en una afirmación. Quien después compare
«la dosis no puede pasar de `dosis_max`» leerá que el máximo autorizado es
cero, y **cualquier dosis será un exceso**. En un programa que sirve para
recetar, eso es un aviso que salta siempre o un cálculo que da cero.

Y el texto guardado era peor todavía: `"0.2 - 0.0 %"` se lee como una horquilla
que baja de 0,2 a 0, cuando es una dosis única de 0,2 %.

Es la misma regla que el plazo de seguridad y la vigencia al recetar: **un
hueco se ve, un cero que parece un dato no.**
"""
import pytest

from ingestar_json_mapa import _dosis_de, _numero


def uso(mn=None, mx=None, unidad="%", dosis=None):
    u = {"Dosis_Min": mn, "Dosis_Max": mx, "Unidad Medida dosis": unidad}
    if dosis is not None:
        u["Dosis"] = dosis
    return u


# --------------------------------------------------------------------------
# El cero
# --------------------------------------------------------------------------

@pytest.mark.parametrize("valor", [0, 0.0, "0", "0.0", "", None])
def test_un_cero_o_un_hueco_se_guardan_como_hueco(valor):
    assert _numero(valor) is None


@pytest.mark.parametrize("valor,esperado", [(0.2, 0.2), ("0,,", None), ("3", 3.0), (15, 15.0)])
def test_una_cifra_de_verdad_se_conserva(valor, esperado):
    assert _numero(valor) == esperado


def test_el_caso_real_de_clementgros():
    """
    `0.2 - 0.0 %` en la base venía de Min=0,2 y Max=0. Es una dosis única de
    0,2 %, no una horquilla que baja hasta cero.
    """
    d_min, d_max, _, texto = _dosis_de(uso(mn=0.2, mx=0))

    assert d_min == 0.2
    assert d_max is None, "el 0 del Ministerio no puede guardarse como un máximo de cero"
    assert texto == "0.2 %"


def test_la_cifra_unica_tambien_llega_por_el_maximo():
    """A veces el Ministerio la pone en Max y deja Min a 0. Pasa 2.491 veces."""
    d_min, d_max, _, texto = _dosis_de(uso(mn=0, mx=0.2))

    assert d_min is None
    assert d_max == 0.2
    assert texto == "0.2 %"


def test_sin_ninguna_cifra_se_dice_que_no_la_hay():
    """Escribir «0 %» sería afirmar algo que nadie ha dicho."""
    d_min, d_max, _, texto = _dosis_de(uso(mn=0, mx=0))

    assert (d_min, d_max) == (None, None)
    assert "0" not in texto
    assert "Sin dosis" in texto


# --------------------------------------------------------------------------
# Lo que no debe cambiar
# --------------------------------------------------------------------------

def test_una_horquilla_de_verdad_se_respeta():
    d_min, d_max, unidad, texto = _dosis_de(uso(mn=0.06, mx=0.1))

    assert (d_min, d_max, unidad) == (0.06, 0.1, "%")
    assert texto == "0.06 - 0.1 %"


def test_los_dos_iguales_no_son_una_horquilla():
    _, _, _, texto = _dosis_de(uso(mn=2.5, mx=2.5))
    assert texto == "2.5 %"


def test_la_unidad_se_conserva():
    assert _dosis_de(uso(mn=500, mx=666, unidad="l/ha"))[2] == "l/ha"
    assert _dosis_de(uso(mn=3, mx=0, unidad="kg/ha"))[3] == "3 kg/ha"


def test_el_texto_no_arrastra_decimales_inventados():
    """«0.20000000000000001 %» no es más preciso, es más feo y menos legible."""
    assert _dosis_de(uso(mn=0.2, mx=0))[3] == "0.2 %"
    assert _dosis_de(uso(mn=3.0, mx=0))[3] == "3 %"
