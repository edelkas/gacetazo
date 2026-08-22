#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Descargador de La Gaceta de la RSME (https://gaceta.rsme.es).

Construye un archivo local de la revista: una carpeta por volumen, una
subcarpeta por número, y un sitemap.json que describe todo lo encontrado.
"""

import json
import os
import re
import sys
from optparse import IndentedHelpFormatter, OptionParser
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup, Comment

URL_BASE = "https://gaceta.rsme.es/"
URL_INDICE = URL_BASE + "otrosnumeros.php"
NOMBRE_MAPA = "sitemap.json"

# Prefacio que casi todos los números publican junto a la portada, en la
# columna derecha. Va bajo un <h4> que no cuelga de ningún <h3>, así que se
# trata como caso conocido y no como la subsección huérfana que aparenta ser.
TITULO_PORTADA = "Acerca de la portada"
AUTOR_PORTADA = "Redacción de La Gaceta"

AGENTE_USUARIO = (
    "Mozilla/5.0 (compatible; gaceta-archivador/0.1; "
    "+https://gaceta.rsme.es/) Python-requests"
)

# guiones que la revista usa indistintamente en los rangos de páginas
GUIONES = "-‐-―"

# "Volumen 29 (2026)" -> (29, 2026)
RE_VOLUMEN = re.compile(r"Volumen\s+(\d+)\s*\((\d{4})\)")
# "Número 1" -> 1
RE_NUMERO = re.compile(r"N\w*mero\s+(\d+)")
# "Pág. 271-518" -> (271, 518); se deja laxo, vale cualquier rango numérico
RE_PAGINAS = re.compile(r"(\d+)\s*[%s]\s*(\d+)" % GUIONES)
# unos pocos números llevan un volumen extra servido por versuplemento.php
RE_SUPLEMENTO = re.compile(r"versuplemento\.php")

# dentro de la página de un número: cada artículo se abre con abrir.php?id=N
RE_ARTICULO = re.compile(r"abrir\.php\?id=(\d+)")
# los enlaces no usan href, sino onclick='window.open("./destino")'
RE_VENTANA = re.compile(r"""window\.open\(\s*["']([^"']+)["']""")
# y algunos números ofrecen además el ejemplar completo con abrirentero.php
RE_ENTERO = re.compile(r"abrirentero\.php\?id=(\d+)")
# "DOI: 10.63427/ISDN5447"; sólo lo llevan los números recientes
RE_DOI = re.compile(r"DOI:\s*(\S+)")
# "Pág. 103-116" o "Pág. 42"; aquí hay que anclar en "Pág" porque el título
# de un artículo puede contener un rango, como "6 años de La Gaceta (1998-2003)"
RE_PAGINAS_ARTICULO = re.compile(
    r"P[áa]gs?\.?\s*(\d+)\s*(?:[%s]\s*(\d+))?" % GUIONES
)


class FormateadorAyuda(IndentedHelpFormatter):
    """Traduce al español los rótulos fijos que optparse escribe en inglés."""

    def format_usage(self, uso):
        return "Uso: %s\n" % uso

    def format_heading(self, rotulo):
        if rotulo == "Options":
            rotulo = "Opciones"
        return IndentedHelpFormatter.format_heading(self, rotulo)


def informar(opciones, mensaje):
    """Muestra información de progreso salvo que se pida silencio."""
    if not opciones.silencioso:
        print(mensaje)


def avisar(mensaje):
    """Advierte de una anomalía del documento. Siempre se muestra."""
    print("aviso: %s" % mensaje)


def error(mensaje):
    """Escribe un error en la salida de errores y devuelve el código de salida."""
    sys.stderr.write("error: %s\n" % mensaje)
    return 1


def descargar(url):
    """Pide una URL y devuelve su contenido ya decodificado."""
    respuesta = requests.get(url, headers={"User-Agent": AGENTE_USUARIO}, timeout=30)
    respuesta.raise_for_status()
    return respuesta.text


def url_absoluta(enlace):
    """Convierte un enlace relativo como './portadas/x.jpg' en una URL completa."""
    return urljoin(URL_BASE, enlace)


def texto_limpio(elemento):
    """Texto de un elemento con los espacios normalizados a uno solo."""
    return re.sub(r"\s+", " ", elemento.get_text()).strip()


def extraer_doi(texto):
    """Separa el DOI del texto que lo acompaña.

    Devuelve (doi, resto) con el doi a None si no aparece; el resto se
    entrega sin él para que no se duplique allá donde se guarde.
    """
    coincidencia = RE_DOI.search(texto)
    if coincidencia is None:
        return None, texto
    return coincidencia.group(1), RE_DOI.sub("", texto, count=1)


def destino_enlace(etiqueta):
    """Destino de un <a>, que la revista escribe en href o en window.open()."""
    partes = (etiqueta.get("href"), etiqueta.get("onclick"))
    return " ".join(parte for parte in partes if parte)


def url_enlace(etiqueta):
    """URL absoluta de un <a>, o None si no apunta a ninguna parte."""
    if etiqueta.get("href"):
        return url_absoluta(etiqueta["href"])
    coincidencia = RE_VENTANA.search(etiqueta.get("onclick") or "")
    if coincidencia is not None:
        return url_absoluta(coincidencia.group(1))
    return None


# --------------------------------------------------------------------------
# Índice general de volúmenes (otrosnumeros.php)
# --------------------------------------------------------------------------


def analizar_celda_numero(celda):
    """Extrae un número a partir de un <td> de una tabla 'listanumeros'.

    Devuelve None para las celdas de relleno, que no llevan enlace.
    """
    enlace = celda.find("a", href=re.compile(r"vernumero\.php"))
    if enlace is None:
        return None

    coincidencia = RE_NUMERO.search(enlace.get_text(" ", strip=True))
    if coincidencia is None:
        return None

    imagen = celda.find("img")
    portada = url_absoluta(imagen["src"]) if imagen and imagen.get("src") else None

    numero = {
        "num": int(coincidencia.group(1)),
        "portada": portada,
        "link": url_absoluta(enlace["href"]),
    }

    suplemento = celda.find("a", href=RE_SUPLEMENTO)
    if suplemento is not None:
        numero["sup"] = url_absoluta(suplemento["href"])

    # Rango de páginas, escrito normalmente "Pág. 271-518". Se descarta antes
    # el rótulo del número para que un "Número 1" no abra un rango espurio.
    rotulo = enlace.get_text(" ", strip=True)
    texto = celda.get_text(" ", strip=True).replace(rotulo, " ", 1)
    paginas = RE_PAGINAS.search(texto)
    if paginas is not None:
        numero["pagina_inicio"] = int(paginas.group(1))
        numero["pagina_fin"] = int(paginas.group(2))

    return numero


def analizar_indice_volumenes(html):
    """Analiza otrosnumeros.php y devuelve la lista de volúmenes.

    La página presenta cada volumen como un <div class='barravolano'> seguido
    de una <table class='listanumeros'> con sus números, así que recorremos el
    documento en orden y emparejamos cada cabecera con la tabla que le sigue.
    """
    sopa = BeautifulSoup(html, "html.parser")

    volumenes = []
    pendiente = None

    for elemento in sopa.find_all(["div", "table"]):
        clases = elemento.get("class") or []

        if elemento.name == "div" and "barravolano" in clases:
            coincidencia = RE_VOLUMEN.search(elemento.get_text(" ", strip=True))
            pendiente = None
            if coincidencia:
                pendiente = {
                    "num": int(coincidencia.group(1)),
                    "año": int(coincidencia.group(2)),
                    "numeros": [],
                }

        elif elemento.name == "table" and "listanumeros" in clases:
            if pendiente is None:
                continue
            for celda in elemento.find_all("td"):
                numero = analizar_celda_numero(celda)
                if numero is not None:
                    pendiente["numeros"].append(numero)
            pendiente["numeros"].sort(key=lambda numero: numero["num"])
            volumenes.append(pendiente)
            pendiente = None

    volumenes.sort(key=lambda volumen: volumen["num"])
    return volumenes


# --------------------------------------------------------------------------
# Página de un número suelto (vernumero.php)
# --------------------------------------------------------------------------


def analizar_articulo(enlace, id_articulo):
    """Construye la entrada de un artículo a partir de su <a>.

    Los metadatos que lo acompañan (autores en cursiva y rango de páginas)
    van sueltos detrás del enlace, separados por <br />, y ambos son opcionales.
    """
    articulo = {"nombre": texto_limpio(enlace)}

    # El <em> se busca entre los hermanos del enlace y no en todo el párrafo,
    # para no confundir una cursiva del propio título con la firma del autor.
    autor = enlace.find_next_sibling("em")
    if autor is not None:
        articulo["autor"] = texto_limpio(autor)

    articulo["id"] = id_articulo
    articulo["link"] = url_absoluta("abrir.php?id=%d" % id_articulo)

    resto = "".join(
        hermano if isinstance(hermano, str) else hermano.get_text(" ")
        for hermano in enlace.next_siblings
    )
    paginas = RE_PAGINAS_ARTICULO.search(resto)
    if paginas is not None:
        inicio = int(paginas.group(1))
        articulo["pagina_inicio"] = inicio
        # "Pág. 42" es un artículo de una sola página
        articulo["pagina_fin"] = int(paginas.group(2) or inicio)

    doi, _ = extraer_doi(resto)
    if doi is not None:
        articulo["doi"] = doi

    return articulo


def analizar_acerca_portada(celda):
    """Construye el artículo del prefacio que acompaña a la portada.

    No se sirve por abrir.php, sino como PDF suelto, de modo que no tiene ni
    id ni páginas; a cambio suele venir acompañado de un texto de presentación
    que se conserva en 'descripcion'. Cualquiera de los dos puede faltar: los
    números más antiguos traen sólo el texto, y unos pocos sólo el PDF.
    """
    articulo = {"nombre": TITULO_PORTADA, "autor": AUTOR_PORTADA}

    enlace = celda.find("a")
    if enlace is not None:
        destino = url_enlace(enlace)
        if destino is not None:
            articulo["link"] = destino

    # Todo el texto de la celda salvo el del propio <h4>, que repetiría el
    # título, y el del enlace, que no es más que un "(descargar)".
    trozos = [
        texto
        for texto in celda.find_all(string=True)
        if not isinstance(texto, Comment) and texto.find_parent(["h4", "a"]) is None
    ]

    # el DOI viaja en su propia línea dentro de la celda: se guarda aparte y
    # se retira del texto para no repetirlo en la descripción
    doi, resto = extraer_doi("".join(trozos))
    if doi is not None:
        articulo["doi"] = doi

    descripcion = re.sub(r"\s+", " ", resto).strip()
    if descripcion:
        articulo["descripcion"] = descripcion

    if "link" not in articulo and "descripcion" not in articulo:
        avisar("«%s» no trae ni enlace ni texto" % TITULO_PORTADA)

    return articulo


def analizar_anuncio_suplemento(sopa):
    """Datos del suplemento que anuncia la página de un número, si lo trae.

    Viene en un <div class='suplemento'> con su título, su portada y el
    enlace a versuplemento.php; el suplemento en sí se registra aparte, como
    un número más del volumen.
    """
    bloque = sopa.find("div", class_="suplemento")
    if bloque is None:
        return None

    enlace = bloque.find("a", href=RE_SUPLEMENTO)
    if enlace is None:
        return None

    datos = {"link": url_absoluta(enlace["href"])}

    cabecera = bloque.find("h4")
    if cabecera is not None:
        datos["nombre"] = texto_limpio(cabecera)

    imagen = bloque.find("img")
    if imagen is not None and imagen.get("src"):
        datos["portada"] = url_absoluta(imagen["src"])

    return datos


def nueva_seccion(titulo):
    """Crea una sección vacía, que se distingue de un artículo por 'articulos'."""
    return {"nombre": texto_limpio(titulo), "articulos": []}


def avisar_secciones_vacias(entradas, camino=()):
    """Recorre el árbol y avisa de las secciones que no contienen nada."""
    for entrada in entradas:
        if "articulos" not in entrada:
            continue
        rama = camino + (entrada["nombre"],)
        if not entrada["articulos"]:
            avisar("sección sin artículos: %s" % " > ".join(rama))
        else:
            avisar_secciones_vacias(entrada["articulos"], rama)


def analizar_pagina_numero(html):
    """Analiza vernumero.php o versuplemento.php, que comparten formato.

    Devuelve (árbol de artículos, enlace al número entero, suplemento). El
    contenido vive en una <table class='indice'> de varias columnas que se
    recorren de izquierda a derecha. Dentro de cada una, un <h3> abre una
    sección y un <h4> una subsección; los artículos que siguen cuelgan de la
    última abierta, y el final de la columna cierra ambas.
    """
    sopa = BeautifulSoup(html, "html.parser")

    entero = None
    for enlace in sopa.find_all("a"):
        coincidencia = RE_ENTERO.search(destino_enlace(enlace))
        if coincidencia is not None:
            entero = url_absoluta("abrirentero.php?id=%s" % coincidencia.group(1))
            break

    suplemento = analizar_anuncio_suplemento(sopa)

    tabla = sopa.find("table", class_="indice")
    if tabla is None:
        return None, entero, suplemento

    articulos = []
    portada = None

    for celda in tabla.find_all("td"):
        seccion = None
        subseccion = None

        for elemento in celda.find_all(["h3", "h4", "a"]):
            if elemento.find_parent("div", class_="suplemento") is not None:
                continue  # el suplemento se registra como número aparte

            if elemento.name == "h3":
                seccion = nueva_seccion(elemento)
                subseccion = None
                articulos.append(seccion)

            elif elemento.name == "h4":
                if seccion is None and texto_limpio(elemento) == TITULO_PORTADA:
                    # caso conocido: se recoge como artículo suelto y su
                    # cabecera se descarta, en vez de abrir una sección vacía
                    portada = analizar_acerca_portada(celda)

                elif seccion is None:
                    # un <h4> que no cuelga de ningún <h3> no puede ser
                    # subsección de nada, así que lo ascendemos a sección
                    avisar(
                        "subsección huérfana, se trata como sección: %s"
                        % texto_limpio(elemento)
                    )
                    seccion = nueva_seccion(elemento)
                    articulos.append(seccion)
                    subseccion = None
                else:
                    subseccion = nueva_seccion(elemento)
                    seccion["articulos"].append(subseccion)

            else:
                coincidencia = RE_ARTICULO.search(destino_enlace(elemento))
                if coincidencia is None:
                    continue  # no es un artículo: índice, portada, suplemento...
                articulo = analizar_articulo(elemento, int(coincidencia.group(1)))

                contenedor = subseccion or seccion
                if contenedor is None:
                    avisar("artículo fuera de toda sección: %s" % articulo["nombre"])
                    articulos.append(articulo)
                else:
                    contenedor["articulos"].append(articulo)

    # el prefacio vive en la última columna, pero en el ejemplar impreso abre
    # el número, así que encabeza también el árbol
    if portada is not None:
        articulos.insert(0, portada)

    avisar_secciones_vacias(articulos)
    return articulos, entero, suplemento


# --------------------------------------------------------------------------
# Estructura de carpetas y mapa
# --------------------------------------------------------------------------


def es_suplemento(numero):
    """Un número es suplemento de otro si dice de cuál lo es."""
    return "principal" in numero


def nombre_carpeta_volumen(volumen):
    """Nombre de carpeta de un volumen, por ejemplo 'Vol 01 (1998)'."""
    return "Vol %02d (%d)" % (volumen["num"], volumen["año"])


def nombre_carpeta_numero(numero):
    """Nombre de subcarpeta de un número: '2', o '2 sup' si es suplemento.

    Un suplemento comparte el número de aquel al que acompaña, así que hace
    falta el sufijo para que no se pisen dentro del volumen.
    """
    if es_suplemento(numero):
        return "%d sup" % numero["num"]
    return str(numero["num"])


def ordenar_numeros(volumen):
    """Ordena los números dejando cada suplemento tras el número que amplía."""
    volumen["numeros"].sort(
        key=lambda numero: (numero["num"], 1 if es_suplemento(numero) else 0)
    )


def crear_carpeta_numero(volumen, numero, opciones):
    """Crea la carpeta de un número; devuelve su ruta sólo si no existía."""
    ruta = os.path.join(
        opciones.destino,
        nombre_carpeta_volumen(volumen),
        nombre_carpeta_numero(numero),
    )
    if os.path.isdir(ruta):
        return None
    if not opciones.simulacion:
        os.makedirs(ruta)
    return ruta


def crear_arbol(volumenes, opciones):
    """Crea la estructura de carpetas de volúmenes y números en el destino."""
    creadas = 0

    for volumen in volumenes:
        for numero in volumen["numeros"]:
            ruta = crear_carpeta_numero(volumen, numero, opciones)
            if ruta is not None:
                creadas += 1
                informar(opciones, "  creada %s" % ruta)

    return creadas


def ruta_mapa(opciones):
    """Ruta del fichero de mapa dentro de la carpeta de destino."""
    return os.path.join(opciones.destino, NOMBRE_MAPA)


def leer_mapa(opciones):
    """Lee el mapa del disco, o devuelve None si todavía no existe."""
    ruta = ruta_mapa(opciones)
    if not os.path.isfile(ruta):
        return None
    with open(ruta, encoding="utf-8") as fichero:
        return json.load(fichero)


def escribir_mapa(mapa, opciones):
    """Escribe el mapa en la carpeta de destino."""
    ruta = ruta_mapa(opciones)

    if not opciones.simulacion:
        if not os.path.isdir(opciones.destino):
            os.makedirs(opciones.destino)
        with open(ruta, "w", encoding="utf-8") as fichero:
            json.dump(mapa, fichero, ensure_ascii=False, indent=2)
            fichero.write("\n")

    return ruta


def buscar_numero(mapa, num_volumen, num_numero, suplemento=False):
    """Localiza un número dentro del mapa, o (None, None) si no está."""
    for volumen in mapa.get("volumenes", []):
        if volumen["num"] != num_volumen:
            continue
        for numero in volumen["numeros"]:
            if numero["num"] == num_numero and es_suplemento(numero) == suplemento:
                return volumen, numero
    return None, None


def registrar_suplemento(volumen, principal, datos):
    """Crea o actualiza la entrada del suplemento de un número.

    El índice general no menciona el nombre ni la portada del suplemento, así
    que sólo se conocen al visitar la página del número que lo publica.
    """
    entrada = None
    for numero in volumen["numeros"]:
        if es_suplemento(numero) and numero["num"] == principal["num"]:
            entrada = numero
            break

    nueva = entrada is None
    if nueva:
        entrada = {}
        volumen["numeros"].append(entrada)

    # se rehacen las claves de cabecera, pero sin tirar lo que ya se mapeó
    articulos = entrada.pop("articulos", None)
    entrada.clear()
    entrada["num"] = principal["num"]
    if "nombre" in datos:
        entrada["nombre"] = datos["nombre"]
    entrada["principal"] = principal["num"]
    if "portada" in datos:
        entrada["portada"] = datos["portada"]
    entrada["link"] = datos["link"]
    if articulos is not None:
        entrada["articulos"] = articulos

    ordenar_numeros(volumen)
    return entrada, nueva


def fusionar_mapa(volumenes, anterior):
    """Traslada al índice recién descargado lo que ya se había mapeado.

    El índice general sólo conoce la portada y el enlace de cada número, de
    modo que regenerarlo sin más borraría los artículos ya extraídos y los
    suplementos, que ni siquiera figuran en él.
    """
    if anterior is None:
        return 0

    previos = {}
    for volumen in anterior.get("volumenes", []):
        for numero in volumen["numeros"]:
            clave = (volumen["num"], numero["num"], es_suplemento(numero))
            previos[clave] = numero

    conservados = 0

    for volumen in volumenes:
        for numero in volumen["numeros"]:
            viejo = previos.get((volumen["num"], numero["num"], False))
            if viejo is None:
                continue
            for clave in ("link_todo", "articulos"):
                if clave in viejo:
                    numero[clave] = viejo[clave]
            if "articulos" in viejo:
                conservados += 1

        suplementos = [
            viejo
            for (num_vol, _, sup), viejo in previos.items()
            if sup and num_vol == volumen["num"]
        ]
        volumen["numeros"].extend(suplementos)
        conservados += len(suplementos)
        if suplementos:
            ordenar_numeros(volumen)

    return conservados


def mapear_indice(opciones):
    """Descarga el índice general, prepara las carpetas y escribe el mapa."""
    informar(opciones, "Descargando %s ..." % URL_INDICE)
    volumenes = analizar_indice_volumenes(descargar(URL_INDICE))

    if not volumenes:
        return error(
            "no se ha encontrado ningún volumen; "
            "puede que la página haya cambiado de formato"
        )

    total = sum(len(volumen["numeros"]) for volumen in volumenes)
    informar(
        opciones,
        "Encontrados %d volúmenes y %d números." % (len(volumenes), total),
    )

    conservados = fusionar_mapa(volumenes, leer_mapa(opciones))
    if conservados:
        informar(
            opciones,
            "Conservadas %d entradas ya mapeadas del mapa anterior." % conservados,
        )

    creadas = crear_arbol(volumenes, opciones)
    informar(opciones, "Creadas %d carpetas de números nuevas." % creadas)

    ruta = escribir_mapa({"volumenes": volumenes}, opciones)
    informar(opciones, "Escrito %s" % ruta)

    if opciones.simulacion:
        informar(opciones, "(simulación: no se ha escrito nada en el disco)")

    return 0


def contar_articulos(entradas):
    """Cuenta las hojas del árbol, es decir, los artículos de verdad."""
    return sum(
        contar_articulos(entrada["articulos"]) if "articulos" in entrada else 1
        for entrada in entradas
    )


def mapear_numero(opciones):
    """Analiza la página de un número y completa su entrada en el mapa."""
    mapa = leer_mapa(opciones)
    if mapa is None:
        return error(
            "no existe %s; ejecuta antes --mapa para crearlo" % ruta_mapa(opciones)
        )

    volumen, numero = buscar_numero(mapa, opciones.vol, opciones.num, opciones.sup)
    if numero is None:
        if opciones.sup:
            return error(
                "el mapa no recoge ningún suplemento del volumen %d, número %d; "
                "mapea antes ese número para descubrirlo"
                % (opciones.vol, opciones.num)
            )
        return error(
            "el mapa no contiene el volumen %d, número %d"
            % (opciones.vol, opciones.num)
        )

    informar(opciones, "Descargando %s ..." % numero["link"])
    articulos, entero, suplemento = analizar_pagina_numero(descargar(numero["link"]))

    if articulos is None:
        return error(
            "no se ha encontrado el índice del número; "
            "puede que la página haya cambiado de formato"
        )

    numero["articulos"] = articulos
    if entero is not None:
        numero["link_todo"] = entero
    else:
        numero.pop("link_todo", None)

    informar(
        opciones,
        "Vol %02d (%d), número %s: %d artículos en %d entradas de primer nivel."
        % (
            volumen["num"],
            volumen["año"],
            nombre_carpeta_numero(numero),
            contar_articulos(articulos),
            len(articulos),
        ),
    )
    if es_suplemento(numero):
        informar(opciones, "Suplemento «%s»" % numero.get("nombre", "sin título"))
    informar(
        opciones,
        "Número entero: %s" % (entero if entero else "no disponible, sólo por partes"),
    )

    if suplemento is not None:
        entrada, nueva = registrar_suplemento(volumen, numero, suplemento)
        informar(
            opciones,
            "Suplemento %s: «%s» (número %s)"
            % (
                "registrado" if nueva else "actualizado",
                entrada.get("nombre", "sin título"),
                nombre_carpeta_numero(entrada),
            ),
        )
        ruta = crear_carpeta_numero(volumen, entrada, opciones)
        if ruta is not None:
            informar(opciones, "  creada %s" % ruta)

    ruta = escribir_mapa(mapa, opciones)
    informar(opciones, "Escrito %s" % ruta)

    if opciones.simulacion:
        informar(opciones, "(simulación: no se ha escrito nada en el disco)")

    return 0


def principal(argumentos):
    # Los mensajes llevan acentos; en una consola con codificación limitada
    # se sustituyen los caracteres en vez de abortar con UnicodeEncodeError.
    for flujo in (sys.stdout, sys.stderr):
        if hasattr(flujo, "reconfigure"):
            flujo.reconfigure(errors="replace")

    analizador = OptionParser(
        usage="%prog [opciones]",
        description=(
            "Archiva La Gaceta de la RSME. Con --mapa a secas construye la "
            "estructura de carpetas y el sitemap.json; añadiendo --vol y --num "
            "completa el índice de artículos de ese número concreto."
        ),
        version="%prog 0.2",
        formatter=FormateadorAyuda(),
        add_help_option=False,
    )
    analizador.add_option(
        "-h", "--ayuda",
        action="help",
        help="muestra esta ayuda y termina",
    )
    analizador.get_option("--version").help = "muestra la versión del programa y termina"
    analizador.add_option(
        "-m", "--mapa",
        action="store_true", default=False,
        help="descarga el índice de volúmenes, crea las carpetas y escribe sitemap.json",
    )
    analizador.add_option(
        "-v", "--vol",
        type="int", metavar="N",
        help="número de volumen sobre el que actuar",
    )
    analizador.add_option(
        "-N", "--num",
        type="int", metavar="N",
        help="número dentro del volumen indicado con --vol",
    )
    analizador.add_option(
        "-s", "--sup",
        action="store_true", default=False,
        help="actúa sobre el suplemento de ese número, no sobre el número",
    )
    analizador.add_option(
        "-d", "--destino",
        metavar="DIR", default=".",
        help="carpeta raíz del archivo [por defecto: %default]",
    )
    analizador.add_option(
        "-n", "--simulacion",
        action="store_true", default=False,
        help="indica lo que se haría, sin crear ni escribir nada",
    )
    analizador.add_option(
        "-q", "--silencioso",
        action="store_true", default=False,
        help="no muestra información de progreso",
    )

    opciones, sueltos = analizador.parse_args(argumentos)

    if sueltos:
        analizador.error("argumento inesperado: %s" % sueltos[0])

    if (opciones.vol is None) != (opciones.num is None):
        analizador.error("--vol y --num deben indicarse juntos")

    if opciones.sup and opciones.vol is None:
        analizador.error("--sup necesita que se indiquen --vol y --num")

    if not opciones.mapa and opciones.vol is None:
        analizador.print_help()
        return 0

    try:
        if opciones.vol is None:
            return mapear_indice(opciones)
        if opciones.mapa:
            return mapear_numero(opciones)
        return error("la descarga de números todavía no está implementada")
    except requests.RequestException as fallo:
        return error("no se ha podido descargar el sitio: %s" % fallo)


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
