# Bitácora de decisiones arquitectónicas (ADR)

Cada entrada registra el contexto, la decisión, las alternativas descartadas
y sus consecuencias. Se escribe en el momento de decidir, no después.

---

## ADR-001 — `uv` como gestor de entorno y dependencias

**Fecha:** 2026-09-06 · **Estado:** aceptada

**Contexto.** El proyecto se despliega en dos entornos distintos (AWS ECS
Fargate y un homelab) desde una máquina de desarrollo macOS/arm64. Una
divergencia de versiones entre los tres es un fallo silencioso garantizado.

**Decisión.** `uv` con `uv.lock` commiteado y la versión del intérprete
fijada en `.python-version`.

**Alternativas descartadas.**
- `pip` + `requirements.txt`: no fija dependencias transitivas de forma
  reproducible.
- `poetry`: buen lockfile, pero resolución lenta y no gestiona el intérprete.
- `conda`: pensado para binarios científicos; pesado dentro de Docker.

**Consecuencias.** El Dockerfile de Fase 4 instalará desde `uv.lock`,
garantizando paridad bit a bit con el entorno local.

---

## ADR-002 — Python 3.12 en vez del 3.14 disponible

**Fecha:** 2026-09-06 · **Estado:** aceptada

**Contexto.** El sistema tiene Python 3.14. El proyecto depende en Fase 3 de
`faster-whisper` (sobre `ctranslate2`) y del stack ROCm de PyTorch.

**Decisión.** Fijar 3.12.

**Alternativas descartadas.**
- 3.14: el ecosistema de ML publica wheels precompilados con retraso; el
  riesgo es acabar compilando extensiones C++ dentro del contenedor.
- 3.11: más conservador aún, pero se pierde mejoras de tipado sin ganar nada.

**Consecuencias.** Si en Fase 3 alguna dependencia solo tiene wheels 3.12,
se estrechará `requires-python` a `>=3.12,<3.13` para que el fallo aparezca
al resolver dependencias y no en runtime.

---

## ADR-003 — LangGraph como orquestador del agente

**Fecha:** 2026-09-06 · **Estado:** aceptada

**Contexto.** El agente necesita memoria conversacional por llamada, un nodo
de clarificación determinista para casos ambiguos, y tracing por componente
(STT/LLM/TTS) en Fase 5.

**Decisión.** LangGraph con estado explícito (`TypedDict` + reducers).

**Alternativas descartadas.**
- Loop ReAct manual (`while` + function calling): habría que implementar
  checkpointing y trazabilidad por paso a mano.
- CrewAI / AutoGen: diseñados para múltiples agentes colaborando; añaden
  abstracciones de "roles" y "tasks" innecesarias para un agente con 3 tools.
- Function calling nativo del proveedor: ata al proveedor e impide insertar
  un nodo de clarificación determinista.

**Consecuencias.** El checkpointing de Fase 2 y los spans por nodo de Fase 5
salen del framework. El diagrama de arquitectura se autogenera con
`draw_mermaid()` y por tanto no se desincroniza del código.

---

## ADR-004 — Estructura de repo por frontera arquitectónica

**Fecha:** 2026-09-06 · **Estado:** aceptada

**Contexto.** El proyecto tiene piezas con ciclos de vida y despliegues
potencialmente distintos.

**Decisión.** Carpetas de primer nivel `mcp_server/`, `agent/`, `voice/`,
`deploy/`, `observability/` — cada una una frontera, no una conveniencia.

**Alternativas descartadas.**
- `src/` monolítico con subcarpetas por tipo de archivo: oculta qué piezas
  son independientes.

**Consecuencias.** `agent/` no importa nada de `mcp_server/`: se comunican
solo por protocolo MCP. Esto permite mover el servidor MCP a otro proceso o
máquina sin tocar el agente.

---

## ADR-005 — MCP SDK 2.x (`MCPServer`), sin fijar a `mcp<2`

**Fecha:** 2026-09-06 · **Estado:** aceptada

**Contexto.** El SDK oficial de Python resolvió a 2.1.1. En la serie 2.x
`FastMCP` fue renombrado a `MCPServer` y el API cambió. La mayoría de
tutoriales públicos siguen mostrando el API de la serie 1.x.

**Decisión.** Usar 2.x y programar contra el SDK instalado, leyendo su
código fuente en lugar de tutoriales.

**Alternativas descartadas.**
- Fijar `mcp<2`: permitiría copiar tutoriales, a costa de construir el
  portafolio sobre un API ya obsoleto.

**Consecuencias.** Menos material de referencia disponible; a cambio, el
repo demuestra la versión vigente del protocolo.

---

## ADR-006 — Clasificación de intención por reglas en Fase 0, LLM en Fase 2

**Fecha:** 2026-09-06 · **Estado:** aceptada

**Contexto.** El "hello world" del grafo necesitaba clasificar intención.

**Decisión.** Diccionario de palabras clave, sin LLM.

**Alternativas descartadas.**
- LLM desde Fase 0: introduce latencia, costo y una API key antes de tener
  nada funcionando, y hace imposible distinguir un fallo del grafo de un
  fallo del modelo.

**Consecuencias.** El límite es medible y reproducible: la frase
"¿Cuánto cuesta agendar el sábado?" se clasifica como `consultar_precio`
porque "cuesta" aparece antes en el diccionario. Ese caso queda como
línea base para comparar contra el clasificador LLM de Fase 2.

---

## ADR-007 — SQLite como almacén del mock de negocio

**Fecha:** 2026-09-06 · **Estado:** aceptada

**Contexto.** El agente necesita consultar precios, disponibilidad y crear
citas. La plataforma real del negocio existe, pero integrarse con ella no
es el objetivo de este proyecto ni se usarán datos reales de clientes.

**Decisión.** SQLite embebido, con toda la BD detrás de `db/conexion.py` y
`tools.py`.

**Alternativas descartadas.**
- PostgreSQL: requiere servicio, credenciales y un contenedor extra antes de
  poder probar una tool. El volumen (7 servicios, ~125 franjas) no lo
  justifica.
- Datos en memoria / diccionarios Python: no permitiría demostrar
  transacciones ni el control de concurrencia de `registrar_servicio`.

**Consecuencias.**
- Costo de las rarezas de SQLite: sin tipo fecha (ISO 8601 en TEXT), sin
  booleano (INTEGER + CHECK), claves foráneas desactivadas por defecto.
- **Persistencia asimétrica en el despliegue dual (Fase 4):** el sistema de
  archivos de ECS Fargate es efímero, así que las citas creadas en AWS se
  pierden al reiniciar la tarea; en el homelab persisten vía volumen Docker.
  Se decidirá en Fase 4 entre documentarlo como demo sin estado, montar EFS,
  o migrar solo AWS a Postgres.

---

## ADR-008 — Sin base de datos vectorial

**Fecha:** 2026-09-06 · **Estado:** aceptada

**Contexto.** El plan mencionaba Qdrant Cloud como posible vector store.

**Decisión.** No incorporar búsqueda vectorial en el alcance actual.

**Alternativas descartadas.**
- Qdrant / pgvector para emparejar el nombre de servicio dicho por el cliente
  contra el catálogo: sobredimensionado para 7 elementos, y sustituye una
  búsqueda exacta por una aproximada en datos (precios, cupos) donde la
  exactitud es un requisito.

**Consecuencias.** El emparejamiento difuso de nombres de servicio queda a
cargo del LLM de Fase 2, que recibe el catálogo completo en el prompt.
Se reconsideraría solo si el negocio aportara un corpus no estructurado
(garantías, manuales, FAQ) sobre el que responder preguntas abiertas.

---

## ADR-009 — WSL2 sobre Windows para el homelab (en vez de dual boot)

**Fecha:** 2026-09-06 · **Estado:** propuesta (se confirma en Fase 4)

**Contexto.** El nodo del homelab es una PC con 7900XTX que sigue en uso
como máquina de gaming. ROCm requiere Linux. El nodo debe servir tráfico
público de forma continua vía Cloudflare Tunnel.

**Decisión.** Ubuntu 24.04 LTS sobre WSL2, conservando Windows como sistema
principal.

**Alternativas descartadas.**
- Dual boot: solo un sistema arranca a la vez, así que el servidor estaría
  caído durante cada sesión de gaming. Descalifica la opción por sí solo.
- Ubuntu Server nativo dedicado: mejor soporte de ROCm, pero implica perder
  la máquina como PC de gaming.

**Consecuencias.**
- El túnel no se ve afectado por el NAT de WSL2: `cloudflared` establece una
  conexión SALIENTE, así que no hay port forwarding que atravesar.
- Riesgos a vigilar: WSL2 se detiene al suspender Windows (ajustar energía y
  autoarranque), y ROCm sobre WSL2 soporta un subconjunto de features.
- Plan B si ROCm sobre WSL2 no rinde en Fase 3: mantener LocalVoiceProvider
  sobre CPU y documentar la medición, en vez de reinstalar el sistema.

---

## ADR-010 — LLM tras endpoint compatible con OpenAI; modelo elegido por admisión

**Fecha:** 2026-09-12 · **Estado:** aceptada

**Contexto.** El plan nombraba Groq, pero el acceso a su consola falló. Groq,
OpenRouter, Mistral, Moonshot, DeepSeek y un vLLM autoalojado exponen la misma
API compatible con OpenAI. La tarea del agente es clasificar intención y elegir
entre tres herramientas: clasificación con vocabulario cerrado, donde la
latencia pesa más que la capacidad de razonamiento.

**Decisión.**
- `langchain-openai` apuntando a `LLM_BASE_URL`; proveedor y modelo son
  configuración, no código. Proveedor actual: OpenRouter (tier gratuito).
- Modelo: `liquid/lfm-2.5-2.6b:free`, elegido con una prueba de admisión sobre
  las 3 tools reales (`sandbox/11_admision_real.py`).

**Resultados de la admisión** (4 casos: precio, fecha en lenguaje natural,
saludo sin tool, negarse a agendar con datos incompletos):

| Modelo | Aciertos | Latencia media |
|---|---|---|
| liquid/lfm-2.5-2.6b:free | 4/4 | 1.20 s |
| dots-studio/dots-3-note-preview:free | 4/4 | 2.42 s |
| nvidia/nemotron-3.5-lightning:free | apto en prueba simple | 5.4 s, descartado por latencia |
| google/gemma-4-26b/31b:free | — | 429, pool compartido saturado |
| minimax/minimax-m2.7:free | — | 404, sin endpoint bajo la política de datos |

**Alternativas descartadas.**
- `langchain-groq` o SDKs por proveedor: una dependencia y un cambio de código
  por cada proveedor.
- Modelos grandes de razonamiento: peor tiempo hasta el primer token, crítico
  en una llamada telefónica, sin mejora medible en la selección de 3 tools.

**Consecuencias y riesgos.**
- Cuatro casos no garantizan la calidad: la validación real son los 5
  escenarios de conversación de Fase 2. Respaldo si falla:
  `dots-studio/dots-3-note-preview:free`.
- Los pools gratuitos devuelven 429 sin aviso. El nodo de manejo de error de
  Fase 2 debe incluir modelo de respaldo.
- Los modelos gratuitos pueden entrenar con los prompts. Aceptable con datos
  sintéticos; **inaceptable** con conversaciones reales de clientes, lo que
  exigiría un modelo de pago con política de no retención.
- Habilita servir el LLM desde la 7900XTX en el futuro sin rediseño, y comparar
  modelos en Fase 5 cambiando solo variables de entorno.

---

## ADR-011 — Grafo del agente: puente MCP propio, clarificación determinista y taxonomía de fallos

**Fecha:** 2026-09-12 · **Estado:** aceptada

**Contexto.** El agente debe descubrir las tools del servidor MCP, decidir
cuándo usarlas, no cotizar el servicio equivocado ante ambigüedad y no dejar
al cliente en silencio si algo falla. El adaptador oficial
`langchain-mcp-adapters` exige `mcp<2`, incompatible con el ADR-005.

**Decisión.**
- Puente propio (`agent/mcp_puente.py`): `tools/list` a formato OpenAI, y
  `tools/call` que nunca lanza excepción y devuelve todo fallo como dato.
- Una conexión MCP por llamada: medido en 11-14 ms frente a ~1200 ms del LLM.
- Grafo de 4 nodos: `agente`, `herramientas`, `clarificar`, `manejar_error`.
  La respuesta final la redacta el segundo paso por `agente`; un nodo
  `responder` separado duplicaría la misma llamada al LLM.
- **La clarificación es una ruta determinista**: si `consultar_precio`
  devuelve sugerencias, el grafo pregunta sin consultar al LLM.
- Taxonomía de fallos: error de la tool → vuelve al LLM para autocorregirse
  (máximo 2); fallo de transporte o LLM caído → `manejar_error`.
- Modelo de respaldo con `with_fallbacks` y memoria por llamada con
  checkpointer (`thread_id`); los campos de un solo turno se reinician en cada
  entrada porque el checkpointer persiste todo el estado.

**Alternativas descartadas.**
- Bajar a MCP 1.x para usar el adaptador: construir sobre un API obsoleto.
- Dejar la ambigüedad al criterio del LLM: ante dos candidatos, un modelo
  tiende a elegir el más probable en vez de preguntar.
- Sesión MCP persistente: más compleja y sin ganancia medible; la conexión
  por llamada además se recupera sola cuando el servidor vuelve.

**Consecuencias medidas.**
- Clarificar es más seguro y además más barato: se salta la segunda llamada
  al LLM (0.83 s frente a 2.55 s en la misma corrida).
- Caída del servidor a mitad de llamada: ruta a `manejar_error` sin traceback,
  y recuperación sin reiniciar el agente.
- `evals/fase2_escenarios.py`: 5/5 escenarios (2 ambiguos), 7/7
  verificaciones objetivas contra la base, sin cita duplicada ante un "sí"
  repetido. Latencia media 3.05 s por turno, máxima 7.41 s sin explicación
  posible sin tracing.
- Limitación: una corrida sobre un modelo no determinista; Fase 5 debe repetir
  cada escenario y reportar tasas.

---

## ADR-012 — Voz local primero: faster-whisper + Piper detrás de VoiceProvider

**Fecha:** 2026-09-12 · **Estado:** aceptada

**Contexto.** El plan de Fase 3 empezaba por el proveedor de voz en la nube.
El acceso a Groq falló (ADR-010) y Azure exige registrar una tarjeta para crear
el directorio de una cuenta personal. El proveedor local no necesita cuentas.

**Decisión.**
- Invertir el orden: `LocalVoiceProvider` primero, en CPU de la Mac. El Switch B
  no depende del orden; `CloudVoiceProvider` se añade después sin tocar el agente.
- STT: faster-whisper `small` con `int8`, `language="es"`, `beam_size=1` y
  `vad_filter=True`. TTS: Piper con la voz `es_MX-claude-high`.
- Interfaz `VoiceProvider` como ABC con métodos async; el trabajo pesado va en
  `asyncio.to_thread`. Contrato `Audio` con la frecuencia de muestreo explícita.
- La única decisión local/nube vive en `voice/fabrica.py`.
- Dependencias en el grupo `voz-local`, predeterminado en desarrollo y excluido
  en la imagen de AWS con `uv sync --no-group voz-local`.
- Modelos descargados explícitamente a `models/` (ignorada por git), nunca de
  forma implícita la primera vez que se usa el agente.

**Mediciones (Mac, CPU).**

| Medición | Resultado |
|---|---|
| Whisper `base` | 0.60 s, pero transcribió "le gustarí la agenda" |
| Whisper `small` | 0.86-1.17 s, transcripción correcta |
| Piper, caliente | 0.06-0.08 s para ~4 s de audio |
| Whisper directo en el event loop | 0 de 19 latidos: loop congelado |
| Whisper con `to_thread` | 18 de 18 latidos |
| 2 transcripciones en paralelo | 1.88 s, igual que en serie |
| 3 s de silencio con VAD | cadena vacía en 0.01 s |

**Alternativas descartadas.**
- Azure Speech: requiere tarjeta para crear el directorio de una cuenta personal.
- `edge-tts`: usa un endpoint no oficial del navegador Edge, frágil y en zona gris
  de términos de servicio.
- Whisper `base`: más rápido, pero confunde el verbo de la intención principal.
- Kokoro: mejor calidad potencial, pero arrastra PyTorch (varios GB); se
  reevaluará en el homelab.
- Extras opcionales de `uv`: un `uv sync` a secas los desinstala sin avisar.

**Consecuencias y riesgos.**
- En la Mac, `ctranslate2` corre solo en CPU (no usa la GPU de Apple).
- Capacidad actual: una transcripción a la vez; las concurrentes esperan.
- Riesgo abierto para Fase 4: la aceleración GPU de `ctranslate2` es para CUDA; en
  la 7900XTX puede requerir un build para ROCm o Whisper vía PyTorch con ROCm.
- La puntuación de Whisper no es fiable; el agente no debe depender de ella.
- `CloudVoiceProvider` sigue pendiente, y con él la prueba del switch en ambos modos.
