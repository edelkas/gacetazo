# gaceta

Herramienta para archivar **La Gaceta de la RSME** (<https://gaceta.rsme.es>).

La revista no publica sus números de forma uniforme: unos se ofrecen enteros en
PDF y otros sólo artículo por artículo. `gaceta.py` recorre la web y vuelca en
`sitemap.json` todo lo que encuentra (números, suplementos, secciones, artículos
y sus metadatos), para después descargarlo, organizarlo por volumen y número y
servirlo en una web local.

## Requisitos

Python 3, `requests` y `beautifulsoup4`. `Pillow` es opcional: sólo se usa
para reescalar las portadas, y sin él todo lo demás funciona igual.

```
pip install requests beautifulsoup4 Pillow
```

## Uso

Sin argumentos muestra la ayuda.

```
python gaceta.py --mapa                        # indice general de volúmenes y números
python gaceta.py --mapa --vol 29 --num 1       # indice de artículos de un número
python gaceta.py --mapa --vol 6 --num 2 --sup  # ídem, del suplemento de ese número

python gaceta.py --descarga --vol 1 --num 1    # descarga un número
python gaceta.py --descarga --vol 15 --num 1 --formato numero  # ídem, de una pieza
python gaceta.py --descarga --vol 15 --num 1 --formato ambos   # ídem, las dos cosas
python gaceta.py --descarga                    # descarga todo (pide confirmación)

python gaceta.py --web                         # genera la web con lo descargado
python gaceta.py --web --externa               # ídem, enlazando los PDF a la RSME
python gaceta.py --web --publicar ../gaceta-web # el sitio que se cuelga, aparte
```

| Opción | Descripción |
| --- | --- |
| `-h`, `--ayuda` | Muestra la ayuda y termina |
| `--version` | Muestra la versión y termina |
| `-m`, `--mapa` | Mapea el índice general, o el número indicado con `--vol`/`--num` |
| `-D`, `--descarga` | Descarga ese número, o el archivo entero si no se acota |
| `-f MODO`, `--formato=MODO` | Qué bajar de cada número: `articulo`, `numero` o `ambos` |
| `-v N`, `--vol=N` | Volumen sobre el que actuar |
| `-N N`, `--num=N` | Número dentro de ese volumen |
| `-s`, `--sup` | Actúa sobre el suplemento de ese número |
| `-u NOMBRE`, `--usuario=NOMBRE` | Usuario de socio con el que acceder |
| `-p CLAVE`, `--contraseña=CLAVE` | Su contraseña (no se guarda en ninguna parte); también `--contrasena` |
| `-c VALOR`, `--cookie=VALOR` | Cookie `PHPSESSID` de una sesión ya abierta |
| `-d DIR`, `--destino=DIR` | Carpeta raíz del archivo (por defecto, la actual) |
| `-w`, `--web` | Rehace la web local a partir del mapa y de lo descargado |
| `-x`, `--externa` | Con `--web`, enlaza los PDF a la RSME en vez de a las copias locales |
| `-M`, `--sin-miniaturas` | No reescala las portadas para el índice, y así no hace falta Pillow |
| `-P DIR`, `--publicar=DIR` | Con `--web`, escribe el sitio en `DIR` (con las portadas, sin los PDF) |
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
numeros/
  vol.06-2003/
    2/                    <- número 2
      Portada.jpg
      Miniatura.jpg         <- la portada al tamaño del índice
      Acerca de la portada.pdf
      6 años de La Gaceta (1998-2003).pdf
      ...
    2-sup/                <- suplemento del número 2
sitemap.json
```

Las carpetas y las páginas del sitio se nombran con lo más llano del ASCII
—letras, cifras, puntos, guiones y subrayados—, de modo que ninguna dirección
necesita escapes y hasta un navegador viejo las abre. Los PDF, que no se
publican, conservan su título con tildes y espacios. Si el archivo viene de una
versión anterior, que llamaba a las carpetas `Vol 06 (2003)` y `2 sup`, el
programa las renombra solo y corrige las rutas anotadas en el mapa.

Cada número puede bajarse de tres formas, según `--formato`:

| Valor | Qué se baja |
| --- | --- |
| `articulo` | Los artículos sueltos, uno a uno (por defecto) |
| `numero` | El ejemplar completo de una pieza, si la revista lo ofrece |
| `ambos` | Las dos cosas, cuando ambas están disponibles |

Con `numero`, si el ejemplar completo no se ofrece o está reservado, se recurre
a los artículos sueltos. Con `ambos` conviven en la misma carpeta el `Número
completo` y los artículos, sin estorbarse.

Cada fichero se guarda con el título de su artículo, saneado para Windows (se
eliminan `<>:"/\|?*`, se recorta a 120 caracteres y se desambiguan los títulos
repetidos con un sufijo `(2)`), y conserva la extensión que anuncia el
servidor. La portada se llama siempre `Portada`, y el ejemplar completo,
`Número completo`.

De cada artículo descargado se anota en su entrada del mapa una clave
`fichero` con la ruta relativa a la raíz, el tamaño y el MD5 calculado al
vuelo. La del ejemplar completo se anota en el número en vez de en un
artículo, así que con `--formato=ambos` se llevan las dos.

```jsonc
"fichero": { "ruta": "numeros/vol.06-2003/2-sup/Anexo 6....pdf",
             "tamaño": 86489, "md5": "cdafbcd00e3aaf648a083d30f00457ce" }
```

Nada se descarga dos veces: si el fichero ya está y su MD5 cuadra con el
anotado, se salta. Se vuelve a bajar, sustituyendo lo que hubiera, cuando el
MD5 no cuadra (fichero corrupto o a medias) o cuando no hay ninguno anotado.

### Miniaturas de las portadas

El índice enseña las noventa y tantas portadas a la vez, y a tamaño completo
son tres megas que se bajan de golpe. Así que al guardar una portada se
reescala también al hueco que ocupa allí, y queda junto a ella como
`Miniatura.jpg`: 168x236 píxeles —el doble del hueco, para que no se vea
borrosa en pantallas finas— y recortada como la recorta el navegador, con
`object-fit: cover`. Las noventa y seis pesan 0,9 MB en vez de 3,0 MB.

Se hace una sola vez: si la miniatura ya está, no se toca; sólo se rehace si
la portada se ha vuelto a bajar después. `--web` reescala de paso las que
falten, que para eso las necesita el índice. La página de cada número sigue
mostrando la portada entera.

Esto es lo único que necesita Pillow. Con `--sin-miniaturas` no se reescala
nada, y el índice tira de las portadas enteras (o de las miniaturas que ya
hubiera); sin Pillow instalado ocurre lo mismo, con un aviso.

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

## Web local

`--web` vuelca el archivo en un sitio estático que se abre con un doble clic,
sin servidor de por medio:

```
index.html                        <- portada: la tabla de volúmenes
estilo.css
tema.js                           <- el modo oscuro y los botones de la esquina
buscar.html                       <- resultados de la búsqueda
buscar-autores.html               <- y los de la búsqueda de autores
numeros/vol.29-2026/1/            <- una carpeta por número, con su index.html
secciones/index.html              <- índice de secciones
secciones/Editorial.html          <- una página por sección
autores/index.html                <- índice de autores
autores/Maria-Gaspar.html         <- una página por autor
```

El sitio se rehace entero cada vez, así que no conviene editarlo a mano. Hace
falta tener mapeado el archivo completo; si falta algún número por mapear, se
dice cuál y no se genera nada.

La portada muestra una tabla con un volumen por fila —del más reciente al más
antiguo— y sus números por columna, cada uno con su imagen de portada si ya
está descargada (y su nombre si no), enlazada a la página del número. Encima,
una barra de saltos a cada volumen, esta en orden natural.

La página de cada número lleva su título (volumen, año, número y nombre, si lo
tiene), que enlaza a la página que la revista le dedica; una barra para
recorrer el archivo de número en número (índice, primero, anterior, siguiente y
último; los extremos salen apagados) y, a la derecha, la portada en grande con
el enlace al ejemplar completo —el descargado, o el de la revista si no está— y
al «Acerca de la portada».

A la izquierda, el índice del número reproduce el árbol del mapa: un
encabezado por sección y subsección —las de primer nivel enlazan a su página
del índice de secciones—, y cada artículo como una cita:

> **Carta de la Presidenta**, *M. Victoria Otero Espinar*, págs. 5-8,
> <https://www.doi.org/10.63427/ISDN5447>, RSME

El título enlaza al PDF descargado (y va sin enlace si no está), el DOI al
resolutor oficial y «RSME» al artículo en la web de la revista.

### Índice de secciones

La mayoría de las secciones se repiten número tras número, así que el archivo
puede recorrerse también por ellas. Los artículos se agrupan por su sección de
primer nivel —los «Acerca de la portada», que van sueltos en la raíz de cada
número, forman una sección aparte—, y se listan de la más nutrida a la menos:

```
Artículos (339 artículos, 1998-2026)
Noticias de la Sociedad (241 artículos, 2008-2026)
...
```

Al agrupar se igualan espacios y mayúsculas, para que una sección no se parta
en dos por un cambio de grafía.

La página de cada sección recorre sus artículos del número más reciente al más
antiguo, con un encabezado por número (enlazado a su página) y una barra para
saltar directamente a cualquiera de ellos. Las citas tienen la misma forma que
en las páginas de número.

### Índice de autores

Los autores se sacan del campo `autor` de cada artículo, que la revista escribe
seguido: se parte por las comas y por la conjunción (`y`, o `e` ante palabra
que empieza por i-), y se normaliza igual que las secciones. En las citas cada
nombre enlaza a su página.

El índice va por orden alfabético, con un encabezado por letra y una barra de
la A a la Z (las letras que nadie estrena salen apagadas). Cada autor se
resume como en las secciones, y su página lista sus artículos del más reciente
al más antiguo, agrupados por número (un `<h2>` que enlaza a su página, como en
las páginas de sección) y, dentro de cada número, por sección (un `<h3>` que
enlaza a la suya, como en las páginas de número).

Hay nombres que llevan dentro una coma o una conjunción y que la separación
partiría donde no debe: un apellido con `y` (José Echegaray y Eizaguirre), una
institución con `e` (Sociedad de Estadística e Investigación Operativa). Esos
se apartan enteros antes de cortar, según la tabla de la clave `excepciones`
de `config.json`:

```jsonc
"excepciones": [
  "Comisión de Educación, Cultura y Deporte del Senado",
  "José Echegaray y Eizaguirre",
  "Redacción de la sección de Problemas y Soluciones",
  "Sociedad de Estadística e Investigación Operativa"
]
```

La primera vez, `--web` anota ahí la tabla que trae el programa; a partir de
entonces manda la del fichero, que puede ampliarse o vaciarse a mano. Basta con
que el nombre aparezca dentro del campo `autor`, y da igual cómo se acentúen
las mayúsculas.

Aun así la separación no lo arregla todo: una coletilla (`Joan Cerdà, editor`)
sigue dando un autor de más.

#### Firmas de una misma persona

Casi nadie firma siempre igual, así que las firmas que son de la misma persona
se reúnen bajo una sola. Se dan por suyas cuando:

- sólo cambian las tildes, las mayúsculas o los guiones (*Andrei
  Martínez-Finkelshtein* y *Andrei Martínez Finkelshtein*);
- una deja apellidos por el camino (*Adolfo Quirós* de *Adolfo Quirós
  Gracián*);
- una lleva iniciales donde la otra lleva el nombre entero (*A.
  Moreno-González* de *Auxiliadora Moreno-González*, o *M.ª Victoria* de
  *María Victoria*);
- una se calla un segundo nombre que en la otra va abreviado (*Ágata Timón
  García-Longoria* de *Ágata A. Timón García-Longoria*). Sólo se admite que
  lo callado sea una inicial: si fuese un nombre entero se emparejarían
  apellidos, como *Manuel Domínguez* con *Manuel Perera Domínguez*.

Sólo abrevia la firma corta: si es la larga la que lleva la inicial no se
empareja nada, porque *Antonio Martínez* podría ser cualquier *Antonio M.* Y
cuando una firma corta encaja en dos largas que no se parecen entre sí, se
avisa por pantalla y se la deja aparte.

De todas las firmas de un autor se muestra la más completa, y su página las
enumera con las veces que aparece cada una:

```
Firmas: María Jesús Carro Rossell (4), María J. Carro (2), María J. Carro Rossell (1)
```

Lo que ninguna regla alcanza va en la clave `equivalencias` de
`config.json`, una lista con las firmas de cada persona:

```jsonc
"equivalencias": [
  ["Marc Felipe Alsina", "Marc Felipe i Alsina"],
  ["José Carrillo", "José Carrillo Yáñez"],
  ["José Almira", "José María Almira"],
  ["Marco Fontelos", "Marco Antonio Fontelos"]
]
```

Se anota y se retoca igual que la de excepciones, manda sobre lo que se
deduzca, y las firmas que no aparezcan en el archivo se ignoran. Sirve tanto
para reunir lo que las reglas no ven como para desempatar una firma corta que
encaja en dos personas distintas: *José Carrillo* podría ser *José Carrillo
Yáñez* o *José A. Carrillo*, y sin la tabla se quedaría aparte.

### Búsqueda

Todas las páginas llevan un buscador en la barra de navegación, que busca por
título y lleva a `buscar.html` con lo pedido en la dirección
(`buscar.html?q=gauss`). Los resultados salen del más reciente al más antiguo,
agrupados por número y por sección y formateados como en el resto del sitio.
Se buscan coincidencias sueltas, sin distinguir mayúsculas ni tildes: *«gauss»*
encuentra *«Gauss y la regla de signos de Descartes»*. Lo pedido se parte por
los espacios y cada trozo ha de aparecer en el título, en cualquier orden y sin
tener que estar entero: *«mat oli»* encuentra *«Olimpiada Matemática
Española»*.

En el índice de autores el buscador es el de autores, que busca por el nombre y
lleva a `buscar-autores.html`. Funciona igual —varios términos, sin distinguir
mayúsculas ni tildes— y los resultados salen por orden alfabético y agrupados
por letras, como el propio índice: *«gar lop»* encuentra a *Jesús García López
de Lacalle*, y *«canada»* a *A. Cañada*.

El sitio es estático, así que el trabajo lo hace el navegador con estos
ficheros de la raíz:

```
buscar.html                       <- la página de resultados, vacía
buscar-autores.html               <- la de los autores, también vacía
busqueda.js                       <- el índice: una entrada por artículo y autor
buscador.js                       <- las cien líneas que buscan y pintan
```

Las dos páginas de resultados son la misma salvo por un `data-busca` que dice
qué se busca en ella, y el guion, que es uno solo, lo lee para saber en qué
tabla mirar y cómo pintar lo hallado.

El índice va como guion y no como JSON porque el sitio también se abre con un
doble clic, y desde `file://` el navegador no deja leer un fichero suelto pero
sí cargar un guion. Con eso el sitio se basta a sí mismo: no necesita el
`sitemap.json` ni ningún servidor que sepa nada del archivo.

Cada artículo viaja en piezas —título, autores, páginas, DOI y enlaces— y es
`buscador.js` quien arma la cita, igual que la arma `gaceta.py` para las
páginas. Mandarla ya escrita costaba el doble: así el índice se queda en 535 KB
(334 KB con `--externa`), que el servidor manda comprimidos a 147 y 104 KB. Los
encabezados de número y de sección, que son ciento veintitrés y no dos mil, sí
viajan montados. Sólo lo carga `buscar.html`, y buscar lleva unas centésimas de
segundo.

### Modo oscuro

Arriba a la derecha, ancladas a la esquina y siempre a la vista, van dos
botones: una media luna que enciende el modo oscuro —y que entonces se vuelve
un sol para deshacerlo— y el logotipo de GitHub, que lleva al repositorio. Los
iconos son de [Octicons](https://primer.style/octicons/) (`moon-24`, `sun-24` y
`mark-github-24`, con licencia MIT), incrustados como SVG.

La paleta entera vive en un puñado de variables CSS al principio de
`estilo.css`, y el tema oscuro no hace más que redefinirlas:

```css
:root { --fondo: #fff; --tinta: #222; --enlace: #036; ... }
:root[data-tema="oscuro"] { --fondo: #14171a; --tinta: #d7dae0; ... }
```

Quién pone ese `data-tema` es `tema.js`, que va en la cabecera de todas las
páginas para que el color esté puesto antes de pintar nada y la página no
parpadee. A falta de elección previa hace caso al sistema
(`prefers-color-scheme`), y lo que se elija con el botón se recuerda en el
`localStorage` del navegador, que el sitio es estático y no tiene otro sitio
donde apuntarlo. Si el navegador no lo deja —en una ventana privada, por
ejemplo—, el botón sigue funcionando, sólo que sin memoria.

Los botones también los pone `tema.js`, en vez de venir en cada página: los
tres iconos ocupan más de dos kilobytes, y así viajan una sola vez y no mil
trescientas.

### Web para publicar

Con `--externa`, el sitio no enlaza ni un solo PDF del disco: el título de cada
artículo lleva a su `abrir.php` de la revista (y entonces sobra el remate
«RSME», que ya no añadiría nada), el número completo a su `abrirentero.php`, y
el «Acerca de la portada» a su PDF. Las imágenes de portada siguen siendo
locales, que son ligeras. Así puede publicarse el archivo sin repartir los PDF,
que además en parte están reservados a los socios.

`--publicar DIR` da un paso más: en vez de dejar el sitio dentro del archivo,
lo escribe entero en otra carpeta, copiando allí las portadas y nada más. Da
por supuesto `--externa`, así que en esa carpeta no hay ni un PDF que enseñar
por descuido: es el archivo listo para colgar, unos 7 MB. También deja un
`.nojekyll`, para que GitHub sirva los ficheros tal cual sin pasarlos por
Jekyll.

Al rehacer el sitio se retiran las páginas de `autores/` y de `secciones/`
que ya no correspondan a nadie, de modo que un cambio de nombre no deja
páginas sueltas. Sólo se borran ficheros `.html` de esas dos carpetas: lo
descargado no se toca.

## Publicar en GitHub Pages

El repositorio guarda dos cosas que no tienen nada que ver, así que van en dos
ramas: `master` lleva sólo el código (`gaceta.py`, este README y el
`.gitignore`), y `gh-pages` lleva sólo la web, sin historia común con la otra.
Cada rama vive en su propia carpeta, para no tener que cambiar de rama nunca:

```
programs/gaceta/       <- master: el código, el archivo descargado y el mapa
programs/gaceta-web/   <- gh-pages: sólo el sitio que se cuelga
```

### Cada vez que se quiera actualizar lo publicado

```
cd programs/gaceta
python gaceta.py --mapa                          # si hay número nuevo
python gaceta.py --descarga                      # si se quiere bajar
python gaceta.py --web --publicar ../gaceta-web  # rehace el sitio publicable

cd ../gaceta-web
git add -A
git commit -m "web al día"
git push
```

`git add -A` recoge lo nuevo y lo que haya dejado de existir. Si nada ha
cambiado, `git commit` avisa de que no hay nada que confirmar y no se crea un
commit vacío: rehacer el sitio dos veces seguidas da los mismos ficheros.

Conviene mirar el `git status` antes de confirmar: ahí no debe aparecer nunca
un `.pdf`, ni `sitemap.json`, ni `config.json`. Con `--publicar` no pueden
llegar, porque no se copian.

### Cómo se preparó todo esto (no hace falta repetirlo)

```
git worktree add --detach ../gaceta-web     # una carpeta más, del mismo repo
git -C ../gaceta-web checkout --orphan gh-pages   # rama sin historia común
git -C ../gaceta-web rm -rf .               # que empieza vacía
python gaceta.py --web --publicar ../gaceta-web
git -C ../gaceta-web add -A
git -C ../gaceta-web commit -m "web del archivo de La Gaceta"
```

La primera vez hay que subir la rama con `git push -u origin gh-pages`, y
luego, en GitHub, *Settings → Pages → Source: Deploy from a branch*, eligiendo
`gh-pages` y `/ (root)`. La web queda en
`https://edelkas.github.io/rsme/`.

Para deshacerlo todo: `git worktree remove ../gaceta-web` y
`git branch -D gh-pages`.

## Material reservado a los socios

Los números más recientes están reservados a los socios de la RSME. Su página
se consulta y se mapea con normalidad, pero el PDF redirige al formulario de
acceso; esas descargas se cuentan aparte como *reservadas* y no se guarda nada
en su lugar. Con `--formato=numero`, si el ejemplar completo está reservado
se recurre a los artículos sueltos, que a menudo sí están abiertos.

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

En cualquiera de los dos casos la cookie queda anotada en `config.json` y las
siguientes ejecuciones la reutilizan sin necesidad de repetir nada. Si la
revista deja de reconocerla, se avisa por pantalla, se borra de los ajustes y
la descarga continúa como visitante. Conviene recordar que esa cookie es una
sesión viva: no compartas el `config.json` con nadie.

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

## Los dos ficheros

Lo que se guarda va en dos sitios, según de quién sea:

| Fichero | Qué lleva |
| --- | --- |
| `sitemap.json` | El mapa del archivo: volúmenes, números, artículos y qué se ha descargado. Es de trabajo: la web no lo lee, porque el buscador lleva su propio índice |
| `config.json` | Lo personal: la cookie de sesión y las tablas de `excepciones` y `equivalencias`. **No lo compartas**: la cookie es una sesión de socio viva |

Las versiones anteriores lo guardaban todo junto en `sitemap.json`. Al leer un
mapa de aquéllos, el programa se lleva las tres claves personales a
`config.json` y lo dice por pantalla; no hay que hacer nada a mano.

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
- [x] Web local: portada con la tabla de volúmenes y números.
- [x] Web local: página de cada número, con sus secciones y artículos.
- [x] Web local: índice de secciones, con una página por sección.
- [x] Web local: índice de autores, con una página por autor.
- [x] Web local: versión con enlaces externos, para publicar sin los PDF.
- [x] Web local: búsqueda de artículos por título y de autores por nombre, en
      el navegador, con varios términos a la vez.
- [x] Publicación en GitHub Pages desde una rama aparte.
- [x] Web local: modo oscuro, con botón en la esquina y enlace al repositorio.
- [x] Miniaturas de las portadas para el índice, con Pillow.
