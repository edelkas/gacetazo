#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Descargador de La Gaceta de la RSME (https://gaceta.rsme.es).

Construye un archivo local de la revista: una carpeta por volumen, una
subcarpeta por número, y un sitemap.json que describe todo lo encontrado.
"""

import copy
import hashlib
import json
import os
import posixpath
import re
import shutil
import sys
import time
import unicodedata
from collections import Counter, deque
from html import escape as escapar_html
from optparse import IndentedHelpFormatter, OptionParser
from urllib.parse import quote, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup, Comment

URL_BASE = "https://gaceta.rsme.es/"
SERVIDOR = urlparse(URL_BASE).hostname
URL_INDICE = URL_BASE + "otrosnumeros.php"
URL_ACCESO = URL_BASE + "control.php"
NOMBRE_MAPA = "sitemap.json"
# lo personal se aparta del mapa: éste describe el archivo y puede publicarse,
# aquello es de cada cual y no debe salir de su ordenador
NOMBRE_CONFIG = "config.json"

# ficheros del sitio que se genera con --web
NOMBRE_PAGINA = "index.html"
NOMBRE_ESTILO = "estilo.css"
# GitHub Pages pasa por Jekyll lo que se le cuelga, salvo si encuentra esto
NOMBRE_NOJEKYLL = ".nojekyll"
NOMBRE_BUSQUEDA = "buscar.html"
NOMBRE_BUSQUEDA_AUTORES = "buscar-autores.html"
NOMBRE_INDICE = "busqueda.js"
NOMBRE_BUSCADOR = "buscador.js"
# el nombre con que el formulario manda lo que se busca, y que lee buscador.js
PARAMETRO_BUSQUEDA = "q"
CARPETA_NUMEROS = "numeros"
CARPETA_SECCIONES = "secciones"
RUTA_SECCIONES = CARPETA_SECCIONES + "/" + NOMBRE_PAGINA
CARPETA_AUTORES = "autores"
RUTA_AUTORES = CARPETA_AUTORES + "/" + NOMBRE_PAGINA
# los nombres que no empiezan por letra del abecedario se archivan juntos
LETRA_RESTO = "#"

# Nombres que la separación por comas y conjunciones partiría donde no
# debe: un apellido con «y» dentro, una institución con «e», una sección
# cuyo nombre lleva «y». Se apartan enteros antes de cortar. La tabla se
# copia a config.json la primera vez, y de ahí se puede retocar.
CLAVE_EXCEPCIONES = "excepciones"
EXCEPCIONES = [
    "Comisión de Educación, Cultura y Deporte del Senado",
    "José Echegaray y Eizaguirre",
    "Redacción de la sección de Problemas y Soluciones",
    "Sociedad de Estadística e Investigación Operativa",
]

# Firmas que son de la misma persona y que ninguna regla puede emparejar: un
# apellido con la «i» catalana en medio, un segundo nombre que unas veces se
# escribe entero y otras se calla. Cada lista son las firmas de uno. También
# se copia a config.json la primera vez.
CLAVE_EQUIVALENCIAS = "equivalencias"
EQUIVALENCIAS = [
    ["Marc Felipe Alsina", "Marc Felipe i Alsina"],
    ["José Carrillo", "José Carrillo Yáñez"],
    ["José Almira", "José María Almira"],
    ["Marco Fontelos", "Marco Antonio Fontelos"],
]

# lo que vive en config.json, y que las versiones anteriores guardaban en el mapa
CLAVES_CONFIG = ("cookie", CLAVE_EXCEPCIONES, CLAVE_EQUIVALENCIAS)

# los DOI se enlazan a traves del resolutor oficial
URL_DOI = "https://www.doi.org/"
URL_ARTICULO = URL_BASE + "abrir.php?id="

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

# formas en que puede bajarse un número: suelto por artículos, de una pieza,
# o las dos cosas a la vez cuando la revista ofrece ambas
FORMATO_ARTICULO = "articulo"
FORMATO_NUMERO = "numero"
FORMATO_AMBOS = "ambos"
FORMATOS = (FORMATO_ARTICULO, FORMATO_NUMERO, FORMATO_AMBOS)
# se admiten con tilde, que es como se escriben de verdad
FORMATOS_ALIAS = {"artículo": FORMATO_ARTICULO, "número": FORMATO_NUMERO}

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
# la revista lista los autores separados por comas y con la conjunción al
# final, que ante palabra que empieza por i- se escribe "e"
RE_AUTORES = re.compile(r"\s*,\s*|\s+[ye]\s+")

# lo que no vale en el nombre de una página del sitio: fuera del ASCII más
# llano hay navegadores viejos que se lían con los escapes de la dirección
RE_NO_URL = re.compile(r"[^A-Za-z0-9._-]+")
# marca con la que se aparta un nombre para que no lo parta la separación
MARCA = "\x00%d\x00"
# la inicial de un nombre: «J», «J.», y la «M.ª» con que se abrevia María
RE_ABREVIATURA = re.compile(r"^[^\W\d_]\.?[aoªº]?$", re.UNICODE)
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


def nombre_url(texto):
    """Convierte un nombre en otro que sirva tal cual dentro de una dirección.

    Se le quitan las tildes (y la eñe se queda en ene), y todo lo que no sea
    letra, cifra, punto, guion o subrayado se vuelve un guion.
    """
    return RE_NO_URL.sub("-", sin_tildes(texto)).strip("-._")


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
    """Nombre de carpeta de un volumen, por ejemplo 'vol.01-1998'."""
    return "vol.%02d-%d" % (volumen["num"], volumen["año"])


def nombre_carpeta_numero(numero):
    """Nombre de subcarpeta de un número: '2', o '2-sup' si es suplemento.

    Un suplemento comparte el número de aquel al que acompaña, así que hace
    falta el sufijo para que no se pisen dentro del volumen.
    """
    if es_suplemento(numero):
        return "%d-sup" % numero["num"]
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
        CARPETA_NUMEROS,
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


def ruta_config(opciones):
    """Ruta de los ajustes personales dentro de la carpeta de destino."""
    return os.path.join(opciones.destino, NOMBRE_CONFIG)


def leer_config(opciones):
    """Lee los ajustes personales, o devuelve unos vacíos si no los hay."""
    ruta = ruta_config(opciones)
    if not os.path.isfile(ruta):
        return {}
    with open(ruta, encoding="utf-8") as fichero:
        return json.load(fichero)


def escribir_config(opciones):
    """Escribe los ajustes personales en la carpeta de destino."""
    ruta = ruta_config(opciones)
    if not opciones.simulacion:
        if not os.path.isdir(opciones.destino):
            os.makedirs(opciones.destino)
        with open(ruta, "w", encoding="utf-8") as fichero:
            json.dump(opciones.config, fichero, ensure_ascii=False, indent=2)
            fichero.write("\n")
    return ruta


def leer_mapa(opciones):
    """Lee el mapa del disco, o devuelve None si todavía no existe."""
    ruta = ruta_mapa(opciones)
    if not os.path.isfile(ruta):
        return None
    with open(ruta, encoding="utf-8") as fichero:
        mapa = json.load(fichero)
    migrar_mapa(mapa, opciones)
    return mapa


def renombrar(viejo, nuevo, opciones):
    """Cambia el nombre de una carpeta del archivo, si hace falta y se puede."""
    if viejo == nuevo or not os.path.isdir(viejo):
        return False
    if os.path.exists(nuevo):
        avisar("no se renombra %s porque ya existe %s" % (viejo, nuevo))
        return False
    if not opciones.simulacion:
        # la carpeta de números puede no existir todavía, si el archivo viene
        # de cuando los volúmenes colgaban de la raíz
        os.makedirs(os.path.dirname(nuevo), exist_ok=True)
        os.rename(viejo, nuevo)
    return True


def renombrar_carpetas(mapa, opciones):
    """Pone al día las carpetas que una versión anterior nombró de otro modo.

    Se llamaban 'Vol 01 (1998)' y '2 sup', con espacios y paréntesis que la
    dirección de cada página tenía que escapar.
    """
    raiz = os.path.join(opciones.destino, CARPETA_NUMEROS)
    renombradas = 0
    for volumen in mapa.get("volumenes", ()):
        antes = "Vol %02d (%d)" % (volumen["num"], volumen["año"])
        ahora = os.path.join(raiz, nombre_carpeta_volumen(volumen))
        # las versiones más viejas dejaban los volúmenes en la raíz del archivo
        for viejo in (os.path.join(raiz, antes), os.path.join(opciones.destino, antes)):
            renombradas += renombrar(viejo, ahora, opciones)
        for numero in volumen.get("numeros", ()):
            if es_suplemento(numero):
                renombradas += renombrar(
                    os.path.join(ahora, "%d sup" % numero["num"]),
                    os.path.join(ahora, nombre_carpeta_numero(numero)),
                    opciones,
                )
    return renombradas


def rutas_al_dia(mapa):
    """Rehace la ruta anotada de cada fichero descargado.

    Del camino sólo se conserva el nombre del fichero; lo demás se vuelve a
    componer, así que da igual cómo se llamaran las carpetas en su día.
    """
    rehechas = 0
    for volumen in mapa.get("volumenes", ()):
        for numero in volumen.get("numeros", ()):
            carpeta = "%s/%s/%s" % (
                CARPETA_NUMEROS,
                nombre_carpeta_volumen(volumen),
                nombre_carpeta_numero(numero),
            )
            for entrada in [numero] + articulos_de(numero.get("articulos", ())):
                ficha = entrada.get("fichero")
                if ficha is None:
                    continue
                nueva = "%s/%s" % (carpeta, ficha["ruta"].rsplit("/", 1)[-1])
                if nueva != ficha["ruta"]:
                    ficha["ruta"] = nueva
                    rehechas += 1
    return rehechas


def migrar_mapa(mapa, opciones):
    """Pone al día un mapa escrito por una versión anterior del programa."""
    renombradas = renombrar_carpetas(mapa, opciones)
    rehechas = rutas_al_dia(mapa)
    # la cookie y las tablas vivían en el mapa; ahora son ajustes personales
    mudadas = [clave for clave in CLAVES_CONFIG if clave in mapa]
    for clave in mudadas:
        opciones.config.setdefault(clave, mapa.pop(clave))

    if renombradas:
        informar(opciones, "  %d carpetas renombradas" % renombradas)
    if rehechas:
        informar(opciones, "  %d rutas rehechas" % rehechas)
    if mudadas:
        informar(
            opciones, "  %s a %s" % (enumerar(mudadas), escribir_config(opciones))
        )
    if renombradas or rehechas or mudadas:
        informar(opciones, "  mapa al día en %s" % escribir_mapa(mapa, opciones))


def preparar_cookie(opciones):
    """Deja lista la sesión de socio, si la hay. Indica si se puede seguir.

    Manda la cookie que se haya indicado a mano; en su defecto se entra con
    usuario y contraseña, y si tampoco los hay se recurre a la cookie que
    quedara anotada de una ejecución anterior.
    """
    valor = opciones.cookie
    recien_accedido = False
    opciones.sesion = True  # se mira la sesión: la cookie queda al día después

    if not valor and opciones.usuario:
        informar(opciones, "Accediendo como %s ..." % opciones.usuario)
        valor = acceder(opciones.usuario, opciones.contrasena)
        if valor is None:
            error("la revista ha rechazado ese usuario o esa contraseña")
            return False
        informar(opciones, "Acceso concedido.")
        recien_accedido = True

    if not valor:
        valor = opciones.config.get("cookie")

    opciones.cookie_activa = valor
    if valor:
        usar_cookie(valor)
        if not recien_accedido:
            informar(opciones, "Sesión de socio activa.")
    return True


def anotar_cookie(opciones):
    """Guarda la cookie en los ajustes, o la retira si ha dejado de valer."""
    if opciones.cookie_activa:
        opciones.config["cookie"] = opciones.cookie_activa
    else:
        opciones.config.pop("cookie", None)


def escribir_mapa(mapa, opciones):
    """Escribe el mapa y, si hubo sesión, deja al día los ajustes personales."""
    ruta = ruta_mapa(opciones)
    if opciones.sesion:
        anotar_cookie(opciones)
        escribir_config(opciones)

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
    if not preparar_cookie(opciones):
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

    if not preparar_cookie(opciones):
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


def hay_entero(numero, opciones):
    """¿Toca bajar el ejemplar de una pieza, y lo ofrece la revista?"""
    return bool(
        opciones.formato in (FORMATO_NUMERO, FORMATO_AMBOS)
        and numero.get("link_todo")
    )


def ficheros_previstos(numero, opciones):
    """Cuántos ficheros se van a intentar bajar de un número."""
    previstos = 1 if numero.get("portada") else 0
    if hay_entero(numero, opciones):
        previstos += 1
        if opciones.formato == FORMATO_NUMERO:
            return previstos  # sólo la pieza entera, salvo que falle
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

    # con --formato=numero los artículos sueltos sólo se bajan si el ejemplar
    # completo no está; con --formato=ambos se bajan siempre
    partes = opciones.formato != FORMATO_NUMERO

    if opciones.formato in (FORMATO_NUMERO, FORMATO_AMBOS):
        if numero.get("link_todo"):
            estado = guardar(
                numero["link_todo"], carpeta, FICHERO_ENTERO, opciones, resumen, numero
            )
            if estado not in ("guardado", "existe") and not partes:
                # reservado a socios o caído: los sueltos suelen seguir ahí
                informar(opciones, "  no se ha podido traer entero; se baja por partes")
                partes = True
                BARRA.ampliar(contar_descargables(numero["articulos"]))
        elif not partes:
            informar(opciones, "  no se ofrece entero; se baja por partes")
            partes = True
            BARRA.ampliar(contar_descargables(numero["articulos"]))

    if partes:
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

    if not preparar_cookie(opciones):
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

    if not preparar_cookie(opciones):
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


# --------------------------------------------------------------------------
# Sitio web
#
# Con --web se vuelca el mapa en un sitio estático que se abre con un doble
# clic, sin servidor de por medio. Los enlaces apuntan a los ficheros ya
# descargados, así que el sitio sólo tiene sentido junto al archivo local.
# --------------------------------------------------------------------------

ESTILO = """\
/* Generado por gaceta.py; los cambios a mano se pierden al rehacer el sitio. */

html { scroll-behavior: smooth; }

body {
    font-family: system-ui, "Segoe UI", Arial, sans-serif;
    color: #222;
    margin: 2rem auto;
    max-width: 60rem;
    padding: 0 1rem;
}

h1 { font-size: 1.6rem; margin-bottom: 1rem; }

/* barra de saltos a cada volumen */
.volumenes { margin-bottom: 1.5rem; line-height: 2; }
.volumenes a {
    border: 1px solid #ccd;
    border-radius: 3px;
    color: #036;
    padding: 0.15rem 0.4rem;
    text-decoration: none;
}
.volumenes a:hover { background: #eef; }

table { border-collapse: collapse; }
th, td { border: 1px solid #ddd; padding: 0.35rem; text-align: center; }
tr { scroll-margin-top: 1rem; }
th.volumen { font-weight: normal; text-align: left; white-space: nowrap; }
td.vacia { border: none; }

td a { color: #036; display: block; text-decoration: none; }
td a:hover { text-decoration: underline; }

/* todas las portadas del mismo tamaño, y pequeñas para que quepan
   cuatro o cinco volúmenes en pantalla */
td img { display: block; height: 118px; object-fit: cover; width: 84px; }

/* --- página de un número ------------------------------------------- */

.navegacion { line-height: 2.2; margin-bottom: 1.5rem; }
.navegacion a, .navegacion span {
    border: 1px solid #ccd;
    border-radius: 3px;
    color: #036;
    padding: 0.15rem 0.5rem;
    text-decoration: none;
}
.navegacion a:hover { background: #eef; }
.navegacion span { border-color: #eee; color: #aaa; }  /* extremo del archivo */

.numero { align-items: flex-start; display: flex; gap: 2rem; }
.contenido { flex: 1 1 20rem; }
.portada { flex: 0 0 13rem; text-align: center; }
.portada img { border: 1px solid #ddd; height: auto; width: 100%; }
.portada p { margin: 0.6rem 0 0; }

h2 { border-bottom: 1px solid #ddd; font-size: 1.2rem; margin-top: 1.6rem; }
h3 { font-size: 1.05rem; margin-top: 1.2rem; }
h4 { font-size: 1rem; margin-top: 1rem; }

/* cada artículo, como una cita con sangría francesa */
.cita { line-height: 1.45; margin: 0.5rem 0 0.5rem 1.5rem; text-indent: -1.5rem; }
.cita a { color: #036; }
.cita .doi, .cita .rsme { font-size: 0.85em; }

/* en pantalla estrecha la portada se va arriba y el índice debajo */
@media (max-width: 45rem) {
    .numero { flex-direction: column; }
    .portada { align-self: center; order: -1; }
}

/* --- índice de secciones y páginas de sección ----------------------- */

.linea { margin: 0.4rem 0; }
.linea a { color: #036; font-weight: 600; text-decoration: none; }
.linea a:hover { text-decoration: underline; }

/* saltos a cada número con presencia en la sección */
.numeros { font-size: 0.9rem; line-height: 2; margin-bottom: 1.5rem; }
.numeros a {
    border: 1px solid #ccd;
    border-radius: 3px;
    color: #036;
    padding: 0.1rem 0.35rem;
    text-decoration: none;
}
.numeros a:hover { background: #eef; }

h2[id] { scroll-margin-top: 1rem; }
h1 a, h2 a, h3 a { color: inherit; text-decoration: none; }
h1 a:hover, h2 a:hover, h3 a:hover { text-decoration: underline; }

/* --- índice de autores ---------------------------------------------- */

/* saltos a cada letra del abecedario */
.letras { line-height: 2; margin-bottom: 1.5rem; }
.letras a, .letras span {
    border: 1px solid #ccd;
    border-radius: 3px;
    color: #036;
    display: inline-block;
    min-width: 1.2rem;
    padding: 0.1rem 0.3rem;
    text-align: center;
    text-decoration: none;
}
.letras a:hover { background: #eef; }
.letras span { border-color: #eee; color: #ccc; }  /* letra sin autores */

/* --- buscador -------------------------------------------------------- */

/* el formulario, que va al final de la barra de navegación */
.buscar { display: inline-block; margin-left: 0.4rem; white-space: nowrap; }
.buscar input, .buscar button {
    border: 1px solid #ccd;
    border-radius: 3px;
    font: inherit;
    padding: 0.15rem 0.4rem;
}
.buscar input { width: 12rem; }
.buscar button { background: #fff; color: #036; cursor: pointer; }
.buscar button:hover { background: #eef; }

/* cuántos artículos han salido */
.cuenta { color: #555; margin-bottom: 1.5rem; }

/* las maneras en que un autor ha firmado */
.firmas { color: #555; font-size: 0.9rem; margin-bottom: 1.5rem; }
"""

# Todo el trabajo de búsqueda lo hace el navegador: el sitio es estático y ha
# de poder abrirse tanto colgado de un servidor como con un doble clic.
BUSCADOR = r"""/* Generado por gaceta.py; los cambios a mano se pierden al rehacer el sitio. */

var URL_ARTICULO = "https://gaceta.rsme.es/abrir.php?id=";
var URL_DOI = "https://www.doi.org/";

/* Las claves por las que se busca, normalizadas una sola vez por tabla. */
var CLAVES = {};

function normalizar(texto) {
    /* sin tildes y en minúsculas, como se normaliza también al generar */
    return texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
                .toLowerCase().replace(/\s+/g, " ").trim();
}

function terminos(pedido) {
    /* cada palabra por su lado, que 'mat oli' halle 'Olimpiada Matemática' */
    return pedido.split(/\s+/).filter(function (trozo) { return trozo; });
}

function casan(clave, buscados) {
    /* todos los términos han de estar, aunque sea sueltos y en desorden */
    for (var i = 0; i < buscados.length; i++) {
        if (clave.indexOf(buscados[i]) < 0) { return false; }
    }
    return true;
}

function claves(cual) {
    /* el nombre va el primero tanto en un artículo como en un autor */
    if (!CLAVES[cual]) {
        CLAVES[cual] = BUSQUEDA[cual].map(function (entrada) {
            return normalizar(entrada[0]);
        });
    }
    return CLAVES[cual];
}

function escapar(texto) {
    return String(texto).replace(/&/g, "&amp;").replace(/</g, "&lt;")
        .replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#x27;");
}

function enlace(destino, rotulo, clase) {
    return "<a" + (clase ? ' class="' + clase + '"' : "")
        + ' href="' + destino + '">' + rotulo + "</a>";
}

function enlaceRevista(dato) {
    /* un número es el id de abrir.php; una cadena, un PDF suelto */
    return escapar(typeof dato === "number" ? URL_ARTICULO + dato : dato);
}

function enumerar(trozos) {
    /* como se enumera en castellano: 'a, b y c' */
    if (trozos.length < 2) { return trozos.join(""); }
    return trozos.slice(0, -1).join(", ") + " y " + trozos[trozos.length - 1];
}

function autores(quienes) {
    /* una cadena cuando no se pudieron separar; si no, índices en la tabla */
    if (typeof quienes === "string") { return escapar(quienes); }
    var trozos = [];
    for (var i = 0; i < quienes.length; i++) {
        var firma = BUSQUEDA.firmas[quienes[i]];
        var rotulo = escapar(firma[0]);
        trozos.push(firma[1] ? enlace(firma[1], rotulo) : rotulo);
    }
    return enumerar(trozos);
}

function paginas(rango) {
    if (rango[0] === rango[1]) { return "pág. " + rango[0]; }
    return "págs. " + rango[0] + "-" + rango[1];
}

function cita(articulo) {
    /* [título, número, sección, autores, revista, páginas, doi, fichero] */
    var nombre = "<strong>" + escapar(articulo[0]) + "</strong>";
    var revista = articulo[4] ? enlaceRevista(articulo[4]) : "";
    var destino = BUSQUEDA.externa ? revista : (articulo[7] || "");
    var partes = [destino ? enlace(destino, nombre) : nombre];

    if (articulo[3]) { partes.push("<em>" + autores(articulo[3]) + "</em>"); }
    if (articulo[5]) { partes.push(paginas(articulo[5])); }
    if (articulo[6]) {
        var doi = escapar(URL_DOI + articulo[6]);
        partes.push(enlace(doi, doi, "doi"));
    }
    /* con la web externa el título ya lleva a la revista, y sobra el remate */
    if (revista && !BUSQUEDA.externa) {
        partes.push(enlace(revista, "RSME", "rsme"));
    }
    return '<p class="cita">' + partes.join(", ") + "</p>";
}

function agrupar(buscados) {
    /* Los artículos vienen en el orden del archivo, así que se agrupan según
       van saliendo y al final se les da la vuelta a los números; dentro de
       cada uno se leen como en su página, del primero al último. */
    var bloques = [], bloque = null, total = 0, todas = claves("articulos");
    for (var i = 0; i < BUSQUEDA.articulos.length; i++) {
        if (!casan(todas[i], buscados)) { continue; }
        var articulo = BUSQUEDA.articulos[i];
        total++;
        if (bloque === null || bloque.numero !== articulo[1]) {
            bloque = { numero: articulo[1], tandas: [] };
            bloques.push(bloque);
        }
        var tanda = bloque.tandas[bloque.tandas.length - 1];
        if (!tanda || tanda.seccion !== articulo[2]) {
            tanda = { seccion: articulo[2], citas: [] };
            bloque.tandas.push(tanda);
        }
        tanda.citas.push(cita(articulo));
    }
    bloques.reverse();
    return { bloques: bloques, total: total };
}

function montar(bloques) {
    var trozos = [];
    for (var i = 0; i < bloques.length; i++) {
        trozos.push(BUSQUEDA.numeros[bloques[i].numero]);
        var tandas = bloques[i].tandas;
        for (var j = 0; j < tandas.length; j++) {
            if (tandas[j].seccion >= 0) {
                trozos.push(BUSQUEDA.secciones[tandas[j].seccion]);
            }
            trozos.push(tandas[j].citas.join("\n"));
        }
    }
    return trozos.join("\n");
}

function hallarArticulos(buscados) {
    var hallado = agrupar(buscados);
    return { total: hallado.total, html: montar(hallado.bloques) };
}

function inicial(nombre) {
    /* la letra bajo la que se archiva, como en el índice de autores */
    var letra = normalizar(nombre.slice(0, 1)).toUpperCase();
    return letra >= "A" && letra <= "Z" ? letra : "#";
}

function lineaAutor(autor) {
    /* [nombre, página, artículos, desde, hasta] */
    var cuantos = autor[2] === 1 ? "1 artículo" : autor[2] + " artículos";
    var hasta = autor.length > 4 ? autor[4] : autor[3];
    var años = autor[3] === hasta ? autor[3] : autor[3] + "-" + hasta;
    return '<p class="linea">' + enlace(escapar(autor[1]), escapar(autor[0]))
        + " (" + cuantos + ", " + años + ")</p>";
}

function hallarAutores(buscados) {
    /* vienen ya ordenados y se pintan como en su índice, por letras */
    var trozos = [], letra = null, total = 0, todas = claves("autores");
    for (var i = 0; i < BUSQUEDA.autores.length; i++) {
        if (!casan(todas[i], buscados)) { continue; }
        var autor = BUSQUEDA.autores[i];
        total++;
        if (inicial(autor[0]) !== letra) {
            letra = inicial(autor[0]);
            trozos.push("<h2>" + escapar(letra) + "</h2>");
        }
        trozos.push(lineaAutor(autor));
    }
    return { total: total, html: trozos.join("\n") };
}

/* Qué se busca en cada página de resultados, que ella misma dice cuál es. */
var MODOS = {
    articulos: { uno: "artículo", varios: "artículos", en: "en el título",
                 hallar: hallarArticulos },
    autores: { uno: "autor", varios: "autores", en: "en el nombre",
               hallar: hallarAutores }
};

function modoDe(resultados) {
    return MODOS[resultados.getAttribute("data-busca")] || MODOS.articulos;
}

function contar(total, pedidos, modo) {
    /* el verbo concuerda con los artículos, no con los términos */
    var cuales = enumerar(pedidos.map(function (pedido) {
        return "«" + pedido + "»";
    }));
    if (total === 0) {
        return "Ningún " + modo.uno + " lleva " + cuales + " " + modo.en + ".";
    }
    if (total === 1) {
        return "Un " + modo.uno + " lleva " + cuales + " " + modo.en + ".";
    }
    return total + " " + modo.varios + " llevan " + cuales + " " + modo.en + ".";
}

function buscar() {
    var pedido = loQuePiden().trim();
    var casilla = document.querySelector(".buscar input");
    if (casilla) { casilla.value = pedido; }

    var cuenta = document.getElementById("cuenta");
    var resultados = document.getElementById("resultados");
    var modo = modoDe(resultados);
    if (!pedido) {
        cuenta.textContent = "Escribe una o varias palabras que aparezcan "
            + modo.en + ".";
        resultados.innerHTML = "";
        return;
    }

    /* el título de la pestaña ya dice qué se busca aquí */
    document.title = pedido + " - " + document.title;
    var pedidos = terminos(pedido);
    var hallado = modo.hallar(pedidos.map(function (suelto) {
        return normalizar(suelto);
    }));
    cuenta.textContent = contar(hallado.total, pedidos, modo);
    resultados.innerHTML = hallado.html;
}

function loQuePiden() {
    return new URLSearchParams(location.search).get("q") || "";
}

document.addEventListener("DOMContentLoaded", buscar);
"""

PLANTILLA_PAGINA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>%(titulo)s - La Gaceta de la RSME</title>
<link rel="stylesheet" href="%(estilo)s">
</head>
<body>
<h1>%(cabecera)s</h1>
%(cuerpo)s
</body>
</html>
"""


def rotulo_volumen(volumen):
    """Cómo se nombra un volumen en el sitio: 'Vol. 01 (1998)'."""
    return "Vol. %02d (%d)" % (volumen["num"], volumen["año"])


def rotulo_numero(numero):
    """Cómo se nombra un número: 'Núm. 3', o con su coletilla si es suplemento."""
    rotulo = "Núm. %d" % numero["num"]
    if es_suplemento(numero):
        rotulo += " (Suplemento)"
    return rotulo


def ancla_volumen(volumen):
    """Identificador con el que se salta a la fila de un volumen."""
    return "vol-%02d" % volumen["num"]


def ruta_pagina_numero(volumen, numero):
    """Ruta de la página de un número, que vive en su propia carpeta."""
    return "%s/%s/%s/%s" % (
        CARPETA_NUMEROS,
        nombre_carpeta_volumen(volumen),
        nombre_carpeta_numero(numero),
        NOMBRE_PAGINA,
    )


def portada_descargada(volumen, numero, opciones):
    """Ruta relativa de la portada guardada de un número, si está en el disco."""
    ruta = fichero_existente(
        ruta_carpeta_numero(volumen, numero, opciones), FICHERO_PORTADA
    )
    return ruta_relativa(ruta, opciones) if ruta else None


def enlace_web(ruta):
    """Codifica una ruta relativa para poder usarla como href o src."""
    return quote(ruta)


def celda_numero(volumen, numero, opciones):
    """Celda de la tabla: la portada si la hay, y si no el nombre del número."""
    rotulo = rotulo_numero(numero)
    portada = portada_descargada(volumen, numero, opciones)
    if portada:
        contenido = '<img src="%s" alt="%s">' % (enlace_web(portada), escapar_html(rotulo))
    else:
        contenido = escapar_html(rotulo)
    return '<td><a href="%s" title="%s">%s</a></td>' % (
        enlace_web(ruta_pagina_numero(volumen, numero)),
        escapar_html(rotulo),
        contenido,
    )


def fila_volumen(volumen, columnas, opciones):
    """Fila de la tabla: el rótulo del volumen y sus números, rellenada al ancho."""
    celdas = [celda_numero(volumen, numero, opciones) for numero in volumen["numeros"]]
    celdas += ['<td class="vacia"></td>'] * (columnas - len(celdas))
    return '<tr id="%s"><th class="volumen" scope="row">%s</th>%s</tr>' % (
        ancla_volumen(volumen),
        escapar_html(rotulo_volumen(volumen)),
        "".join(celdas),
    )


def barra_volumenes(volumenes):
    """Enlaces internos que saltan a la fila de cada volumen."""
    enlaces = [
        '<a href="#%s" title="%s">%d</a>'
        % (ancla_volumen(volumen), escapar_html(rotulo_volumen(volumen)), volumen["num"])
        for volumen in volumenes
    ]
    return '<p class="volumenes">%s</p>' % "\n".join(enlaces)


def pagina_indice(mapa, opciones):
    """Arma el index.html con la tabla de volúmenes y números."""
    volumenes = mapa["volumenes"]
    # la tabla es rectangular: tantas columnas como números tenga el volumen
    # más nutrido, contando los suplementos
    columnas = max(len(volumen["numeros"]) for volumen in volumenes)
    # la tabla empieza por lo más reciente; la barra de saltos, en cambio, se
    # deja en orden natural, que es como se busca un volumen concreto
    filas = [
        fila_volumen(volumen, columnas, opciones) for volumen in reversed(volumenes)
    ]
    return """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>La Gaceta de la RSME</title>
<link rel="stylesheet" href="%s">
</head>
<body>
<h1>La Gaceta de la RSME</h1>
%s
%s
<table>
%s
</table>
</body>
</html>
""" % (
        enlace_web(NOMBRE_ESTILO),
        barra_navegacion(botones_indices("", salvo=NOMBRE_PAGINA), ""),
        barra_volumenes(volumenes),
        "\n".join(filas),
    )


def rotulo_paginas(entrada):
    """Cómo se citan las páginas: 'pág. 5', o 'págs. 5-8' si son varias."""
    inicio = entrada.get("pagina_inicio")
    if inicio is None:
        return None
    fin = entrada.get("pagina_fin", inicio)
    if fin == inicio:
        return "pág. %d" % inicio
    return "págs. %d-%d" % (inicio, fin)


def fichero_local(entrada, opciones):
    """Ruta del fichero descargado de una entrada, si sigue en el disco.

    El mapa recuerda lo que se descargó, pero el fichero puede haberse
    borrado después, y entonces no hay a dónde enlazar.
    """
    ficha = entrada.get("fichero")
    if not ficha:
        return None
    ruta = os.path.join(opciones.destino, ficha["ruta"].replace("/", os.sep))
    return ficha["ruta"] if os.path.isfile(ruta) else None


def destino_revista(entrada, clave="link"):
    """El PDF que sirve la revista, ya listo para meter en un href."""
    return escapar_html(entrada[clave]) if entrada.get(clave) else None


def destino_articulo(entrada, carpeta, opciones, clave="link"):
    """A dónde lleva un artículo, ya listo para meter en un href.

    Con --externa se enlaza siempre a la revista, aunque haya copia local: el
    sitio se publica sin los PDF. Sin ella manda lo que haya en el disco.
    """
    if opciones.externa:
        return destino_revista(entrada, clave)
    local = fichero_local(entrada, opciones)
    return enlace_desde(local, carpeta) if local else None


def enlace_desde(ruta, carpeta):
    """Enlace a una ruta del archivo desde la página que vive en esa carpeta."""
    return enlace_web(posixpath.relpath(ruta, carpeta))


def enumerar(trozos):
    """Une los trozos como se enumera en castellano: 'a, b y c'."""
    if len(trozos) < 2:
        return "".join(trozos)
    return "%s y %s" % (", ".join(trozos[:-1]), trozos[-1])


def enlaces_autores(articulo, carpeta, indices):
    """Los autores del artículo, cada uno enlazado a su página."""
    paginas = (indices or {}).get("autores") or {}
    nombres = []
    for nombre in autores_de(articulo, (indices or {}).get("excepciones") or ()):
        pagina = paginas.get(clave_firma(nombre))
        rotulo = escapar_html(nombre)
        if pagina:
            rotulo = '<a href="%s">%s</a>' % (enlace_desde(pagina, carpeta), rotulo)
        nombres.append(rotulo)
    return enumerar(nombres) if nombres else escapar_html(articulo["autor"])


def cita_articulo(articulo, carpeta, opciones, indices=None):
    """Un artículo, formateado como una cita bibliográfica."""
    nombre = "<strong>%s</strong>" % escapar_html(articulo["nombre"])
    destino = destino_articulo(articulo, carpeta, opciones)
    if destino:
        nombre = '<a href="%s">%s</a>' % (destino, nombre)
    partes = [nombre]

    if "autor" in articulo:
        partes.append("<em>%s</em>" % enlaces_autores(articulo, carpeta, indices))
    paginas = rotulo_paginas(articulo)
    if paginas:
        partes.append(paginas)
    if "doi" in articulo:
        url = escapar_html(URL_DOI + articulo["doi"])
        partes.append('<a class="doi" href="%s">%s</a>' % (url, url))
    # con --externa el nombre ya lleva a la revista, así que sobra el remate
    if "link" in articulo and not opciones.externa:
        partes.append(
            '<a class="rsme" href="%s">RSME</a>' % escapar_html(articulo["link"])
        )
    return '<p class="cita">%s</p>' % ", ".join(partes)


def encabezado_numero(volumen, numero, carpeta, nivel=2, ancla=None):
    """Encabezado que abre el bloque de un número, enlazado a su página."""
    etiqueta = "h%d" % nivel
    return '<%s%s><a href="%s">%s</a></%s>' % (
        etiqueta,
        ' id="%s"' % ancla if ancla else "",
        enlace_desde(ruta_pagina_numero(volumen, numero), carpeta),
        escapar_html(titulo_numero(volumen, numero)),
        etiqueta,
    )


def encabezado_seccion(nombre, carpeta, nivel=2, indices=None):
    """Encabezado de una sección de primer nivel, enlazado a su página."""
    etiqueta = "h%d" % nivel
    rotulo = escapar_html(nombre)
    pagina = ((indices or {}).get("secciones") or {}).get(clave_indice(nombre))
    if pagina:
        rotulo = '<a href="%s">%s</a>' % (enlace_desde(pagina, carpeta), rotulo)
    return "<%s>%s</%s>" % (etiqueta, rotulo, etiqueta)


def arbol_web(entradas, carpeta, opciones, nivel=2, omitir=None, indices=None):
    """Vuelca el árbol de secciones y artículos, con un encabezado por nivel.

    Las secciones de primer nivel se enlazan a su página del índice de
    secciones; las de dentro no, porque ese índice no baja de ahí.
    """
    trozos = []
    for entrada in entradas:
        if "articulos" in entrada:
            # sólo las secciones de primer nivel tienen página propia
            if nivel == 2:
                trozos.append(encabezado_seccion(entrada["nombre"], carpeta, 2, indices))
            else:
                etiqueta = "h%d" % min(nivel, 6)
                trozos.append(
                    "<%s>%s</%s>"
                    % (etiqueta, escapar_html(entrada["nombre"]), etiqueta)
                )
            trozos.extend(
                arbol_web(
                    entrada["articulos"], carpeta, opciones, nivel + 1, indices=indices
                )
            )
        elif entrada is not omitir:
            trozos.append(cita_articulo(entrada, carpeta, opciones, indices))
    return trozos


def articulo_portada(numero):
    """El prefacio 'Acerca de la portada', que se muestra junto a la imagen."""
    for entrada in numero["articulos"]:
        if "articulos" not in entrada and entrada["nombre"] == TITULO_PORTADA:
            return entrada
    return None


def titulo_numero(volumen, numero):
    """Cómo se encabeza un número, con su nombre detrás si lo tiene."""
    titulo = "%s, %s" % (rotulo_volumen(volumen), rotulo_numero(numero))
    if numero.get("nombre"):
        titulo += ": %s" % numero["nombre"]
    return titulo


def envolver_pagina(titulo, cuerpo, carpeta, destino=None):
    """Viste un cuerpo de página con la cabecera y el título comunes.

    Con 'destino' el titular se enlaza ahí; el nombre de la pestaña se queda
    en texto llano, que no admite otra cosa.
    """
    cabecera = escapar_html(titulo)
    if destino:
        cabecera = '<a href="%s">%s</a>' % (destino, cabecera)
    return PLANTILLA_PAGINA % {
        "titulo": escapar_html(titulo),
        "cabecera": cabecera,
        "estilo": enlace_desde(NOMBRE_ESTILO, carpeta),
        "cuerpo": cuerpo,
    }


def formulario_busqueda(carpeta, autores=False):
    """El buscador, que acompaña a la barra de navegación de cada página.

    Busca por título salvo donde se anden mirando autores, que allí lo suyo
    es buscarlos por el nombre.
    """
    pagina, rotulo = NOMBRE_BUSQUEDA, "Buscar por título"
    if autores:
        pagina, rotulo = NOMBRE_BUSQUEDA_AUTORES, "Buscar por autor"
    return (
        '<form class="buscar" action="%s" method="get" role="search">'
        '<input type="search" name="%s" placeholder="%s" aria-label="%s">'
        "<button>Buscar</button>"
        "</form>"
    ) % (enlace_desde(pagina, carpeta), PARAMETRO_BUSQUEDA, rotulo, rotulo)


def barra_navegacion(botones, carpeta, autores=False):
    """Envuelve una tanda de botones y el buscador en su barra.

    Va en un <div> y no en un <p> porque un formulario no cabe dentro de un
    párrafo: el navegador lo cerraría al toparse con él, y el buscador
    acabaría en la línea de abajo.
    """
    return '<div class="navegacion">%s</div>' % "\n".join(
        list(botones) + [formulario_busqueda(carpeta, autores)]
    )


def botones_indices(carpeta, salvo=None):
    """Botones a los tres índices; se calla el de la página en la que se está."""
    indices = [
        ("Números", NOMBRE_PAGINA),
        ("Secciones", RUTA_SECCIONES),
        ("Autores", RUTA_AUTORES),
    ]
    return [
        boton_web(rotulo, enlace_desde(destino, carpeta))
        for rotulo, destino in indices
        if destino != salvo
    ]


def boton_web(rotulo, destino=None):
    """Botón de la barra de navegación; sin destino sale apagado."""
    if destino is None:
        return "<span>%s</span>" % escapar_html(rotulo)
    return '<a href="%s">%s</a>' % (destino, escapar_html(rotulo))


def navegacion_numero(numeros, posicion, carpeta):
    """Botones para recorrer el archivo de número en número."""

    def salto(indice):
        if indice == posicion or not 0 <= indice < len(numeros):
            return None
        return enlace_desde(ruta_pagina_numero(*numeros[indice]), carpeta)

    botones = botones_indices(carpeta) + [
        boton_web("« Primero", salto(0)),
        boton_web("‹ Anterior", salto(posicion - 1)),
        boton_web("Siguiente ›", salto(posicion + 1)),
        boton_web("Último »", salto(len(numeros) - 1)),
    ]
    return barra_navegacion(botones, carpeta)


def columna_portada(volumen, numero, carpeta, opciones):
    """La portada en grande y los enlaces que la acompañan."""
    trozos = []
    portada = portada_descargada(volumen, numero, opciones)
    if portada:
        trozos.append(
            '<img src="%s" alt="Portada del %s">'
            % (
                enlace_desde(portada, carpeta),
                escapar_html(titulo_numero(volumen, numero)),
            )
        )

    # el ejemplar completo: el que haya en el disco, y si no el de la revista
    entero = destino_articulo(numero, carpeta, opciones, "link_todo")
    rotulo = "Número completo"
    if not entero:
        # aquí sólo se llega sin --externa: se avisa de que el enlace se va fuera
        entero = destino_revista(numero, "link_todo")
        rotulo += " (RSME)"
    if entero:
        trozos.append('<p><a href="%s">%s</a></p>' % (entero, rotulo))

    prefacio = articulo_portada(numero)
    if prefacio:
        destino = destino_articulo(prefacio, carpeta, opciones) or destino_revista(
            prefacio
        )
        if destino:
            trozos.append('<p><a href="%s">%s</a></p>' % (destino, TITULO_PORTADA))

    return '<aside class="portada">\n%s\n</aside>' % "\n".join(trozos)


def pagina_numero(numeros, posicion, opciones, indices=None):
    """Arma la página de un número: navegación, artículos y portada."""
    volumen, numero = numeros[posicion]
    carpeta = posixpath.dirname(ruta_pagina_numero(volumen, numero))
    articulos = arbol_web(
        numero["articulos"],
        carpeta,
        opciones,
        omitir=articulo_portada(numero),
        indices=indices,
    )
    cuerpo = """%s
<div class="numero">
<div class="contenido">
%s
</div>
%s
</div>""" % (
        navegacion_numero(numeros, posicion, carpeta),
        "\n".join(articulos),
        columna_portada(volumen, numero, carpeta, opciones),
    )
    # el titular lleva a la página que la revista dedica al número
    return envolver_pagina(
        titulo_numero(volumen, numero), cuerpo, carpeta, destino_revista(numero)
    )


def clave_indice(nombre):
    """Nombre de sección normalizado, para no partir en dos lo que es una.

    Basta con igualar los espacios y las mayúsculas: así 'Educación' y
    'EDUCACIÓN ' cuentan como la misma sección.
    """
    return " ".join(nombre.split()).lower()


def articulos_de(entradas):
    """Todos los artículos que cuelgan de una sección, a cualquier hondura."""
    hojas = []
    for entrada in entradas:
        if "articulos" in entrada:
            hojas.extend(articulos_de(entrada["articulos"]))
        else:
            hojas.append(entrada)
    return hojas


def tandas_del_numero(numero):
    """Las secciones de primer nivel de un número, con sus artículos.

    El prefacio de la portada vive suelto en la raíz, así que se le da una
    sección propia; cualquier otro suelto se queda fuera de este índice.
    """
    for entrada in numero["articulos"]:
        if "articulos" in entrada:
            yield entrada["nombre"], articulos_de(entrada["articulos"])
        elif entrada["nombre"] == TITULO_PORTADA:
            yield TITULO_PORTADA, [entrada]


def secciones_del_numero(numero):
    """De qué sección de primer nivel cuelga cada artículo del número."""
    duenos = {}
    for nombre, articulos in tandas_del_numero(numero):
        for articulo in articulos:
            duenos.setdefault(id(articulo), nombre)
    return duenos


def fichero_indice(nombre, usados, respaldo):
    """Nombre de fichero libre, y seguro en una dirección, para una página."""
    base = nombre_url(nombre) or respaldo
    candidato, orden = base, 2
    while (candidato + ".html").lower() in usados:
        candidato, orden = "%s-%d" % (base, orden), orden + 1
    usados.add((candidato + ".html").lower())
    return candidato + ".html"


def agrupar_secciones(numeros):
    """Reúne los artículos de todo el archivo por su sección de primer nivel."""
    grupos = {}
    for volumen, numero in numeros:
        for nombre, articulos in tandas_del_numero(numero):
            if not articulos:
                continue
            grupo = grupos.setdefault(
                clave_indice(nombre), {"grafias": Counter(), "tandas": []}
            )
            grupo["grafias"][nombre] += 1
            grupo["tandas"].append((volumen, numero, articulos))

    secciones = []
    for grupo in grupos.values():
        años = [volumen["año"] for volumen, _, _ in grupo["tandas"]]
        secciones.append(
            {
                # de las grafías vistas se queda la más repetida
                "nombre": grupo["grafias"].most_common(1)[0][0],
                "tandas": grupo["tandas"],
                "articulos": sum(len(hojas) for _, _, hojas in grupo["tandas"]),
                "desde": min(años),
                "hasta": max(años),
            }
        )

    secciones.sort(key=lambda seccion: (-seccion["articulos"], clave_indice(seccion["nombre"])))
    usados = {NOMBRE_PAGINA.lower()}
    for seccion in secciones:
        seccion["pagina"] = "%s/%s" % (
            CARPETA_SECCIONES,
            fichero_indice(seccion["nombre"], usados, "seccion"),
        )
    return secciones


def rotulo_años(entrada):
    """'1998-2026', o un solo año si la entrada no pasó de ahí."""
    if entrada["desde"] == entrada["hasta"]:
        return "%d" % entrada["desde"]
    return "%d-%d" % (entrada["desde"], entrada["hasta"])


def linea_indice(entrada, carpeta):
    """Una entrada de índice: el nombre enlazado y de qué se compone."""
    cuantos = (
        "1 artículo"
        if entrada["articulos"] == 1
        else "%d artículos" % entrada["articulos"]
    )
    return '<p class="linea"><a href="%s">%s</a> (%s, %s)</p>' % (
        enlace_desde(entrada["pagina"], carpeta),
        escapar_html(entrada["nombre"]),
        cuantos,
        rotulo_años(entrada),
    )


def pagina_secciones(secciones, opciones):
    """El índice de secciones, de la más nutrida a la menos."""
    carpeta = posixpath.dirname(RUTA_SECCIONES)
    lineas = [linea_indice(seccion, carpeta) for seccion in secciones]
    cuerpo = "\n".join(
        [barra_navegacion(botones_indices(carpeta, salvo=RUTA_SECCIONES), carpeta)]
        + lineas
    )
    return envolver_pagina("Secciones", cuerpo, carpeta)


def ancla_tanda(volumen, numero):
    """Identificador con el que se salta al bloque de un número."""
    return "n-%02d-%s" % (volumen["num"], nombre_carpeta_numero(numero).replace(" ", "-"))


def barra_tandas(tandas, carpeta):
    """Saltos al bloque de cada número con presencia en la sección."""
    enlaces = [
        '<a href="#%s" title="%s">%d.%s</a>'
        % (
            ancla_tanda(volumen, numero),
            escapar_html(titulo_numero(volumen, numero)),
            volumen["num"],
            nombre_carpeta_numero(numero),
        )
        for volumen, numero, _ in tandas
    ]
    return '<p class="numeros">%s</p>' % "\n".join(enlaces)


def pagina_seccion(secciones, posicion, opciones, indices=None):
    """La página de una sección: sus artículos, del número más nuevo al más viejo."""
    seccion = secciones[posicion]
    carpeta = posixpath.dirname(seccion["pagina"])

    def salto(indice):
        if not 0 <= indice < len(secciones):
            return None
        return enlace_desde(secciones[indice]["pagina"], carpeta)

    navegacion = barra_navegacion(
        botones_indices(carpeta)
        + [
            boton_web("‹ Anterior", salto(posicion - 1)),
            boton_web("Siguiente ›", salto(posicion + 1)),
        ],
        carpeta,
    )

    tandas = list(reversed(seccion["tandas"]))
    trozos = [navegacion, barra_tandas(tandas, carpeta)]
    for volumen, numero, articulos in tandas:
        trozos.append(
            encabezado_numero(
                volumen, numero, carpeta, ancla=ancla_tanda(volumen, numero)
            )
        )
        trozos.extend(
            cita_articulo(articulo, carpeta, opciones, indices)
            for articulo in articulos
        )

    return envolver_pagina(seccion["nombre"], "\n".join(trozos), carpeta)


def sin_tildes(texto):
    """Quita las tildes, para ordenar y agrupar como en un listín."""
    descompuesto = unicodedata.normalize("NFD", texto)
    return "".join(letra for letra in descompuesto if not unicodedata.combining(letra))


def apartar(texto, excepciones):
    """Cambia por una marca lo que no debe partirse. Devuelve (texto, guardados)."""
    guardados = []
    # de mayor a menor, por si una excepción contiene a otra
    for excepcion in sorted(excepciones, key=len, reverse=True):
        excepcion = " ".join(excepcion.split())
        if not excepcion:
            continue

        def guardar(coincidencia):
            guardados.append(coincidencia.group(0))
            return MARCA % (len(guardados) - 1)

        texto = re.sub(re.escape(excepcion), guardar, texto, flags=re.IGNORECASE)
    return texto, guardados


def devolver(trozo, guardados):
    """Deshace lo que hizo apartar()."""
    for orden, guardado in enumerate(guardados):
        trozo = trozo.replace(MARCA % orden, guardado)
    return trozo


def autores_de(articulo, excepciones=()):
    """Los autores de un artículo, uno a uno.

    La revista los escribe seguidos, separados por comas y rematados con la
    conjunción ('Ana, Luis y Marta'), que en castellano se vuelve 'e' delante
    de i- ('Ana e Ignacio'). Los nombres de la tabla de excepciones se apartan
    antes de cortar, porque llevan dentro una coma o una conjunción.
    """
    texto = " ".join(articulo.get("autor", "").split())
    texto, guardados = apartar(texto, excepciones)

    nombres = []
    for trozo in RE_AUTORES.split(texto):
        trozo = " ".join(devolver(trozo, guardados).split())
        if trozo:
            nombres.append(trozo)
    return nombres


def inicial(nombre):
    """Letra bajo la que se archiva un nombre; lo demás va junto al final."""
    letra = sin_tildes(nombre[:1]).upper()
    return letra if "A" <= letra <= "Z" else LETRA_RESTO


def es_lista_de_textos(tabla):
    """¿Es una lista de cadenas, que es lo que la tabla debe ser?"""
    return isinstance(tabla, list) and all(isinstance(x, str) for x in tabla)


def es_lista_de_grupos(tabla):
    """¿Es una lista de listas de cadenas?"""
    return isinstance(tabla, list) and all(es_lista_de_textos(x) for x in tabla)


def tabla_de_ajustes(opciones, clave, fabrica, tiene_forma):
    """Una de las tablas que el usuario puede retocar en config.json.

    Devuelve la tabla y si ha habido que rellenarla con la de fábrica, que es
    lo que obliga a reescribir los ajustes.
    """
    tabla = opciones.config.get(clave)
    if tabla is None:
        opciones.config[clave] = copy.deepcopy(fabrica)
        return opciones.config[clave], True

    if not tiene_forma(tabla):
        avisar(
            "la clave «%s» de %s no tiene la forma esperada; se usa la de fábrica"
            % (clave, ruta_config(opciones))
        )
        return copy.deepcopy(fabrica), False

    return tabla, False


def preparar_tablas(opciones):
    """Las tablas de excepciones y de equivalencias, de los ajustes o de fábrica.

    Las que falten se anotan en config.json, para poder retocarlas a mano.
    """
    excepciones, falta_una = tabla_de_ajustes(
        opciones, CLAVE_EXCEPCIONES, EXCEPCIONES, es_lista_de_textos
    )
    equivalencias, falta_otra = tabla_de_ajustes(
        opciones, CLAVE_EQUIVALENCIAS, EQUIVALENCIAS, es_lista_de_grupos
    )

    faltan = [
        clave
        for clave, falta in ((CLAVE_EXCEPCIONES, falta_una), (CLAVE_EQUIVALENCIAS, falta_otra))
        if falta
    ]
    if faltan:
        rotulo = "se anotaría" if opciones.simulacion else "anotada"
        informar(
            opciones,
            "  %s la tabla de %s en %s"
            % (rotulo, " y la de ".join(faltan), escribir_config(opciones)),
        )

    return excepciones, equivalencias


def partes_nombre(nombre):
    """Un nombre partido en piezas comparables, sin tildes ni guiones.

    Se deshacen los guiones porque la misma persona firma unas veces
    'Martínez-Finkelshtein' y otras 'Martínez Finkelshtein'.
    """
    llano = sin_tildes(nombre.replace("-", " ").replace("‐", " ")).lower()
    return [pieza for pieza in llano.split() if pieza]


def clave_firma(nombre):
    """Firma normalizada, que es como se decide si dos son la misma."""
    return " ".join(partes_nombre(nombre))


def es_abreviatura(pieza):
    """¿Es la inicial de un nombre? 'J', 'J.' y también la 'M.ª' de María."""
    return bool(RE_ABREVIATURA.match(pieza))


def abrevia(corta, larga):
    """¿La primera es la segunda con menos apellidos, o con iniciales?

    Vale que se dejen apellidos por el camino ('Adolfo Quirós' de 'Adolfo
    Quirós Gracián') y que los nombres vayan con inicial ('A. Moreno-González'
    de 'Auxiliadora Moreno-González'), pero sólo abrevia la corta: si es la
    larga la que lleva la inicial, no hay manera de saber qué esconde.
    """
    piezas_corta, piezas_larga = corta.split(), larga.split()
    if len(piezas_corta) > len(piezas_larga) or piezas_corta == piezas_larga:
        return False
    for pieza, otra in zip(piezas_corta, piezas_larga):
        if pieza == otra:
            continue
        if es_abreviatura(pieza) and pieza[0] == otra[0]:
            continue
        return False
    return True


def calla_segundo_nombre(corta, larga):
    """¿La primera es la segunda sin su segundo nombre? ('Ágata A. Timón').

    Se exige que lo que se calla sea una inicial y que el resto case palabra
    por palabra: admitir que fuese un nombre entero emparejaría apellidos
    ('Manuel Domínguez' con 'Manuel Perera Domínguez').
    """
    piezas_corta, piezas_larga = corta.split(), larga.split()
    if len(piezas_larga) != len(piezas_corta) + 1 or len(piezas_corta) < 2:
        return False
    if not es_abreviatura(piezas_larga[1]):
        return False
    return piezas_corta == piezas_larga[:1] + piezas_larga[2:]


def es_reduccion(corta, larga):
    """¿Es la primera una manera abreviada de firmar la segunda?"""
    return abrevia(corta, larga) or calla_segundo_nombre(corta, larga)


def se_parecen(claves):
    """¿Son todas variantes unas de otras, o hay dos que no tienen que ver?"""
    return all(
        una == otra or es_reduccion(una, otra) or es_reduccion(otra, una)
        for una in claves
        for otra in claves
    )


def mismas_personas(claves, equivalencias=()):
    """Decide qué firmas son de la misma persona; devuelve firma -> persona.

    Cuando una firma corta encaja en dos largas que no se parecen entre sí,
    no hay manera de saber de quién es y se la deja sola, salvo que la tabla
    de equivalencias del mapa diga a quién pertenece.
    """
    claves = sorted(claves)
    # la primera pieza siempre casa, así que basta comparar con quien la
    # empiece por la misma letra
    montones = {}
    for clave in claves:
        montones.setdefault(clave[:1], []).append(clave)

    padre = {}

    def raiz(clave):
        while padre.get(clave, clave) != clave:
            clave = padre[clave]
        return clave

    def unir(una, otra):
        una, otra = raiz(una), raiz(otra)
        if una != otra:
            padre[una] = otra

    dudosas = []
    for clave in claves:
        largas = [
            otra
            for otra in montones.get(clave[:1], ())
            if otra != clave and es_reduccion(clave, otra)
        ]
        if len(largas) > 1 and not se_parecen(largas):
            dudosas.append((clave, largas))
            continue
        for larga in largas:
            unir(clave, larga)

    # lo que diga el mapa va por encima de lo que se deduzca
    conocidas = set(claves)
    for iguales in equivalencias:
        firmas = [clave_firma(firma) for firma in iguales]
        firmas = [firma for firma in firmas if firma in conocidas]
        for otra in firmas[1:]:
            unir(firmas[0], otra)

    for clave, largas in dudosas:
        raices = {raiz(larga) for larga in largas}
        if raiz(clave) in raices:
            continue  # la tabla ya ha dicho de quién es esta firma
        if len(raices) == 1:
            unir(clave, largas[0])  # las candidatas resultaron ser la misma
            continue
        avisar(
            "la firma «%s» encaja en varias que no se parecen (%s); se deja aparte"
            % (clave, ", ".join("«%s»" % larga for larga in largas))
        )

    return {clave: raiz(clave) for clave in claves}


def nombre_canonico(firmas):
    """De todas las firmas de un autor, la más completa y luego la más usada."""

    def puntuar(nombre):
        piezas = partes_nombre(nombre)
        enteras = sum(0 if es_abreviatura(pieza) else 1 for pieza in piezas)
        # a igualdad de todo, la grafía con más tildes: en castellano lo que
        # se descuida es ponerlas, no inventárselas
        tildes = sum(1 for letra in nombre if sin_tildes(letra) != letra)
        return (enteras, firmas[nombre], tildes, len(nombre))

    return max(firmas, key=puntuar)


def linea_firmas(autor):
    """Las distintas maneras en que este autor ha firmado, y cuántas veces."""
    firmas = sorted(autor["firmas"].items(), key=lambda par: (-par[1], par[0]))
    return '<p class="firmas">Firmas: %s</p>' % ", ".join(
        "%s (%d)" % (escapar_html(nombre), veces) for nombre, veces in firmas
    )


def agrupar_autores(numeros, excepciones=(), equivalencias=()):
    """Reúne los artículos de todo el archivo por autor.

    Una misma persona firma de varias maneras, así que primero se decide qué
    firmas son suyas y luego se junta lo que haya publicado con todas ellas.
    """
    apariciones = []
    firmas = Counter()
    for volumen, numero in numeros:
        secciones = secciones_del_numero(numero)
        for articulo in articulos_de(numero["articulos"]):
            nombres = autores_de(articulo, excepciones)
            for nombre in nombres:
                firmas[nombre] += 1
            if nombres:
                seccion = secciones.get(id(articulo))
                apariciones.append((volumen, numero, seccion, articulo, nombres))

    de_quien = mismas_personas(
        {clave_firma(nombre) for nombre in firmas}, equivalencias
    )

    grupos = {}
    for volumen, numero, seccion, articulo, nombres in apariciones:
        # dict.fromkeys quita repetidos sin descolocar el orden, por si el
        # mismo autor apareciera dos veces firmando distinto
        for clave in dict.fromkeys(de_quien[clave_firma(n)] for n in nombres):
            grupo = grupos.setdefault(clave, {"firmas": Counter(), "apariciones": []})
            grupo["apariciones"].append((volumen, numero, seccion, articulo))
    for nombre, veces in firmas.items():
        grupos[de_quien[clave_firma(nombre)]]["firmas"][nombre] += veces

    autores = []
    for grupo in grupos.values():
        años = [volumen["año"] for volumen, _, _, _ in grupo["apariciones"]]
        autores.append(
            {
                "nombre": nombre_canonico(grupo["firmas"]),
                "firmas": grupo["firmas"],
                "apariciones": grupo["apariciones"],
                "articulos": len(grupo["apariciones"]),
                "desde": min(años),
                "hasta": max(años),
            }
        )

    autores.sort(key=lambda autor: sin_tildes(clave_indice(autor["nombre"])))
    usados = {NOMBRE_PAGINA.lower()}
    for autor in autores:
        autor["pagina"] = "%s/%s" % (
            CARPETA_AUTORES,
            fichero_indice(autor["nombre"], usados, "autor"),
        )
    return autores


def barra_letras(autores, carpeta):
    """Saltos a cada letra del abecedario; las que nadie estrena van apagadas."""
    presentes = {inicial(autor["nombre"]) for autor in autores}
    letras = [chr(codigo) for codigo in range(ord("A"), ord("Z") + 1)]
    if LETRA_RESTO in presentes:
        letras.append(LETRA_RESTO)
    saltos = [
        '<a href="#%s">%s</a>' % (ancla_letra(letra), letra)
        if letra in presentes
        else "<span>%s</span>" % letra
        for letra in letras
    ]
    return '<p class="letras">%s</p>' % "\n".join(saltos)


def ancla_letra(letra):
    """Identificador con el que se salta al bloque de una letra."""
    return "letra-%s" % (letra if letra != LETRA_RESTO else "resto")


def pagina_autores(autores, opciones):
    """El índice de autores, por orden alfabético y agrupado por letras."""
    carpeta = posixpath.dirname(RUTA_AUTORES)
    trozos = [
        barra_navegacion(
            botones_indices(carpeta, salvo=RUTA_AUTORES), carpeta, True
        ),
        barra_letras(autores, carpeta),
    ]
    letra_abierta = None
    for autor in autores:
        letra = inicial(autor["nombre"])
        if letra != letra_abierta:
            trozos.append('<h2 id="%s">%s</h2>' % (ancla_letra(letra), letra))
            letra_abierta = letra
        trozos.append(linea_indice(autor, carpeta))
    return envolver_pagina("Autores", "\n".join(trozos), carpeta)


def tandas_del_autor(autor):
    """Los artículos del autor, por número (del más nuevo al más viejo).

    Dentro de cada número se respeta el orden del sitemap, igual que en las
    páginas de sección, agrupando los artículos por la sección de la que
    cuelgan.
    """
    bloques = []
    for volumen, numero, seccion, articulo in autor["apariciones"]:
        if not bloques or bloques[-1][1] is not numero:
            bloques.append((volumen, numero, []))
        tandas = bloques[-1][2]
        if not tandas or tandas[-1][0] != seccion:
            tandas.append((seccion, []))
        tandas[-1][1].append(articulo)
    bloques.reverse()
    return bloques


def pagina_autor(autores, posicion, opciones, indices=None):
    """La página de un autor: sus artículos, del más reciente al más antiguo."""
    autor = autores[posicion]
    carpeta = posixpath.dirname(autor["pagina"])

    def salto(indice):
        if indice == posicion or not 0 <= indice < len(autores):
            return None
        return enlace_desde(autores[indice]["pagina"], carpeta)

    botones = botones_indices(carpeta) + [
        boton_web("« Primero", salto(0)),
        boton_web("‹ Anterior", salto(posicion - 1)),
        boton_web("Siguiente ›", salto(posicion + 1)),
        boton_web("Último »", salto(len(autores) - 1)),
    ]
    trozos = [barra_navegacion(botones, carpeta), linea_firmas(autor)]
    for volumen, numero, tandas in tandas_del_autor(autor):
        trozos.append(encabezado_numero(volumen, numero, carpeta))
        for seccion, articulos in tandas:
            if seccion is not None:
                trozos.append(encabezado_seccion(seccion, carpeta, 3, indices))
            trozos.extend(
                cita_articulo(articulo, carpeta, opciones, indices)
                for articulo in articulos
            )
    return envolver_pagina(autor["nombre"], "\n".join(trozos), carpeta)


def firma_indice(nombre, firmas, indices):
    """Apunta una firma en la tabla del índice y devuelve dónde ha quedado."""
    pagina = ((indices or {}).get("autores") or {}).get(clave_firma(nombre))
    return firmas.setdefault((nombre, pagina), len(firmas))


def datos_articulo(articulo, opciones, firmas, indices):
    """Lo que necesita el navegador para montar la cita de un artículo.

    Es lo mismo que compone cita_articulo(), pero en piezas: sale a menos de
    la mitad que mandar la cita ya escrita, y el guion la rehace igual.
    """
    quienes = 0  # ni una lista vacía: para el guion sería un autor de mentira
    if "autor" in articulo:
        quienes = [
            firma_indice(nombre, firmas, indices)
            for nombre in autores_de(articulo, (indices or {}).get("excepciones") or ())
        ]
        # si no se pudo separar, va el campo tal cual, como en la cita
        quienes = quienes or articulo["autor"]

    enlace = articulo.get("link") or 0
    if enlace and enlace.startswith(URL_ARTICULO):
        enlace = int(enlace[len(URL_ARTICULO):])  # basta con el id

    inicio = articulo.get("pagina_inicio")
    paginas = 0 if inicio is None else [inicio, articulo.get("pagina_fin", inicio)]

    local = None if opciones.externa else fichero_local(articulo, opciones)
    datos = [
        articulo["nombre"],
        0,  # el número, que rellena quien llama
        0,  # y la sección
        quienes,
        enlace,
        paginas,
        articulo.get("doi", 0),
        enlace_desde(local, "") if local else 0,
    ]
    # los huecos del final no hacen falta: el guion los lee como vacíos
    while len(datos) > 3 and not datos[-1]:
        datos.pop()
    return datos


def datos_autor(autor):
    """Lo que necesita el navegador para montar la línea de un autor.

    Es lo mismo que compone linea_indice(), pero en piezas, igual que con los
    artículos.
    """
    datos = [
        autor["nombre"],
        enlace_web(autor["pagina"]),
        autor["articulos"],
        autor["desde"],
        autor["hasta"],
    ]
    if datos[-1] == datos[-2]:  # un solo año, y el guion lo repite
        datos.pop()
    return datos


def indice_busqueda(numeros, autores, opciones, indices):
    """El índice que el navegador recorre al buscar, listo para servirlo.

    Va como guion y no como JSON porque el sitio también se abre con un doble
    clic, y desde file:// el navegador no deja leer un fichero suelto pero sí
    cargar un guion. Los encabezados, que son pocos, viajan ya montados y
    relativos a la raíz, que es donde vive la página de resultados; las citas,
    que son dos mil, viajan en piezas y las monta el guion.
    """
    encabezados, tandas, firmas, articulos = [], {}, {}, []
    for volumen, numero in numeros:
        secciones = secciones_del_numero(numero)
        encabezados.append(encabezado_numero(volumen, numero, ""))
        for articulo in articulos_de(numero["articulos"]):
            seccion = secciones.get(id(articulo))
            datos = datos_articulo(articulo, opciones, firmas, indices)
            datos[1] = len(encabezados) - 1
            datos[2] = tandas.setdefault(seccion, len(tandas)) if seccion else -1
            articulos.append(datos)

    datos = {
        "externa": bool(opciones.externa),
        "numeros": encabezados,
        "secciones": [encabezado_seccion(nombre, "", 3, indices) for nombre in tandas],
        "firmas": [[nombre, pagina] for nombre, pagina in firmas],
        "articulos": articulos,
        "autores": [datos_autor(autor) for autor in autores],
    }
    return "var BUSQUEDA = %s;\n" % json.dumps(
        datos, ensure_ascii=False, separators=(",", ":")
    )


def pagina_busqueda(autores=False):
    """La página de resultados, que el guion rellena en el propio navegador.

    Hay una por cada cosa que se busca; el guion es el mismo, y sabe cuál es
    la suya porque la propia página se lo dice.
    """
    cuerpo = """%s
<p class="cuenta" id="cuenta">Hace falta JavaScript para buscar.</p>
<div id="resultados" data-busca="%s"></div>
<script src="%s"></script>
<script src="%s"></script>""" % (
        barra_navegacion(botones_indices(""), "", autores),
        "autores" if autores else "articulos",
        enlace_web(NOMBRE_INDICE),
        enlace_web(NOMBRE_BUSCADOR),
    )
    titulo = "Búsqueda de autores" if autores else "Búsqueda"
    return envolver_pagina(titulo, cuerpo, "")


def ruta_del_sitio(nombre, opciones):
    """Dónde cae en el disco un fichero del sitio, dada su ruta desde la raíz.

    El sitio se escribe dentro del archivo, salvo con --publicar, que lo manda
    a otra carpeta para poder colgarlo sin los PDF.
    """
    return os.path.join(opciones.sitio, nombre.replace("/", os.sep))


def escribir_web(nombre, contenido, opciones, callado=False):
    """Escribe uno de los ficheros del sitio, dada su ruta desde la raíz."""
    ruta = ruta_del_sitio(nombre, opciones)
    if opciones.simulacion:
        if not callado:
            informar(opciones, "  se escribiría %s" % ruta)
        return
    with open(ruta, "w", encoding="utf-8") as fichero:
        fichero.write(contenido)
    if not callado:
        informar(opciones, "  %s" % ruta)


def limpiar_sobras(carpetas, escritos, opciones):
    """Retira los HTML que dejó una generación anterior y ya no se enlazan.

    Sólo se miran las carpetas que son del sitio de arriba abajo, y dentro de
    ellas sólo se borran ficheros .html: lo descargado no se toca. La
    comparación no distingue mayúsculas, porque Windows conserva el nombre con
    el que se creó el fichero aunque después se escriba de otra manera.
    """
    quedan = {nombre.lower() for nombre in escritos}
    sobras = 0
    for carpeta in carpetas:
        raiz = ruta_del_sitio(carpeta, opciones)
        if not os.path.isdir(raiz):
            continue
        for nombre in sorted(os.listdir(raiz)):
            camino = os.path.join(raiz, nombre)
            if not nombre.lower().endswith(".html") or not os.path.isfile(camino):
                continue
            if ("%s/%s" % (carpeta, nombre)).lower() in quedan:
                continue
            informar(
                opciones,
                "  %s %s"
                % ("se retiraría" if opciones.simulacion else "retirado", camino),
            )
            if not opciones.simulacion:
                os.remove(camino)
            sobras += 1
    return sobras


def copiar_portada(volumen, numero, opciones):
    """Lleva al sitio la portada de un número, si la hay y no está ya allí."""
    portada = portada_descargada(volumen, numero, opciones)
    if portada is None:
        return False
    destino = ruta_del_sitio(portada, opciones)
    if not opciones.simulacion:
        shutil.copyfile(os.path.join(opciones.destino, portada), destino)
    return True


def sin_mapear(mapa):
    """Números del mapa cuyo índice de artículos todavía no se ha descargado."""
    return [
        (volumen, numero)
        for volumen in mapa["volumenes"]
        for numero in volumen["numeros"]
        if "articulos" not in numero
    ]


def generar_web(opciones):
    """Rehace el sitio a partir del mapa y de lo que haya en el disco."""
    mapa = leer_mapa(opciones)
    if mapa is None:
        return error(
            "no existe %s; ejecuta antes --mapa para crearlo" % ruta_mapa(opciones)
        )

    pendientes = sin_mapear(mapa)
    if pendientes:
        volumen, numero = pendientes[0]
        cuantos = (
            "falta un número por mapear"
            if len(pendientes) == 1
            else "faltan %d números por mapear" % len(pendientes)
        )
        return error(
            "el sitio necesita el archivo entero mapeado, y %s (el primero, "
            "%s, %s); ejecuta antes --mapa sobre ellos"
            % (cuantos, rotulo_volumen(volumen), rotulo_numero(numero))
        )

    asegurar_carpeta(opciones.sitio, opciones)
    escribir_web(NOMBRE_PAGINA, pagina_indice(mapa, opciones), opciones)
    escribir_web(NOMBRE_ESTILO, ESTILO, opciones)
    if opciones.publicar:
        escribir_web(NOMBRE_NOJEKYLL, "", opciones)

    numeros = [
        (volumen, numero)
        for volumen in mapa["volumenes"]
        for numero in volumen["numeros"]
    ]
    excepciones, equivalencias = preparar_tablas(opciones)
    secciones = agrupar_secciones(numeros)
    autores = agrupar_autores(numeros, excepciones, equivalencias)
    # dónde vive la página de cada sección y de cada autor, para enlazarlas
    indices = {
        "secciones": {
            clave_indice(seccion["nombre"]): seccion["pagina"] for seccion in secciones
        },
        # se busca por cualquiera de sus firmas, no sólo por la elegida
        "autores": {
            clave_firma(firma): autor["pagina"]
            for autor in autores
            for firma in autor["firmas"]
        },
        "excepciones": excepciones,
    }

    portadas = 0
    for posicion, (volumen, numero) in enumerate(numeros):
        # la carpeta falta si ese número no se llegó a descargar
        pagina = ruta_pagina_numero(volumen, numero)
        asegurar_carpeta(
            ruta_del_sitio(posixpath.dirname(pagina), opciones), opciones
        )
        escribir_web(
            pagina,
            pagina_numero(numeros, posicion, opciones, indices),
            opciones,
            callado=True,
        )
        if opciones.publicar:
            portadas += copiar_portada(volumen, numero, opciones)
    informar(opciones, "  %d páginas de número" % len(numeros))
    if opciones.publicar:
        informar(
            opciones,
            "  %d portadas %s"
            % (portadas, "por copiar" if opciones.simulacion else "copiadas"),
        )

    asegurar_carpeta(ruta_del_sitio(CARPETA_SECCIONES, opciones), opciones)
    escribir_web(RUTA_SECCIONES, pagina_secciones(secciones, opciones), opciones)
    for posicion, seccion in enumerate(secciones):
        escribir_web(
            seccion["pagina"],
            pagina_seccion(secciones, posicion, opciones, indices),
            opciones,
            callado=True,
        )
    informar(opciones, "  %d páginas de sección" % len(secciones))

    asegurar_carpeta(ruta_del_sitio(CARPETA_AUTORES, opciones), opciones)
    escribir_web(RUTA_AUTORES, pagina_autores(autores, opciones), opciones)
    for posicion, autor in enumerate(autores):
        escribir_web(
            autor["pagina"],
            pagina_autor(autores, posicion, opciones, indices),
            opciones,
            callado=True,
        )
    informar(opciones, "  %d páginas de autor" % len(autores))

    escribir_web(NOMBRE_BUSQUEDA, pagina_busqueda(), opciones)
    escribir_web(NOMBRE_BUSQUEDA_AUTORES, pagina_busqueda(True), opciones)
    escribir_web(NOMBRE_BUSCADOR, BUSCADOR, opciones)
    escribir_web(
        NOMBRE_INDICE,
        indice_busqueda(numeros, autores, opciones, indices),
        opciones,
    )

    # lo que quedó de una generación anterior sobra: los nombres cambian
    escritos = {RUTA_SECCIONES, RUTA_AUTORES}
    escritos.update(seccion["pagina"] for seccion in secciones)
    escritos.update(autor["pagina"] for autor in autores)
    sobras = limpiar_sobras((CARPETA_SECCIONES, CARPETA_AUTORES), escritos, opciones)
    if sobras:
        informar(opciones, "  %d páginas obsoletas de más" % sobras)

    informar(
        opciones,
        "Sitio generado en %s: %d volúmenes, %d números, %d secciones y "
        "%d autores."
        % (
            opciones.sitio,
            len(mapa["volumenes"]),
            len(numeros),
            len(secciones),
            len(autores),
        ),
    )
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
        "-D", "--descarga",
        action="store_true", default=False,
        help="descarga el número indicado con --vol/--num, o todo el archivo",
    )
    analizador.add_option(
        "-f", "--formato",
        metavar="MODO",
        help="qué bajar de cada número: «articulo» (los artículos sueltos, "
             "por defecto), «numero» (el ejemplar de una pieza, si se ofrece) "
             "o «ambos» (las dos cosas)",
    )
    analizador.add_option(
        "-w", "--web",
        action="store_true", default=False,
        help="genera el sitio web que sirve el archivo ya descargado",
    )
    analizador.add_option(
        "-P", "--publicar",
        metavar="DIR",
        help="con --web, escribe el sitio en esa carpeta en vez de dentro del "
             "archivo, con las portadas pero sin los PDF, listo para colgarlo",
    )
    analizador.add_option(
        "-x", "--externa",
        action="store_true", default=False,
        help="con --web, enlaza los PDF a la revista en vez de a las copias "
             "locales, para poder publicar el sitio sin ellas",
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
    opciones.sesion = False
    opciones.config = leer_config(opciones)

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

    if opciones.formato is not None:
        if not opciones.descarga:
            analizador.error("--formato sólo tiene sentido junto a --descarga")
        elegido = opciones.formato.strip().lower()
        elegido = FORMATOS_ALIAS.get(elegido, elegido)
        if elegido not in FORMATOS:
            analizador.error(
                "formato desconocido: «%s»; elige entre %s"
                % (opciones.formato, ", ".join("«%s»" % f for f in FORMATOS))
            )
        opciones.formato = elegido
    else:
        opciones.formato = FORMATO_ARTICULO

    if opciones.externa and not opciones.web:
        analizador.error("--externa sólo tiene sentido junto a --web")

    if opciones.publicar is not None and not opciones.web:
        analizador.error("--publicar sólo tiene sentido junto a --web")

    # el sitio se escribe dentro del archivo mientras no se diga otra cosa; lo
    # que se publica no lleva PDF, así que enlaza a la revista
    opciones.sitio = opciones.publicar or opciones.destino
    if opciones.publicar:
        opciones.externa = True

    if opciones.web:
        if opciones.mapa or opciones.descarga:
            analizador.error("--web se usa por su cuenta, sin --mapa ni --descarga")
        if opciones.vol is not None:
            analizador.error("--web rehace el sitio entero; no admite --vol ni --num")

    if not opciones.mapa and not opciones.descarga and not opciones.web:
        if opciones.vol is not None:
            analizador.error("indica qué hacer con ese número: --mapa o --descarga")
        analizador.print_help()
        return 0

    try:
        if opciones.web:
            return generar_web(opciones)
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
