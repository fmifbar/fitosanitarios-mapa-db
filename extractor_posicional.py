"""
Extractor de las fichas oficiales del MAPA (PDF) leyendo por POSICIÓN en la página.

SOLO LECTURA sobre los PDF: lee los de la carpeta de origen y escribe JSON en la de
salida. Quien los carga en la base es `enriquecer_fichas.py`, vía `adaptador_canonico.py`.

Por qué este extractor y no `motor_canonico.ExtractorFichaMAPA`
---------------------------------------------------------------
Son dos formas de leer la misma ficha. Esta lee por posición y color, y se midió el
02/10/2026 sobre las 2.080 fichas del registro: **2.049 bien y 31 a revisar (98,5 %)**.
Y cada ficha se contrasta después contra los usos del JSON nacional, que es lo que
permite decir **cuáles** son esas 31 y por qué, en vez de confiar y ya está.

El motor canónico sigue aquí y no se toca: lo usa `descargador_fichas_mapa.py`.

Por qué por posición y no como texto corrido: las fichas son tablas y cuadros; leídas
como texto, las columnas se mezclan (el «2022» de un párrafo acaba en otra tabla, las
cabeceras de «Sistema de Cultivo» se pegan a las filas...). Aquí se usa:
  - títulos de sección: negrita, 12 pt, azul (#154480)
  - cabecera de grupo de usos («Ámbito de Aplicación ... Sistema de Cultivo ...»): verde (#006400)
  - cultivo de cada fila de usos: marrón (#8B4513)
  - columnas de la tabla de usos: las celdas dibujadas de su cabecera
  - filas de la tabla de clasificaciones: las líneas horizontales dibujadas

Uso:
    python extractor_posicional.py <carpeta de PDF> <carpeta de salida> [lista de archivos...]
"""
import hashlib, json, os, re, sys, datetime, unicodedata
from collections import defaultdict

try:
    # El nombre nuevo. `import fitz` sigue funcionando pero avisa de que está
    # obsoleto en cada ejecución, y un aviso que sale siempre acaba siendo un
    # aviso que nadie lee.
    import pymupdf as fitz
except ImportError:                      # PyMuPDF anterior a la 1.24.3
    import fitz

AZUL, VERDE, MARRON, ETIQUETA, VALOR = 0x154480, 0x006400, 0x8B4513, 0x000080, 0x696969
VERSION = "1.1 (02/10/2026)"


def sha256_de(ruta):
    """La huella del PDF. Es lo que permite no reprocesar lo que no ha cambiado."""
    h = hashlib.sha256()
    with open(ruta, "rb") as fh:
        for trozo in iter(lambda: fh.read(1 << 20), b""):
            h.update(trozo)
    return h.hexdigest()


def llano(t):
    s = unicodedata.normalize("NFKD", str(t or ""))
    return re.sub(r"\s+", " ", "".join(c for c in s if not unicodedata.combining(c))).strip().lower()


# ---------------------------------------------------------------- lectura de bajo nivel
def spans_de(doc):
    out = []
    for pn, page in enumerate(doc):
        for b in page.get_text("dict")["blocks"]:
            for l in b.get("lines", []):
                for s in l["spans"]:
                    t = s["text"].replace("\u00a0", " ")
                    if not t.strip():
                        continue
                    x0, y0, x1, y1 = s["bbox"]
                    out.append({"p": pn, "x0": x0, "y0": y0, "x1": x1, "y1": y1, "yc": (y0 + y1) / 2,
                                "t": t, "size": s["size"], "bold": "Bold" in s["font"], "color": s["color"]})
    return out


def en_cuerpo(s, alto):
    return 80 < s["y0"] < alto - 30          # fuera la cabecera del Ministerio y el pie de página


def lineas(spans, tol=4.5):
    """Agrupa trozos en renglones (los trozos de una misma línea salen con alturas algo distintas)."""
    res = []
    for s in sorted(spans, key=lambda s: (s["p"], s["yc"], s["x0"])):
        if res and res[-1]["p"] == s["p"] and abs(res[-1]["yc"] - s["yc"]) <= tol:
            res[-1]["spans"].append(s)
            n = len(res[-1]["spans"])
            res[-1]["yc"] = (res[-1]["yc"] * (n - 1) + s["yc"]) / n
        else:
            res.append({"p": s["p"], "yc": s["yc"], "spans": [s]})
    for r in res:
        r["spans"].sort(key=lambda s: s["x0"])
        r["texto"] = unir(r["spans"])
        r["x0"] = r["spans"][0]["x0"]
        r["y0"] = min(s["y0"] for s in r["spans"])
        r["y1"] = max(s["y1"] for s in r["spans"])
    return res


def unir(spans):
    txt, prev = "", None
    for s in spans:
        t = s["t"]
        if prev is not None and s["x0"] - prev["x1"] > 1.5 and not txt.endswith(" ") and not t.startswith(" "):
            txt += " "
        txt += t
        prev = s
    return re.sub(r"\s+", " ", txt).strip()


def parrafos(lns):
    """Une renglones en párrafos; corta cuando hay un hueco vertical o el renglón empieza por guion."""
    out, prev = [], None
    for l in lns:
        nuevo = (prev is None or l["p"] != prev["p"] or l["y0"] - prev["y1"] > 6
                 or re.match(r"^[-•·]\s*", l["texto"]))
        if nuevo:
            out.append(l["texto"])
        else:
            out[-1] += " " + l["texto"]
        prev = l
    return [re.sub(r"\s+", " ", p).strip() for p in out if p.strip()]


# ---------------------------------------------------------------- secciones
def secciones(doc, spans):
    alto = doc[0].rect.height
    cuerpo = [s for s in spans if en_cuerpo(s, alto)]
    titulos = [s for s in cuerpo if s["bold"] and s["size"] >= 11.5 and s["color"] == AZUL]
    titulos.sort(key=lambda s: (s["p"], s["y0"], s["x0"]))
    sec = defaultdict(list)
    for s in cuerpo:
        if s in titulos:
            continue
        # el título vigente es el último que queda por encima (en esta página o en las anteriores)
        candidatos = [t for t in titulos if (t["p"], t["y0"]) <= (s["p"], s["y0"] + 2)]
        if not candidatos:
            sec["_sin_seccion"].append(s)
            continue
        ultimo = candidatos[-1]
        # Titular y Fabricante van lado a lado en la misma altura
        mismos = [t for t in candidatos if t["p"] == ultimo["p"] and abs(t["y0"] - ultimo["y0"]) < 3]
        if len(mismos) > 1:
            ancho = doc[s["p"]].rect.width
            mismos.sort(key=lambda t: t["x0"])
            ultimo = mismos[0] if s["x0"] < ancho / 2 - 50 else mismos[-1]
        sec[ultimo["t"].strip()].append(s)
    tk = next((k for k in sec if llano(k) == "titular"), None)
    fk = next((t["t"].strip() for t in titulos if llano(t["t"]) == "fabricante"), None)
    if tk and fk:
        sec.setdefault(fk, [])
        juntos = sec[tk] + sec[fk]
        xs = sorted({round(s["x0"]) for s in juntos})
        if len(xs) > 1:
            hueco = max(range(len(xs) - 1), key=lambda i: xs[i + 1] - xs[i])
            corte = (xs[hueco] + xs[hueco + 1]) / 2
            sec[tk] = [s for s in juntos if s["x0"] < corte]
            sec[fk] = [s for s in juntos if s["x0"] >= corte]
    return sec, [t["t"].strip() for t in titulos]


def buscar(sec, *claves):
    for k in sec:
        if any(c in llano(k) for c in claves):
            return sec[k]
    return []


# ---------------------------------------------------------------- datos del producto
def datos_producto(spans):
    etiquetas = [s for s in spans if s["color"] == ETIQUETA]
    valores = [s for s in spans if s["color"] != ETIQUETA]
    res = {}
    for v in valores:
        misma = [e for e in etiquetas if e["p"] == v["p"] and abs(e["yc"] - v["yc"]) < 8 and e["x1"] <= v["x0"] + 2]
        e = max(misma, key=lambda e: e["x1"]) if misma else None
        if e is None:
            arriba = [e for e in etiquetas if e["p"] == v["p"] and 0 < v["yc"] - e["yc"] < 40]
            e = min(arriba, key=lambda e: abs(e["x0"] - v["x0"])) if arriba else None
        clave = llano(e["t"]).rstrip(":").strip() if e else "otros"
        res.setdefault(clave, []).append(v["t"].strip())
    traduce = {"numero de registro": "num_registro", "estado": "estado", "inscripcion": "fecha_inscripcion",
               "renovacion": "fecha_renovacion", "caducidad": "fecha_caducidad", "nombre comercial": "nombre_comercial",
               "cancelacion": "fecha_cancelacion", "fecha limite de venta": "fecha_limite_venta",
               "fecha limite de uso": "fecha_limite_uso"}
    out = {}
    for k, v in res.items():
        out[traduce.get(k, k.replace(" ", "_"))] = " ".join(v)
    return out


def empresa(spans):
    lns = lineas(spans)
    if not lns:
        return None
    return {"nombre": lns[0]["texto"], "direccion": ", ".join(l["texto"] for l in lns[1:])}


# ---------------------------------------------------------------- usos
CAB = ["uso", "agente", "dosis", "aplicaciones", "intervalo", "caldo", "condiciones"]
CAB_TXT = {"uso": "uso", "agente": "agente", "dosis": "dosis", "nº aplic.": "aplicaciones", "n° aplic.": "aplicaciones",
           "intervalos": "intervalo", "vol. caldo": "caldo", "condic. especifico": "condiciones"}
RX_AMBITO = re.compile(r"Ámbito de Aplicación:\s*(?P<ambito>.*?)(?:\s*-\s*Tipo de Usuario:\s*(?P<usuario>.*?))?"
                       r"(?:\s*-\s*Sistema de Cultivo:\s*(?P<sistema>.*?))?"
                       r"(?:\s*-\s*Método de Aplicación:\s*(?P<metodo>.*?))?\s*$", re.I)


# Medidas de las columnas en la plantilla habitual (A4 apaisado, 1190 pt de ancho)
COLUMNAS_POR_DEFECTO = {"uso": (11, 111), "agente": (111, 228), "dosis": (228, 343), "aplicaciones": (343, 437),
                        "intervalo": (437, 507), "caldo": (507, 636), "condiciones": (636, 1053)}


def columnas_de_pagina(doc, pn, spans_cab):
    """Celdas dibujadas de la cabecera de la tabla de usos: dan el ancho exacto de cada columna."""
    cols = {}
    rects = [d["rect"] for d in doc[pn].get_drawings() if d.get("fill") and 15 < d["rect"].height < 40]
    for s in spans_cab:
        k = CAB_TXT.get(llano(s["t"]).replace("º", "º"))
        if not k:
            k = next((v for kk, v in CAB_TXT.items() if llano(kk) == llano(s["t"])), None)
        if not k:
            continue
        cx, cy = (s["x0"] + s["x1"]) / 2, s["yc"]
        r = next((r for r in rects if r.x0 - 1 <= cx <= r.x1 + 1 and r.y0 - 2 <= cy <= r.y1 + 2), None)
        if r:
            cols[k] = (r.x0, r.x1)
    return cols if len(cols) >= 5 else None


def separadores(doc, pn):
    """Alturas de las líneas horizontales dibujadas que separan filas de una tabla."""
    return sorted({round(d["rect"].y0, 1) for d in doc[pn].get_drawings()
                   if d["rect"].height < 0.5 and d["rect"].width > 50 and d["rect"].x0 < 20})


def franja(seps, y):
    arriba = max([v for v in seps if v <= y], default=-1)
    abajo = min([v for v in seps if v > y], default=1e6)
    return arriba, abajo


def partir_agentes(textos):
    """Una celda puede llevar varias plagas, cada una partida en renglones. Empieza una nueva cuando
    el renglón va en mayúscula y la anterior ya tiene «nombre común, nombre científico»."""
    out = []
    for t in textos:
        t = t.strip()
        if out and not (t[:1].isupper() and re.search(r",\s*\S", out[-1])):
            out[-1] += " " + t
        else:
            out.append(t)
    return out


def usos(doc, spans):
    if not spans:
        return [], []
    avisos = []
    lns = lineas(spans)
    # cabeceras de columna por página
    cols_pag, ultimas = {}, None
    for pn in sorted({s["p"] for s in spans}):
        cab = [s for s in spans if s["p"] == pn and s["color"] == AZUL and not s["bold"]]
        c = columnas_de_pagina(doc, pn, cab) if cab else None
        if c:
            ultimas = c
        cols_pag[pn] = ultimas or COLUMNAS_POR_DEFECTO
        if not ultimas:
            avisos.append(f"Usos, página {pn + 1}: columnas no reconocidas; se usan las medidas estándar de la ficha")
    grupos = []          # [{cabecera, filas:[{ancla, spans}]}]
    actual = None
    datos = [s for s in spans if not (s["color"] == AZUL and not s["bold"])]
    # cabeceras de grupo (pueden partirse en dos trozos de la misma línea)
    for l in lns:
        if any(s["color"] == VERDE for s in l["spans"]):
            pass
    orden = sorted(datos, key=lambda s: (s["p"], s["yc"], s["x0"]))
    # 1) separar por grupos
    tramos, cab_actual = [], None
    for s in orden:
        if s["color"] == VERDE:
            if tramos and tramos[-1]["cab_spans"] and tramos[-1]["cab_spans"][-1]["p"] == s["p"] \
                    and abs(tramos[-1]["cab_spans"][-1]["yc"] - s["yc"]) < 4.5 and not tramos[-1]["spans"]:
                tramos[-1]["cab_spans"].append(s)
            else:
                tramos.append({"cab_spans": [s], "spans": []})
        else:
            if not tramos:
                tramos.append({"cab_spans": [], "spans": []})
            tramos[-1]["spans"].append(s)
    filas, seps_pag = [], {}
    for tr in tramos:
        cab_txt = unir(sorted(tr["cab_spans"], key=lambda s: s["x0"])) if tr["cab_spans"] else ""
        m = RX_AMBITO.search(cab_txt) if cab_txt else None
        g = {k: (m.group(k).strip() if m and m.group(k) else None) for k in ("ambito", "usuario", "sistema", "metodo")}
        sueltas = sorted([s for s in tr["spans"] if s["color"] == MARRON], key=lambda s: (s["p"], s["yc"]))
        anclas, nombre_ancla = [], {}
        for s in sueltas:
            seps = seps_pag.setdefault(s["p"], separadores(doc, s["p"]))
            prev = anclas[-1] if anclas else None
            ultimo = nombre_ancla[id(prev)][-1] if prev else None
            if prev and prev["p"] == s["p"] and franja(seps, prev["yc"]) == franja(seps, s["yc"])                     and s["yc"] - ultimo["yc"] < 14:
                nombre_ancla[id(prev)].append(s)
            else:
                anclas.append(s)
                nombre_ancla[id(s)] = [s]
        if not anclas:
            if tr["spans"]:
                avisos.append(f"Usos: {len(tr['spans'])} trozos sin cultivo reconocible en «{cab_txt[:60]}»")
            continue
        asign = defaultdict(list)
        for s in tr["spans"]:
            mismas = [a for a in anclas if a["p"] == s["p"]] or anclas
            seps = seps_pag.setdefault(s["p"], separadores(doc, s["p"]))
            fr = franja(seps, s["yc"])
            en_franja = [a for a in mismas if a["p"] == s["p"] and franja(seps, a["yc"]) == fr]
            pag_sig = [a for a in anclas if a["p"] == s["p"] + 1]
            pag_ant = [a for a in anclas if a["p"] == s["p"] - 1]
            if len(en_franja) == 1:
                a = en_franja[0]
            elif not en_franja and pag_sig and fr[1] >= max(seps, default=0) - 60                     and not [x for x in mismas if x["p"] == s["p"] and x["yc"] > s["yc"]]:
                a = min(pag_sig, key=lambda a: a["yc"])      # fila partida: su cultivo está en la página siguiente
            elif not en_franja and pag_ant and not [x for x in mismas if x["p"] == s["p"] and x["yc"] < s["yc"]]                     and not [x for x in tr["spans"] if x["p"] == s["p"] and x["color"] == VERDE]:
                a = max(pag_ant, key=lambda a: a["yc"])      # fila partida: su cultivo quedó en la anterior
            else:
                a = min(mismas, key=lambda a: (abs(a["yc"] - s["yc"]) if a["p"] == s["p"] else 1e6))
            asign[id(a)].append(s)
        for a in sorted(anclas, key=lambda a: (a["p"], a["yc"])):
            cols = cols_pag.get(a["p"])
            celdas = defaultdict(list)
            for s in asign[id(a)]:
                if cols:
                    cx = (s["x0"] + s["x1"]) / 2
                    k = next((k for k, (x0, x1) in cols.items() if x0 - 1 <= cx <= x1 + 1), None)
                    if k is None:
                        k = min(cols, key=lambda k: min(abs(cx - cols[k][0]), abs(cx - cols[k][1])))
                else:
                    k = "sin_columna"
                celdas[k].append(s)
            fila = {"ambito": g["ambito"], "tipo_usuario": g["usuario"], "sistema_cultivo": g["sistema"],
                    "metodo_aplicacion": g["metodo"], "cabecera_grupo": cab_txt or None,
                    "uso": " ".join(x["t"].strip() for x in nombre_ancla[id(a)])}
            celdas.pop("uso", None)
            for k in CAB + ["sin_columna"]:
                if k in celdas:
                    renglones = [l["texto"] for l in lineas(celdas[k])]
                    fila[k] = " ".join(renglones)
                    if k == "agente":
                        fila["agentes"] = partir_agentes(renglones)
            if not fila.get("sistema_cultivo"):
                lc = llano(fila.get("condiciones"))
                ded = []
                if "aire libre" in lc and not re.search(r"no (se )?(autoriza|aplicar|utilizar)[^.]*aire libre", lc):
                    ded.append("Aire libre")
                if re.search(r"invernadero|walk-in|macrotunel|estructuras no permanentes|cultivo protegido", lc)                         and not re.search(r"(exclusivamente|solo|unicamente) al aire libre", lc):
                    ded.append("Invernadero / protegido")
                fila["sistema_cultivo_deducido"] = ded or None
            filas.append(fila)
    return filas, avisos


# ---------------------------------------------------------------- plazos
def plazos(spans):
    if not spans:
        return []
    ps_col = [s for s in spans if llano(s["t"]).startswith("p.s.")]
    uso_col = [s for s in spans if llano(s["t"]) == "uso" and s["color"] == AZUL]
    if ps_col and uso_col:
        corte = (uso_col[0]["x1"] + ps_col[0]["x0"]) / 2      # mitad entre las dos cabeceras
    else:
        corte = 600
    out = []
    for l in lineas([s for s in spans if s["color"] != AZUL]):
        izq = unir([s for s in l["spans"] if s["x0"] < corte])
        der = unir([s for s in l["spans"] if s["x0"] >= corte])
        if izq and der:
            out.append({"uso": izq, "plazo": der})
        elif izq and out and not out[-1].get("_cerrado"):
            out[-1]["uso"] += " " + izq          # nombre de cultivo partido en dos renglones
        elif der and out:
            out[-1]["plazo"] += " " + der
    return out


# ---------------------------------------------------------------- manipulación
def manipulacion(spans):
    lns = lineas(spans)
    bloques, actual = [], {"apartado": None, "lineas": []}
    for l in lns:
        t = l["texto"]
        if len(t) < 70 and t.endswith(":") and not t.startswith("-"):
            if actual["lineas"] or actual["apartado"]:
                bloques.append(actual)
            actual = {"apartado": t.rstrip(":").strip(), "lineas": []}
        else:
            actual["lineas"].append(l)
    bloques.append(actual)
    res = {"apartados": []}
    padre = None
    for b in bloques:
        texto = parrafos(b["lineas"])
        ap = b["apartado"] or ""
        la = llano(ap)
        if la.startswith("seguridad del") or la.startswith("normativa") or la.startswith("medidas"):
            padre = ap
        res["apartados"].append({"apartado": ap or None, "dentro_de": padre if padre != ap else None,
                                 "texto": texto})
    todo = " ".join(p for a in res["apartados"] for p in a["texto"])
    frases = [f.strip() for f in re.split(r"(?<=[.;])\s+|\s-\s", todo) if f.strip()]
    reent = [f for f in frases if re.search(r"reentrada|no entrar|no se entrar|volver a entrar", llano(f))]
    res["reentrada_frases"] = reent
    # Cada plazo va con su frase: «13 días en cítricos» no es un plazo general del producto
    plazos_r = []
    for f in reent:
        lf = llano(f)
        for m in re.finditer(r"(\d+)\s*(horas?|h\b|dias?)", lf):
            plazos_r.append({"valor": f"{m.group(1)} {'horas' if m.group(2).startswith('h') else 'días'}",
                             "frase": f})
        if "secad" in lf or "seco" in lf:
            plazos_r.append({"valor": "hasta que se haya secado", "frase": f})
    res["plazos_reentrada"] = plazos_r
    res["plazo_reentrada"] = "; ".join(sorted({x["valor"] for x in plazos_r})) or None
    return res


# ---------------------------------------------------------------- clasificación
RX_H = re.compile(r"^(EUH\s?\d{3}[A-Z]?|H\d{3}[A-Za-z]*(?:\s?\+\s?H\d{3}[A-Za-z]*)*)\s*-?\s*(.*)$")
RX_P = re.compile(r"^(P\d{3}(?:\s?\+\s?P\d{3})*)\s*-?\s*(.*)$")


def clasificacion(doc, spans):
    if not spans:
        return None
    pags = sorted({s["p"] for s in spans})
    # separadores horizontales dibujados en la columna de etiquetas
    cortes = []
    for pn in pags:
        ys = sorted({round(d["rect"].y0, 1) for d in doc[pn].get_drawings()
                     if d["rect"].height < 0.5 and d["rect"].x0 < 20 and 200 < d["rect"].width < 300})
        cortes += [(pn, y) for y in ys]
    etiquetas = [s for s in spans if s["color"] == ETIQUETA and s["x0"] < 268]
    valores = [s for s in spans if s not in etiquetas and s["x0"] >= 260]
    filas = []
    for e in sorted(etiquetas, key=lambda s: (s["p"], s["yc"])):
        ys = [y for p, y in cortes if p == e["p"]]
        arriba = max([y for y in ys if y <= e["yc"]], default=0)
        abajo = min([y for y in ys if y > e["yc"]], default=1e6)
        vs = [s for s in valores if s["p"] == e["p"] and arriba - 1 <= s["yc"] <= abajo + 1]
        filas.append({"etiqueta": e["t"].strip(), "lineas": [l["texto"] for l in lineas(vs)]})
    # fusionar etiquetas partidas en dos renglones dentro de la misma fila
    res = {"humana": {}, "ambiental": {}}
    bloque = "humana"
    for f in filas:
        le = llano(f["etiqueta"])
        if "medio ambiental" in le:
            bloque = "ambiental"
        b = res[bloque]
        if le.startswith("clase y categoria"):
            b["clases_peligro"] = f["lineas"]
        elif le.startswith("pictograma"):
            b["pictogramas"] = [{"codigo": re.match(r"(GHS\d+)", x).group(1) if re.match(r"(GHS\d+)", x) else None,
                                 "texto": x} for x in f["lineas"]]
        elif le.startswith("palabra"):
            b["palabra_advertencia"] = " ".join(f["lineas"]) or None
        elif le.startswith("indicaciones"):
            b["indicaciones_peligro"] = items_codigo(f["lineas"], RX_H)
        elif le.startswith("consejos"):
            b["consejos_prudencia"] = items_codigo(f["lineas"], RX_P)
        else:
            b.setdefault("otros", []).append({"etiqueta": f["etiqueta"], "lineas": f["lineas"]})
    return res


def items_codigo(lineas_, rx):
    out = []
    for t in lineas_:
        m = rx.match(t.strip())
        if m:
            out.append({"codigo": re.sub(r"\s+", "", m.group(1)), "texto": m.group(2).strip(" -")})
        elif out:
            out[-1]["texto"] = (out[-1]["texto"] + " " + t.strip()).strip()
        else:
            out.append({"codigo": None, "texto": t.strip()})
    return out


# ---------------------------------------------------------------- mitigación ambiental
ORGANISMOS = [("acuatic", "organismos acuáticos"), ("artropodo", "artrópodos no objetivo"),
              ("abeja", "abejas y polinizadores"), ("polinizador", "abejas y polinizadores"),
              ("plantas no objetivo", "plantas no objetivo"), ("aves", "aves"), ("mamifero", "mamíferos"),
              ("aguas subterraneas", "aguas subterráneas"), ("lombric", "organismos del suelo"),
              ("organismos del suelo", "organismos del suelo")]


def mitigaciones(spans):
    out = []
    for p in parrafos(lineas(spans)):
        m = re.match(r"^(SPe\s?\d+|SP\s?\d+|SPo\s?\d+|SPa\s?\d+)\s*:?\s*", p, re.I)
        codigo = re.sub(r"\s", "", m.group(1)) if m else None
        lp = llano(p)
        org = sorted({v for k, v in ORGANISMOS if k in lp})
        out.append({
            "codigo": codigo[:3].upper() + codigo[3:] if codigo else None,
            "organismos": org,
            "distancias_m": sorted({int(x) for x in re.findall(r"(\d+)\s*m\b", lp)}),
            "reduccion_deriva_pct": sorted({int(x) for x in re.findall(r"(\d+)\s*%", lp)}),
            "horas": sorted({int(x) for x in re.findall(r"(\d+)\s*horas", lp)}),
            "no_aplicar_en_floracion": "floracion" in lp and ("no aplicar" in lp or "no se aplicar" in lp),
            "texto": p,
        })
    return out


# ---------------------------------------------------------------- ficha completa
def extraer(ruta):
    doc = fitz.open(ruta)
    try:
        return _extraer(doc, ruta)
    finally:
        # 2.080 PDF abiertos y nunca cerrados son 2.080 descriptores retenidos.
        doc.close()


def _extraer(doc, ruta):
    spans = spans_de(doc)
    sec, titulos = secciones(doc, spans)
    pie = next((m.group(0) for s in spans if s["y0"] > doc[0].rect.height - 40
                for m in [re.search(r"\d{4,}\s*-\s*\d{4,}", s["t"])] if m), None)
    ficha = {
        "archivo": os.path.basename(ruta),
        # De dónde salió **de verdad** este PDF, de cuándo es y su huella. Se
        # apunta aquí, al leerlo, porque es el único sitio donde se sabe: los
        # pasos siguientes solo ven JSON ya extraídos y no pueden más que
        # creerse lo que se les diga. Un campo de procedencia escrito a mano es
        # una afirmación que nadie ha comprobado, y deja de ser cierta en
        # cuanto alguien corre esto con otros PDF.
        "origen_pdf": os.path.dirname(os.path.abspath(ruta)),
        "pdf_modificado": datetime.datetime.fromtimestamp(
            os.path.getmtime(ruta)).isoformat(timespec="seconds"),
        "sha256": sha256_de(ruta),
        "extraido_en": datetime.datetime.now().isoformat(timespec="seconds"),
        "extractor_version": VERSION,
        "paginas": doc.page_count,
        "id_documento_pie": pie,
        "secciones_encontradas": titulos,
        "producto": datos_producto(buscar(sec, "datos del producto")),
        "titular": empresa(buscar(sec, "titular")),
        "fabricante": empresa(buscar(sec, "fabricante")),
        "composicion": parrafos(lineas(buscar(sec, "composicion"))),
        "envases": " ".join(parrafos(lineas(buscar(sec, "envases")))) or None,
    }
    ficha["usos"], avisos = usos(doc, buscar(sec, "usos y dosis"))
    ficha["plazos_seguridad"] = plazos(buscar(sec, "plazos de seguridad"))
    ficha["condiciones_generales_uso"] = " ".join(parrafos(lineas(buscar(sec, "condiciones generales")))) or None
    ficha["clase_usuario"] = " ".join(parrafos(lineas(buscar(sec, "clase de usuario")))) or None
    ficha["manipulacion"] = manipulacion(buscar(sec, "manipulacion"))
    ficha["clasificacion"] = clasificacion(doc, buscar(sec, "clasificaciones"))
    ficha["mitigacion_ambiental"] = mitigaciones(buscar(sec, "riesgos ambientales"))
    ficha["eliminacion_producto_caldo"] = mitigaciones(buscar(sec, "eliminacion"))
    ficha["gestion_envases"] = " ".join(parrafos(lineas(buscar(sec, "gestion de envases")))) or None
    ficha["otras_indicaciones"] = parrafos(lineas(buscar(sec, "otras indicaciones")))
    conocidas = ("datos del producto", "titular", "fabricante", "composicion", "envases", "usos y dosis",
                 "plazos de seguridad", "condiciones generales", "clase de usuario", "manipulacion",
                 "clasificaciones", "riesgos ambientales", "eliminacion", "gestion de envases", "otras indicaciones")
    otras = {k: parrafos(lineas(v)) for k, v in sec.items()
             if k != "_sin_seccion" and not any(c in llano(k) for c in conocidas)}
    if otras:
        ficha["otras_secciones"] = otras
    # resumen para filtrar rápido
    spe8 = [m for m in ficha["mitigacion_ambiental"] if "abejas y polinizadores" in m["organismos"]]
    ficha["resumen"] = {
        "sistemas_cultivo": sorted({u.get("sistema_cultivo") or "no declarado" for u in ficha["usos"]}),
        "autorizado_invernadero": any("invernadero" in llano(u.get("sistema_cultivo")) for u in ficha["usos"]),
        "invernadero_segun_condiciones": any("invernadero" in llano(" ".join(u.get("sistema_cultivo_deducido") or []))
                                             for u in ficha["usos"]),
        "plazo_reentrada": ficha["manipulacion"]["plazo_reentrada"],
        "riesgo_abejas": bool(spe8),
        "horas_colmenas": sorted({h for m in spe8 for h in m["horas"]}),
        "bandas_seguridad_m": sorted({d for m in ficha["mitigacion_ambiental"] for d in m["distancias_m"]}),
        "pictogramas": sorted({p["codigo"] for b in (ficha["clasificacion"] or {}).values()
                               for p in b.get("pictogramas", []) if p.get("codigo")}),
    }
    falta = [n for n, v in (("datos del producto", ficha["producto"]), ("usos", ficha["usos"]),
                            ("clasificación", ficha["clasificacion"])) if not v]
    if falta:
        avisos.append("No se ha encontrado: " + ", ".join(falta))
    ficha["avisos_extraccion"] = avisos
    return ficha


def main(origen, destino, archivos=None):
    os.makedirs(os.path.join(destino, "fichas"), exist_ok=True)
    archivos = archivos or sorted(f for f in os.listdir(origen) if f.lower().endswith(".pdf"))
    todas, errores = [], []
    for i, f in enumerate(archivos, 1):
        try:
            ficha = extraer(os.path.join(origen, f))
            reg = ficha["producto"].get("num_registro") or os.path.splitext(f)[0].replace("Ficha_", "")
            with open(os.path.join(destino, "fichas", f"{reg}.json"), "w", encoding="utf-8") as fh:
                json.dump(ficha, fh, ensure_ascii=False, indent=2)
            todas.append(ficha)
        except Exception as e:
            errores.append({"archivo": f, "error": f"{type(e).__name__}: {e}"})
        if i % 200 == 0:
            print(f"  {i}/{len(archivos)}", flush=True)
    return todas, errores


if __name__ == "__main__":
    origen, destino = sys.argv[1], sys.argv[2]
    todas, errores = main(origen, destino, sys.argv[3:] or None)
    print(f"{len(todas)} fichas extraídas, {len(errores)} errores")
    for e in errores[:20]:
        print("  ", e)
