/* Generado por gaceta.py; los cambios a mano se pierden al rehacer el sitio. */

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

function casaAlguno(clave, buscados) {
    /* con que aparezca uno de ellos basta */
    for (var i = 0; i < buscados.length; i++) {
        if (clave.indexOf(buscados[i]) >= 0) { return true; }
    }
    return false;
}

function pruebaDe(pedido, variante) {
    /* La manera de casar que dicen los botones de la búsqueda avanzada:
       la unión, la intersección o la frase entera sin trocear. Sin nada
       pedido no hay prueba, y ese campo no filtra. */
    var limpio = normalizar(pedido);
    if (!limpio) { return null; }
    if (variante === "exacto") {
        return function (clave) { return clave.indexOf(limpio) >= 0; };
    }
    var buscados = terminos(limpio);
    if (variante === "algunos") {
        return function (clave) { return casaAlguno(clave, buscados); };
    }
    return function (clave) { return casan(clave, buscados); };
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

function enumerar(trozos, conjuncion) {
    /* como se enumera en castellano: 'a, b y c', o 'a, b o c' */
    if (trozos.length < 2) { return trozos.join(""); }
    return trozos.slice(0, -1).join(", ") + " " + (conjuncion || "y") + " "
        + trozos[trozos.length - 1];
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

/* Los nombres con que se firma cada artículo, normalizados a la primera. */
var FIRMAS = null;

function firmasDe(articulo) {
    /* una cadena cuando no se pudieron separar; si no, índices en la tabla */
    var quienes = articulo[3];
    if (!quienes) { return []; }
    if (typeof quienes === "string") { return [normalizar(quienes)]; }
    var nombres = [];
    for (var i = 0; i < quienes.length; i++) {
        nombres.push(normalizar(BUSQUEDA.firmas[quienes[i]][0]));
    }
    return nombres;
}

function firmas() {
    if (!FIRMAS) { FIRMAS = BUSQUEDA.articulos.map(firmasDe); }
    return FIRMAS;
}

function algunaFirma(nombres, prueba) {
    /* basta con que lo cumpla uno de los que firman */
    for (var i = 0; i < nombres.length; i++) {
        if (prueba(nombres[i])) { return true; }
    }
    return false;
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

function agrupar(pasa) {
    /* Los artículos vienen en el orden del archivo, así que se agrupan según
       van saliendo y al final se les da la vuelta a los números; dentro de
       cada uno se leen como en su página, del primero al último. */
    var bloques = [], bloque = null, total = 0;
    for (var i = 0; i < BUSQUEDA.articulos.length; i++) {
        if (!pasa(i)) { continue; }
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

function conFiltro(pasa) {
    var hallado = agrupar(pasa);
    return { total: hallado.total, html: montar(hallado.bloques) };
}

function hallarArticulos(buscados) {
    var titulos = claves("articulos");
    return conFiltro(function (i) { return casan(titulos[i], buscados); });
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

/* --- búsqueda avanzada ------------------------------------------- */

var VARIANTES = ["algunos", "todos", "exacto"];

function variante(pedida) {
    return VARIANTES.indexOf(pedida) >= 0 ? pedida : "todos";
}

function limiteAño(cual, atributo, respaldo) {
    /* el archivo entero, que es lo que el formulario trae puesto */
    var casilla = document.getElementById(cual);
    var limite = casilla ? Number(casilla.getAttribute(atributo)) : 0;
    return limite || respaldo;
}

function añoPedido(busca, cual, atributo, respaldo) {
    var pedido = parseInt(busca.get(cual), 10);
    return isNaN(pedido) ? limiteAño(cual, atributo, respaldo) : pedido;
}

function loPedido() {
    /* los cinco campos del formulario, tal como vengan en la dirección */
    var busca = new URLSearchParams(location.search);
    return {
        titulo: (busca.get("q") || "").trim(),
        variante: variante(busca.get("variante")),
        autor: (busca.get("autor") || "").trim(),
        varianteautor: variante(busca.get("varianteautor")),
        seccion: (busca.get("seccion") || "").trim(),
        desde: añoPedido(busca, "desde", "min", 0),
        hasta: añoPedido(busca, "hasta", "max", 9999),
        minimo: limiteAño("desde", "min", 0),
        maximo: limiteAño("hasta", "max", 9999)
    };
}

function rellenarCampo(cual, valor) {
    var campo = document.getElementById(cual);
    if (campo) { campo.value = valor; }
}

function marcarVariante(nombre, valor) {
    var botones = document.getElementsByName(nombre);
    for (var i = 0; i < botones.length; i++) {
        botones[i].checked = botones[i].value === valor;
    }
}

function rellenarFormulario(pedidos) {
    /* lo pedido vuelve al formulario, que el navegador no lo repone solo */
    rellenarCampo("titulo", pedidos.titulo);
    rellenarCampo("autor", pedidos.autor);
    rellenarCampo("seccion", pedidos.seccion);
    rellenarCampo("desde", pedidos.desde);
    rellenarCampo("hasta", pedidos.hasta);
    marcarVariante("variante", pedidos.variante);
    marcarVariante("varianteautor", pedidos.varianteautor);
}

function entrecomillar(trozos) {
    return trozos.map(function (trozo) { return "«" + trozo + "»"; });
}

function criterioTexto(pedido, cual, donde) {
    /* cómo se lee en voz alta lo que se ha pedido en un campo de texto */
    if (cual === "exacto") { return "«" + pedido + "» entero " + donde; }
    var trozos = entrecomillar(terminos(pedido));
    if (trozos.length < 2) { return trozos.join("") + " " + donde; }
    if (cual === "algunos") { return enumerar(trozos, "o") + " " + donde; }
    return enumerar(trozos) + " " + donde;
}

function criterioAños(pedidos) {
    /* nada que decir mientras no se acote el archivo */
    var abre = pedidos.desde > pedidos.minimo;
    var cierra = pedidos.hasta < pedidos.maximo;
    if (!abre && !cierra) { return ""; }
    if (pedidos.desde === pedidos.hasta) { return "de " + pedidos.desde; }
    if (!cierra) { return "de " + pedidos.desde + " en adelante"; }
    if (!abre) { return "hasta " + pedidos.hasta; }
    return "de " + pedidos.desde + " a " + pedidos.hasta;
}

function criteriosDe(pedidos) {
    /* lo que se ha pedido, en palabras; si no sale nada, es que no se pide */
    var criterios = [];
    if (pedidos.titulo) {
        criterios.push(criterioTexto(pedidos.titulo, pedidos.variante,
                                     "en el título"));
    }
    if (pedidos.autor) {
        criterios.push(criterioTexto(pedidos.autor, pedidos.varianteautor,
                                     "en la firma"));
    }
    if (pedidos.seccion) {
        criterios.push("de la sección «" + pedidos.seccion + "»");
    }
    var años = criterioAños(pedidos);
    if (años) { criterios.push(años); }
    return criterios;
}

function filtroAvanzado(pedidos) {
    /* una prueba por campo relleno, y el artículo ha de pasarlas todas */
    var pruebas = [];
    var porTitulo = pruebaDe(pedidos.titulo, pedidos.variante);
    if (porTitulo) {
        var titulos = claves("articulos");
        pruebas.push(function (i) { return porTitulo(titulos[i]); });
    }
    var porAutor = pruebaDe(pedidos.autor, pedidos.varianteautor);
    if (porAutor) {
        var quienes = firmas();
        pruebas.push(function (i) {
            return algunaFirma(quienes[i], porAutor);
        });
    }
    if (pedidos.seccion) {
        pruebas.push(function (i) {
            var tanda = BUSQUEDA.articulos[i][2];
            return tanda >= 0 && BUSQUEDA.rotulos[tanda] === pedidos.seccion;
        });
    }
    pruebas.push(function (i) {
        var año = BUSQUEDA.años[BUSQUEDA.articulos[i][1]];
        return año >= pedidos.desde && año <= pedidos.hasta;
    });
    return function (i) {
        for (var k = 0; k < pruebas.length; k++) {
            if (!pruebas[k](i)) { return false; }
        }
        return true;
    };
}

function contarAvanzada(total, criterios) {
    /* como en la búsqueda sencilla, pero enumerando todo lo pedido */
    var lista = enumerar(criterios);
    if (total === 0) { return "Ningún artículo cumple lo pedido: " + lista + "."; }
    if (total === 1) { return "Un artículo cumple lo pedido: " + lista + "."; }
    return total + " artículos cumplen lo pedido: " + lista + ".";
}

function buscarAvanzada() {
    var pedidos = loPedido();
    rellenarFormulario(pedidos);

    var cuenta = document.getElementById("cuenta");
    var resultados = document.getElementById("resultados");
    var criterios = criteriosDe(pedidos);
    if (!criterios.length) {
        cuenta.textContent = "Rellena algún campo y pulsa «Buscar».";
        resultados.innerHTML = "";
        return;
    }

    /* el título de la pestaña ya dice qué se busca aquí */
    var rotulo = pedidos.titulo || pedidos.autor || pedidos.seccion;
    if (rotulo) { document.title = rotulo + " - " + document.title; }
    var hallado = conFiltro(filtroAvanzado(pedidos));
    cuenta.textContent = contarAvanzada(hallado.total, criterios);
    resultados.innerHTML = hallado.html;
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
    /* la página de resultados dice de qué búsqueda es */
    var resultados = document.getElementById("resultados");
    if (resultados.getAttribute("data-busca") === "avanzada") {
        buscarAvanzada();
    } else {
        buscarSencilla();
    }
}

function buscarSencilla() {
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
