#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Descargador de La Gaceta de la RSME (https://gaceta.rsme.es).

Construye un archivo local de la revista: una carpeta por volumen, una
subcarpeta por número, y un sitemap.json que describe todo lo encontrado.
"""

import hashlib
import json
import os
import re
import shutil
import sys
import time
from collections import deque
from optparse import IndentedHelpFormatter, OptionParser
from urllib.parse import urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Comment

URL_BASE = "https://gaceta.rsme.es/"
SERVIDOR = urlparse(URL_BASE).hostname
URL_INDICE = URL_BASE + "otrosnumeros.php"
URL_ACCESO = URL_BASE + "control.php"
NOMBRE_MAPA = "sitemap.json"

# el formulario de acceso de la portada manda a control.php estos tres campos,
# y el servidor responde redirigiendo: a la dirección pedida si las
# credenciales valen, o de vuelta a login.php si no
DIRECCION_ACCESO = "index.php"
DESTINO_RECHAZO = "login.php"

# Prefacio que casi todos los números publican junto a la portada, en la
# columna derecha. Va bajo un <h4> que no cuelga de ningún <h3>, así que se
# trata como caso conocido y no como la subsección huérfana que aparenta ser.
TITULO_PORTADA = "Acerca de la portada"
AUTOR_PORTADA = "Redacción de La Gaceta"

# nombres de fichero fijos dentro de la carpeta de cada número
FICHERO_PORTADA = "Portada"
FICHERO_ENTERO = "Número completo"

# Windows prohíbe estos caracteres en un nombre de fichero, y también los
# nombres heredados de los dispositivos del DOS
RE_PROHIBIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVADOS = {"CON", "PRN", "AUX", "NUL"}
RESERVADOS |= {"COM%d" % n for n in range(1, 10)}
RESERVADOS |= {"LPT%d" % n for n in range(1, 10)}
# los títulos de los artículos pueden ser larguísimos, y la ruta completa no
# debería acercarse al límite de 260 caracteres de Windows
LARGO_NOMBRE = 120

# tamaño del trozo con que se leen y escriben los ficheros
TROZO = 64 * 1024

# extensión a usar según lo que anuncie el servidor, ya que abrir.php sirve
# todos los artículos con el mismo nombre genérico
EXTENSIONES = {
    "application/pdf": ".pdf",
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
}
RE_ADJUNTO = re.compile(r'filename\*?=(?:"([^"]+)"|([^;]+))', re.IGNORECASE)

AGENTE_USUARIO = (
    "Mozilla/5.0 (compatible; gaceta-archivador/0.1; "
    "+https://gaceta.rsme.es/) Python-requests"
)

# La revista reconoce al socio por su cookie de sesión de PHP. Suele ser de 32
# dígitos hexadecimales, pero la longitud es configurable en el servidor.
COOKIE_SESION = "PHPSESSID"
RE_COOKIE = re.compile(r"^[0-9a-fA-F]{22,256}$")

# una única sesión para todas las peticiones, que es quien lleva la cookie
SESION = requests.Session()
SESION.headers["User-Agent"] = AGENTE_USUARIO

# guiones que la revista usa indistintamente en los rangos de páginas
GUIONES = "-‐-―"

# "Volumen 29 (2026)" -> (29, 2026)
RE_VOLUMEN = re.compile(r"Volumen\s+(\d+)\s*\((\d{4})\)")
# "Número 1" -> 1
RE_NUMERO = re.compile(r"N\w*mero\s+(\d+)")
# "Pág. 271-518" -> (271, 518); se deja laxo, vale cualquier rango numérico
RE_PAGINAS = re.compile(r"(\d+)\s*[%s]\s*(\d+)" % GUIONES)
# cada número se consulta con vernumero.php?id=N, y ese N lo identifica
RE_NUMERO_ID = re.compile(r"vernumero\.php\?id=(\d+)")
# unos pocos números llevan un volumen extra servido por versuplemento.php
RE_SUPLEMENTO = re.compile(r"versuplemento\.php\?id=(\d+)")

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


def habilitar_ansi():
    """Enciende las secuencias de escape en las consolas de Windows."""
    if os.name != "nt":
        return True
    try:
        import ctypes

        kernel = ctypes.windll.kernel32
        modo = ctypes.c_uint()
        asa = kernel.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        if not kernel.GetConsoleMode(asa, ctypes.byref(modo)):
            return False
        # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        return bool(kernel.SetConsoleMode(asa, modo.value | 0x0004))
    except Exception:
        return False


def formato_bytes(cantidad):
    """Tamaño en MB con un decimal, que es la escala de estos ficheros."""
    return "%.1f MB" % (cantidad / (1024.0 * 1024.0))


class Barra:
    """Barra de estado anclada a la última línea de la consola.

    Cualquier mensaje se escribe por encima de ella: se borra la línea, se
    suelta el texto y se vuelve a pintar la barra debajo. Así nunca quedan
    barras huérfanas por la pantalla.
    """

    INTERVALO = 1.0  # segundos entre repintados
    VENTANA = 5.0  # segundos que promedia la velocidad
    MUESTREO = 0.2  # cada cuánto se anota una marca para la velocidad

    BORRAR_LINEA = "\r\033[2K"

    def __init__(self):
        self.activa = False
        self.pintada = False
        self.contexto = ""
        self.hechos = 0
        self.total = 0
        self.bytes_fichero = 0
        self.bytes_total = 0
        self.marcas = deque()
        self.ultimo_pintado = 0.0
        self.ultima_marca = 0.0

    # -- control ----------------------------------------------------------

    def arrancar(self, opciones):
        """Activa la barra si la consola la admite y no se pidió silencio."""
        self.activa = (
            not opciones.silencioso
            and sys.stdout.isatty()
            and habilitar_ansi()
        )
        self.hechos = self.total = 0
        self.bytes_fichero = self.bytes_total = 0
        self.marcas.clear()

    def parar(self):
        """Retira la barra y deja la consola como estaba."""
        if self.activa and self.pintada:
            sys.stdout.write(self.BORRAR_LINEA)
            sys.stdout.flush()
        self.pintada = False
        self.activa = False

    # -- contenido --------------------------------------------------------

    def situar(self, contexto):
        """Fija el rótulo de lo que se está descargando ahora mismo."""
        self.contexto = contexto
        self.refrescar(forzar=True)

    def ampliar(self, cuantos):
        """Suma ficheros al total previsto, que se va descubriendo sobre la marcha."""
        self.total += cuantos
        self.refrescar(forzar=True)

    def abrir_fichero(self):
        """Empieza a contar un fichero nuevo."""
        self.bytes_fichero = 0

    def avanzar(self, cuantos):
        """Anota los bytes recién recibidos."""
        self.bytes_fichero += cuantos
        self.bytes_total += cuantos

        ahora = time.monotonic()
        if ahora - self.ultima_marca >= self.MUESTREO:
            self.marcas.append((ahora, self.bytes_total))
            self.ultima_marca = ahora
        self.refrescar()

    def cerrar_fichero(self):
        """Da por terminado un fichero, se haya bajado o no."""
        self.hechos += 1
        self.refrescar(forzar=True)

    # -- pintado ----------------------------------------------------------

    def velocidad(self, ahora):
        """Ritmo medio de los últimos segundos, o None si aún no se sabe."""
        while len(self.marcas) > 1 and ahora - self.marcas[0][0] > self.VENTANA:
            self.marcas.popleft()
        if len(self.marcas) < 2:
            return None
        inicio, bytes_inicio = self.marcas[0]
        fin, bytes_fin = self.marcas[-1]
        if fin <= inicio:
            return None
        return (bytes_fin - bytes_inicio) / (fin - inicio)

    def texto(self, ahora):
        """Compone la línea de estado."""
        piezas = []
        if self.contexto:
            piezas.append(self.contexto)
        piezas.append("%d de %d" % (self.hechos, self.total))
        piezas.append(
            "%s (total %s)"
            % (formato_bytes(self.bytes_fichero), formato_bytes(self.bytes_total))
        )
        ritmo = self.velocidad(ahora)
        if ritmo is not None:
            piezas.append("%s/s" % formato_bytes(ritmo))

        linea = " · ".join(piezas)
        ancho = shutil.get_terminal_size((80, 24)).columns - 1
        return linea[:ancho]

    def refrescar(self, forzar=False):
        """Repinta la barra, como mucho una vez por segundo."""
        if not self.activa:
            return
        ahora = time.monotonic()
        if not forzar and ahora - self.ultimo_pintado < self.INTERVALO:
            return
        self.ultimo_pintado = ahora
        sys.stdout.write(self.BORRAR_LINEA + self.texto(ahora))
        sys.stdout.flush()
        self.pintada = True

    def escribir(self, mensaje, flujo=None):
        """Suelta un mensaje por encima de la barra y la vuelve a pintar."""
        destino = flujo or sys.stdout
        if not self.activa:
            destino.write(mensaje + "\n")
            destino.flush()
            return

        sys.stdout.write(self.BORRAR_LINEA)
        sys.stdout.flush()
        destino.write(mensaje + "\n")
        destino.flush()
        self.refrescar(forzar=True)


BARRA = Barra()


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
        BARRA.escribir(mensaje)


def avisar(mensaje):
    """Advierte de una anomalía del documento. Siempre se muestra."""
    BARRA.escribir("aviso: %s" % mensaje)


def error(mensaje):
    """Escribe un error en la salida de errores y devuelve el código de salida."""
    BARRA.escribir("error: %s" % mensaje, sys.stderr)
    return 1


def asegurar_https(url):
    """Eleva a HTTPS los enlaces de la revista que vengan en claro.

    El servidor atiende igual por HTTP y no redirige a HTTPS, de modo que un
    solo enlace absoluto en claro bastaría para mandar la sesión sin cifrar.
    """
    partes = urlparse(url)
    if partes.scheme == "http" and partes.hostname == SERVIDOR:
        return urlunparse(partes._replace(scheme="https"))
    return url


def comprobar_cifrado(respuesta):
    """Avisa si alguna redirección ha sacado la petición de HTTPS."""
    for salto in respuesta.history + [respuesta]:
        if urlparse(salto.url).scheme != "https":
            avisar("la petición ha acabado sin cifrar en %s" % salto.url)
            return False
    return True


def pedir(url, flujo=False):
    """Pide una URL y devuelve la respuesta, ya comprobada."""
    respuesta = SESION.get(asegurar_https(url), timeout=60, stream=flujo)
    respuesta.raise_for_status()
    comprobar_cifrado(respuesta)
    return respuesta


def usar_cookie(valor):
    """Empieza a presentarse como socio con esa cookie de sesión.

    Se marca como segura para que no salga nunca por una conexión en claro,
    ya que vale tanto como la contraseña.
    """
    SESION.cookies.set(
        COOKIE_SESION, valor, domain=SERVIDOR, path="/", secure=True
    )


def acceder(usuario, contrasena):
    """Entra como socio y devuelve la cookie obtenida, o None si la rechazan.

    Es el mismo POST que hace el formulario de la portada. El servidor no
    devuelve ningún mensaje: se sabe si ha colado por adónde redirige.
    """
    # el formulario viaja sin cifrar de ninguna otra forma: si esto no fuera
    # HTTPS, la contraseña iría en claro por la red
    if urlparse(URL_ACCESO).scheme != "https":
        raise ValueError("el acceso exige HTTPS: %s" % URL_ACCESO)

    SESION.cookies.clear()
    respuesta = SESION.post(
        URL_ACCESO,
        data={
            "usuario": usuario,
            "contrasena": contrasena,
            "direccion": DIRECCION_ACCESO,
        },
        allow_redirects=False,
        timeout=60,
    )
    respuesta.raise_for_status()

    if DESTINO_RECHAZO in respuesta.headers.get("Location", ""):
        SESION.cookies.clear()
        return None

    return SESION.cookies.get(COOKIE_SESION)


def descartar_cookie(opciones):
    """Deja de usar la cookie: la revista no la ha reconocido."""
    if not opciones.cookie_activa:
        return
    avisar(
        "la revista no reconoce la cookie de sesión: será inválida o habrá "
        "caducado. Se descarta y se sigue como visitante"
    )
    SESION.cookies.clear()
    opciones.cookie_activa = None


def descargar(url):
    """Pide una URL y devuelve su contenido ya decodificado."""
    return pedir(url).text


def es_muro(respuesta):
    """Indica si la respuesta acabó en el formulario de acceso para socios."""
    return "login.php" in respuesta.url


def extension_de(respuesta):
    """Extensión que corresponde a lo que ha servido el servidor."""
    adjunto = RE_ADJUNTO.search(respuesta.headers.get("Content-Disposition", ""))
    if adjunto is not None:
        nombre = (adjunto.group(1) or adjunto.group(2)).strip()
        extension = os.path.splitext(nombre)[1]
        if extension:
            return extension.lower()

    tipo = respuesta.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if tipo in EXTENSIONES:
        return EXTENSIONES[tipo]

    return os.path.splitext(urlparse(respuesta.url).path)[1].lower()


def sanear_nombre(nombre):
    """Convierte un título en un nombre de fichero admisible en Windows."""
    limpio = RE_PROHIBIDOS.sub("", nombre)
    limpio = re.sub(r"\s+", " ", limpio).strip()
    limpio = limpio[:LARGO_NOMBRE]
    # un nombre no puede acabar en punto ni en espacio
    limpio = limpio.rstrip(" .")
    if not limpio:
        return "sin título"
    if limpio.upper() in RESERVADOS:
        return limpio + "_"
    return limpio


def nombre_libre(carpeta, nombre, usados):
    """Añade un sufijo al nombre si dos artículos comparten título."""
    candidato = nombre
    orden = 1
    while candidato.lower() in usados:
        orden += 1
        candidato = "%s (%d)" % (nombre, orden)
    usados.add(candidato.lower())
    return candidato


def md5_de(ruta):
    """Hash MD5 de un fichero ya guardado en el disco."""
    digest = hashlib.md5()
    with open(ruta, "rb") as fichero:
        for trozo in iter(lambda: fichero.read(TROZO), b""):
            digest.update(trozo)
    return digest.hexdigest()


def ruta_relativa(ruta, opciones):
    """Ruta relativa a la raíz del archivo, con barras normales.

    Se guarda así, y no con la barra invertida de Windows, para que el mapa
    sea legible y sirva igual en cualquier sistema.
    """
    return os.path.relpath(ruta, opciones.destino).replace(os.sep, "/")


def fichero_existente(carpeta, nombre):
    """Ruta del fichero ya descargado con ese nombre, sea cual sea su extensión."""
    if not os.path.isdir(carpeta):
        return None
    for entrada in os.listdir(carpeta):
        if os.path.splitext(entrada)[0] == nombre:
            return os.path.join(carpeta, entrada)
    return None


def url_absoluta(enlace):
    """Convierte un enlace relativo como './portadas/x.jpg' en una URL completa."""
    return asegurar_https(urljoin(URL_BASE, enlace))


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
    enlace = celda.find("a", href=RE_NUMERO_ID)
    if enlace is None:
        return None

    coincidencia = RE_NUMERO.search(enlace.get_text(" ", strip=True))
    if coincidencia is None:
        return None

    imagen = celda.find("img")
    portada = url_absoluta(imagen["src"]) if imagen and imagen.get("src") else None

    numero = {
        "num": int(coincidencia.group(1)),
        "id": int(RE_NUMERO_ID.search(enlace["href"]).group(1)),
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

    datos = {
        "id": int(RE_SUPLEMENTO.search(enlace["href"]).group(1)),
        "link": url_absoluta(enlace["href"]),
    }

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


def ruta_carpeta_numero(volumen, numero, opciones):
    """Ruta de la carpeta de un número dentro del destino."""
    return os.path.join(
        opciones.destino,
        nombre_carpeta_volumen(volumen),
        nombre_carpeta_numero(numero),
    )


def asegurar_carpeta(ruta, opciones):
    """Crea la carpeta si falta; indica si ha habido que crearla.

    Las carpetas se abren al descargar, y sólo las de aquello que se descarga,
    para no sembrar el destino de directorios vacíos.
    """
    if os.path.isdir(ruta):
        return False
    if not opciones.simulacion:
        os.makedirs(ruta)
    return True


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


def preparar_cookie(mapa, opciones):
    """Deja lista la sesión de socio, si la hay. Indica si se puede seguir.

    Manda la cookie que se haya indicado a mano; en su defecto se entra con
    usuario y contraseña, y si tampoco los hay se recurre a la cookie que
    quedara anotada de una ejecución anterior.
    """
    valor = opciones.cookie
    recien_accedido = False

    if not valor and opciones.usuario:
        informar(opciones, "Accediendo como %s ..." % opciones.usuario)
        valor = acceder(opciones.usuario, opciones.contrasena)
        if valor is None:
            error("la revista ha rechazado ese usuario o esa contraseña")
            return False
        informar(opciones, "Acceso concedido.")
        recien_accedido = True

    if not valor:
        valor = (mapa or {}).get("cookie")

    opciones.cookie_activa = valor
    if valor:
        usar_cookie(valor)
        if not recien_accedido:
            informar(opciones, "Sesión de socio activa.")
    return True


def anotar_cookie(mapa, opciones):
    """Guarda la cookie en el mapa, o la retira si ha dejado de valer."""
    if opciones.cookie_activa:
        mapa["cookie"] = opciones.cookie_activa
    else:
        mapa.pop("cookie", None)


def escribir_mapa(mapa, opciones):
    """Escribe el mapa en la carpeta de destino."""
    ruta = ruta_mapa(opciones)
    anotar_cookie(mapa, opciones)

    # la cookie va delante, que si no queda sepultada bajo los volúmenes
    contenido = {}
    if mapa.get("cookie"):
        contenido["cookie"] = mapa["cookie"]
    contenido.update(mapa)
    mapa = contenido

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
    entrada["id"] = datos["id"]
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
    """Descarga el índice general de volúmenes y escribe el mapa."""
    anterior = leer_mapa(opciones)
    if not preparar_cookie(anterior, opciones):
        return 1

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

    conservados = fusionar_mapa(volumenes, anterior)
    if conservados:
        informar(
            opciones,
            "Conservadas %d entradas ya mapeadas del mapa anterior." % conservados,
        )

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

    if not preparar_cookie(mapa, opciones):
        return 1

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

    codigo = mapear_entrada(volumen, numero, opciones)
    if codigo:
        return codigo

    ruta = escribir_mapa(mapa, opciones)
    informar(opciones, "Escrito %s" % ruta)

    if opciones.simulacion:
        informar(opciones, "(simulación: no se ha escrito nada en el disco)")

    return 0


def mapear_entrada(volumen, numero, opciones):
    """Rellena la entrada de un número a partir de su página."""
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

    return 0


# --------------------------------------------------------------------------
# Descarga
# --------------------------------------------------------------------------


def conviene_rehacer(previo, entrada, opciones):
    """Decide si hay que volver a bajar un fichero que ya está en el disco.

    Se rehace cuando su MD5 no cuadra con el anotado en el mapa, y también
    cuando no hay ninguno anotado, porque entonces no hay forma de saber si
    lo que hay en el disco está entero.
    """
    if entrada is None:
        return False  # sin entrada donde anotarlo, basta con que exista

    registro = entrada.get("fichero") or {}
    if not registro.get("md5"):
        informar(opciones, "  sin MD5 anotado, se vuelve a bajar: %s" % previo)
        return True

    if md5_de(previo) != registro["md5"]:
        avisar("%s no cuadra con su MD5; se vuelve a bajar" % previo)
        return True

    return False


def guardar(url, carpeta, nombre, opciones, resumen, entrada=None):
    """Descarga una URL en la carpeta dada, con el nombre dado y su extensión.

    Si se le pasa la entrada del mapa correspondiente, anota en ella la ruta,
    el tamaño y el MD5 de lo descargado. Devuelve el estado: 'existe',
    'guardado', 'reservado' o 'error'.
    """
    BARRA.abrir_fichero()
    try:
        return intentar_guardar(url, carpeta, nombre, opciones, resumen, entrada)
    finally:
        BARRA.cerrar_fichero()


def intentar_guardar(url, carpeta, nombre, opciones, resumen, entrada):
    """Lo que hace guardar(), sin la contabilidad de la barra."""
    previo = fichero_existente(carpeta, nombre)

    if previo is None and entrada is not None:
        # el fichero ya no está: el registro que hubiera es papel mojado
        entrada.pop("fichero", None)

    rehacer = False
    if previo is not None:
        rehacer = conviene_rehacer(previo, entrada, opciones)
        if not rehacer:
            resumen["existe"] += 1
            return "existe"

    try:
        respuesta = pedir(url, flujo=True)
    except requests.RequestException as fallo:
        avisar("no se ha podido descargar %s: %s" % (url, fallo))
        resumen["error"] += 1
        return "error"

    with respuesta:
        # los números más recientes están reservados a los socios: la página
        # se consulta, pero el PDF redirige al formulario de acceso
        if es_muro(respuesta):
            # si veníamos autenticados, la cookie ya no sirve para nada
            descartar_cookie(opciones)
            resumen["reservado"] += 1
            informar(opciones, "  reservado a socios: %s" % nombre)
            return "reservado"

        ruta = os.path.join(carpeta, nombre + extension_de(respuesta))
        if opciones.simulacion:
            resumen["guardado"] += 1
            informar(opciones, "  se guardaría %s" % ruta)
            return "guardado"

        digest = hashlib.md5()
        tamaño = 0
        try:
            with open(ruta, "wb") as fichero:
                for trozo in respuesta.iter_content(TROZO):
                    fichero.write(trozo)
                    digest.update(trozo)
                    tamaño += len(trozo)
                    BARRA.avanzar(len(trozo))
        except requests.RequestException as fallo:
            avisar("se ha cortado la descarga de %s: %s" % (url, fallo))
            if os.path.exists(ruta):
                os.remove(ruta)  # no dejar un fichero a medias
            resumen["error"] += 1
            return "error"

    # si la extensión ha cambiado, el fichero viejo sobra
    if previo is not None and os.path.abspath(previo) != os.path.abspath(ruta):
        os.remove(previo)

    if entrada is not None:
        entrada["fichero"] = {
            "ruta": ruta_relativa(ruta, opciones),
            "tamaño": tamaño,
            "md5": digest.hexdigest(),
        }

    if rehacer:
        resumen["rehecho"] += 1
    else:
        resumen["guardado"] += 1
    informar(opciones, "  %s" % ruta)
    return "guardado"


def descargar_articulos(entradas, carpeta, opciones, resumen, usados):
    """Recorre el árbol y descarga cada artículo que tenga enlace."""
    for entrada in entradas:
        if "articulos" in entrada:
            descargar_articulos(entrada["articulos"], carpeta, opciones, resumen, usados)
            continue

        if "link" not in entrada:
            continue  # p. ej. un «Acerca de la portada» que sólo trae texto

        nombre = nombre_libre(carpeta, sanear_nombre(entrada["nombre"]), usados)
        guardar(entrada["link"], carpeta, nombre, opciones, resumen, entrada)


def contar_descargables(entradas):
    """Hojas del árbol que tienen algo que descargar."""
    return sum(
        contar_descargables(entrada["articulos"])
        if "articulos" in entrada
        else (1 if "link" in entrada else 0)
        for entrada in entradas
    )


def ficheros_previstos(numero, opciones):
    """Cuántos ficheros se van a intentar bajar de un número."""
    previstos = 1 if numero.get("portada") else 0
    if opciones.entero and numero.get("link_todo"):
        return previstos + 1
    return previstos + contar_descargables(numero["articulos"])


def descargar_numero(volumen, numero, opciones, resumen, posicion=""):
    """Descarga la portada y el contenido de un número en su carpeta."""
    etiqueta = "Vol %02d (%d), número %s" % (
        volumen["num"],
        volumen["año"],
        nombre_carpeta_numero(numero),
    )
    if posicion:
        etiqueta = "%s %s" % (posicion, etiqueta)
    informar(opciones, etiqueta)

    if "articulos" not in numero:
        informar(opciones, "  sin mapear todavía; se mapea primero")
        codigo = mapear_entrada(volumen, numero, opciones)
        if codigo:
            return codigo
        resumen["mapeados"] += 1

    BARRA.situar(etiqueta)
    BARRA.ampliar(ficheros_previstos(numero, opciones))

    carpeta = ruta_carpeta_numero(volumen, numero, opciones)
    if asegurar_carpeta(carpeta, opciones):
        informar(opciones, "  creada %s" % carpeta)

    if numero.get("portada"):
        guardar(numero["portada"], carpeta, FICHERO_PORTADA, opciones, resumen)

    if opciones.entero and numero.get("link_todo"):
        estado = guardar(
            numero["link_todo"], carpeta, FICHERO_ENTERO, opciones, resumen, numero
        )
        if estado in ("guardado", "existe"):
            return 0
        # reservado a socios o caído: los artículos sueltos suelen seguir ahí
        informar(opciones, "  no se ha podido traer entero; se baja por partes")
        BARRA.ampliar(contar_descargables(numero["articulos"]))
    elif opciones.entero:
        informar(opciones, "  no se ofrece entero; se baja por partes")

    descargar_articulos(numero["articulos"], carpeta, opciones, resumen, set())
    return 0


def nuevo_resumen():
    """Contadores de una tanda de descargas."""
    return dict(guardado=0, existe=0, reservado=0, error=0, mapeados=0, rehecho=0)


def contar_resumen(opciones, resumen):
    """Informa de cómo ha ido la tanda."""
    informar(
        opciones,
        "Ficheros: %d nuevos, %d ya estaban, %d reservados a socios, %d fallidos."
        % (
            resumen["guardado"],
            resumen["existe"],
            resumen["reservado"],
            resumen["error"],
        ),
    )
    if resumen["rehecho"]:
        informar(
            opciones,
            "Se han rehecho %d ficheros por MD5 ausente o incorrecto."
            % resumen["rehecho"],
        )
    if resumen["mapeados"]:
        informar(opciones, "Se han mapeado %d números por el camino." % resumen["mapeados"])
    if opciones.simulacion:
        informar(opciones, "(simulación: no se ha escrito nada en el disco)")


def confirmar(pregunta):
    """Pide una confirmación por consola; un stdin cerrado equivale a que no."""
    try:
        respuesta = input("%s [s/N] " % pregunta)
    except EOFError:
        return False
    return respuesta.strip().lower() in ("s", "si", "sí")


def descargar_uno(opciones):
    """Descarga el número indicado con --vol, --num y, si acaso, --sup."""
    mapa = leer_mapa(opciones)
    if mapa is None:
        return error(
            "no existe %s; ejecuta antes --mapa para crearlo" % ruta_mapa(opciones)
        )

    if not preparar_cookie(mapa, opciones):
        return 1

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

    resumen = nuevo_resumen()
    BARRA.arrancar(opciones)
    try:
        codigo = descargar_numero(volumen, numero, opciones, resumen)
    finally:
        BARRA.parar()
    if codigo:
        return codigo

    # la descarga anota en el mapa lo que va guardando
    ruta = escribir_mapa(mapa, opciones)
    informar(opciones, "Escrito %s" % ruta)

    contar_resumen(opciones, resumen)
    return 0


def descargar_todo(opciones):
    """Descarga el archivo entero, previa confirmación."""
    mapa = leer_mapa(opciones)
    if mapa is None:
        return error(
            "no existe %s; ejecuta antes --mapa para crearlo" % ruta_mapa(opciones)
        )

    if not preparar_cookie(mapa, opciones):
        return 1

    numeros = [
        (volumen, numero)
        for volumen in mapa["volumenes"]
        for numero in volumen["numeros"]
    ]
    pendientes = sum(1 for _, numero in numeros if "articulos" not in numero)

    # la simulación no toca el disco, así que no hay nada que confirmar
    if not opciones.simulacion:
        aviso = "Se van a descargar %d números" % len(numeros)
        if pendientes:
            aviso += ", mapeando antes %d de ellos" % pendientes
        aviso += ". Esto tardará un buen rato. ¿Seguimos?"
        if not confirmar(aviso):
            informar(opciones, "Cancelado.")
            return 0

    resumen = nuevo_resumen()
    BARRA.arrancar(opciones)
    try:
        for orden, (volumen, numero) in enumerate(numeros, 1):
            codigo = descargar_numero(
                volumen, numero, opciones, resumen, "[%d/%d]" % (orden, len(numeros))
            )
            if codigo:
                return codigo
            # se guarda número a número para no perder el avance si se interrumpe
            escribir_mapa(mapa, opciones)
    finally:
        BARRA.parar()

    contar_resumen(opciones, resumen)
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
        "-D", "--descarga",
        action="store_true", default=False,
        help="descarga el número indicado con --vol/--num, o todo el archivo",
    )
    analizador.add_option(
        "-e", "--entero",
        action="store_true", default=False,
        help="baja el número completo de una pieza cuando la revista lo ofrezca",
    )
    analizador.add_option(
        "-s", "--sup",
        action="store_true", default=False,
        help="actúa sobre el suplemento de ese número, no sobre el número",
    )
    analizador.add_option(
        "-u", "--usuario",
        metavar="NOMBRE",
        help="usuario de socio con el que acceder, junto con --contraseña",
    )
    analizador.add_option(
        "-p", "--contraseña", "--contrasena",
        dest="contrasena", metavar="CLAVE",
        help="contraseña de ese usuario; no se guarda en ninguna parte",
    )
    analizador.add_option(
        "-c", "--cookie",
        metavar="VALOR",
        help="valor de la cookie PHPSESSID de una sesión ya abierta; tiene "
             "preferencia sobre --usuario y se recuerda en el mapa",
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
    opciones.cookie_activa = None

    if sueltos:
        analizador.error("argumento inesperado: %s" % sueltos[0])

    if (opciones.usuario is None) != (opciones.contrasena is None):
        analizador.error("--usuario y --contraseña deben indicarse juntos")

    if opciones.cookie is not None and not RE_COOKIE.match(opciones.cookie):
        analizador.error(
            "la cookie debe ser una cadena hexadecimal de entre 22 y 256 "
            "caracteres (sin el «PHPSESSID=» delante)"
        )

    if (opciones.vol is None) != (opciones.num is None):
        analizador.error("--vol y --num deben indicarse juntos")

    if opciones.sup and opciones.vol is None:
        analizador.error("--sup necesita que se indiquen --vol y --num")

    if opciones.entero and not opciones.descarga:
        analizador.error("--entero sólo tiene sentido junto a --descarga")

    if not opciones.mapa and not opciones.descarga:
        if opciones.vol is not None:
            analizador.error("indica qué hacer con ese número: --mapa o --descarga")
        analizador.print_help()
        return 0

    try:
        if opciones.descarga:
            if opciones.vol is None:
                return descargar_todo(opciones)
            return descargar_uno(opciones)
        if opciones.vol is None:
            return mapear_indice(opciones)
        return mapear_numero(opciones)
    except requests.RequestException as fallo:
        return error("no se ha podido descargar el sitio: %s" % fallo)


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
