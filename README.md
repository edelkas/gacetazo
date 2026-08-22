# gaceta

Herramienta para archivar **La Gaceta de la RSME** (<https://gaceta.rsme.es>).

La revista no publica sus números de forma uniforme: unos se ofrecen enteros en
PDF y otros sólo artículo por artículo. `gaceta.py` recorre la web, construye un
árbol de carpetas por volumen y número, y vuelca en `sitemap.json` todo lo que
encuentra (números, suplementos, secciones, artículos y sus metadatos).

## Requisitos

Python 3, `requests` y `beautifulsoup4`.

```
pip install requests beautifulsoup4
```

## Uso

Sin argumentos muestra la ayuda.

```
python gaceta.py --mapa                        # indice general: carpetas + sitemap.json
python gaceta.py --mapa --vol 29 --num 1       # indice de artículos de un número
python gaceta.py --mapa --vol 6 --num 2 --sup  # ídem, del suplemento de ese número
```

| Opción | Descripción |
| --- | --- |
| `-h`, `--ayuda` | Muestra la ayuda y termina |
| `--version` | Muestra la versión y termina |
| `-m`, `--mapa` | Mapea el índice general, o el número indicado con `--vol`/`--num` |
| `-v N`, `--vol=N` | Volumen sobre el que actuar |
| `-N N`, `--num=N` | Número dentro de ese volumen |
| `-s`, `--sup` | Actúa sobre el suplemento de ese número |
| `-d DIR`, `--destino=DIR` | Carpeta raíz del archivo (por defecto, la actual) |
| `-n`, `--simulacion` | Informa de lo que haría, sin escribir nada |
| `-q`, `--silencioso` | Oculta la información de progreso |

El mapeo de un número exige que `sitemap.json` exista ya. Volver a ejecutar
`--mapa` no destruye lo mapeado: los artículos y los suplementos se trasladan al
índice recién descargado.

## Estructura

```
Vol 06 (2003)/
  1/  2/  2 sup/  3/      <- "N sup" es el suplemento del número N
sitemap.json
```

## Formato de `sitemap.json`

Las claves marcadas con `?` son opcionales y se omiten si no hay dato.

```jsonc
{ "volumenes": [ {
    "num": 6, "año": 2003,
    "numeros": [ {
      "num": 2,
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
{ "num": 2, "nombre": "Gaceta Selecta", "principal": 2,
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
- [ ] Descarga y organización de portadas, PDF y artículos.
