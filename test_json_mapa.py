import httpx

url = "https://servicio.mapa.gob.es/regfiweb/Exportaciones/ExportJsonProductosAutorizados"
print("Probando POST a ExportJsonProductosAutorizados...")
try:
    r = httpx.post(url, timeout=30, follow_redirects=True, verify=False)
    print("Status POST:", r.status_code)
    print("Content-Type:", r.headers.get("content-type"))
    print("Content-Disposition:", r.headers.get("content-disposition"))
    print("Content-Length bytes:", len(r.content))
    print("Primeros 300 caracteres:", r.text[:300])
except Exception as e:
    print("Error:", e)
