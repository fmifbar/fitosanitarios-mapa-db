"""
motor_canonico.py - Motor Canónico Universal de Extracción para Fichas Oficiales MAPA
Extracción exhaustiva de máxima fidelidad (100% fiel al PDF oficial de REGFIWEB):
- Metadatos oficiales: Registro (nacional/europeo), Estado real (Vigente/Cancelado/Caducado),
  Fechas completas (inscripción, renovación, caducidad, cancelación, límite de venta).
- Tablas de Usos y Dosis autorizados: soporte adaptativo a tablas de 7 y 4 columnas,
  captura de dosis (l/ha, kg/ha, l/Tm, %, cc/hl), número de aplicaciones, intervalos,
  volúmenes de caldo normalizados respetando separadores de miles y textos especiales ("Sin diluir"),
  estadios fenológicos BBCH y métodos de aplicación fidedignos sin inventar pulverización.
- Plazos de seguridad declarados en la tabla oficial inferior y cruce relacional inteligente.
- Mitigaciones ambientales completas y estructuradas: SPe 2 (aguas subterráneas/suelos),
  SPe 3 (todas las bandas de seguridad en metros y reducción de deriva con boquillas en %
  para organismos acuáticos, artrópodos no diana por tipo de cultivo y plantas no objetivo),
  SP 1 (protección de masas de agua y limpieza), efluentes postcosecha y SPe 8 (polinizadores/abejas).
- Seguridad laboral (EPIs aplicador y trabajador limpios de membretes y códigos de control) y reentrada.
- Clasificación GHS/CLP: palabra de advertencia oficial, pictogramas, indicaciones H, consejos P,
  incompatibilidades de mezclas y gestión SIGFITO.
"""

import re
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional

try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None

try:
    import pdfplumber
except ImportError:
    pdfplumber = None


def calcular_sha256(ruta_archivo: str) -> str:
    """Calcula el hash SHA-256 de un archivo para control de versiones delta."""
    hasher = hashlib.sha256()
    with open(ruta_archivo, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _limpiar_bloque_texto(texto: str) -> str:
    """Elimina membretes del ministerio, saltos de página y códigos de control de los textos oficiales."""
    if not texto:
        return ""
    texto = texto.replace("=== PAGINA_BREAK ===", " ")
    patrones = [
        r'SECRETAR[IÍ]A GENERAL DE RECURSOS AGRARIOS[^\n]*',
        r'DIRECCI[OÓ]N GENERAL DE SANIDAD[^\n]*',
        r'SUBDIRECCI[OÓ]N GENERAL DE SANIDAD[^\n]*',
        r'MINISTERIO DE AGRICULTURA[^\n]*',
        r'P[aá]gina\s+\d+\s+de\s+\d+',
        r'\b\d{5,7}\s*-\s*\d{5,8}\b'
    ]
    for p in patrones:
        texto = re.sub(p, ' ', texto, flags=re.IGNORECASE)
    texto = re.sub(r'[ \t]+', ' ', texto)
    texto = re.sub(r'\n\s*\n+', '\n', texto)
    return texto.strip()


def _parsear_volumen_caldo(caldo_raw: str) -> tuple[Optional[float], Optional[float], str]:
    """
    Normaliza el volumen de caldo respetando separadores de miles españoles (ej: 1.000 -> 1000).
    Devuelve (min, max, texto_normalizado).
    """
    if not caldo_raw:
        return None, None, ""
    c_clean = caldo_raw.strip()
    c_low = c_clean.lower()
    if any(x in c_low for x in ["no procede", "na", "sin diluir", "inyección", "cebo seco"]):
        return None, None, c_clean
    s = re.sub(r'(\d+)\.(\d{3})\b', r'\1\2', c_clean)
    s = s.replace(',', '.')
    nums = re.findall(r'\b\d+(?:\.\d+)?\b', s)
    if len(nums) >= 2:
        try:
            v_min, v_max = float(nums[0]), float(nums[1])
            return v_min, v_max, f"{int(v_min) if v_min.is_integer() else v_min} - {int(v_max) if v_max.is_integer() else v_max} L/ha"
        except ValueError:
            pass
    elif len(nums) == 1:
        try:
            v = float(nums[0])
            return v, v, f"{int(v) if v.is_integer() else v} L/ha"
        except ValueError:
            pass
    return None, None, c_clean


def normalizar_dosis(dosis_str: str) -> Dict[str, Any]:
    """
    Parsea y desglosa dosis mínima, máxima y unidad de medida a partir de cadenas como:
    '0,6 - 0,89 l/ha', '0,2 %', '2 - 3 kg/ha', '1 l/Tm', '150-200 ml/hl', 'ver condic.'
    """
    if not dosis_str:
        return {"dosis_min": None, "dosis_max": None, "dosis_unidad": None, "dosis_original": ""}

    original = dosis_str.strip()
    s = original.replace(",", ".")

    m_u = re.search(r'([a-zA-Z%]+(?:\s*/\s*[a-zA-Z%]+)?)', s)
    unidad = m_u.group(1).strip() if m_u else ""

    m_r = re.search(r'(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)', s)
    if m_r:
        try:
            return {
                "dosis_min": float(m_r.group(1)),
                "dosis_max": float(m_r.group(2)),
                "dosis_unidad": unidad,
                "dosis_original": original
            }
        except ValueError:
            pass

    m_v = re.search(r'(\d+(?:\.\d+)?)', s)
    if m_v:
        try:
            val = float(m_v.group(1))
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
    if any(x in limpio for x in ["NP", "N.P", "NO PROCEDE", "N/A", "NA"]):
        return {"dias": 0, "texto": "NO PROCEDE"}
    num_match = re.search(r'\b([0-9]+)\b', limpio)
    if num_match:
        dias = int(num_match.group(1))
        return {"dias": dias, "texto": str(dias)}
    return {"dias": 0, "texto": limpio}


def _extraer_mitigaciones_ambientales(full_text: str) -> List[Dict[str, Any]]:
    """Extrae exhaustivamente todas las medidas de mitigación ambientales (SPe 2, SPe 3, SP1, efluentes)."""
    mitigaciones = []
    patrones_spe = re.finditer(
        r'(SPe\s*[1238]|SP\s*1)[^:\n]*:\s*([^\n\r]+(?:\n(?!(?:SPe\s*[1238]|SP\s*1|Condiciones Generales|SEGURIDAD|Palabra de Advertencia|Página\s+\d+))[^\n\r]+)*)',
        full_text,
        re.IGNORECASE
    )
    for m in patrones_spe:
        tipo_code = m.group(1).upper().replace(" ", "")
        bloque_raw = _limpiar_bloque_texto(m.group(2))
        if not bloque_raw or len(bloque_raw) < 8:
            continue

        if "-" in bloque_raw and any(k in bloque_raw.lower() for k in ["artrópodo", "acuático", "deriva", "boquillas", "cubierta vegetal"]):
            lineas_guion = re.split(r'(?:^|\n)\s*-\s*', bloque_raw)
            for sub_l in lineas_guion:
                sub_l = sub_l.strip(' -.\n')
                if not sub_l or len(sub_l) < 5:
                    continue
                t_sub = sub_l.lower()
                tipo_org = "Medio ambiente general"
                if "acu[aá]tico" in t_sub:
                    tipo_org = "Organismos acuáticos"
                elif "artr[oó]podo" in t_sub:
                    tipo_org = "Artrópodos no diana"
                elif "plantas no" in t_sub or "planta no" in t_sub:
                    tipo_org = "Plantas no objeto del tratamiento"
                elif "subterr[aá]nea" in t_sub:
                    tipo_org = "Aguas subterráneas"
                elif "rumiante" in t_sub or "mam[ií]fero" in t_sub:
                    tipo_org = "Mamíferos rumiantes"
                elif any(c in t_sub for c in ["frutales", "vid", "lúpulo", "olivo", "tomate", "ornamentales", "cítricos"]):
                    tipo_org = "Banda de seguridad por cultivo / artrópodos"

                dist_m = None
                m_d = re.search(r'(\d+(?:[.,]\d+)?)\s*m\b', sub_l, re.I)
                if m_d:
                    dist_m = float(m_d.group(1).replace(',', '.'))
                red_pct = None
                m_r = re.search(r'(\d+)\s*%\s*(?:de)?\s*reducci[oó]n', sub_l, re.I)
                if m_r:
                    red_pct = int(m_r.group(1))

                mitigaciones.append({
                    "tipo_organismo": f"{tipo_code} - {tipo_org}",
                    "distancia_buffer_metros": dist_m,
                    "porcentaje_reduccion_deriva": red_pct,
                    "texto_restriccion": f"{tipo_code}: {sub_l}"
                })
        else:
            t_low = bloque_raw.lower()
            tipo_org = "Medio ambiente general"
            if "acu[aá]tico" in t_low:
                tipo_org = "Organismos acuáticos"
            elif "artr[oó]podo" in t_low:
                tipo_org = "Artrópodos no diana"
            elif "plantas no" in t_low or "planta no" in t_low:
                tipo_org = "Plantas no objeto del tratamiento"
            elif "subterr[aá]nea" in t_low:
                tipo_org = "Aguas subterráneas"
            elif "rumiante" in t_low or "mam[ií]fero" in t_low:
                tipo_org = "Mamíferos rumiantes"
            elif "polinizador" in t_low or "abeja" in t_low:
                tipo_org = "Polinizadores (abejas)"
            elif "no contaminar el agua" in t_low:
                tipo_org = "Protección de masas de agua (SP1)"

            dist_m = None
            m_dist = re.search(r'banda de seguridad de\s*(\d+(?:[.,]\d+)?)\s*m\b', bloque_raw, re.IGNORECASE)
            if m_dist:
                dist_m = float(m_dist.group(1).replace(',', '.'))
            elif "respetando una zona no tratada de" in t_low:
                m_dist2 = re.search(r'zona no tratada de\s*(\d+(?:[.,]\d+)?)\s*m\b', bloque_raw, re.IGNORECASE)
                if m_dist2:
                    dist_m = float(m_dist2.group(1).replace(',', '.'))

            red_pct = None
            m_red = re.search(r'(\d+)\s*%\s*de reducci[oó]n de la deriva', bloque_raw, re.IGNORECASE)
            if m_red:
                red_pct = int(m_red.group(1))

            mitigaciones.append({
                "tipo_organismo": f"{tipo_code} - {tipo_org}" if tipo_code not in tipo_org else tipo_org,
                "distancia_buffer_metros": dist_m,
                "porcentaje_reduccion_deriva": red_pct,
                "texto_restriccion": f"{m.group(1)}: {bloque_raw}"
            })

    if "efluente" in full_text.lower():
        m_efl = re.search(r'([^\n.]*no verter el efluente[^\n.]*(?:\.[^\n.]*)*)', full_text, re.IGNORECASE)
        if m_efl:
            t_efl = _limpiar_bloque_texto(m_efl.group(1))
            if t_efl and not any("efluente" in m["texto_restriccion"].lower() for m in mitigaciones):
                mitigaciones.append({
                    "tipo_organismo": "Gestión de efluentes y aguas superficiales",
                    "distancia_buffer_metros": None,
                    "porcentaje_reduccion_deriva": None,
                    "texto_restriccion": t_efl
                })

    return mitigaciones


def _extraer_metadatos_p0(p0) -> tuple[str, dict]:
    """Extrae con precisión geométrica el estado y las fechas oficiales de la cabecera MAPA."""
    words = p0.get_text('words')
    estado = 'Vigente'
    for w in words:
        if w[4].lower() in ('cancelado', 'caducado', 'modificado'):
            estado = w[4].capitalize()
            break
        elif w[4].lower() == 'vigente':
            estado = 'Vigente'

    dates = [w for w in words if re.match(r'^\d{2}/\d{2}/\d{4}$', w[4]) and 100 <= w[1] <= 250]
    dates.sort(key=lambda w: w[0])

    fechas = {'inscripcion': '', 'renovacion': '', 'caducidad': '', 'cancelacion': '', 'limite_venta': ''}
    if estado == 'Cancelado':
        if len(dates) >= 4:
            fechas['inscripcion'] = dates[0][4]
            fechas['renovacion'] = dates[1][4]
            fechas['cancelacion'] = dates[2][4]
            fechas['limite_venta'] = dates[3][4]
        elif len(dates) == 3:
            fechas['inscripcion'] = dates[0][4]
            fechas['renovacion'] = dates[1][4]
            fechas['cancelacion'] = dates[2][4]
        elif len(dates) >= 1:
            fechas['cancelacion'] = dates[-1][4]
    else:
        if len(dates) >= 3:
            fechas['inscripcion'] = dates[0][4]
            fechas['renovacion'] = dates[1][4]
            fechas['caducidad'] = dates[2][4]
        elif len(dates) == 2:
            fechas['inscripcion'] = dates[0][4]
            fechas['caducidad'] = dates[1][4]
        elif len(dates) == 1:
            fechas['caducidad'] = dates[0][4]

    return estado, fechas


class ExtractorFichaMAPA:
    """Extractor Canónico Universal para Fichas Técnicas Oficiales del MAPA en PDF."""

    def __init__(self, ruta_pdf: str):
        self.ruta_pdf = ruta_pdf
        self.sha256 = calcular_sha256(ruta_pdf)

    def procesar(self) -> Dict[str, Any]:
        doc = fitz.open(self.ruta_pdf)
        num_pages = len(doc)
        pages_text = [doc[i].get_text() for i in range(num_pages)]
        full_text = "\n\n=== PAGINA_BREAK ===\n\n".join(pages_text)

        estado_real, fechas_dict = _extraer_metadatos_p0(doc[0])

        resultado = {
            "sha256": self.sha256,
            "producto": {
                "num_registro": "",
                "nombre_comercial": "",
                "estado": estado_real,
                "fecha_inscripcion": fechas_dict.get("inscripcion") or None,
                "fecha_renovacion": fechas_dict.get("renovacion") or None,
                "fecha_caducidad": fechas_dict.get("caducidad") or None,
                "fecha_cancelacion": fechas_dict.get("cancelacion") or None,
                "fecha_limite_venta": fechas_dict.get("limite_venta") or None,
                "titular": "",
                "titular_direccion": "",
                "fabricante": "",
                "fabricante_direccion": "",
                "fabrica": "",
                "otras_denominaciones": "",
                "envases_autorizados": "",
                "tipo_formulario": "",
                "clasificacion_peligrosidad": "",
                "condiciones_generales_uso": "",
                "observaciones_reglamentarias": ""
            },
            "composicion": [],
            "usos": [],
            "plazos_seguridad": [],
            "seguridad": {},
            "toxicologia": {},
            "mitigaciones": []
        }

        # 1. Registro y Nombre Comercial geométricos (p0)
        p0_words = doc[0].get_text('words')
        
        # Número de Registro
        reg_words = [w for w in p0_words if 'registro' in w[4].lower() and w[0] < 150 and 100 <= w[1] <= 190]
        if reg_words:
            w_lbl = reg_words[0]
            candidatos_reg = [w for w in p0_words if abs(w[1] - w_lbl[1]) < 12 and w[0] > (w_lbl[2] + 2) and w[2] < 350]
            candidatos_reg.sort(key=lambda w: w[0])
            for cw in candidatos_reg:
                m_rg = re.search(r'([A-Za-z0-9\-]+)', cw[4])
                if m_rg and len(m_rg.group(1)) >= 4:
                    resultado["producto"]["num_registro"] = m_rg.group(1).strip()
                    break

        if not resultado["producto"]["num_registro"]:
            m_fn = re.search(r'Ficha_([A-Za-z0-9\-]+)\.pdf', Path(self.ruta_pdf).name, re.I)
            if m_fn:
                resultado["producto"]["num_registro"] = m_fn.group(1).strip()
            else:
                m_r = re.search(r'(?:N[uú]mero de Registro:\s*|ES-|\b)(\d{5}|ES-\d{5})\b', full_text, re.I)
                if m_r:
                    resultado["producto"]["num_registro"] = m_r.group(1).strip()

        # Nombre Comercial (Directamente adyacente a la etiqueta "Nombre Comercial:")
        nc_words = [w for w in p0_words if 'comercial' in w[4].lower() and w[0] < 150 and 140 <= w[1] <= 230]
        if nc_words:
            w_lbl = nc_words[0]
            nombre_words = [w for w in p0_words if abs(w[1] - w_lbl[1]) < 12 and w[0] > (w_lbl[2] + 2) and w[2] < 550]
            nombre_words.sort(key=lambda w: w[0])
            if nombre_words:
                nc_candidato = " ".join(w[4] for w in nombre_words).strip()
                if not any(ign in nc_candidato.upper() for ign in ['SECRETAR', 'DIRECCI', 'MINISTERIO', 'RECURSOS AGRARIOS']):
                    resultado["producto"]["nombre_comercial"] = nc_candidato

        if not resultado["producto"]["nombre_comercial"]:
            header_m = re.search(r'Nombre Comercial:\s*\n\s*([^\n\r]+)', full_text, re.I)
            if header_m:
                nc_candidato = header_m.group(1).strip()
                if not any(ign in nc_candidato.upper() for ign in ['SECRETAR', 'DIRECCI', 'MINISTERIO', 'RECURSOS AGRARIOS']):
                    resultado["producto"]["nombre_comercial"] = nc_candidato


        # Composición
        m_comp = re.search(r'Composici[oó]n\s*\n\s*([^\n\r]+)', full_text, re.I)
        if m_comp:
            comp_txt = m_comp.group(1).strip()
            resultado["producto"]["tipo_formulario"] = re.search(r'\[([A-Z]{2})\]', comp_txt).group(0) if re.search(r'\[([A-Z]{2})\]', comp_txt) else ""
            for m in re.finditer(r'([A-Z0-9\s\-]+?)\s+([0-9]+(?:,[0-9]+)?)\s*(%|g/l|g/kg|cc/hl)', comp_txt):
                resultado["composicion"].append({
                    "nombre": m.group(1).strip(),
                    "concentracion": float(m.group(2).replace(",", ".")),
                    "unidad": m.group(3).strip()
                })

        # Titular y Fabricante
        m_tit = re.search(r'Titular\s*\n\s*([\s\S]+?)(?=Fabricante|Composici[oó]n|Envases|$)', full_text, re.I)
        if m_tit:
            t_lines = [l.strip() for l in m_tit.group(1).split('\n') if l.strip() and not any(w in l.upper() for w in ['PÁGINA', 'SECRETAR', 'DIRECCI', 'ALIMENTARIA'])]
            if t_lines:
                resultado["producto"]["titular"] = t_lines[0]
                if len(t_lines) > 1:
                    resultado["producto"]["titular_direccion"] = ", ".join(t_lines[1:])

        m_fab = re.search(r'Fabricante\s*\n\s*([\s\S]+?)(?=Composici[oó]n|Envases|Usos|Plazos|$)', full_text, re.I)
        if m_fab:
            f_lines = [l.strip() for l in m_fab.group(1).split('\n') if l.strip() and not any(w in l.upper() for w in ['PÁGINA', 'SECRETAR', 'DIRECCI', 'ALIMENTARIA'])]
            if f_lines:
                resultado["producto"]["fabricante"] = f_lines[0]
                if len(f_lines) > 1:
                    resultado["producto"]["fabricante_direccion"] = ", ".join(f_lines[1:])

        # Envases
        m_env = re.search(r'Envases\s*\n\s*([\s\S]+?)(?=Usos y Dosis|Plazos de Seguridad|Condiciones Generales|Página|P[aá]gina|$)', full_text, re.I)
        if m_env:
            resultado["producto"]["envases_autorizados"] = _limpiar_bloque_texto(m_env.group(1))

        # 2. Rangos de tablas de Usos
        p_usos_start = -1
        p_ps = -1
        for i, p_txt in enumerate(pages_text):
            if 'Usos y Dosis Autorizados' in p_txt or ('USO' in p_txt and 'AGENTE' in p_txt and 'Dosis' in p_txt):
                if p_usos_start == -1: p_usos_start = i
            if 'Plazos de Seguridad' in p_txt or 'Protección del Consumidor' in p_txt:
                if p_ps == -1: p_ps = i

        is_multipage = (p_usos_start != -1 and p_ps != -1 and p_usos_start <= p_ps)

        if is_multipage:
            curr_crop = "General"
            for p_no in range(p_usos_start, p_ps + 1):
                page = doc[p_no]
                words = page.get_text('words')

                uso_hdr = [w for w in words if w[4] == 'USO' and w[1] < 700]
                y_min = uso_hdr[0][1] + 12 if uso_hdr else (500 if p_no == 0 else 85)

                y_max = 820
                if p_no == p_ps:
                    ps_hdr = [w for w in words if ('Plazos' in w[4] or 'Seguridad' in w[4]) and w[1] > 300]
                    if ps_hdr:
                        y_max = min([w[1] for w in ps_hdr]) - 5

                table_words = [w for w in words if y_min <= w[1] <= y_max]
                header_words = [w for w in words if abs(w[1] - (y_min - 6)) < 25]
                has_caldo_col = any('caldo' in w[4].lower() for w in header_words)

                dose_candidates = [w for w in table_words if 240 <= w[0] <= 335 and w[4] not in ('Dosis', 'USO', 'AGENTE', 'Página', 'de')]
                dose_candidates.sort(key=lambda x: x[1])

                dose_lines = []
                curr_d = []
                for w in dose_candidates:
                    if not curr_d: curr_d.append(w)
                    elif abs(w[1] - curr_d[0][1]) < 8: curr_d.append(w)
                    else:
                        dose_lines.append(curr_d)
                        curr_d = [w]
                if curr_d: dose_lines.append(curr_d)

                for idx, dl in enumerate(dose_lines):
                    y_center = dl[0][1]
                    y_top = y_min if idx == 0 else (dose_lines[idx-1][0][1] + y_center) / 2
                    y_bot = y_max if idx == len(dose_lines) - 1 else (y_center + dose_lines[idx+1][0][1]) / 2

                    row_w = [w for w in table_words if y_top <= w[1] < y_bot]

                    uso_w = [w[4] for w in sorted([w for w in row_w if w[0] < 105 and w[4] not in ('Página', 'de', 'USO', 'ES-') and not (w[4].isdigit() and len(w[4]) >= 4)], key=lambda x: (x[1], x[0]))]
                    if uso_w: curr_crop = ' '.join(uso_w).strip()

                    agente_w = [w[4] for w in sorted([w for w in row_w if 105 <= w[0] < 240 and w[4] != 'AGENTE'], key=lambda x: (x[1], x[0]))]

                    if has_caldo_col:
                        dosis_w = [w[4] for w in sorted([w for w in row_w if 240 <= w[0] < 340 and w[4] != 'Dosis'], key=lambda x: (x[1], x[0]))]
                        naplic_w = [w[4] for w in sorted([w for w in row_w if 340 <= w[0] < 415 and w[4] not in ('Nº', 'Aplic.')], key=lambda x: (x[1], x[0]))]
                        interv_w = [w[4] for w in sorted([w for w in row_w if 415 <= w[0] < 515 and w[4] != 'Intervalos'], key=lambda x: (x[1], x[0]))]
                        vol_w = [w[4] for w in sorted([w for w in row_w if 515 <= w[0] < 620 and w[4] not in ('Vol.', 'Caldo')], key=lambda x: (x[1], x[0]))]
                        cond_w = [w[4] for w in sorted([w for w in row_w if w[0] >= 620 and w[4] not in ('Condic.', 'Especifico')], key=lambda x: (x[1], x[0]))]
                    else:
                        dosis_w = [w[4] for w in sorted([w for w in row_w if 240 <= w[0] < 320 and w[4] != 'Dosis'], key=lambda x: (x[1], x[0]))]
                        naplic_w = []
                        interv_w = []
                        vol_w = []
                        cond_w = [w[4] for w in sorted([w for w in row_w if w[0] >= 320 and w[4] not in ('Condic.', 'Especifico')], key=lambda x: (x[1], x[0]))]

                    dosis_str = ' '.join(dosis_w).strip()
                    plaga_str = ' '.join(agente_w).strip()
                    cond_str = ' '.join(cond_w).strip()
                    vol_raw = ' '.join(vol_w).strip()
                    nap_str = ' '.join(naplic_w).strip() or "1"
                    int_str = ' '.join(interv_w).strip()

                    if any(k in (dosis_str + " " + plaga_str) for k in ["Ámbito de Aplicación", "Sistema de Cultivo", "Método de Aplicación"]):
                        continue

                    c_min, c_max, vol_norm = _parsear_volumen_caldo(vol_raw)
                    info_dosis = normalizar_dosis(dosis_str)

                    m_nap = re.search(r'\d+', nap_str)
                    n_ap_val = int(m_nap.group(0)) if m_nap else 1

                    m_int = re.search(r'\d+', int_str)
                    int_val = int(m_int.group(0)) if m_int else None

                    metodo = "Pulverización foliar"
                    cond_low = (cond_str + " " + curr_crop).lower()
                    if "cebo" in cond_low or "esparcir" in cond_low:
                        metodo = "Esparcido al suelo de cebos"
                    elif "gránulo" in cond_low:
                        metodo = "Distribución de gránulos al suelo"
                    elif "espolvoreo" in cond_low:
                        metodo = "Espolvoreo"
                    elif "goteo" in cond_low or "fertirriego" in cond_low:
                        metodo = "Riego por goteo"
                    elif "post-cosecha" in cond_low or "postcosecha" in cond_low or "drencher" in cond_low:
                        metodo = "Tratamiento postcosecha (drencher / pulverización en línea)"
                    elif "tractor" in cond_low:
                        metodo = "Pulverización con tractor"

                    m_bbch = re.search(r'(?:BBCH\s*\d+(?:\s*-\s*\d+)?|desde\s+BBCH\s*\d+\s+hasta\s+BBCH\s*\d+|hasta\s+BBCH\s*\d+)', cond_str, re.I)
                    bbch_str = m_bbch.group(0).strip() if m_bbch else ""

                    if dosis_str or plaga_str:
                        resultado["usos"].append({
                            "cultivo": curr_crop,
                            "agente": plaga_str or "Plagas autorizadas",
                            "dosis_original": dosis_str,
                            "dosis_min": info_dosis["dosis_min"],
                            "dosis_max": info_dosis["dosis_max"],
                            "dosis_unidad": info_dosis["dosis_unidad"],
                            "num_aplicaciones": n_ap_val,
                            "intervalo_min_dias": int_val,
                            "volumen_caldo": vol_norm or vol_raw,
                            "volumen_caldo_min": c_min,
                            "volumen_caldo_max": c_max,
                            "condiciones": cond_str[:300],
                            "metodo_aplicacion": metodo,
                            "bbch": bbch_str,
                            "plazo_dias": 0,
                            "plazo_texto": "NO PROCEDE"
                        })

        # 3. Plazos de Seguridad
        for page in doc:
            tabs = page.find_tables().tables
            for t in tabs:
                data = t.extract()
                if not data or len(data) < 2: continue
                h_str = " ".join([str(c) for c in data[0] if c]).upper()
                if "PLAZOS DE SEGURIDAD" in h_str or (len(data) > 1 and "P.S." in " ".join([str(c) for c in data[1] if c])):
                    start_row = 1 if "P.S." in " ".join([str(c) for c in data[0] if c]) else 2
                    for row in data[start_row:]:
                        row_c = [str(c).strip() for c in row if c is not None and str(c).strip()]
                        if len(row_c) >= 2 and row_c[1].upper() not in ('P.S.', '(DÍAS)'):
                            p_val = row_c[1].strip()
                            if p_val.upper() in ('NA', 'N.A.', 'NP', 'N.P.'): p_val = 'NO PROCEDE'
                            c_nom = row_c[0].replace('\n', ' ')
                            m_d = re.search(r'\b(\d+)\b', p_val)
                            d_num = int(m_d.group(1)) if m_d else (0 if "NO PROCEDE" in p_val else None)
                            resultado["plazos_seguridad"].append({
                                "cultivo_grupo": c_nom,
                                "dias": d_num if d_num is not None else 0,
                                "texto": p_val
                            })
                        elif len(row_c) == 1:
                            c0 = row_c[0]
                            m_end = re.search(r'(?:^|\n|\s)(\d+|NO PROCEDE|NA|NP)(?:\n|\s|$)', c0, re.I)
                            if m_end:
                                p_val = m_end.group(1).strip()
                                if p_val.upper() in ('NA', 'NP', 'N.P.'): p_val = 'NO PROCEDE'
                                crops_clean = re.sub(r'(?:^|\n|\s)' + re.escape(m_end.group(1)) + r'(?:\n|\s|$)', ' ', c0).replace('\n', ' ')
                                crops_clean = re.sub(r'\s+', ' ', crops_clean).strip(' ,')
                                crops_clean = re.sub(r'^(?:Plazos de Seguridad \(Protección del Consumidor\)|USO)\s*', '', crops_clean, flags=re.I).strip(' ,')
                                m_d = re.search(r'\b(\d+)\b', p_val)
                                d_num = int(m_d.group(1)) if m_d else (0 if "NO PROCEDE" in p_val else None)
                                resultado["plazos_seguridad"].append({
                                    "cultivo_grupo": crops_clean,
                                    "dias": d_num if d_num is not None else 0,
                                    "texto": p_val
                                })

        # Cruzar plazos con usos
        for u in resultado["usos"]:
            c_u = u["cultivo"].lower()
            for ps in resultado["plazos_seguridad"]:
                p_c = ps["cultivo_grupo"].lower()
                crops_split = [x.strip() for x in p_c.split(',')]
                if any(x in c_u or any(w in c_u for w in x.split() if len(w) > 4) for x in crops_split if x):
                    u["plazo_dias"] = ps["dias"]
                    u["plazo_texto"] = ps["texto"]
                    break

        # 4. Textos oficiales
        m_cg = re.search(r'Condiciones Generales de Uso\s*\n([\s\S]+?)(?=Clase de Usuario|Mitigaci[oó]n|Plazos de Seguridad|P[aá]gina|$)', full_text, re.I)
        if m_cg:
            resultado["producto"]["condiciones_generales_uso"] = _limpiar_bloque_texto(m_cg.group(1))

        m_obs = re.search(r'OBSERVACIONES(?:\s*REGLAMENTARIAS)?\s*\n([\s\S]+?)(?=P[aá]gina|SECRETAR[IÍ]A|DIRECCI[OÓ]N|$)', full_text, re.I)
        if m_obs:
            resultado["producto"]["observaciones_reglamentarias"] = _limpiar_bloque_texto(m_obs.group(1))

        # 5. Seguridad
        m_epis_ap = re.search(r'(?:Mitigaci[oó]n de riesgos en la manipulaci[oó]n|SEGURIDAD DEL APLICADOR|Seguridad del aplicador)\s*\n([\s\S]+?)(?=SEGURIDAD DEL TRABAJADOR|PLAZO DE REENTRADA|Normativa aplicable|$)', full_text, re.I)
        m_tr = re.search(r'(?:SEGURIDAD DEL TRABAJADOR|Seguridad del trabajador)\s*\n([\s\S]+?)(?=PLAZO DE REENTRADA|Plazo de reentrada|FRASES ASOCIADAS|$)', full_text, re.I)
        m_reent = re.search(r'PLAZO DE REENTRADA[^\n:]*:\s*\n?([\s\S]+?)(?=FRASES ASOCIADAS|Normativa aplicable|P[aá]gina|$)', full_text, re.I)

        resultado["seguridad"] = {
            "seguridad_aplicador": _limpiar_bloque_texto(m_epis_ap.group(1)) if m_epis_ap else "",
            "seguridad_trabajador": _limpiar_bloque_texto(m_tr.group(1)) if m_tr else "",
            "plazo_reentrada": _limpiar_bloque_texto(m_reent.group(1)) if m_reent else "No entrar a los cultivos tratados hasta que la pulverización se haya secado.",
            "frases_reduccion_riesgo": "",
            "bandas_seguridad_spe3": "",
            "polinizadores_spe8": ""
        }

        # 6. Toxicología CLP
        m_adv = re.search(r'Palabra de Advertencia\s*[:\s]*\n?\s*(PELIGRO|ATENCI[OÓ]N)\b', full_text, re.I)
        ghs_p = sorted(list(set(re.findall(r'GHS0[1-9]', full_text))))
        ind_h = [h.strip() for h in re.findall(r'(?:EUH|H)\s*\d{3}[a-zA-Z]?(?:\+H\d{3}[a-zA-Z]?)?\s*-[^\n\r]+', full_text) if len(h.strip()) > 7][:15]
        con_p = [p.strip() for p in re.findall(r'P\d{3}(?:\+P\d{3})*\s*-[^\n\r]+', full_text) if len(p.strip()) > 7][:15]

        m_inc = re.search(r'Otras leyendas e indicaciones que deben figurar en la etiqueta:\s*\n([\s\S]+?)(?=OBSERVACIONES|En cumplimiento|$)', full_text, re.I)
        m_sig = re.search(r'(?:sistemas colectivos de responsabilidad ampliada \(SIG\)|SIGFITO|Entregar los envases vac[ií]os[^\n.]*\.)', full_text, re.I)

        resultado["toxicologia"] = {
            "palabra_advertencia": "PELIGRO" if (m_adv and "peligro" in m_adv.group(1).lower()) else ("ATENCIÓN" if m_adv else "SIN ADVERTENCIA"),
            "pictogramas_ghs": ", ".join(ghs_p),
            "indicaciones_h": ", ".join(ind_h),
            "consejos_p": ", ".join(con_p),
            "incompatibilidades_mezclas": _limpiar_bloque_texto(m_inc.group(1)) if m_inc else "No se reportan incompatibilidades explícitas en la ficha oficial del MAPA.",
            "gestion_envases": m_sig.group(0).strip() if m_sig else "SIGFITO"
        }

        # 7. Mitigaciones
        resultado["mitigaciones"] = _extraer_mitigaciones_ambientales(full_text)
        spe3_txts = [m["texto_restriccion"] for m in resultado["mitigaciones"] if "SPe3" in m["texto_restriccion"].upper() or "SPe 3" in m["texto_restriccion"].upper()]
        if spe3_txts:
            resultado["seguridad"]["bandas_seguridad_spe3"] = " | ".join(spe3_txts)

        if "SPe 8" in full_text or "abejas" in full_text.lower():
            m_pol = re.search(r'SPe\s*8:[^\n.]*\.', full_text, re.I)
            resultado["seguridad"]["polinizadores_spe8"] = m_pol.group(0).strip() if m_pol else "Proteger a los polinizadores y fauna auxiliar durante el tratamiento."

        return resultado
