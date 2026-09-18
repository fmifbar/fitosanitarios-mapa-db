"""
motor_canonico.py - Motor Canónico Universal de Extracción para Fichas Oficiales MAPA
Geometría A3 Apaisada (Landscape 1190.6 x 841.9 pt) con parsing estructurado (3FN).
"""

import re
import hashlib
from typing import Dict, List, Any, Optional
import pdfplumber

def calcular_sha256(ruta_archivo: str) -> str:
    """Calcula el hash SHA-256 de un archivo para control de versiones delta."""
    hasher = hashlib.sha256()
    with open(ruta_archivo, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()

def normalizar_dosis(dosis_str: str) -> Dict[str, Any]:
    """
    Parsea y extrae dosis mínima, máxima y unidad de medida a partir de cadenas como:
    '0,06 - 0,1 %', '0,2 %', '2 - 3 kg/ha', '150-200 ml/hl', 'ver condic.'
    """
    if not dosis_str:
        return {"dosis_min": None, "dosis_max": None, "dosis_unidad": None, "dosis_original": ""}

    original = dosis_str.strip()
    texto = original.replace(",", ".")
    
    # Extraer unidad si existe
    unidad_match = re.search(r'(kg/ha|l/ha|g/ha|ml/ha|g/hl|ml/hl|%|kg|l)\b', texto, re.IGNORECASE)
    if not unidad_match and "%" in texto:
        unidad = "%"
    else:
        unidad = unidad_match.group(1).lower() if unidad_match else None
        if unidad == "%":
            unidad = "%"

    # Buscar rangos: "0.06 - 0.1" o "2 - 3"
    rango_match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*[-–]\s*([0-9]+(?:\.[0-9]+)?)', texto)
    if rango_match:
        try:
            d_min = float(rango_match.group(1))
            d_max = float(rango_match.group(2))
            return {
                "dosis_min": d_min,
                "dosis_max": d_max,
                "dosis_unidad": unidad,
                "dosis_original": original
            }
        except ValueError:
            pass

    # Buscar valor único: "0.2 %", "3 l/ha"
    unico_match = re.search(r'([0-9]+(?:\.[0-9]+)?)', texto)
    if unico_match:
        try:
            val = float(unico_match.group(1))
            return {
                "dosis_min": val,
                "dosis_max": val,
                "dosis_unidad": unidad,
                "dosis_original": original
            }
        except ValueError:
            pass

    return {
        "dosis_min": None,
        "dosis_max": None,
        "dosis_unidad": unidad or "ver condic.",
        "dosis_original": original
    }

def normalizar_plazo_seguridad(plazo_str: str) -> Dict[str, Any]:
    """Parsea el plazo de seguridad a entero (días) y texto normalizado."""
    if not plazo_str:
        return {"dias": 0, "texto": "NO PROCEDE"}
    
    limpio = plazo_str.strip().upper()
    if "NP" in limpio or "NO PROCEDE" in limpio or "N/A" in limpio:
        return {"dias": 0, "texto": "NO PROCEDE"}
    
    num_match = re.search(r'\b([0-9]+)\b', limpio)
    if num_match:
        dias = int(num_match.group(1))
        return {"dias": dias, "texto": str(dias)}
    
    return {"dias": 0, "texto": limpio}

class ExtractorFichaMAPA:
    """Extractor universal basado en la geometría canónica de los documentos A3 del MAPA."""

    def __init__(self, ruta_pdf: str):
        self.ruta_pdf = ruta_pdf
        self.sha256 = calcular_sha256(ruta_pdf)

    def procesar(self) -> Dict[str, Any]:
        with pdfplumber.open(self.ruta_pdf) as pdf:
            resultado = {
                "sha256": self.sha256,
                "producto": self._extraer_datos_producto(pdf),
                "composicion": [],
                "usos": [],
                "plazos_seguridad": [],
                "seguridad": {},
                "toxicologia": {},
                "mitigaciones": []
            }

            # Enriquecer composición a partir del producto
            if resultado["producto"].get("composicion_texto"):
                resultado["composicion"] = self._parsear_composicion(resultado["producto"]["composicion_texto"])

            # Recorrer las páginas identificando secciones por su contenido
            for page_idx, page in enumerate(pdf.pages):
                texto_pagina = page.extract_text() or ""
                texto_lower = texto_pagina.lower()
                
                # Página de Usos y Dosis
                if "usos y dosis autorizados" in texto_lower or "ámbito de aplicación:" in texto_lower or "ambito de aplicacion:" in texto_lower:
                    usos, plazos = self._extraer_usos_y_plazos(page)
                    resultado["usos"].extend(usos)
                    resultado["plazos_seguridad"].extend(plazos)
                
                # Página de Mitigación de riesgos / Seguridad
                if "seguridad del aplicador" in texto_lower or "seguridad del trabajador" in texto_lower:
                    seg = self._extraer_seguridad(page, texto_pagina)
                    if any(seg.values()):
                        resultado["seguridad"].update(seg)

                # Página de Clasificaciones y Etiquetado
                if "clasificaciones y etiquetado" in texto_lower or "palabra de advertencia" in texto_lower:
                    tox = self._extraer_toxicologia(page, texto_pagina)
                    if any(tox.values()):
                        resultado["toxicologia"].update(tox)

                # Página de Mitigaciones Ambientales
                if "mitigaci" in texto_lower or "organismos acu" in texto_lower or "artr" in texto_lower:
                    mits = self._extraer_mitigaciones(page, texto_pagina)
                    if mits:
                        resultado["mitigaciones"].extend(mits)

            # Asignar plazos de seguridad cruzados a los usos correspondientes si están vacíos
            self._asociar_plazos_a_usos(resultado["usos"], resultado["plazos_seguridad"])

            return resultado

    def _extraer_datos_producto(self, pdf) -> Dict[str, Any]:
        """Extrae la información administrativa de la página 1."""
        p1 = pdf.pages[0]
        texto = p1.extract_text() or ""
        
        datos = {
            "num_registro": "",
            "nombre_comercial": "",
            "estado": "Vigente",
            "fecha_inscripcion": None,
            "fecha_caducidad": None,
            "titular": "",
            "fabricante": "",
            "composicion_texto": "",
            "tipo_formulario": "",
            "clasificacion_peligrosidad": ""
        }

        # Registro (soportando formato nacional numérico y europeo ES-XXXXX)
        reg_match = re.search(r'Número de Registro:\s*([A-Z0-9\-]+)', texto)
        if not reg_match or not reg_match.group(1).strip():
            reg_match = re.search(r'\b(ES-[0-9]{4,6})\b', texto)
        if not reg_match:
            reg_match = re.search(r'\n([0-9]{5})\n', texto)
        if reg_match:
            datos["num_registro"] = reg_match.group(1).strip()

        # Estado
        estado_match = re.search(r'Estado:\s*([A-Za-z]+)', texto)
        if estado_match:
            datos["estado"] = estado_match.group(1).strip()

        # Fechas
        f_insc = re.search(r'Inscripción:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})', texto)
        if f_insc:
            datos["fecha_inscripcion"] = f_insc.group(1).strip()

        f_cad = re.search(r'Caducidad:\s*([0-9]{2}/[0-9]{2}/[0-9]{4})', texto)
        if f_cad:
            datos["fecha_caducidad"] = f_cad.group(1).strip()

        # Nombre comercial
        nom_match = re.search(r'Nombre Comercial:\s*\n*([^\n]+)', texto)
        if nom_match:
            datos["nombre_comercial"] = nom_match.group(1).strip()

        # Titular y Fabricante
        tit_match = re.search(r'Titular\s+Fabricante\s*\n([^\n]+)', texto)
        if tit_match:
            linea_tit_fab = tit_match.group(1).strip()
            partes = re.split(r'\s{3,}', linea_tit_fab)
            if len(partes) >= 2:
                datos["titular"] = partes[0].strip()
                datos["fabricante"] = partes[1].strip()
            elif len(partes) == 1:
                datos["titular"] = partes[0].strip()

        # Composición
        comp_match = re.search(r'Composición\s*\n([^\n]+)', texto)
        if comp_match:
            datos["composicion_texto"] = comp_match.group(1).strip()

        return datos

    def _parsear_composicion(self, comp_texto: str) -> List[Dict[str, Any]]:
        """Extrae sustancias activas, porcentajes y unidades."""
        sustancias = []
        patron = r'([A-Z0-9\s\-]+?)\s+([0-9]+(?:,[0-9]+)?)\s*(%|g/l|g/kg)'
        matches = re.finditer(patron, comp_texto)
        for m in matches:
            nombre = m.group(1).strip()
            conc = float(m.group(2).replace(",", "."))
            unidad = m.group(3).strip()
            sustancias.append({
                "nombre": nombre,
                "concentracion": conc,
                "unidad": unidad
            })
        return sustancias

    def _extraer_usos_y_plazos(self, page) -> (List[Dict[str, Any]], List[Dict[str, Any]]):
        """
        Segmentación por franjas horizontales X canónicas de A3 Landscape:
        - Columna 1 (USO / Cultivo):   x0: 10  a 115
        - Columna 2 (AGENTE / Plaga):  x0: 115 a 255
        - Columna 3 (Dosis):           x0: 255 a 355
        - Columna 4 (Nº Aplic):        x0: 355 a 435
        - Columna 5 (Vol. Caldo):      x0: 435 a 555
        - Columna 6 (Condiciones):     x0: 555 a 1180
        """
        words = page.extract_words()
        
        # Detectar altura donde empieza la sección de plazos de seguridad
        y_plazos = 9999.0
        for w in words:
            if "Plazos de Seguridad" in w["text"] or ("Plazos" == w["text"] and w["top"] > 300):
                if w["top"] < y_plazos:
                    y_plazos = w["top"]
                break

        # Separar palabras de la tabla de usos y de la tabla de plazos
        words_usos = [w for w in words if 135 < w["top"] < y_plazos]
        words_plazos = [w for w in words if w["top"] >= y_plazos]

        usos = self._interpretar_filas_usos(words_usos)
        plazos = self._interpretar_filas_plazos(words_plazos)

        return usos, plazos

    def _interpretar_filas_usos(self, words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Agrupa palabras por cercanía vertical Y y las asigna a sus columnas correspondientes."""
        if not words:
            return []

        # Ordenar palabras por coordenada Y
        words.sort(key=lambda w: (round(w["top"] / 5) * 5, w["x0"]))

        # Agrupar en líneas visuales de altura similar (tolerancia ±4 pt)
        lineas = []
        linea_actual = []
        y_actual = None

        for w in words:
            if y_actual is None:
                y_actual = w["top"]
                linea_actual.append(w)
            elif abs(w["top"] - y_actual) <= 6:
                linea_actual.append(w)
            else:
                lineas.append(linea_actual)
                linea_actual = [w]
                y_actual = w["top"]
        if linea_actual:
            lineas.append(linea_actual)

        # Distribuir palabras de cada línea en slots de columnas
        filas_procesadas = []
        cultivo_actual = ""
        plaga_actual = ""
        
        for linea in lineas:
            col_uso = []
            col_agente = []
            col_dosis = []
            col_naplic = []
            col_vol = []
            col_condic = []

            for w in linea:
                x = w["x0"]
                t = w["text"]
                if x < 115:
                    col_uso.append(t)
                elif 115 <= x < 255:
                    col_agente.append(t)
                elif 255 <= x < 355:
                    col_dosis.append(t)
                elif 355 <= x < 435:
                    col_naplic.append(t)
                elif 435 <= x < 555:
                    col_vol.append(t)
                else:
                    col_condic.append(t)

            str_uso = " ".join(col_uso).strip()
            str_agente = " ".join(col_agente).strip()
            str_dosis = " ".join(col_dosis).strip()
            str_naplic = " ".join(col_naplic).strip()
            str_vol = " ".join(col_vol).strip()
            str_condic = " ".join(col_condic).strip()

            # Si la línea es una cabecera de ámbito, omitir
            if "Ámbito de Aplicación" in str_uso or "Ámbito de Aplicación" in str_agente or "Ámbito de Aplicación" in str_condic or "Tipo de Usuario" in str_uso or "Tipo de Usuario" in str_agente:
                continue

            # El cultivo o la plaga pueden venir de filas anteriores si están fusionadas
            if str_uso:
                cultivo_actual = str_uso
            if str_agente:
                plaga_actual = str_agente

            # Si encontramos dosis o agente, es una fila agronómica válida
            if str_dosis or str_agente:
                info_dosis = normalizar_dosis(str_dosis)
                
                n_aplic = None
                m_naplic = re.search(r'\b([0-9]+)\b', str_naplic)
                if m_naplic:
                    n_aplic = int(m_naplic.group(1))

                filas_procesadas.append({
                    "cultivo": cultivo_actual,
                    "agente": plaga_actual if plaga_actual else "General",
                    "dosis_original": info_dosis["dosis_original"],
                    "dosis_min": info_dosis["dosis_min"],
                    "dosis_max": info_dosis["dosis_max"],
                    "dosis_unidad": info_dosis["dosis_unidad"],
                    "num_aplicaciones": n_aplic,
                    "volumen_caldo": str_vol,
                    "condiciones": str_condic,
                    "plazo_dias": 0,
                    "plazo_texto": "NO PROCEDE"
                })
            elif str_condic and filas_procesadas:
                # Continuación de texto de condiciones de la fila previa
                filas_procesadas[-1]["condiciones"] += " " + str_condic

        return filas_procesadas

    def _interpretar_filas_plazos(self, words: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extrae los plazos de seguridad de la subtabla inferior."""
        if not words:
            return []
        
        texto_unido = " ".join([w["text"] for w in words])
        plazos = []

        # Buscar patrones "Cultivo(s) [días|NP]"
        lineas_raw = [w["text"] for w in words if w["top"] > 430]
        # Reconstruir líneas por Y
        words_ordenadas = sorted([w for w in words if w["top"] > 430], key=lambda w: (round(w["top"] / 6) * 6, w["x0"]))
        lineas = {}
        for w in words_ordenadas:
            y = round(w["top"] / 6) * 6
            lineas.setdefault(y, []).append(w)

        for y, lw in lineas.items():
            texto_linea = " ".join([w["text"] for w in lw]).strip()
            if not texto_linea:
                continue
            texto_lower = texto_linea.lower()
            if "p.s." in texto_lower or "seguridad" in texto_lower or "página" in texto_lower or "pagina" in texto_lower:
                continue
            
            # La última palabra o número suele ser el plazo
            m_ps = re.search(r'([0-9]+|NP|NO PROCEDE)\s*(?:\([^\)]+\))?$', texto_linea, re.IGNORECASE)
            if m_ps:
                ps_str = m_ps.group(1)
                cultivos_str = texto_linea[:m_ps.start()].strip()
                if not cultivos_str or len(cultivos_str) < 3 or "página" in cultivos_str.lower() or "pagina" in cultivos_str.lower():
                    continue
                info_ps = normalizar_plazo_seguridad(ps_str)
                if info_ps["dias"] > 365:
                    continue
                plazos.append({
                    "cultivo_grupo": cultivos_str,
                    "dias": info_ps["dias"],
                    "texto": info_ps["texto"]
                })

        return plazos

    def _asociar_plazos_a_usos(self, usos: List[Dict[str, Any]], plazos: List[Dict[str, Any]]):
        """Cruza los plazos de seguridad con los cultivos de los usos autorizados."""
        for uso in usos:
            cultivo_uso = uso.get("cultivo", "").lower()
            for p in plazos:
                grupo = p.get("cultivo_grupo", "").lower()
                # Coincidencia por subcadena (ej: "Mandarino" en "Mandarino, Naranjo...")
                if cultivo_uso and (cultivo_uso in grupo or grupo in cultivo_uso):
                    uso["plazo_dias"] = p["dias"]
                    uso["plazo_texto"] = p["texto"]
                    break

    def _extraer_seguridad(self, page, texto: str) -> Dict[str, Any]:
        """Extrae seguridad de aplicador, trabajador y reentrada."""
        seg = {
            "seguridad_aplicador": "",
            "seguridad_trabajador": "",
            "plazo_reentrada": "",
            "bandas_seguridad_spe3": "",
            "polinizadores_spe8": ""
        }

        m_ap = re.search(r'SEGURIDAD DEL APLICADOR:?\s*\n*(.*?)(?=SEGURIDAD DEL TRABAJADOR|USO NO PROFESIONAL|NORMATIVA|PLAZO DE REENTRADA|\Z)', texto, re.DOTALL | re.IGNORECASE)
        if m_ap:
            seg["seguridad_aplicador"] = " ".join(m_ap.group(1).split())

        m_tr = re.search(r'SEGURIDAD DEL TRABAJADOR:?\s*\n*(.*?)(?=USO NO PROFESIONAL|NORMATIVA|PLAZO DE REENTRADA|Medidas adicionales|MITIGACI|\Z)', texto, re.DOTALL | re.IGNORECASE)
        if m_tr:
            seg["seguridad_trabajador"] = " ".join(m_tr.group(1).split())

        m_re = re.search(r'(?:PLAZO DE REENTRADA:?|No entrar al cultivo[^\n\.]*)(.*?)(?=Clasificaciones y Etiquetado|Clase y categor[íi]a|NORMATIVA|Medidas adicionales|MITIGACI|P[áa]gina|\Z)', texto, re.DOTALL | re.IGNORECASE)
        if m_re:
            seg["plazo_reentrada"] = " ".join(m_re.group(0).split())

        return seg

    def _extraer_toxicologia(self, page, texto: str) -> Dict[str, Any]:
        """Extrae pictogramas, advertencia, frases H, frases P y envases."""
        tox = {
            "palabra_advertencia": "",
            "pictogramas_ghs": "",
            "indicaciones_h": "",
            "consejos_p": "",
            "incompatibilidades_mezclas": "",
            "gestion_envases": ""
        }

        m_adv = re.search(r'Palabra de Advertencia\s*\n*\s*(Peligro|Atenci[oó]n)', texto, re.IGNORECASE)
        if m_adv:
            tox["palabra_advertencia"] = m_adv.group(1).strip().capitalize()

        # Pictogramas GHS (GHS01 a GHS09)
        ghs_found = re.findall(r'GHS0[1-9]', texto)
        if ghs_found:
            tox["pictogramas_ghs"] = ", ".join(sorted(list(set(ghs_found))))

        # Frases H y EUH (soportando saltos de línea entre letra y dígitos, ej: H\n314 o EUH\n401)
        frases_h = []
        for m in re.finditer(r'\b(H|EUH)\s*([0-9]{3}[a-zA-Z]?)\b', texto, re.IGNORECASE):
            frases_h.append(f"{m.group(1).upper()}{m.group(2).upper()}")
        if frases_h:
            tox["indicaciones_h"] = ", ".join(sorted(list(set(frases_h))))

        # Frases P (soportando saltos de línea, ej: P\n262 o P262+P280)
        frases_p = []
        for m in re.finditer(r'\b(P)\s*([0-9]{3}[a-zA-Z]?)\b', texto, re.IGNORECASE):
            frases_p.append(f"{m.group(1).upper()}{m.group(2).upper()}")
        if frases_p:
            tox["consejos_p"] = ", ".join(sorted(list(set(frases_p))))

        # Incompatibilidades
        m_inc = re.search(r'([^\.\n]*?(?:no se usará en combinación|incompatible con|no mezclar)[^\.\n]*)', texto, re.IGNORECASE)
        if m_inc:
            tox["incompatibilidades_mezclas"] = m_inc.group(1).strip()

        # Gestión de envases
        m_env = re.search(r'Gestión de Envases\s*\n*(.*?)(?=Otras Indicaciones|\Z)', texto, re.DOTALL | re.IGNORECASE)
        if m_env:
            tox["gestion_envases"] = " ".join(m_env.group(1).split())

        return tox

    def _extraer_mitigaciones(self, page, texto: str) -> List[Dict[str, Any]]:
        """Extrae medidas de mitigación ambientales (SPe3, SPe8, SP1)."""
        mitigaciones = []
        # Buscar SPe 3 acuático
        m_ac = re.search(r'(SPe\s*3:?\s*Para proteger los organismos acuáticos[^\.\n]*?([0-9]+)\s*m\b[^\.\n]*)', texto, re.IGNORECASE)
        if m_ac:
            dist = int(m_ac.group(2)) if m_ac.group(2) else 5
            mitigaciones.append({
                "tipo_organismo": "Acuático",
                "distancia_buffer_metros": dist,
                "porcentaje_reduccion_deriva": 0,
                "texto_restriccion": m_ac.group(1).strip()
            })

        # Buscar SPe 3 artrópodos no diana
        m_art = re.search(r'(SPe\s*3:?\s*Para proteger los artrópodos no objetivo.*?(?=Cualquier actividad|Eliminación|\Z))', texto, re.DOTALL | re.IGNORECASE)
        if m_art:
            mitigaciones.append({
                "tipo_organismo": "Artrópodos no diana",
                "distancia_buffer_metros": 5,
                "porcentaje_reduccion_deriva": 50,
                "texto_restriccion": " ".join(m_art.group(1).split())
            })

        # SP1 protección de aguas
        m_sp1 = re.search(r'(SP1:?\s*NO CONTAMINAR EL AGUA[^\n\.]*)', texto, re.IGNORECASE)
        if m_sp1:
            mitigaciones.append({
                "tipo_organismo": "Protección de Aguas (SP1)",
                "distancia_buffer_metros": 0,
                "porcentaje_reduccion_deriva": 0,
                "texto_restriccion": m_sp1.group(1).strip()
            })

        return mitigaciones

if __name__ == "__main__":
    import sys
    import json
    if sys.stdout.encoding != 'utf-8':
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass

    ruta_test = r"C:\Users\mifso\Downloads\Ficha producto-100231-17_09_2026.pdf"
    extractor = ExtractorFichaMAPA(ruta_test)
    datos = extractor.procesar()

    print("=" * 60)
    print("DATOS ADMINISTRATIVOS DEL PRODUCTO:")
    print("=" * 60)
    for k, v in datos["producto"].items():
        print(f"  {k}: {v}")

    print("\n" + "=" * 60)
    print("COMPOSICIÓN QUÍMICA NORMALIZADA:")
    print("=" * 60)
    for comp in datos["composicion"]:
        print(f"  • {comp['nombre']}: {comp['concentracion']} {comp['unidad']}")

    print("\n" + "=" * 60)
    print(f"USOS Y DOSIS AUTORIZADOS ({len(datos['usos'])} filas extraídas):")
    print("=" * 60)
    for u in datos["usos"][:5]:
        print(f"  • Cultivo: {u['cultivo']} | Plaga: {u['agente']}")
        print(f"    Dosis: {u['dosis_original']} (Min: {u['dosis_min']}, Max: {u['dosis_max']} {u['dosis_unidad']})")
        print(f"    P.S.: {u['plazo_texto']} ({u['plazo_dias']} días) | Aplicaciones: {u['num_aplicaciones']}")

    print("\n" + "=" * 60)
    print("SEGURIDAD Y TOXICOLOGÍA:")
    print("=" * 60)
    print(f"  Advertencia: {datos['toxicologia'].get('palabra_advertencia')}")
    print(f"  Pictogramas: {datos['toxicologia'].get('pictogramas_ghs')}")
    print(f"  Frases H: {datos['toxicologia'].get('indicaciones_h')}")
    print(f"  Aplicador: {datos['seguridad'].get('seguridad_aplicador')[:100]}...")
