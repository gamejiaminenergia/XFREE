# Pantalla de decisión para congreso — la IA como protagonista

> **Estado (2026-10-11): superado por [`../DESIGN.md`](../DESIGN.md).**
> Este plan describe la iteración que introdujo el inspector con pestañas en una
> ventana única. El usuario descartó las pestañas ("quiero mostrar todo sin que
> me toque mover o seleccionar cosas") y la presentación adoptó la disciplina de
> un SCADA de transmisión. `panel.py` ya no tiene pestañas, ni scroll, ni
> `ScrollFrame`, ni `Card`/`Pill` con acento de color. Se conserva como registro
> de lo intentado; la guía viva es `DESIGN.md`.

Fecha: 2026-10-11 · Estado: **implementado como ventana única, verificado offline**
· Objetivo del usuario: mostrar **las decisiones de la IA** de la mejor manera
posible (mucho detalle, claro y bonito) en un **congreso internacional de IA**;
**mitad de la ventana para el juego, mitad para la decisión y el resto**.

## 0.05 Estado de implementación (ventana única)

Implementado y verificado **100 % offline (\$0)**. El usuario pidió **una sola
ventana** (dos interfaces confundían), así que la superficie de decisión y el
inspector se **fusionaron**:

| Pieza | Dónde | Qué hace |
|---|---|---|
| Ventana única (dos mitades) | `jev_duum/panel.py` (`Dashboard` + `HeroBar`) | **Mitad izquierda: el juego** — la vista viva del motor, los meters (vida/armadura/munición), el minimapa y el estado. **Mitad derecha: la decisión** — 3 ejes (`MOVIMIENTO`/`APUNTADO`/`ACCIÓN`) con la opción elegida en grande, barra apilada, confianza, intervención del guardia y timeline; debajo, las pestañas de auditoría (`DECISIÓN`/`RESPUESTA`/`PETICIÓN`/`MUNDO`/`HISTORIAL`). |
| Juego | `panel.py` | El canvas real del motor (`tkcv`) se rejilla en la mitad izquierda, así que conserva el zoom entero nítido y los 60 Hz (sin *picture-in-picture* intermedio). |
| Verificación | `tools/preview_panel.py` | Render offline de la ventana con cliente falso → `artifacts/ui-audit/01..08`. |

El loop sigue alimentando la UI con el mismo `decision` (no toca el loop, el
worker ni el contrato). El `HISTORIAL` y el timeline se llenan de un buffer en
memoria dentro de `Dashboard`.

Idioma: el **hero de la decisión quedó en inglés** (como eligió el usuario para
el congreso); las pestañas de auditoría siguen en español. Unificar todo a inglés
es un cambio mecánico pendiente y trivial.

**Decisión del usuario (2026-10-11):** se descartó la segunda ventana
(`stage.py`, flag `--stage`) por confusa; su contenido se fusionó aquí.

**Pendiente inmediato:** el **modo cine** (elegido por el usuario para el
directo) aún no está; hoy la ventana se alimenta de decisiones **en vivo**. El
modo cine reproducirá un historial grabado a ritmo fijo sin red — ver F4.9 y la
sección 7.

Esta iteración 3 reorienta el foco respecto del plan anterior
([`UI_IMPROVEMENT_PLAN.md`](UI_IMPROVEMENT_PLAN.md)): ya no se trata de un panel
para operar el piloto, sino de una **superficie de presentación** donde la
decisión del modelo es la protagonista y el juego es un *picture-in-picture*.

Igual que la iteración 2, **todo se audita y se prueba offline y a coste \$0**.

## 0. Cómo se diseñó (offline, sin jugar contra Jev)

Se añadió un mockup que renderiza la superficie de decisión con un **frame real
del motor** y una **respuesta falsa del modelo** (sin red):

```bash
cd jev-duum
python3 tools/decision_stage_mockup.py --allow-any-commit --out artifacts/ui-audit
# -> artifacts/ui-audit/10-decision-stage.png
```

El mockup (`10-decision-stage.png`) es la referencia visual de este plan: una
sola pantalla con la decisión en el centro, la percepción a la izquierda (con el
juego y el minimapa como secundarios) y el razonamiento/métricas/historial a la
derecha.

## 1. Principios de diseño para la audiencia

1. **La decisión es el héroe.** Las acciones elegidas (movimiento, apuntado,
   acción) en tipografía grande, legibles a distancia; la probabilidad completa
   visible como barra apilada.
2. **Una historia por decisión:** *qué percibe → qué considera → qué decide →
   (si el guardia corrige, por qué) → cuánto tarda y cuánto cuesta*.
3. **Transparencia = credibilidad.** Mostrar siempre la probabilidad completa y
   la distinción **propuesto vs aplicado**; cuando el guardia determinista
   interviene, decirlo en voz alta (es justamente lo que un público de IA quiere
   ver).
4. **Legibilidad de sala, no de escritorio:** escala tipográfica, alto contraste,
   frases cortas, nada de párrafos monoespaciados de 9 px.
5. **El juego, en segundo plano:** ventana PiP + minimapa esquemático, presentes
   para dar contexto, nunca compitiendo con la decisión.
6. **Se siente vivo:** contador de decisiones, timeline y coste acumulado que se
   mueven en tiempo real (animación sutil).

## 2. Qué cambia respecto de la UI actual

| Aspecto | Hoy (inspector) | Superficie de decisión |
|---|---|---|
| Protagonista | El juego (640×400) | La decisión (tipografía 30–40 px) |
| Decisiones | Pestaña lateral, barras de 9 px | Centro, barras apiladas grandes + conf |
| Juego | Centro | PiP pequeño etiquetado «vista del agente» |
| «Por qué» | Texto monoespaciado crudo | Frases cortas: misión, prioridad, plan, corrección |
| Historial | No existe | Timeline + historial reciente |
| Métricas | 4 tiles discretos | Franja visible: #decisión · ms · tokens · coste |
| Uso | Operador | Audiencia / proyector |

## 3. Hallazgos nuevos (enfoque congreso)

| # | Hallazgo | Por qué importa |
|---|---|---|
| N1 | No existe un **modo presentación**; todo está pensado para el operador. | En el escenario nadie va a leer una pestaña. |
| N2 | La decisión y sus probabilidades están **escondidas y en tamaño mínimo**. | Es exactamente lo que el público vino a ver. |
| N3 | No hay **«por qué» en lenguaje llano**; hay códigos (`hitscan-enemy/not-aligned`). | Un público de IA quiere el razonamiento, no el log. |
| N4 | No hay **historial ni timeline**; solo la última decisión. | Sin secuencia no se percibe «que está decidiendo». |
| N5 | No hay **ritmo/animación**; la pantalla puede parecer congelada. | En directo hay que *ver* que el sistema trabaja. |
| N6 | Etiquetas en **español**; congreso internacional. | Decidir ES / EN / bilingüe. |
| N7 | Coste/latencia/tokens no están **«en la pared»**. | Son el argumento de eficiencia del sistema. |
| N8 | F1/F2 de la iteración 2 (línea de modo cortada, observaciones ilegibles) siguen vigentes como bug/higiene. | Higiene mínima para una demo pública. |

## 4. Plan por fases

### F0 — Herramientas offline \$0 (ya entregado)

- `tools/preview_panel.py`: render del inspector real con cliente falso.
- `tools/decision_stage_mockup.py`: mockup de la superficie de decisión.
- Evidencia en `artifacts/ui-audit/` (git-ignored, regenerable).
- Riesgo nulo: no importan el loop, el worker ni el modelo; sin dependencias
  obligatorias nuevas.

### F1 — «Stage mode»: la decisión al centro (el grueso)

Productizar el mockup como un **modo** del panel, conmutables con la tecla `S`
(el inspector actual queda como vista de operador). Layout, de izquierda a
derecha:

- **Cabecera:** título, `decisión #N`, latencia, coste y tokens de un vistazo.
- **PERCEPCIÓN (izquierda):** vida/armadura/munición grandes; **juego en PiP**;
  **minimapa** pequeño; amenazas cercanas (rumbo/distancia/LOS); objetivo
  (misión, pickup, ruta, sala).
- **LA DECISIÓN (centro, héroe):** tres ejes (`MOVIMIENTO`, `APUNTADO`,
  `ACCIÓN`) con la opción elegida en grande, `conf` y **barra apilada** con la
  distribución completa; **banner de intervención del guardia** (propuesto →
  aplicado + motivo); **timeline** de las últimas N decisiones.
- **POR QUÉ + MÉTRICAS + HISTORIAL (derecha):** misión/prioridad/estado y pasos
  del plan; métricas (latencia/tokens/coste/acumulado/modelo/prompt); historial
  reciente navegable.

Se alimenta del `decision` que ya llega a `Dashboard.update` y del hook
`on_decision` que `run_jev_window` ya expone; **no toca el loop de 60 Hz, el
worker ni el contrato del snapshot**.

### F2 — Storytelling en vivo

1. **«Por qué» en lenguaje llano:** derivar 1–2 frases de `strategy`
   (misión/prioridad/plan) y de las correcciones del guardia; verbo y sujeto
   claros («El guardia corrigió el apuntado: *right → left*, la salida queda a
   la izquierda»).
2. **Traducir códigos** de interacción a lenguaje natural (p. ej.
   `enemy=hitscan-enemy/not-aligned/…` → «enemigo a la vista, fuera de apuntado,
   a distancia media»).
3. **Propuesto vs aplicado** siempre visible y coloreado cuando difieren.
4. **Animación sutil:** relleno animado de barras al cambiar de decisión, pulso
   de la opción elegida, contador y coste que suben; sin reescribir todo el
   frame (delta-update ya existente).

### F3 — Legibilidad de sala

5. **Escala tipográfica** configurable (`--ui-scale`) y **autofit** a la
   pantalla; probar a 1920×1080 (proyector típico) y 3840×2160.
6. **Alto contraste** y **paleta apta para daltonismo**; tamaños mínimos 14 px
   para datos, 28 px para la decisión.
7. **Sin cursor / kiosco:** ocultar el puntero y evitar interacción accidental.
8. Arreglar **N8** (línea de modo, observaciones) mientras se reutilicen.

### F4 — Extras de congreso (opcionales)

9. **Exportar cada decisión a PNG** (para slides y el paper) reutilizando el
   mockup.
10. **«Modo cine»:** si no hay demo en vivo, ciclar un historial grabado a ritmo
    fijo.
11. **i18n ES/EN** (o bilingüe) — ver decisión abierta N6.
12. **QR** al repositorio / paper en una esquina.

## 5. Módulos a crear / modificar

| Módulo | Operación | Riesgo |
|---|---|---|
| `jev-duum/jev_duum/panel.py` | **nuevo** `DecisionStage` (modo presentación) + tecla `S`; reutiliza `Card`/`Meter`/delta-update | bajo (presentación pura) |
| `jev-duum/jev_duum/overlays.py` | minimapa/HUD a tamaño de sala, inset del juego | bajo |
| `jev-duum/tools/preview_panel.py` | **nuevo (ya creado)** | nulo |
| `jev-duum/tools/decision_stage_mockup.py` | **nuevo (ya creado)** | nulo |
| `jev-duum/tests/test_jev_panel.py` | tests de helpers puros (formato «por qué», recorte de códigos, buffer de historial) | bajo |
| `docs/README.md` | añadir esta entrada | nulo |

## 6. Verificación (sin red, \$0)

1. `python3 tools/decision_stage_mockup.py` y `tools/preview_panel.py`: comparar
   los PNG antes/después de cada fase.
2. `uv run --no-sync ruff check jev_duum tests tools` limpio.
3. `uv run --no-sync python -m pytest -q` (suite actual + helpers nuevos).
4. **Ensayo de proyector:** revisar a distancia de 6–8 m en 1080p y 4K; el test
   real son los PNG a tamaño completo, no la vista del desarrollador.

No se ejecuta ninguna sesión `--pilot jev*`: el gasto de API de este trabajo es
**\$0**. Una corrida real solo haría falta para ensayar el directo, decisión del
usuario.

## 7. Decisiones abiertas (para el usuario)

- **Idioma:** ¿ES, EN o bilingüe para el congreso? (afecta a todas las etiquetas).
- **Presentación:** ¿demo **en vivo** contra la API, o **modo cine** con historial
  grabado (coste \$0 y sin riesgo de red en el escenario)?
- **Pantalla:** resolución/relación del proyector (define la escala y el autofit).
- **¿Se muestra el juego** o solo la percepción esquemática + decisión?

## 8. Fuera de alcance (explícito)

- No tocar `duum/`, el loop de 60 Hz, el worker de decisión ni el contrato del
  snapshot: sigue siendo presentación.
- No enviar píxeles al modelo.
- **Sin interfaces web** salvo que el usuario levante esa restricción (se
  mantiene Tk puro, sin dependencias obligatorias nuevas; Pillow es dev-only).
