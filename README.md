# gaceta

Herramienta para archivar **La Gaceta de la RSME** (<https://gaceta.rsme.es>).

La revista no publica sus números de forma uniforme: unos se ofrecen enteros en
PDF y otros sólo artículo por artículo. `gaceta.py` recorre la web y vuelca en
`sitemap.json` todo lo que encuentra (números, suplementos, secciones, artículos
y sus metadatos), para después descargarlo y organizarlo por volumen y número.

## Requisitos

Python 3, `requests` y `beautifulsoup4`.

```
pip install requests beautifulsoup4
```

## Uso

Sin argumentos muestra la ayuda.

```
python gaceta.py --mapa                        # indice general de volúmenes y números
python gaceta.py --mapa --vol 29 --num 1       # indice de artículos de un número
python gaceta.py --mapa --vol 6 --num 2 --sup  # ídem, del suplemento de ese número

python gaceta.py --descarga --vol 1 --num 1    # descarga un número
python gaceta.py --descarga --vol 15 --num 1 --entero   # ídem, de una pieza
python gaceta.py --descarga                    # descarga todo (pide confirmación)
```

| Opción | Descripción |
| --- | --- |
| `-h`, `--ayuda` | Muestra la ayuda y termina |
| `--version` | Muestra la versión y termina |
| `-m`, `--mapa` | Mapea el índice general, o el número indicado con `--vol`/`--num` |
| `-D`, `--descarga` | Descarga ese número, o el archivo entero si no se acota |
| `-e`, `--entero` | Baja el número de una pieza cuando la revista lo ofrezca |
| `-v N`, `--vol=N` | Volumen sobre el que actuar |
| `-N N`, `--num=N` | Número dentro de ese volumen |
| `-s`, `--sup` | Actúa sobre el suplemento de ese número |
| `-u NOMBRE`, `--usuario=NOMBRE` | Usuario de socio con el que acceder |
| `-p CLAVE`, `--contraseña=CLAVE` | Su contraseña (no se guarda en ninguna parte); también `--contrasena` |
| `-c VALOR`, `--cookie=VALOR` | Cookie `PHPSESSID` de una sesión ya abierta |
| `-d DIR`, `--destino=DIR` | Carpeta raíz del archivo (por defecto, la actual) |
| `-n`, `--simulacion` | Informa de lo que haría, sin escribir nada |
| `-q`, `--silencioso` | Oculta la información de progreso |

El mapeo de un número exige que `sitemap.json` exista ya. Volver a ejecutar
`--mapa` no destruye lo mapeado: los artículos y los suplementos se trasladan al
índice recién descargado.

## Descarga

Las carpetas se crean al descargar, y sólo las de aquello que se descarga; el
mapeo no toca el disco más allá de `sitemap.json`. Descargar un número que aún
no esté mapeado lo mapea antes automáticamente.

```
Vol 06 (2003)/
  2/                      <- número 2
    Portada.jpg
    Acerca de la portada.pdf
    6 años de La Gaceta (1998-2003).pdf
    ...
  2 sup/                  <- suplemento del número 2
sitemap.json
```

Cada fichero se guarda con el título de su artículo, saneado para Windows (se
eliminan `<>:"/\|?*`, se recorta a 120 caracteres y se desambiguan los títulos
repetidos con un sufijo `(2)`), y conserva la extensión que anuncia el
servidor. La portada se llama siempre `Portada`, y con `--entero`, el ejemplar
completo se guarda como `Número completo`.

De cada artículo descargado se anota en su entrada del mapa una clave
`fichero` con la ruta relativa a la raíz, el tamaño y el MD5 calculado al
vuelo. Con `--entero`, esa clave se anota en el número en vez de en un
artículo.

```jsonc
"fichero": { "ruta": "Vol 06 (2003)/2 sup/Anexo 6....pdf",
             "tamaño": 86489, "md5": "cdafbcd00e3aaf648a083d30f00457ce" }
```

Nada se descarga dos veces: si el fichero ya está y su MD5 cuadra con el
anotado, se salta. Se vuelve a bajar, sustituyendo lo que hubiera, cuando el
MD5 no cuadra (fichero corrupto o a medias) o cuando no hay ninguno anotado.

### Barra de progreso

Mientras se descarga, la última línea de la consola lleva una barra de estado
que se refresca una vez por segundo:

```
[12/96] Vol 03 (2000), número 1 · 7 de 14 · 1.2 MB (total 4.0 MB) · 1.4 MB/s
```

De izquierda a derecha: el número que se está bajando (con su posición, si se
descarga todo el archivo), los ficheros hechos sobre los previstos, lo que
lleva el fichero actual y el total de la tanda, y la velocidad media de los
últimos cinco segundos.

Los mensajes y avisos se imprimen siempre *por encima* de la barra, que se
mantiene abajo del todo sin dejar copias sueltas por la pantalla. La barra se
desactiva sola cuando la salida no es una consola (redirigida a un fichero o a
otro programa) y con `--silencioso`.

## Material reservado a los socios

Los números más recientes están reservados a los socios de la RSME. Su página
se consulta y se mapea con normalidad, pero el PDF redirige al formulario de
acceso; esas descargas se cuentan aparte como *reservadas* y no se guarda nada
en su lugar. Con `--entero`, si el ejemplar completo está reservado se
recurre a los artículos sueltos, que a menudo sí están abiertos.

La forma cómoda de identificarse es con las credenciales de socio, que la
herramienta usa para entrar por su cuenta:

```
python gaceta.py --descarga --vol 29 --num 1 --usuario NOMBRE --contraseña CLAVE
```

Se envían al mismo `control.php` al que manda el formulario de la portada, y
de ahí se toma la cookie de sesión. **Ni el usuario ni la contraseña se
guardan**: sólo la cookie resultante. Si la revista los rechaza, se dice y no
se descarga nada. Ambas opciones van juntas o ninguna.

También puede pasarse directamente la cookie `PHPSESSID` copiada del
navegador, sólo su valor y sin el `PHPSESSID=` delante:

```
python gaceta.py --descarga --vol 29 --num 1 --cookie 2cc72e32b8cd...
```

Se admite una cadena hexadecimal de entre 22 y 256 caracteres (la revista usa
32) y se rechaza cualquier otra cosa. Si se dan las dos formas a la vez,
`--cookie` manda y no se llega a acceder con las credenciales.

En cualquiera de los dos casos la cookie queda anotada en `sitemap.json` y las
siguientes ejecuciones la reutilizan sin necesidad de repetir nada. Si la
revista deja de reconocerla, se avisa por pantalla, se borra del mapa y la
descarga continúa como visitante. Conviene recordar que esa cookie es una
sesión viva: no compartas el `sitemap.json` sin quitarla antes.

### Todo va cifrado

El formulario de acceso manda la contraseña tal cual, sin cifrar por su
cuenta, así que lo único que la protege es la conexión. El servidor de la
revista atiende igual por HTTP y **no** redirige a HTTPS, de modo que la
herramienta se ocupa de que eso no pase nunca:

- todas las peticiones salen por `https://`, y cualquier enlace del sitio que
  venga en claro se eleva a HTTPS antes de pedirlo;
- el acceso con usuario y contraseña se niega a ejecutarse si la dirección no
  es HTTPS;
- la cookie de sesión se marca como segura, así que no se envía por una
  conexión sin cifrar aunque algo redirija a ella;
- se avisa si alguna redirección acaba sacando una petición de HTTPS.

El certificado se valida siempre (hoy la revista sirve TLS 1.3 con
certificado de Let's Encrypt).

## Formato de `sitemap.json`

Las claves marcadas con `?` son opcionales y se omiten si no hay dato.

```jsonc
{ "volumenes": [ {
    "num": 6, "año": 2003,
    "numeros": [ {
      "num": 2, "id": 20,                       // id de vernumero.php
      "portada": "...jpg", "link": "...vernumero.php?id=20",
      "pagina_inicio?": 271, "pagina_fin?": 518,
      "sup?": "...versuplemento.php?id=21",   // enlace al suplemento
      "link_todo?": "...abrirentero.php?id=20", // sólo si se ofrece entero
      "articulos?": [ /* ver abajo */ ]
    } ] } ] }
```

Un **suplemento** es un número más del volumen, con el mismo `num` que aquel al
que acompaña. Se distingue por la clave `principal` y añade `nombre`:

```jsonc
{ "num": 2, "nombre": "Gaceta Selecta", "principal": 2, "id": 21,
  "portada": "...jpg", "link": "...versuplemento.php?id=21", "articulos?": [] }
```

`articulos` es una lista recursiva. Una entrada es **sección** si tiene la clave
`articulos`, y **artículo** en caso contrario:

```jsonc
// sección (o subsección, con la misma forma)
{ "nombre": "Artículos", "articulos": [ ... ] }

// artículo
{ "nombre": "Carta de la Presidenta", "autor?": "M. Victoria Otero Espinar",
  "id": 1932, "link": "...abrir.php?id=1932",
  "pagina_inicio?": 5, "pagina_fin?": 8, "doi?": "10.63427/ISDN5447" }
```

Casos particulares del árbol:

- **«Acerca de la portada»**: prefacio que casi todos los números publican junto
  a la portada. Va como primer artículo de la raíz, con autor fijo *Redacción de
  La Gaceta*, enlace directo al PDF (sin `id` ni páginas) y el texto de
  presentación en `descripcion?`. Es el único artículo con esa clave.
- Un artículo de una sola página tiene `pagina_inicio` y `pagina_fin` iguales.

Durante el mapeo se avisa por pantalla de las anomalías del documento:
subsecciones huérfanas, secciones sin artículos y artículos fuera de toda
sección. Hoy el archivo completo se analiza sin un solo aviso.

## Estado

- [x] Índice general: 29 volúmenes (1998–2026) y 93 números.
- [x] Índice de artículos de un número o suplemento: 3 suplementos y ~1960
      artículos en total.
- [x] Descarga y organización de portadas, artículos y números enteros.
- [x] Acceso a los números reservados a los socios, mediante cookie de sesión.
