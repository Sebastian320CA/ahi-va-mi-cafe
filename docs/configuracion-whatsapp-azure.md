# Configuración de WhatsApp, Azure y despliegue

Cada proveedor se activa de forma independiente con su variable `*_PROVIDER`. Se pueden combinar modos reales y simulados.

## WhatsApp Cloud API (Meta)

1. En Meta for Developers crea una app de tipo Business y agrega el producto WhatsApp. Usa el número de prueba o registra uno propio.
2. Copia `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID` y un token de acceso permanente de usuario del sistema en `WHATSAPP_ACCESS_TOKEN`.
3. Copia el secreto de la app (Configuración básica) en `META_APP_SECRET`. Se usa para validar `X-Hub-Signature-256`.
4. Define `WHATSAPP_VERIFY_TOKEN` y configura el webhook en `https://<tu-dominio>/webhooks/whatsapp` suscrito al campo `messages`. Meta exige HTTPS público; para pruebas locales usa un túnel.
5. `META_GRAPH_API_VERSION` queda en `v27.0` (versión vigente más reciente según el changelog de Graph API consultado el 27/11/2026). Revísala antes del piloto.
6. Fuera de la ventana de servicio de 24 horas, Meta solo permite plantillas aprobadas. Crea una plantilla de utilidad en español con un parámetro de cuerpo y pon su nombre en `WHATSAPP_NOTIFICATION_TEMPLATE`. Sin plantilla, las notificaciones quedan con estado `needs_template` (visible en el simulador).
7. Cambia `WHATSAPP_PROVIDER=meta`.

Los operadores (acopio, transporte, trilladora, puerto) deben existir como usuarios con membresía antes de escribir. Los caficultores pueden registrarse solos y quedan vinculados a la organización `DEFAULT_PRODUCER_ORG_CODE`.

## Azure OpenAI

Despliega un modelo con soporte de tool calling y define `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_DEPLOYMENT` (nombre del despliegue) y `AZURE_OPENAI_API_VERSION`. Luego `LLM_PROVIDER=azure`. El prompt de sistema está en `backend/app/agent/prompts.py` e incluye la prohibición de emojis y las reglas contra prompt injection.

## Azure AI Speech

Crea un recurso Speech y define `AZURE_SPEECH_KEY` y `AZURE_SPEECH_REGION`; `SPEECH_PROVIDER=azure`. El adaptador usa la API REST de audio corto (hasta 60 s), que acepta OGG/Opus tal como lo envía WhatsApp, con idioma `es-CO`.

## Azure AI Document Intelligence

Crea el recurso y define `AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT` y `AZURE_DOCUMENT_INTELLIGENCE_KEY`; `DOCUMENT_PROVIDER=azure`. Se usa `prebuilt-layout` con `features=keyValuePairs` (API 2024-11-30). Las etiquetas del documento se asignan a campos con el diccionario `KEY_ALIASES` de `backend/app/integrations/documents/client.py`; valores con confianza menor a 0,6 se tratan como ilegibles. Los documentos de `data/documents` están renderizados con texto real para poder probar este modo.

## Almacenamiento

`STORAGE_PROVIDER=azure` con `AZURE_STORAGE_CONNECTION_STRING` y `AZURE_STORAGE_CONTAINER`. El contenedor debe ser privado; el panel sirve las evidencias a través de la API con autorización.

## Despliegue en Azure (no realizado)

No se aprovisionó infraestructura de pago. Pasos sugeridos:

1. Azure Database for PostgreSQL servidor flexible (versión 16). Habilita la extensión en el parámetro `azure.extensions` con el valor `POSTGIS` y exige TLS. Usa `DATABASE_URL=postgresql+psycopg://...?sslmode=require`.
2. Azure Cache for Redis para `REDIS_URL` (`rediss://` con TLS).
3. Azure Container Registry con las imágenes `backend/Dockerfile` (contexto raíz) y `frontend/Dockerfile` (construida con `--build-arg BACKEND_INTERNAL_URL=https://<api>`).
4. Azure Container Apps: una app `api` con ingreso HTTPS externo, una app `worker` sin ingreso con el comando `python -m app.workers.main`, una app `web` con ingreso externo y un job manual para `alembic upgrade head`.
5. Secretos en Key Vault o en los secretos de Container Apps, nunca en el código. `APP_ENV=production` deshabilita el simulador y el seed sintético.
6. Azure Blob Storage privado para evidencias, con cifrado en reposo por defecto.
