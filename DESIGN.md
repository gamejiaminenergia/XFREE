# DESIGN.md — guía de estilo de la HMI (jev-duum)

Esta es la **guía de estilo** de la ventana de decisión: la fuente de verdad de
la presentación. ISA-101 exige escribirla *antes* de dibujar, y su ausencia es
la razón por la que la interfaz se rehizo cinco veces. **Se cambia aquí primero
y después en el código**, nunca al revés.

Implementación: `jev-duum/jev_duum/panel.py` (paleta y widgets) y
`jev-duum/jev_duum/overlays.py` (unifilar y banda de estado del canvas).
Verificación visual offline, sin gastar API: `jev-duum/tools/preview_panel.py`.

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
5. Contraste mínimo verificado sobre negro: texto estático 9.7:1, `OFF` 5.3:1,
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
┌─ BANNER ─ JEV·DUUM · mapa · tick y tiempo · EN LÍNEA · ALARMA n · F11 CERRAR ─┐
├──────────────────┬───────────────────────┬───────────────────────────────────┤
│ MEDIDAS          │ DECISIÓN DE LA IA     │ ENLACE · PETICIÓN │ ENLACE·RESPUESTA│
│  barras + tabla  │  una fila por pregunta│  TAG/valor + índice │ TAG/valor +   │
│ DIAGRAMA         │  propuesto vs aplicado│  + preguntas tipadas│ JSON crudo    │
│  unifilar + tags │  guardia · por qué    │                                     │
│  + amenazas      │  estrategia           │                                     │
├──────────────────┴───────────────────────┴───────────────────────────────────┤
│ EVENTOS · # · TICK · MOV · APU · ACC · OBJ · CONF · ESTADO                    │
└───────────────────────────────────────────────────────────────────────────────┘
```

- La columna del juego se dimensiona **al canvas del motor** (zoom entero
  máximo), nunca al revés: un carril más ancho sólo compra fondo.
- Sólo la fila del **diagrama** absorbe el alto sobrante. Dar peso a un panel
  fijo es cómo su cuerpo quedó sin mapear cuando el contenido natural no cabía.
- El unifilar va **a la izquierda de sus tags**, no encima: un mapa
  letterboxed vale menos que uno cuadrado.

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
- un color fuera de la tabla de §3, o un color de dato usado como cromo.

## 7. Cómo se cambia

1. Se cambia esta guía (qué se quiere decir y por qué).
2. Se cambia `panel.py` / `overlays.py` para que la cumpla.
3. Se renderiza con `tools/preview_panel.py` (offline, 0 $) y se miran las
   capturas de `artifacts/ui-audit/`: cinco estados, `01-en-vivo` a
   `05-sin-modelo`.
4. `ruff check` y `pytest`.

Si un cambio no se puede expresar con esta guía, el cambio es la guía.
