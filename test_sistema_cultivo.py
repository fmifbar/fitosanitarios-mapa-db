"""
test_sistema_cultivo.py - Invernadero o aire libre, que en Murgiverde lo decide todo.

Por que esto importa aqui mas que en ningun sitio
-------------------------------------------------
**En Murgiverde solo hay invernaderos.** Toda la produccion es bajo plastico, sin
una sola parcela al aire libre. Asi que `sistema_cultivo` no es un dato
informativo: es el que dice si un producto se puede usar o no.

Un uso autorizado **solo al aire libre no esta autorizado en un invernadero**.
Aplicarlo seria una aplicacion ilegal, y si el programa no lo distingue, seria
una aplicacion ilegal con su visto bueno.

Lo que vigila esta prueba
-------------------------
1. Que la letra se traduzca a lo que de verdad significa, y solo las tres
   comprobadas. La equivalencia se saco cruzando 3.012 usos del JSON con el
   texto de las fichas PDF, no suponiendola.
2. Que un codigo desconocido se guarde **tal cual**, sin inventarle sentido.
3. Que el hueco siga siendo un hueco. El Ministerio lo deja en blanco en el
   54 % de los usos, y rellenarlo por nuestra cuenta es lo peor que se podria
   hacer con este campo concreto.
4. Que nadie confunda `ambito` con esto. `ambito` solo vale «Agrario» o
   «No Agrario» y no distingue invernadero de aire libre.
"""
import pytest

from ingestar_json_mapa import SISTEMAS_DE_CULTIVO, _sistema_cultivo_de


def uso(codigo):
    return {"SistemaCultivo": codigo}


# --------------------------------------------------------------------------
# Las tres comprobadas
# --------------------------------------------------------------------------

@pytest.mark.parametrize("codigo,texto", [("F", "Aire libre"),
                                          ("G", "Invernadero"),
                                          ("I", "Interior")])
def test_las_letras_comprobadas_se_traducen(codigo, texto):
    """F = 2.644/2.644, G = 254/254, I = 114/114 contra las fichas PDF."""
    assert _sistema_cultivo_de(uso(codigo)) == (texto, codigo)


def test_solo_hay_tres_equivalencias():
    """
    Si alguien añade una cuarta, que sea comprobándola como se comprobaron
    estas y no de memoria.
    """
    assert set(SISTEMAS_DE_CULTIVO) == {"F", "G", "I"}


def test_invernadero_y_aire_libre_no_se_confunden():
    """Es la distinción de la que depende poder recetar o no en Murgiverde."""
    assert _sistema_cultivo_de(uso("G"))[0] == "Invernadero"
    assert _sistema_cultivo_de(uso("F"))[0] == "Aire libre"
    assert _sistema_cultivo_de(uso("G"))[0] != _sistema_cultivo_de(uso("F"))[0]


# --------------------------------------------------------------------------
# Lo que no se sabe, no se inventa
# --------------------------------------------------------------------------

@pytest.mark.parametrize("vacio", ["", "   ", None])
def test_en_blanco_se_queda_en_blanco(vacio):
    """
    El Ministerio lo deja vacío en el 54 % de los usos. Suponer «invernadero»
    daría por bueno lo que nadie ha autorizado; suponer «aire libre» quitaría
    productos que sí valen. Las dos suposiciones son malas, así que ninguna.
    """
    assert _sistema_cultivo_de(uso(vacio)) == (None, None)


@pytest.mark.parametrize("raro", ["Otros (ver condic.)", "X9", "GG"])
def test_un_codigo_desconocido_se_guarda_tal_cual(raro):
    texto, codigo = _sistema_cultivo_de(uso(raro))
    assert texto == raro and codigo == raro


def test_no_se_traduce_un_codigo_desconocido_a_invernadero():
    """Lo peor que podría hacer esta función: dar por bueno lo que no consta."""
    for raro in ("Otros (ver condic.)", "X9", "", None):
        assert _sistema_cultivo_de(uso(raro))[0] != "Invernadero"


def test_la_letra_original_se_conserva_siempre():
    """Para poder revisar la traducción después sin volver al Ministerio."""
    assert _sistema_cultivo_de(uso("G"))[1] == "G"
    assert _sistema_cultivo_de(uso("Otros (ver condic.)"))[1] == "Otros (ver condic.)"
