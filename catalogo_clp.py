"""
catalogo_clp.py - Diccionario Canónico Oficial del Reglamento CLP (CE 1272/2008)
Contiene las descripciones oficiales en español de Pictogramas GHS, Frases H y Consejos P.
"""

PICTOGRAMAS_GHS = {
    "GHS01": {"nombre": "Bomba explotando", "significado": "Peligro de explosión"},
    "GHS02": {"nombre": "Llama", "significado": "Inflamable"},
    "GHS03": {"nombre": "Llama sobre un círculo", "significado": "Comburente"},
    "GHS04": {"nombre": "Botella de gas", "significado": "Gas a presión"},
    "GHS05": {"nombre": "Corrosión", "significado": "Corrosivo para metales o provoca quemaduras graves en la piel"},
    "GHS06": {"nombre": "Calavera y tibias cruzadas", "significado": "Toxicidad aguda grave (mortal o tóxico)"},
    "GHS07": {"nombre": "Signo de exclamación", "significado": "Toxicidad aguda, irritante cutáneo u ocular, o sensibilizante"},
    "GHS08": {"nombre": "Peligro para la salud", "significado": "Mutagénico, carcinógeno, tóxico para la reproducción o por aspiración"},
    "GHS09": {"nombre": "Medio ambiente", "significado": "Peligro para el medio ambiente acuático (flora y fauna)"}
}

FRASES_H = {
    "H200": "Explosivo inestable.",
    "H226": "Líquidos y vapores inflamables.",
    "H300": "Mortal en caso de ingestión.",
    "H301": "Tóxico en caso de ingestión.",
    "H302": "Nocivo en caso de ingestión.",
    "H304": "Puede ser mortal en caso de ingestión y penetración en las vías respiratorias.",
    "H311": "Tóxico en contacto con la piel.",
    "H312": "Nocivo en contacto con la piel.",
    "H314": "Provoca quemaduras graves en la piel y lesiones oculares graves.",
    "H315": "Provoca irritación cutánea.",
    "H317": "Puede provocar una reacción alérgica en la piel.",
    "H318": "Provoca lesiones oculares graves.",
    "H319": "Provoca irritación ocular grave.",
    "H330": "Mortal en caso de inhalación.",
    "H331": "Tóxico en caso de inhalación.",
    "H332": "Nocivo en caso de inhalación.",
    "H335": "Puede irritar las vías respiratorias.",
    "H351": "Se sospecha que provoca cáncer.",
    "H360": "Puede perjudicar la fertilidad o dañar al feto.",
    "H361": "Se sospecha que perjudica la fertilidad o daña al feto.",
    "H372": "Provoca daños en los órganos tras exposiciones prolongadas o repetidas.",
    "H373": "Puede provocar daños en los órganos tras exposiciones prolongadas o repetidas.",
    "H400": "Muy tóxico para los organismos acuáticos.",
    "H410": "Muy tóxico para los organismos acuáticos, con efectos nocivos duraderos.",
    "H411": "Tóxico para los organismos acuáticos, con efectos nocivos duraderos.",
    "H412": "Nocivo para los organismos acuáticos, con efectos nocivos duraderos.",
    "EUH401": "A fin de evitar riesgos para las personas y el medio ambiente, siga las instrucciones de uso."
}

FRASES_P = {
    "P102": "Mantener fuera del alcance de los niños.",
    "P201": "Pedir instrucciones especiales antes del uso.",
    "P202": "No manipular la sustancia antes de haber leído y comprendido todas las instrucciones de seguridad.",
    "P260": "No respirar el polvo/el humo/el gas/la niebla/los vapores/el aerosol.",
    "P261": "Evitar respirar el polvo/el humo/el gas/la niebla/los vapores/el aerosol.",
    "P262": "Evitar el contacto con los ojos, la piel o la ropa.",
    "P264": "Lavarse concienzudamente tras la manipulación.",
    "P270": "No comer, beber ni fumar durante su utilización.",
    "P271": "Utilizar únicamente en exteriores o en un lugar bien ventilado.",
    "P273": "Evitar su liberación al medio ambiente.",
    "P280": "Llevar guantes, prendas, gafas o máscara de protección.",
    "P284": "[En caso de ventilación insuficiente,] llevar equipo de protección respiratoria.",
    "P301": "EN CASO DE INGESTIÓN:",
    "P302": "EN CASO DE CONTACTO CON LA PIEL:",
    "P304": "EN CASO DE INHALACIÓN:",
    "P305": "EN CASO DE CONTACTO CON LOS OJOS:",
    "P310": "Llamar inmediatamente a un CENTRO DE TOXICOLOGÍA o a un médico.",
    "P312": "Llamar a un CENTRO DE TOXICOLOGÍA o a un médico si la persona se encuentra mal.",
    "P330": "Enjuagarse la boca.",
    "P331": "NO provocar el vómito.",
    "P338": "Quitar las lentes de contacto cuando estén presentes y pueda hacerse con facilidad. Proseguir con el lavado.",
    "P340": "Transportar a la persona al aire libre y mantenerla en una posición que le facilite la respiración.",
    "P351": "Enjuagar con agua cuidadosamente durante varios minutos.",
    "P352": "Lavar con abundante agua y jabón.",
    "P353": "Enjuagar la piel con agua o ducharse.",
    "P361": "Quitar inmediatamente toda la ropa contaminada.",
    "P362": "Quitar las prendas contaminadas y lavarlas antes de volver a usarlas.",
    "P391": "Recoger el vertido.",
    "P403": "Almacenar en un lugar bien ventilado.",
    "P405": "Guardar bajo llave.",
    "P501": "Eliminar el contenido o el recipiente conforme a la reglamentación local/nacional (SIGFITO)."
}

def traducir_ghs(codigo: str) -> dict:
    cod = codigo.strip().upper()
    info = PICTOGRAMAS_GHS.get(cod, {"nombre": cod, "significado": "Pictograma oficial de seguridad"})
    return {"codigo": cod, "nombre": info["nombre"], "significado": info["significado"]}

def traducir_h(codigo: str) -> dict:
    cod = codigo.strip().upper()
    texto = FRASES_H.get(cod, "Indicación reglamentaria de peligro oficial")
    return {"codigo": cod, "texto": texto}

def traducir_p(codigo: str) -> dict:
    cod = codigo.strip().upper()
    texto = FRASES_P.get(cod, "Consejo reglamentario de prudencia oficial")
    return {"codigo": cod, "texto": texto}
