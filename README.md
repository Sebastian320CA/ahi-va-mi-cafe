# Ahí va mi café

MVP de trazabilidad logística, documental y ambiental para la cadena del café colombiano. Hackathon Microsoft LEAD Aspire Colombia 2026, caso Asoexport.

Caficultores, centros de acopio, trilladoras y puertos reportan por un único número de WhatsApp (texto, notas de voz, fotos de recibos y planillas, ubicaciones). El exportador consulta en un panel web de dónde viene su café, dónde está según el último evento confirmado, en qué tramo hay discrepancias y qué evidencias ambientales respaldan su origen. El caficultor participa gratis y recibe el recorrido de su café por WhatsApp.

Todos los datos de la demostración son sintéticos.

## Inicio rápido

```bash
cp .env.example .env        # opcional: sin .env todo corre en modo simulado
docker compose up --build
```

- Panel: http://localhost:3000 (usuario `exportador@demo.cafe`, contraseña `Cafe2026!`)
- API y Swagger: http://localhost:8000/docs
- Salud: http://localhost:8000/health

El servicio `migrate` aplica las migraciones, carga los datos sintéticos si la base está vacía y genera los recibos y planillas de prueba con la fecha del día. Para reiniciar la demostración desde cero: `docker compose run --rm migrate python -m app.cli seed`.

Usuarios del panel: `exportador@demo.cafe`, `cumplimiento@demo.cafe`, `admin@demo.cafe` (misma contraseña). Los operadores y caficultores interactúan por WhatsApp o por el Simulador del panel (solo en desarrollo).

## Ejecución sin Docker

Requisitos: Python 3.12+, Node 22, PostgreSQL 16 con PostGIS 3, Redis 7.

```bash
# Backend
cd backend
pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://cafe:cafe@localhost:5432/cafe
alembic upgrade head
python -m app.cli seed                 # datos sintéticos y documentos de prueba
uvicorn app.main:app --port 8000       # API
python -m app.workers.main             # worker RQ (otra terminal)

# Frontend
cd frontend
npm install
npm run build && npm start             # o npm run dev
```

Con `QUEUE_MODE=sync` el procesamiento ocurre dentro de la solicitud y no se necesita el worker (útil para depurar).

Guion automático de la demostración contra una API en ejecución: `python scripts/demo_scenario.py`.

## Despliegue (Vercel + Render)

El panel (Next.js) va en Vercel y el backend (FastAPI + PostGIS + Redis) en Render, porque Vercel no ejecuta procesos persistentes.

1. En Render: New > Blueprint > este repositorio. Usa `render.yaml`, crea la API, Postgres y Redis, migra y carga los datos demo.
2. Copia la URL pública de la API (por ejemplo `https://ahi-va-mi-cafe-api.onrender.com`). Si cambia, actualiza `FRONTEND_URL` y `API_BASE_URL` en Render.
3. En Vercel > Settings > Environment Variables: `BACKEND_INTERNAL_URL=<URL de la API>` (sin `/` final) y haz Redeploy. Sin esta variable el build falla a propósito, porque el login respondería "Error 404".

## Pruebas y calidad

```bash
cd backend
createdb cafe_test                     # base de pruebas con PostGIS disponible
pytest -q                              # 43 pruebas, sin credenciales comerciales
ruff check app tests && mypy app
cd ../frontend && npm run typecheck && npm run build
```

Las pruebas usan PostgreSQL real con PostGIS (no una base en memoria), Redis en la base 15 y adaptadores controlados para Meta y Azure. GitHub Actions ejecuta lo mismo en `.github/workflows/ci.yml`.

## Qué incluye

- Registro de caficultores por WhatsApp con consentimiento (Ley 1581) previo a guardar datos, finca y ubicación pendiente de verificación. Teléfonos familiares compartidos.
- Notas de voz (Azure AI Speech) y fotos de recibos y planillas (Azure AI Document Intelligence) con confirmación y corrección conversacional; los campos ilegibles se piden de forma puntual.
- Flujo Interpretación, Validación, Resumen, Confirmación, Ejecución con operaciones pendientes ligadas a un mensaje; confirmaciones tardías no se aplican.
- Compras, consolidación en lotes con genealogía inmutable, despachos y recepciones independientes, conciliación con `Decimal`, alertas, justificación por WhatsApp y resolución humana en el panel.
- Trilla de pergamino seco a café verde sin contabilizarla como pérdida, traslado a puerto con los mismos servicios.
- Evaluación ambiental preliminar con operaciones PostGIS reales sobre capas preparadas (sintéticas en la demo) con tres resultados, y expediente de diligencia debida con reglas versionadas, faltantes y revisión autorizada.
- Notificaciones al caficultor sin duplicados y consulta "¿Dónde va mi café?" desde la base de datos.
- Webhook firmado, deduplicación, outbox transaccional, RQ con reintentos, recuperación de mensajes, bloqueo por número, auditoría de solo adición, métricas de uso y estimación de costos con tarifas configurables.
- Panel Next.js: Lotes, Alertas, Mapa (MapLibre), Expediente EUDR, Indicadores y Simulador de WhatsApp.

## Proveedores reales y simulados

| Proveedor | Variable | Modo por defecto | Estado |
|---|---|---|---|
| WhatsApp Cloud API | `WHATSAPP_PROVIDER` | simulado | Adaptador real listo; pendiente de credenciales |
| Azure OpenAI | `LLM_PROVIDER` | simulado (reglas) | Adaptador real listo; pendiente de credenciales |
| Azure AI Speech | `SPEECH_PROVIDER` | simulado | Adaptador real listo; pendiente de credenciales |
| Azure AI Document Intelligence | `DOCUMENT_PROVIDER` | simulado | Adaptador real listo; pendiente de credenciales |
| Almacenamiento | `STORAGE_PROVIDER` | local | Azure Blob listo; pendiente de credenciales |
| Capas geoespaciales | `GEO_PROVIDER` | local (GeoJSON sintético) | Carga de capas reales por CLI |

Configuración detallada y despliegue en Azure Container Apps: [docs/configuracion-whatsapp-azure.md](docs/configuracion-whatsapp-azure.md).

## Criterios de aceptación

| # | Criterio | Estado |
|---|---|---|
| 1 | Registro por WhatsApp o simulador | Verificado (prueba automatizada y simulador) |
| 2 | Nota de voz a información estructurada | Verificado con transcriptor simulado; Azure Speech pendiente de credenciales |
| 3 | Procesar foto de recibo | Verificado con lector simulado; Document Intelligence pendiente de credenciales |
| 4 | Corrección de datos extraídos | Verificado |
| 5 | Compras almacenadas | Verificado |
| 6 | Lote de 1.000 kg con tres compras | Verificado |
| 7 | Conserva las tres fincas | Verificado |
| 8 | Despacho vinculado a recepción | Verificado |
| 9 | Faltante de 48 kg | Verificado |
| 10 | 4,8 % | Verificado |
| 11 | Exportador consulta evidencias | Verificado (API y navegador) |
| 12 | Alerta justificada y resuelta | Verificado (WhatsApp y panel) |
| 13 | Transformación no es pérdida | Verificado |
| 14 | Continúa al puerto | Verificado |
| 15 | Genealogía conservada | Verificado |
| 16 | Fincas en el mapa | Verificado en navegador (teselas base no disponibles en el entorno de prueba) |
| 17 | Expediente con evidencias y faltantes | Verificado |
| 18 | Consulta del caficultor | Verificado |
| 19 | Duplicados sin operaciones duplicadas | Verificado |
| 20 | Sin acceso no autorizado | Verificado |
| 21 | Reproducible localmente | Verificado con servicios nativos y worker RQ; `docker compose up` no se pudo ejecutar en el entorno de desarrollo |

## Documentación

- [Arquitectura, flujo de mensajes, fórmulas y modelo de datos](docs/arquitectura.md)
- [Configuración de WhatsApp, Azure y despliegue](docs/configuracion-whatsapp-azure.md)
- [Guion de demostración de cinco minutos](docs/demo.md)
- [Limitaciones y backlog](docs/limitaciones-y-backlog.md)

Esta plataforma apoya la recopilación y revisión de evidencias para la diligencia debida. No constituye una certificación ni sustituye las responsabilidades legales del operador.
# ahi-va-mi-cafe
