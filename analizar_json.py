import httpx
import json

url = "https://servicio.mapa.gob.es/regfiweb/Exportaciones/ExportJsonProductosAutorizados"
print("Descargando muestra del JSON oficial...")
r = httpx.post(url, timeout=60, verify=False)
raw = r.json()
# Notice raw is a JSON string or dict with "Contenido"
if isinstance(raw, str):
    data_wrapper = json.loads(raw)
else:
    data_wrapper = raw

if "Contenido" in data_wrapper:
    contenido = json.loads(data_wrapper["Contenido"])
else:
    contenido = data_wrapper

productos = contenido.get("Productos", [])
print(f"Total productos en el JSON oficial del MAPA: {len(productos)}")

if productos:
    p0 = productos[0]
    print("\nClaves del primer producto:")
    for k in p0.keys():
        print(f"  - {k}")
    print("\nDATOSPRODUCTO:")
    print(json.dumps(p0.get("DATOSPRODUCTO", {}), indent=2, ensure_ascii=False)[:500])
    
    # Check what other keys exist (USOS, etc.)
    for k, v in p0.items():
        if k != "DATOSPRODUCTO":
            print(f"\nSección {k} (tipo {type(v).__name__}, longitud {len(v) if isinstance(v, list) else 1}):")
            if isinstance(v, list) and v:
                print(json.dumps(v[0], indent=2, ensure_ascii=False)[:400])
