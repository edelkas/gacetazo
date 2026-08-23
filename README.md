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

Nada se descarga dos veces: si ya existe un fichero con ese nombre, se salta.

Los números más recientes están reservados a los socios de la RSME. Su página
se consulta y se mapea con normalidad, pero el PDF redirige al formulario de
acceso; esas descargas se cuentan aparte como *reservadas* y no se guarda nada
en su lugar. Con `--entero`, si el ejemplar completo está reservado se
recurre a los artículos sueltos, que a menudo sí están abiertos.

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
- [ ] Acceso a los números reservados a los socios.
