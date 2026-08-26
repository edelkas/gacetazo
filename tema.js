/* Generado por gaceta.py; los cambios a mano se pierden al rehacer el sitio. */

var CLAVE_TEMA = "tema";
var REPOSITORIO = "https://github.com/edelkas/rsme";
var REVISTA = "https://gaceta.rsme.es/";

function raiz() {
    /* la raíz del sitio vista desde aquí, que lo dice el src de este guion */
    var guion = document.currentScript;
    var src = guion ? guion.getAttribute("src") : "";
    return src.slice(0, Math.max(0, src.length - "tema.js".length));
}

var RAIZ = raiz();
var ESTADISTICAS = RAIZ + "estadisticas.html";
var AVANZADA = RAIZ + "avanzada.html";
/* con file:// cada página tiene su propio almacén y no se enteran unas de
   otras, así que el tema tiene que viajar con los enlaces */
var SUELTAS = location.protocol === "file:";

/* Octicons (MIT): moon-24, sun-24, graph-24, search-24, home-24 y
   mark-github-24 */
var LUNA = '<svg class="luna" viewBox="0 0 24 24" aria-hidden="true"><path d="M14.768 3.96v.001l-.002-.005a9.08 9.08 0 0 0-.218-.779c-.13-.394.21-.8.602-.67.29.096.575.205.855.328l.01.005A10.002 10.002 0 0 1 12 22a10.002 10.002 0 0 1-9.162-5.985l-.004-.01a9.722 9.722 0 0 1-.329-.855c-.13-.392.277-.732.67-.602.257.084.517.157.78.218l.004.002A9 9 0 0 0 14.999 6a9.09 9.09 0 0 0-.231-2.04ZM16.5 6c0 5.799-4.701 10.5-10.5 10.5-.426 0-.847-.026-1.26-.075A8.5 8.5 0 1 0 16.425 4.74c.05.413.075.833.075 1.259Z"/></svg>';
var SOL = '<svg class="sol" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19a7 7 0 1 1 0-14 7 7 0 0 1 0 14Zm0-1.5a5.5 5.5 0 1 0 0-11 5.5 5.5 0 1 0 0 11Zm-5.657.157a.75.75 0 0 1 0 1.06l-1.768 1.768a.749.749 0 0 1-1.275-.326.749.749 0 0 1 .215-.734l1.767-1.768a.75.75 0 0 1 1.061 0ZM3.515 3.515a.75.75 0 0 1 1.06 0l1.768 1.768a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215L3.515 4.575a.75.75 0 0 1 0-1.06ZM12 0a.75.75 0 0 1 .75.75v2.5a.75.75 0 0 1-1.5 0V.75A.75.75 0 0 1 12 0ZM4 12a.75.75 0 0 1-.75.75H.75a.75.75 0 0 1 0-1.5h2.5A.75.75 0 0 1 4 12Zm8 8a.75.75 0 0 1 .75.75v2.5a.75.75 0 0 1-1.5 0v-2.5A.75.75 0 0 1 12 20Zm12-8a.75.75 0 0 1-.75.75h-2.5a.75.75 0 0 1 0-1.5h2.5A.75.75 0 0 1 24 12Zm-6.343 5.657a.75.75 0 0 1 1.06 0l1.768 1.768a.751.751 0 0 1-.018 1.042.751.751 0 0 1-1.042.018l-1.768-1.767a.75.75 0 0 1 0-1.061Zm2.828-14.142a.75.75 0 0 1 0 1.06l-1.768 1.768a.751.751 0 0 1-1.042-.018.751.751 0 0 1-.018-1.042l1.767-1.768a.75.75 0 0 1 1.061 0Z"/></svg>';
var GRAFICO = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2.5 2.75a.75.75 0 0 0-1.5 0v18.5c0 .414.336.75.75.75H20a.75.75 0 0 0 0-1.5H2.5V2.75Z"/><path d="M22.28 7.78a.75.75 0 0 0-1.06-1.06l-5.72 5.72-3.72-3.72a.75.75 0 0 0-1.06 0l-6 6a.75.75 0 1 0 1.06 1.06l5.47-5.47 3.72 3.72a.75.75 0 0 0 1.06 0l6.25-6.25Z"/></svg>';
var LUPA = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.25 2a8.25 8.25 0 0 1 6.34 13.53l5.69 5.69a.749.749 0 0 1-.326 1.275.749.749 0 0 1-.734-.215l-5.69-5.69A8.25 8.25 0 1 1 10.25 2ZM3.5 10.25a6.75 6.75 0 1 0 13.5 0 6.75 6.75 0 0 0-13.5 0Z"/></svg>';
var CASA = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11.03 2.59a1.501 1.501 0 0 1 1.94 0l7.5 6.363a1.5 1.5 0 0 1 .53 1.144V19.5a1.5 1.5 0 0 1-1.5 1.5h-5.75a.75.75 0 0 1-.75-.75V14h-2v6.25a.75.75 0 0 1-.75.75H4.5A1.5 1.5 0 0 1 3 19.5v-9.403c0-.44.194-.859.53-1.144ZM12 3.734l-7.5 6.363V19.5h5v-6.25a.75.75 0 0 1 .75-.75h3.5a.75.75 0 0 1 .75.75v6.25h5v-9.403Z"/></svg>';
var GITHUB = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M10.226 17.284c-2.965-.36-5.054-2.493-5.054-5.256 0-1.123.404-2.336 1.078-3.144-.292-.741-.247-2.314.09-2.965.898-.112 2.111.36 2.83 1.01.853-.269 1.752-.404 2.853-.404 1.1 0 1.999.135 2.807.382.696-.629 1.932-1.1 2.83-.988.315.606.36 2.179.067 2.942.72.854 1.101 2 1.101 3.167 0 2.763-2.089 4.852-5.098 5.234.763.494 1.28 1.572 1.28 2.807v2.336c0 .674.561 1.056 1.235.786 4.066-1.55 7.255-5.615 7.255-10.646C23.5 6.188 18.334 1 11.978 1 5.62 1 .5 6.188.5 12.545c0 4.986 3.167 9.12 7.435 10.669.606.225 1.19-.18 1.19-.786V20.63a2.9 2.9 0 0 1-1.078.224c-1.483 0-2.359-.808-2.987-2.313-.247-.607-.517-.966-1.034-1.033-.27-.023-.359-.135-.359-.27 0-.27.45-.471.898-.471.652 0 1.213.404 1.797 1.235.45.651.921.943 1.483.943.561 0 .92-.202 1.437-.719.382-.381.674-.718.944-.943"/></svg>';

function apuntado() {
    /* en modo privado algunos navegadores ni dejan mirar */
    try { return localStorage.getItem(CLAVE_TEMA); } catch (error) { return null; }
}

function apuntar(cual) {
    try { localStorage.setItem(CLAVE_TEMA, cual); } catch (error) { /* nada */ }
}

function deLaDireccion() {
    /* el tema que traiga el enlace por el que se ha llegado */
    var trae = new URLSearchParams(location.search).get(CLAVE_TEMA);
    return trae === "claro" || trae === "oscuro" ? trae : null;
}

function conTema(destino, cual) {
    /* la misma dirección, con el tema puesto (o cambiado, si ya lo llevaba) */
    var partes = destino.split("#");
    var trozos = partes[0].split("?");
    var consulta = (trozos[1] || "").split("&").filter(function (par) {
        return par && par.indexOf(CLAVE_TEMA + "=") !== 0;
    });
    consulta.push(CLAVE_TEMA + "=" + cual);
    var camino = trozos[0] + "?" + consulta.join("&");
    return partes.length > 1 ? camino + "#" + partes[1] : camino;
}

function interna(destino) {
    /* una página del sitio: ni un PDF, ni un ancla, ni la revista */
    return destino && /\.html($|[?#])/.test(destino) && !/^[a-z]+:/i.test(destino);
}

function propagar(cual) {
    /* el tema, a todos los enlaces y al buscador de esta página */
    if (!SUELTAS) { return; }
    var enlaces = document.getElementsByTagName("a");
    for (var i = 0; i < enlaces.length; i++) {
        var destino = enlaces[i].getAttribute("href");
        if (interna(destino)) {
            enlaces[i].setAttribute("href", conTema(destino, cual));
        }
    }
    /* los formularios rehacen la consulta al enviarse, y se llevarían por
       delante lo que hubiera en la dirección; el tema va en un campo
       escondido */
    var formularios = document.getElementsByTagName("form");
    for (var j = 0; j < formularios.length; j++) {
        var campo = formularios[j].querySelector("input[name=" + CLAVE_TEMA + "]");
        if (!campo) {
            campo = document.createElement("input");
            campo.type = "hidden";
            campo.name = CLAVE_TEMA;
            formularios[j].appendChild(campo);
        }
        campo.value = cual;
    }
}

function preferido() {
    /* a falta de elección, la del sistema */
    return window.matchMedia
        && window.matchMedia("(prefers-color-scheme: dark)").matches;
}

function esOscuro() {
    return document.documentElement.getAttribute("data-tema") === "oscuro";
}

function poner(cual) {
    document.documentElement.setAttribute("data-tema", cual);
    propagar(cual);
    var boton = document.querySelector(".esquina .tema");
    if (boton) {
        var rotulo = cual === "oscuro" ? "Volver al modo claro"
                                       : "Cambiar al modo oscuro";
        boton.setAttribute("aria-label", rotulo);
        boton.setAttribute("title", rotulo);
    }
}

/* manda lo que traiga el enlace, y de paso se apunta aquí */
var TRAIDO = deLaDireccion();
if (TRAIDO) { apuntar(TRAIDO); }
poner(TRAIDO || apuntado() || (preferido() ? "oscuro" : "claro"));

function atajo(destino, rotulo, icono, fuera) {
    /* un enlace de la esquina: sólo el icono, y el rótulo al posarse encima */
    return '<a href="' + destino + '" title="' + rotulo + '" aria-label="'
        + rotulo + '"' + (fuera ? ' target="_blank" rel="noopener"' : "")
        + ">" + icono + "</a>";
}

function esquina() {
    /* los botones los pone el guion y no cada página: son seis iconos que
       ocupan más que todo esto, y así no viajan mil veces */
    var caja = document.createElement("div");
    caja.className = "esquina";
    caja.innerHTML = atajo(ESTADISTICAS, "Las estadísticas", GRAFICO)
        + atajo(AVANZADA, "La búsqueda avanzada", LUPA)
        + atajo(REVISTA, "La Gaceta en la RSME", CASA, true)
        + '<button class="tema" type="button">' + LUNA + SOL + "</button>"
        + atajo(REPOSITORIO, "El repositorio en GitHub", GITHUB, true);
    document.body.insertBefore(caja, document.body.firstChild);
    caja.querySelector(".tema").addEventListener("click", function () {
        var cual = esOscuro() ? "claro" : "oscuro";
        poner(cual);
        apuntar(cual);
    });
    poner(esOscuro() ? "oscuro" : "claro");  /* para rotular el botón */
}

document.addEventListener("DOMContentLoaded", esquina);
