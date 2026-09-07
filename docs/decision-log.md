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
