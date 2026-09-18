"""
test_api.py - Pruebas automáticas de los endpoints de la API de fitosanitarios
"""

import sys
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from fastapi.testclient import TestClient
from api_fitosanitarios import app

client = TestClient(app)

def test_endpoints():
    print("=" * 60)
    print("PROBANDO ENDPOINTS DE LA API FITOSANITARIOS MAPA (v2)")
    print("=" * 60)

    # 1. Búsqueda con autocompletado
    resp = client.get("/api/v2/fitosanitarios/buscar?q=clement")
    assert resp.status_code == 200
    data = resp.json()
    print(f"\n1. Búsqueda autocompletada ('clement'):")
    print(f"   • Tiempo: {data['tiempo_ms']} ms | Total: {data['total_encontrados']}")
    for r in data["resultados"]:
        print(f"   -> {r['nombre_comercial']} (Reg. {r['num_registro']}) - {r['titular']}")

    # 2. Consulta de Usos (Prescripción)
    resp = client.get("/api/v2/fitosanitarios/consultar-usos?cultivo=Naranjo")
    assert resp.status_code == 200
    data = resp.json()
    print(f"\n2. Prescripción para cultivo 'Naranjo':")
    print(f"   • Tiempo: {data['tiempo_ms']} ms | Total usos: {data['total_usos']}")
    for u in data["usos_autorizados"][:3]:
        print(f"   -> {u['nombre_comercial']} | {u['agente_nombre']} | Dosis: {u['dosis_original']} | P.S.: {u['plazo_seguridad_texto']}")

    # 3. Validación de Receta: Caso legal
    receta_ok = {
        "num_registro": "18926",
        "cultivo": "Naranjo",
        "dosis_prescrita": 0.12,
        "unidad_prescrita": "%",
        "dias_para_cosecha": 25
    }
    resp = client.post("/api/v2/fitosanitarios/validar-receta", json=receta_ok)
    assert resp.status_code == 200
    data = resp.json()
    print(f"\n3. Validación de Receta Correcta (Dosis 0.12% en Naranjo, cosecha en 25 días):")
    print(f"   • Válido: {data['valido']} | Bloqueante: {data['bloqueante']}")
    print(f"   • Mensajes: {data['mensajes']}")

    # 4. Validación de Receta: Caso ilegal por exceso de dosis
    receta_exceso = {
        "num_registro": "18926",
        "cultivo": "Naranjo",
        "dosis_prescrita": 0.25,
        "unidad_prescrita": "%",
        "dias_para_cosecha": 25
    }
    resp = client.post("/api/v2/fitosanitarios/validar-receta", json=receta_exceso)
    assert resp.status_code == 200
    data = resp.json()
    print(f"\n4. Validación de Receta con Exceso de Dosis (Dosis 0.25%, máx oficial 0.15%):")
    print(f"   • Válido: {data['valido']} | Bloqueante: {data['bloqueante']}")
    for m in data['mensajes']:
        print(f"   ⚠️  {m}")

    # 5. Validación de Receta: Caso ilegal por plazo de seguridad
    receta_plazo = {
        "num_registro": "18926",
        "cultivo": "Naranjo",
        "dosis_prescrita": 0.1,
        "unidad_prescrita": "%",
        "dias_para_cosecha": 5 # P.S. oficial es 20 días
    }
    resp = client.post("/api/v2/fitosanitarios/validar-receta", json=receta_plazo)
    assert resp.status_code == 200
    data = resp.json()
    print(f"\n5. Validación de Receta con Infracción de Plazo de Seguridad (Cosecha en 5 días, P.S. 20 días):")
    print(f"   • Válido: {data['valido']} | Bloqueante: {data['bloqueante']}")
    for m in data['mensajes']:
        print(f"   🚨 {m}")

    # 6. Ficha completa
    resp = client.get("/api/v2/fitosanitarios/producto/18926")
    assert resp.status_code == 200
    data = resp.json()
    print(f"\n6. Ficha Técnica Completa:")
    print(f"   • Registro: {data['producto']['num_registro']} - {data['producto']['nombre_comercial']}")
    print(f"   • Composición: {data['composicion']}")
    print(f"   • Toxicología: {data['toxicologia']['palabra_advertencia']} | Pictogramas: {data['toxicologia']['pictogramas_ghs']}")
    print(f"   • Seguridad aplicador: {data['seguridad']['seguridad_aplicador'][:80]}...")

    print("\n" + "=" * 60)
    print("TODAS LAS PRUEBAS DE LA API SUPERADAS CON ÉXITO")
    print("=" * 60)

if __name__ == "__main__":
    test_endpoints()
