---
target: el panel de decision (panel.py)
total_score: 20
max_score: 40
na_heuristics: 
p0_count: 0
p1_count: 4
target_identity: "file:/home/alde/Escritorio/XFREE/jev-duum/jev_duum/panel.py"
target_fingerprint: "sha256:dda1e4e0ed1ee47adee1554654928ac9a6091d6db8f6a905a61121fcc9de31e9"
target_path: /home/alde/Escritorio/XFREE/jev-duum/jev_duum/panel.py
timestamp: 2026-10-11T12-13-01Z
slug: jev-duum-jev-duum-panel-py
---
# Impeccable critique — `jev-duum/jev_duum/panel.py` (ventana de decisión, Tk)

Method: dual-agent (A: general subagent ses_ed523df1affe4THO4k508smFuX · B: general subagent ses_ed523df19ffeqHOXIU41W9hgQV)

Mode: **Operate** (dashboard/herramienta). Superficie nativa Tk, 1600×1000, sin web.

## Design Health Score

| # | Heuristic | Score | Key Issue |
|---|-----------|-------|-----------|
| 1 | Visibility of System Status | 3 | Tick, worker, latencias y banners existen, pero la columna de decisión no cambia de estado. |
| 2 | Match System / Real World | 2 | Cromo en español con verbos y unidades del motor en inglés (`LOS`, `px`, `hold_streak`); error crudo de red. |
| 3 | User Control and Freedom | 2 | Sin teclado para nada; `salir` es una etiqueta de 66×22 px solo-ratón; no hay pausa. |
| 4 | Consistency and Standards | 2 | El mismo dato vive en dos sitios; el ámbar significa cuatro cosas distintas. |
| 5 | Error Prevention | 2 | El guardia previene de verdad, pero una decisión obsoleta se presenta igual de confiada. |
| 6 | Recognition Rather Than Recall | 3 | Etiquetas y tarjetas cubren casi todo; la tira temporal no tiene título, eje ni leyenda. |
| 7 | Flexibility and Efficiency | 1 | Un solo camino rígido: pestañas y salida a ratón, cero atajos, cero pausa. |
| 8 | Aesthetic and Minimalist Design | 2 | Datos duplicados, volcados de ingeniería en la vitrina y relleno plano por todas partes. |
| 9 | Error Recovery | 2 | El fallo del modelo aparece dos veces, en inglés y sin decir qué pasa después. |
| 10 | Help and Documentation | 1 | La única frase que explica el experimento está en 8 pt y 3.09:1. |
| **Total** | | **20/40 (50 %)** | **Acceptable — fondo de la banda** |

## Design Specificity Verdict

**LLM assessment (A).** El contenido está autorado, la composición no. Los tres ejes tipados, el par propuesto→aplicado con su razón (`el modelo dijo «fire» → aplicado «neither»`) y el abanico polar de riesgo por sector son irrepetibles de otro producto. El armazón — cabecera fija + 4 tiles KPI + tarjeta hero + 5 pestañas — es la anatomía por defecto de cualquier pantalla de monitorización desde 2012. Poniendo otra fuente de datos detrás, se envía sin cambios como dashboard de Kafka. Y hay una regresión concreta: la dirección descartada (`10-decision-stage.png`) se titulaba `JEV · cómo decide la IA` y tenía una columna permanente `POR QUÉ · RAZONAMIENTO`; la actual tiene por identidad `DUUM · E1M1` / `INSPECTOR JEV` y enterró el porqué en una pestaña, en inglés y a 8 pt.

**Deterministic scan (B).** El detector se ejecutó dos veces (archivo y directorio): `[]` con salida 0 en ambas. **Escaneo determinista no aplicable a esta superficie**: el modo no-HTML del detector es un pase de regex sobre CSS/JSX/TSX y un `.py` con `tkinter.Label(font=(..., 7))` no tiene ningún token que las reglas lean. Control independiente que prueba que el binario funciona: sobre un HTML de prueba con contraste 2.5:1 y texto de 9 px disparó 2 hallazgos (`low-contrast`, `undersized-ui-text`) con salida 2. Es un falso negativo material: 40 de 48 referencias de tipografía en `panel.py` están por debajo de 11 pt y la regla existiría si el detector pudiera leerlas.

**Visual overlays.** No aplicable: no hay URL. `tools/preview_panel.py` crea un `Toplevel` real de Tk y captura píxeles de pantalla con `PIL.ImageGrab`; los overlays son `canvas.create_rectangle` de Python (`overlays.py:296-330`), sin DOM, sin CSS y sin superficie de inyección. La evidencia visual del proyecto son los 8 PNG de `artifacts/ui-audit/`, generados offline. No hay overlay de usuario disponible; señal de fallback, no error.

## Overall Impression

La pantalla es un buen instrumento y una mala vitrina. El dato está casi todo, pero repartido en un espacio que no coincide con lo que importa: la mitad derecha dedica **482 px de sus 1000 (48 %)** a la tarjeta de decisión — tres palabras grandes y tres barras — y esconde el resto tras una barra de 5 pestañas, mientras **solo el 1.46 % de los píxeles de esa mitad son tinta de texto** y el 63 % es relleno plano. La mitad izquierda, en cambio, deja **289 px de margen horizontal** junto al canvas de juego y bandas de 60 px vacías. El mayor desperdicio no es lo que sobra: es lo que está en otra pestaña.

## What's Working

1. **El delta propuesto/aplicado** (`panel.py:1204-1216`). Cambiado en ámbar, igual en el fondo: la tesis del producto comprimida en cinco palabras, legible en una sola mirada.
2. **El hero de tres ejes y su color** (`panel.py:234-302`, 28 pt, 9.91:1). `MOVIMIENTO`/`APUNTADO`/`ACCIÓN` mapean honestamente las tres preguntas tipadas, y es lo único dimensionado para la sala.
3. **El abanico de riesgo por sector del minimapa** (`overlays.py:174-199`). Un histograma polar de 24 sectores alrededor del agente; ninguna plantilla genérica lo habría producido.
4. *Mención:* `DeltaCache` (`panel.py:95-112`) — refresco que no toca lo que no cambió. Por eso los 8 PNG son nítidos y no desgarrados.

## Priority Issues

### [P1] Todo lo que merece verse está detrás de una barra de 5 pestañas
**What:** `DECISIÓN · RESPUESTA · PETICIÓN · MUNDO · HISTORIAL` (`panel.py:787-793`) es una elección permanente de 5 vías que solo deja ver un quinto de la pantalla. Medido: las tarjetas de la pestaña DECISIÓN ocupan 686-769, 778-853, 862-973 y la cuarta arranca en 982 y **queda cortada al borde** con la barra de desplazamiento activa. Tres de las cinco pestañas son callejones sin salida para un espectador: HISTORIAL termina en y=745 y deja **254 px de negro**; PETICIÓN son **11.793 bytes de JSON crudo**; MUNDO son rumbos en grados y distancias en píxeles.
**Why it matters:** en un congreso el operador tiene que navegar mientras habla, y elegir pestaña es un acto visible que roba la frase. Es exactamente la fricción que el usuario ha señalado: mostrar todo sin tocar nada.
**Fix:** eliminar la barra de pestañas y el desplazamiento. Rejilla fija donde cada dato tiene un sitio permanente, dimensionado por importancia; el JSON de la petición y la lectura del mundo pasan a versiones compactas siempre visibles (claves + valores clave), y lo crudo se va a un volcado a fichero, no a la vitrina.
**Suggested command:** `distill`

### [P1] La decisión se lleva la mitad del observatorio y dice menos que el juego
**What:** el hero ocupa y=163-645: **482 px = 48 % de la columna derecha** para 3 palabras, 3 barras y 3 pills. La mitad derecha completa es **92.6 % relleno plano** (63.3 % `CARD` + 19.5 % `PANEL2` + 6.25 % caja del guardia) y **1.46 % tinta de texto**; 594 de 1000 filas tienen menos del 1 % de tinta. Además el reparto real no es el que dice el código: el comentario "Two equal halves" (`panel.py:516-518`) no se cumple — medido **929 px / 671 px (58/42)**.
**Why it matters:** el espacio que se come la decisión es el que le falta a la conciencia situacional (amenazas, ruta, riesgo, salud cruzada con peligro). Un espectador no necesita ver `STRAFE LEFT` durante 8 segundos; necesita saber dónde está el agente, qué lo amenaza y qué acaba de pasar.
**Fix:** comprimir la decisión a una franja compacta de alto fijo (una línea por eje: etiqueta + elección + distribución + confianza), y devolver el alto restante a bloques de situación. Reparto deliberado: 50/50 real o 55/45, pero decidido, no accidental.
**Suggested command:** `layout`

### [P1] La ventana no reacciona a los estados que existe para explicar
**What:** la diferencia entre `01-decision.png` (sano) y `06-critical` / `07-stale` / `08-error` en la columna derecha es de **6.000 de 671.000 píxeles = 0.9 %**, y toda esa diferencia son tres bandas de 92×20 junto a las barras del hero más un glifo. Con 22 de vida, con la decisión 17 ticks obsoleta y con el modelo en timeout, la sala sigue viendo `STRAFE LEFT · conf 0.60` impecable y un guardia intacto. Y cuando la salud es crítica, el relleno del medidor parpadea a **`#7a2020`, 1.37:1 contra su propia pista**.
**Why it matters:** es la única cosa que separa esta pantalla de ser creíble. Un demo que dice "mire cómo decide la IA en vivo" no puede presentar una decisión caducada como viva, y menos delante de quien va a preguntar por eso.
**Fix:** estados degradados de primera clase en la columna de decisión: con `error` o `stale > 3`, atenuar la elección, poner `conf n/a` y sellar la cabecera con `DECISIÓN OBSOLETA · hace N ticks` / `SIN MODELO`. Con salud crítica, acento rojo fijo en la tarjeta (sin parpadeo). Sin límite de frecuencia ni parpadeo de color en el número.
**Suggested command:** `harden`

### [P1] La distribución de probabilidad es invisible a dos metros
**What:** los segmentos perdedores se pintan `TRACK #232c3d` sobre `CARD #1a2030` = **1.16:1** (medido: solo `x=1052-1384` en cyan; el resto es indistinguible del fondo). Los separadores son `CARD` sobre `TRACK` = 1.27:1. Y cada eje se escala sobre 0..1 con el resto dejado como fondo desnudo, así que `conf 0.60` llena 54 % del carril y `conf 0.80` llena 72 %: la misma confianza se ve distinta por fila.
**Why it matters:** "probabilidades" está en el subtítulo de la propia tarjeta. Hoy la sala ve un bloque de color y debe creerse al ganador. La distribución **es** el producto.
**Fix:** masa perdedora visible (relleno distinto o borde de 1 px por segmento), valor impreso dentro del segmento cuando quepa (≥40 px) para no depender de la línea `alternativas:`, y normalización por eje con la cola vacía marcada.
**Suggested command:** `bolder`

### [P2] Nada en pantalla dice qué es esto, y cada dato tiene dos casas
**What:** la identidad es `DUUM · E1M1` (izq.) e `INSPECTOR JEV` (der.); la única frase explicativa — `estado semántico, sin píxeles · prompt v3w` (`panel.py:728-736`, 8 pt `#5b6376` sobre `#10131b`) mide **3.09:1** y falla AA; el subtítulo del hero (`panel.py:756-759`) mide **2.70:1**. Y se duplica: distribuciones en el hero *y* en RESPUESTA; intervenciones en la caja del guardia *y* en DECISIÓN; el error del modelo en el canvas *y* en el banner inferior; el coste en el tile, en RESPUESTA y en el JSON.
**Why it matters:** el congreso llega con cero contexto y lee desde diez metros. Y duplicar infla la complejidad aparente de un producto cuya tesis son tres preguntas.
**Fix:** un titular en lenguaje llano a 16-18 pt y ≥4.5:1; `mode`/`status` al rincón del operador; una casa por dato.
**Suggested command:** `clarify`

## Persona Red Flags

Selección por tabla (dashboard/data-heavy): **Alex** y **Sam**, más **Jordan** porque el público del congreso es primerizo por definición. Juzgado sobre la implementación Tk real, no sobre supuestos web.

**Alex (usuario experto — el investigador en el escenario).** Acción primaria: correr el demo, saltar a un dato a mitad de frase, sostener una decisión en pantalla, salir limpio.
- Las pestañas son `tkinter.Label` con solo `<Button-1>` (`panel.py:794-799`): Tab nunca las alcanza, no hay Ctrl+1..5 ni flechas.
- La única tecla de todo el fichero es `<F11>` (`panel.py:534`). Salir es una etiqueta de 66×22 px (medido x=1516-1582, fila y=22) sin Esc.
- No hay pausa: la decisión se refresca en `tick % 4` (`panel.py:1525`) y el bucle corre libre (`panel.py:1426`). No puede congelar una decisión para narrarla — que es justo por lo que existe `artifacts/ui-audit/`.
- La rueda está capturada con `bind_all` (`panel.py:399-401`) y con el puntero sobre el canvas de juego no desplaza el inspector.

**Sam (dependiente de accesibilidad — teclado y baja visión).** Acción primaria: leer decisión, distribución y override sin ratón.
- Cero controles enfocables: todo interactivo es `Label` sin `takefocus`. Sin árbol de accesibilidad para las distribuciones (son `create_rectangle`), el timeline ni el minimapa (leyenda a 7 pt).
- Fallos de contraste: `#5b6376` a **3.09:1** en PANEL2 y **2.70:1** en CARD, sobre precisamente las tres cadenas que explican el producto.
- Estado solo por color: la pestaña activa se distingue a **1.14:1** de superficie y por tono de texto a 9 pt; la confianza es relleno verde/ámbar/rojo sin palabra ni icono, y un deuteránope no distingue el ámbar de `MOVIMIENTO 0.60` del verde de `ACCIÓN 0.80`, que son los dos extremos del relato del producto.
- El parpadeo se dispara por tick (`phase = (tick // 4) % 2`, `panel.py:986`, repintado en `tick % 4`) sin límite de frecuencia ni opción de movimiento reducido, y aplica al número que la sala lee.

**Jordan (primerizo confundido — un asistente al congreso).** Acción primaria: entender qué acaba de hacer la IA y por qué.
- Primeros cinco segundos: `DUUM · E1M1` y `INSPECTOR JEV`. Ni el producto ni su tesis. La frase explicativa, 8 pt a 3.09:1.
- La palabra más grande es un verbo de juego que no conoce (`STRAFE LEFT`) y `conf 0.60` no tiene leyenda.
- La distribución es una barra oscura, así que las alternativas solo existen en una línea de 9 pt con cuatro verbos ingleses dentro de cromo español.
- El bloque más llamativo le enseña la lección equivocada: `el modelo dijo «fire» → aplicado «neither»` le hace concluir que la IA falla; nada dice que el guardia es el diseño deliberado del experimento (esa frase está a 8 pt en una pestaña que no tiene motivo para abrir).
- Y lo último que ve probablemente sea una pantalla vacía: HISTORIAL con una fila sobre 254 px de negro.

## Minor Observations

- El timeline se dibuja 6 px fuera de su propio canvas: `height=30` (`panel.py:778`) pero los rectángulos terminan en `y=36` (`panel.py:1170`). De ahí que parezca una fila de marcas y no un gráfico de ritmo, y que no tenga título ni eje.
- Las barras del hero están escaladas al ancho obsoleto del canvas en las cinco capturas estáticas (cola desnuda de 65 px); se corrige en ~67 ms en vivo, pero está en toda la evidencia.
- La barra de munición está clavada en 100 (`panel.py:997-1000`): 50 proyectiles y 200 balas dibujan la misma barra.
- `_percentile` no interpola (`panel.py:78-82`): con una sola decisión —el estado de todas las capturas— p50 y p95 leen ambos `2`.
- Armadura a 0 con `#232c3d` es indistinguible de una barra funcionando; solo salud tiene rampa aviso/crítico.
- Tres ventanas distintas sobre el mismo historial: `deque(maxlen=64)`, timeline `[:24]`, pestaña `[:12]`.
- Mutación sin registro: `interaction == "use"` se reescribe a `"neither"` en silencio (`panel.py:1497-1498`), así que DECISIÓN muestra `use` propuesto y `neither` aplicado sin `AssistanceEvent` que lo explique.
- El banner vacío pinta un rectángulo de **901×22 px** sin texto (`panel.py:709-713`).
- Existen estados hover (`panel.py:588-589`) donde nadie pasa el ratón: una proyección.
- El idioma deriva dentro de una tarjeta: título `ESTRATEGIA` con `advance · advance must_move=true hold=0/5` y bullets en inglés.

## Questions to Consider

- Si el guardia determinista es la tesis de la investigación, ¿por qué es lo tercero de la derecha y no el titular? ¿Cómo se ve esta pantalla con el override como protagonista y la respuesta del modelo como su evidencia?
- La sala lee unas tres cadenas desde diez metros. Hoy son `DUUM · E1M1`, `STRAFE LEFT` e `INTERVENCIÓN DEL GUARDIA DETERMINISTA`. ¿Cuáles quieres que sean, y estás dispuesto a borrar todo lo que compita con ellas?
- El juego es el 16 % de la ventana y el 100 % del movimiento: se lleva el ojo sin llevar la explicación. ¿Hace falta en vivo, o serviría una repetición de 3 s de la última decisión que el ponente pueda narrar?
- ¿Y si la confianza fuera una frase (`muy seguro` / `podría cambiar` / `no sabe`) y el número quedara para el operador? Nadie dice "conf cero punto seis cero" a una sala.
- ¿Cuál es el estado de reposo diseñado? 42.4 % de la columna izquierda y 254 px de HISTORIAL están en fondo plano. Ante un público, vacío no es neutro: lee como roto.
