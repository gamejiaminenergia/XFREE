# DESIGN.md — guía de estilo de la HMI (jev-duum)

Esta es la **guía de estilo** de la ventana de decisión: la fuente de verdad de
la presentación. ISA-101 exige escribirla *antes* de dibujar, y su ausencia es
la razón por la que la interfaz se rehizo cinco veces. **Se cambia aquí primero
y después en el código**, nunca al revés.

Implementación: `jev-duum/jev_duum/panel/` (paleta, widgets, zonas y compositor)
y `jev-duum/jev_duum/overlays/` (unifilar y banda de estado del canvas).
Ambos toman sus colores de `jev-duum/jev_duum/theme.py`, la única casa de la
paleta (la de la pantalla y la del unifilar).
Verificación visual offline, sin gastar API: `jev-duum/tools/preview_panel.py`;
equivalencia determinista: `jev-duum/tools/dump_panel_tree.py`.

## 1. Qué es esta pantalla

Un **sinóptico de operación** (display de nivel 2, ISA-101 §4): el estado de un
proceso —un agente jugando DOOM asistido por un modelo remoto— y la decisión
que lo gobierna, para ser leído de un vistazo desde una sala de congreso.

No es una página web, ni una landing, ni un dashboard de producto. No se
navega: **no hay pestañas, no hay scroll, no hay nada que seleccionar**. Todo
está siempre en pantalla. El objetivo del operador/espectador es **conciencia
situacional**, no interacción.

## 2. Convención adoptada

La referencia es la de un **SCADA de transmisión eléctrica** (centro de
despacho), no la de un HMI de proceso:

| Fuente | Qué se toma |
|---|---|
| **IS 18058:2023** (pantallas SCADA de transmisión) | Fondo negro por defecto, datos estáticos en blanco, **un color reservado por clase de dato dinámico**, tablas `TAG valor unidad`, lista de eventos con hora |
| **ISA-101 / High Performance HMI** | **El color se reserva para lo anormal**; el énfasis se hace con **grosor de línea, no con color**; el color **nunca** es el único indicador; sin animación |
| **ISA-18.2** | Resumen de alarmas **siempre visible**; los colores de alarma no se usan para nada más |
| Diagrama unifilar | Símbolos 2-D, sin 3-D ni sombras, leyenda con el símbolo real |

Desviación consciente de ISA-101: su fondo recomendado es gris claro, mientras
que la convención de transmisión es **fondo negro con valores coloreados**. Se
sigue la de transmisión porque es la que pidió el brief y la que corresponde al
dominio.

## 3. Paleta (nueve valores, y ninguno de adorno)

```python
BG    = "#000000"   # fondo de pantalla
PANEL = "#0d0d0d"   # fondo de panel (cromo, nunca un color de dato)
RULE  = "#333333"   # separadores de 1 px
STATIC= "#b0b0b0"   # texto estático: etiquetas, tags, cabeceras
TITLE = "#ffffff"   # encabezados
VALUE = "#ffffff"   # valores medidos, cuando todo está normal
OK    = "#00ff00"   # en servicio / aplicado tal cual se propuso
WARN  = "#ffa500"   # supera un límite, dato obsoleto, intervención del guardia
ALARM = "#ff0000"   # alarma: sin comunicación, salud crítica, confianza baja
OFF   = "#808080"   # fuera de servicio / sin dato
TRACK = "#3c3c3c"   # fondo de barra (cromo)
```

El código de la paleta vive en `jev_duum/theme.py`: una sola fuente que
importan `panel/`, `telemetry/` y `overlays/`. `DESIGN.md` sigue siendo la
fuente de verdad en prosa; `theme.py` es su casa en código.

#### Paleta del unifilar

El diagrama de la izquierda es un sinóptico, no un mapa de color: usa los
mismos criterios (cromo plano, color reservado para lo anormal) pero con su
propio juego de tonos apagados, porque sobre `BG` negro un unifilar necesita
jerarquía de grises para que el agente y las amenazas lean por encima de la
geometría. Vive también en `theme.py`, con prefijo `MAP_`:

```python
MAP_BACKDROP        = "#0a0c11"   # fondo del canvas del unifilar
MAP_ROOM_FILL       = "#111620"   # relleno de sala
MAP_ROOM_LINE       = "#232d3d"   # contorno de sala / hairline del canvas
MAP_WALL            = "#556077"   # segmentos de pared
MAP_DOOR            = "#c9a227"   # puertas
MAP_EXIT            = "#ef5350"   # salida
MAP_NUKAGE          = "#2f6b3a"   # charca de nukage
MAP_WATER           = "#1f4f6b"   # charca de agua
MAP_PLAYER          = "#65d8ff"   # el agente
MAP_TARGET          = "#8ee8a8"   # objetivo alineado
MAP_TARGET_TURN     = "#ffb74d"   # objetivo al que hay que girar
MAP_TARGET_ASSISTED = "#ff7043"   # objetivo con fuego asistido
MAP_ENEMY           = "#ef5350"   # enemigo despierto
MAP_PROJECTILE      = "#ff8a80"   # proyectil entrante
MAP_GUIDE           = "#b388ff"   # rumbo recomendado
MAP_MUTED           = "#8b93a7"   # entidad dormida, leyenda, rótulos
MAP_STALE_ERROR_BG  = "#6f1a1a"   # banda de estado: sin modelo
MAP_STALE_WARN_BG   = "#6b3f00"   # banda de estado: decisiones obsoletas
MAP_STALE_TEXT      = "#ffe7c2"   # texto de la banda de estado
```

Reglas de uso:

1. **El cromo no usa nunca un color de dato**, y un color de dato **nunca
   decora**: sólo aparece cuando algo se sale de lo normal.
2. **Normal = sin color.** Una pantalla sana es casi monocroma. Si todo está
   pintado, nada destaca.
3. **El color nunca va solo**: cada valor coloreado lleva la palabra que lo
   dice (`EN LÍNEA`, `DATOS OBSOLETOS`, `SIN COMUNICACIÓN`, `INTERVINO ×2`,
   `MEDIA 0.60`, `SALUD CRÍTICA`).
4. `INFO` (amarillo) queda para **referencias** (límites y unidades), no para
   texto corriente. Hoy sólo lo usa la marca de límite de las barras.
5. **Ninguna caja cambia de tamaño con el dato.** Ni panel, ni sección, ni
   celda, ni bloque de estado: **ancho y alto invariantes**. Una caja que crece
   desplaza a sus vecinas y obliga al operador a rebuscar la información. Lo que
   no cabe en la celda **se recorta** (el valor, nunca la caja) y el texto se
   escribe con formato de ancho fijo. Sólo dos anchos son flexibles, y por
   diseño: el **unifilar** (se queda con lo que sobra) y la columna **MOTIVO**
   de la lista de eventos.
   El invariante está codificado en `jev-duum/tests/test_jev_hmi.py`: recorre
   estados hostiles (valores larguísimos, listas vacías, sin modelo, obsoleto) y
   compara la geometría de todas las cajas. **Si ese test falla, la interfaz
   está rota**, aunque se vea bien.
6. Contraste mínimo verificado sobre negro: texto estático 9.7:1, `OFF` 5.3:1,
   rojo 5.3:1, ámbar 10.6:1, verde 15.3:1. El relleno de una barra es blanco
   (21:1); el carril no lleva información.

### Estados y su nivel

Un único mecanismo, `Flag.LEVELS`, decide el aspecto de todo estado:

| Nivel | Uso | Aspecto |
|---|---|---|
| `ok` | en servicio, normal, aplicado | texto gris, **sin fondo** |
| `off` | fuera de servicio, sin dato, no modelado | texto gris oscuro, sin fondo |
| `warn` | por encima de un límite, obsoleto, guardia intervino | **bloque ámbar**, texto negro |
| `alarm` | sin comunicación, crítico, confianza baja | **bloque rojo**, texto negro |

## 4. Tipografía

- Una sola familia: `DejaVu Sans Mono` (valores, tags, tablas) y
  `DejaVu Sans` sólo para la respuesta elegida.
- **Mínimo 9 pt.** Todo lo que explica el producto estaba antes en 7-8 pt con
  2.7:1 de contraste; no vuelve.
- Escala: 20 pt la respuesta elegida; 11-12 pt encabezados y valores
  principales; 10 pt etiquetas; 9 pt tablas y texto secundario.
- Los números se alinean por columnas (`TAG` a la izquierda, valor a la
  derecha). Nada de frases con separadores de adorno.

## 5. Zonas de la pantalla

```
┌─ BANNER ─ SCADA+IA+JEV+DOOM · mapa · tick y tiempo · EN LÍNEA · ALARMA n · F11 CERRAR ─┐
├──────────────────┬───────────────────────┬───────────────────────────────────┤
│ MEDIDAS          │ DECISIÓN DE LA IA     │ ENLACE · PETICIÓN │ ENLACE·RESPUESTA│
│  barras + tabla  │  una fila por pregunta│  TAG/valor + índice │ TAG/valor +   │
│ DIAGRAMA         │  + TELEMETRÍA         │  + consumo          │ confianza +   │
│  unifilar + tags │  guardia · por qué    │                     │ JSON crudo +  │
│  + vida/munición │  estrategia           │                     │ estabilidad   │
├──────────────────┴───────────────────────┴───────────────────────────────────┤
│ EVENTOS · # · TICK · MOV · APU · ACC · OBJ · CONF · ESTADO   │ BALANCE ·     │
│                                                              │ guardia ·acciones│
└───────────────────────────────────────────────────────────────────────────────┘
```

El título de producto —`SCADA+IA+JEV+DOOM`, con el `+` en acento y debajo
`Supervisión en tiempo real · jev-1.13.0`— es la única pieza dimensionada para
leerse desde diez metros. Se compone de glifos sueltos porque Tk no tiene
*tracking*; su ancho es fijo, así que nunca empuja al mapa, al reloj ni al
bloque de enlace.

- La columna del juego se dimensiona **al canvas del motor** (zoom entero
  máximo), nunca al revés: un carril más ancho sólo compra fondo.
- Sólo la fila del **diagrama** absorbe el alto sobrante. Dar peso a un panel
  fijo es cómo su cuerpo quedó sin mapear cuando el contenido natural no cabía.
- El unifilar va **a la izquierda de sus tags**, no encima: un mapa
  letterboxed vale menos que uno cuadrado.

### Telemetría de sesión

`jev_duum/telemetry/` añade siete instrumentos que usan **sólo datos ya
existentes** (latencia, `confidence` por cabeza, `assistance_events`, controles
aplicados, salud/munición, tokens y coste) y llenan el espacio que antes quedaba
en negro:

| Instrumento | Dónde | Dato |
|---|---|---|
| Sparkline de latencia, líneas p50/p95 y puntos ámbar por encima de p95 | bajo las barras de decisión | `decision_ms` |
| Historial de confianza MOV/APU/ACC | panel de respuesta | `confidence` |
| Tasa de intervención y reglas más frecuentes | franja inferior, derecha | `assistance_events` |
| Distribución de movimientos y de acción | franja inferior, derecha | `applied_controls` |
| Vida y munición, con una marca por intervención | junto al diagrama | `player.health/ammo` |
| Tokens in/out por decisión, coste acumulado y medio | panel de petición | `input_tokens`, `usage`, `cost_usd` |
| Decisión anterior vs actual | panel de respuesta | `applied_controls` |

Reglas que no se negocian: cada instrumento es un `Canvas` de alto fijo (y ancho
de petición modesto, para no ensanchar su columna) o una etiqueta de ancho fijo
con el valor recortado, así que **la invariante de §3.5 sigue valiendo**; los
buffers son `deque` acotados que vive el `Dashboard`, no el widget; y el redibujo
va **throttled** (~3 Hz), sin tocar el bucle de 60 Hz ni al worker. Nada aquí usa
un color nuevo: el ámbar solo marca lo anómalo (por encima de p95, el guardia
actuando) y siempre lleva su palabra en el subtítulo.

**Reacomodo.** Si el ancho baja de 1600 px, la franja inferior pasa de
`EVENTOS │ BALANCE` a `EVENTOS` encima de `BALANCE`, en vez de desbordarse; el
resto de la rejilla conserva sus celdas.

## 6. Prohibiciones

No entra en esta pantalla, y no hace falta justificarlo cada vez:

- animación, transiciones, parpadeo y temporizadores de refresco visibles
  (el parpadeo crítico se eliminó: bajaba el número a 1.37:1 justo cuando
  había que leerlo);
- degradados, sombras, esquinas redondeadas, cristal, 3-D;
- barras de acento de color en las tarjetas, píldoras decorativas, emojis o
  glifos Unicode haciendo de icono (los botones dicen `F11` y `CERRAR`);
- duplicar un dato en dos sitios: cada dato tiene **una** casa;
- texto por debajo de 9 pt, o cualquier texto con menos de 4.5:1;
- un color fuera de la tabla de §3, o un color de dato usado como cromo;
- **un panel, sección, celda o bloque de estado cuyo ancho o alto dependa del
  dato**: eso incluye una etiqueta sin `width` que crezca con su texto, un
  valor sin recortar, una línea extra que empuje lo de abajo, o un texto que se
  envuelva en un número variable de líneas.

## 7. Cómo se cambia

1. Se cambia esta guía (qué se quiere decir y por qué).
2. Se cambia `panel/` / `overlays/` para que la cumpla.
3. Se renderiza con `tools/preview_panel.py` (offline, 0 $) y se miran las
   capturas de `artifacts/ui-audit/`: cinco estados, `01-en-vivo` a
   `05-sin-modelo`.
4. `ruff check` y `pytest`.

Si un cambio no se puede expresar con esta guía, el cambio es la guía.
