/* Generado por gaceta.py; los cambios a mano se pierden al rehacer el sitio. */

var URL_ARTICULO = "https://gaceta.rsme.es/abrir.php?id=";
var URL_DOI = "https://www.doi.org/";

/* Las claves por las que se busca: los títulos, normalizados una sola vez. */
var CLAVES = null;

function normalizar(texto) {
    /* sin tildes y en minúsculas, como se normaliza también al generar */
    return texto.normalize("NFD").replace(/[\u0300-\u036f]/g, "")
                .toLowerCase().replace(/\s+/g, " ").trim();
}

function claves() {
    if (CLAVES === null) {
        CLAVES = BUSQUEDA.articulos.map(function (articulo) {
            return normalizar(articulo[0]);
        });
    }
    return CLAVES;
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

function agrupar(consulta) {
    /* Los artículos vienen en el orden del archivo, así que se agrupan según
       van saliendo y al final se les da la vuelta a los números; dentro de
       cada uno se leen como en su página, del primero al último. */
    var bloques = [], bloque = null, total = 0, todas = claves();
    for (var i = 0; i < BUSQUEDA.articulos.length; i++) {
        if (todas[i].indexOf(consulta) < 0) { continue; }
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

function contar(total, pedido) {
    if (total === 0) {
        return "Ningún artículo lleva «" + pedido + "» en el título.";
    }
    if (total === 1) {
        return "Un artículo lleva «" + pedido + "» en el título.";
    }
    return total + " artículos llevan «" + pedido + "» en el título.";
}

function buscar() {
    var pedido = loQuePiden().trim();
    var casilla = document.querySelector(".buscar input");
    if (casilla) { casilla.value = pedido; }

    var cuenta = document.getElementById("cuenta");
    var resultados = document.getElementById("resultados");
    if (!pedido) {
        cuenta.textContent = "Escribe un título, o parte de él, en el buscador.";
        resultados.innerHTML = "";
        return;
    }

    document.title = pedido + " - Búsqueda - La Gaceta de la RSME";
    var hallado = agrupar(normalizar(pedido));
    cuenta.textContent = contar(hallado.total, pedido);
    resultados.innerHTML = montar(hallado.bloques);
}

function loQuePiden() {
    return new URLSearchParams(location.search).get("q") || "";
}

document.addEventListener("DOMContentLoaded", buscar);
