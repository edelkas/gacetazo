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
from bs4 import BeautifulSoup

URL_BASE = "https://gaceta.rsme.es/"
URL_INDICE = URL_BASE + "otrosnumeros.php"

AGENTE_USUARIO = (
    "Mozilla/5.0 (compatible; gaceta-archivador/0.1; "
    "+https://gaceta.rsme.es/) Python-requests"
)

# "Volumen 29 (2026)" -> (29, 2026)
RE_VOLUMEN = re.compile(r"Volumen\s+(\d+)\s*\((\d{4})\)")
# "Número 1" -> 1
RE_NUMERO = re.compile(r"N\w*mero\s+(\d+)")
# "Pág. 271-518" -> (271, 518); se deja laxo, vale cualquier rango numérico
RE_PAGINAS = re.compile(r"(\d+)\s*[-‐-―]\s*(\d+)")
# unos pocos números llevan un volumen extra servido por versuplemento.php
RE_SUPLEMENTO = re.compile(r"versuplemento\.php")


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


def descargar(url):
    """Pide una URL y devuelve su contenido ya decodificado."""
    respuesta = requests.get(url, headers={"User-Agent": AGENTE_USUARIO}, timeout=30)
    respuesta.raise_for_status()
    return respuesta.text


def url_absoluta(enlace):
    """Convierte un enlace relativo como './portadas/x.jpg' en una URL completa."""
    return urljoin(URL_BASE, enlace)


def analizar_numero(celda):
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


def analizar_indice(html):
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
                numero = analizar_numero(celda)
                if numero is not None:
                    pendiente["numeros"].append(numero)
            pendiente["numeros"].sort(key=lambda numero: numero["num"])
            volumenes.append(pendiente)
            pendiente = None

    volumenes.sort(key=lambda volumen: volumen["num"])
    return volumenes


def nombre_carpeta_volumen(volumen):
    """Nombre de carpeta de un volumen, por ejemplo 'Vol 01 (1998)'."""
    return "Vol %02d (%d)" % (volumen["num"], volumen["año"])


def crear_arbol(volumenes, opciones):
    """Crea la estructura de carpetas de volúmenes y números en el destino."""
    creadas = 0

    for volumen in volumenes:
        ruta_volumen = os.path.join(opciones.destino, nombre_carpeta_volumen(volumen))

        for numero in volumen["numeros"]:
            ruta_numero = os.path.join(ruta_volumen, str(numero["num"]))
            if os.path.isdir(ruta_numero):
                continue
            if not opciones.simulacion:
                os.makedirs(ruta_numero)
            creadas += 1
            informar(opciones, "  creada %s" % ruta_numero)

    return creadas


def escribir_mapa(volumenes, opciones):
    """Escribe sitemap.json en la carpeta de destino."""
    ruta = os.path.join(opciones.destino, "sitemap.json")
    mapa = {"volumenes": volumenes}

    if not opciones.simulacion:
        if not os.path.isdir(opciones.destino):
            os.makedirs(opciones.destino)
        with open(ruta, "w", encoding="utf-8") as fichero:
            json.dump(mapa, fichero, ensure_ascii=False, indent=2)
            fichero.write("\n")

    return ruta


def generar_mapa(opciones):
    """Descarga el índice, prepara las carpetas y escribe el mapa."""
    informar(opciones, "Descargando %s ..." % URL_INDICE)
    volumenes = analizar_indice(descargar(URL_INDICE))

    if not volumenes:
        sys.stderr.write(
            "error: no se ha encontrado ningún volumen; "
            "puede que la página haya cambiado de formato\n"
        )
        return 1

    total = sum(len(volumen["numeros"]) for volumen in volumenes)
    informar(
        opciones,
        "Encontrados %d volúmenes y %d números." % (len(volumenes), total),
    )

    creadas = crear_arbol(volumenes, opciones)
    informar(opciones, "Creadas %d carpetas de números nuevas." % creadas)

    ruta = escribir_mapa(volumenes, opciones)
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
            "Archiva La Gaceta de la RSME. Ejecuta con --mapa para crear la "
            "estructura de carpetas de volúmenes y números y el sitemap.json."
        ),
        version="%prog 0.1",
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

    if not opciones.mapa:
        analizador.print_help()
        return 0

    try:
        return generar_mapa(opciones)
    except requests.RequestException as error:
        sys.stderr.write("error: no se ha podido descargar el sitio: %s\n" % error)
        return 1


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
