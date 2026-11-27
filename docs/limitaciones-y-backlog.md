# Limitaciones y backlog

## Limitaciones conocidas del MVP

- Integraciones reales sin verificar en vivo: no había credenciales de Meta ni de Azure. Los adaptadores reales están implementados y probados contra respuestas HTTP controladas; los flujos completos se verificaron con adaptadores simulados.
- El lector de documentos y el transcriptor simulados leen la verdad de referencia embebida en los archivos sintéticos (marca PNG y fragmento WAV). No procesan fotos o audios arbitrarios; para eso se requiere Azure.
- El intérprete simulado de lenguaje natural es un conjunto de reglas en español para el guion de la demo. Frases fuera de esos patrones reciben un mensaje de ayuda. Con Azure OpenAI la interpretación es abierta pero igualmente restringida a herramientas tipadas.
- Las capas ambientales son sintéticas. Para una evaluación real se deben cargar capas preparadas (por ejemplo exportaciones de Global Forest Watch o Copernicus) con `python -m app.cli load-layers <capa> <archivo.geojson> --real`.
- Reglas del expediente marcadas como de demostración y pendientes de validación jurídica. Según fuentes oficiales consultadas, el Reglamento (UE) 2023/1115 fue modificado por el Reglamento (UE) 2025/2650 y aplica desde el 30/12/2026 a operadores grandes y medianos y desde el 30/06/2027 a micro y pequeñas empresas. El expediente no es una declaración oficial de diligencia debida.
- Consolidación solo de compras completas; no hay despachos parciales ni división de lotes.
- La ubicación del lote es el último evento confirmado, no rastreo en tiempo real.
- El simulador de WhatsApp emula la ventana de 24 horas: las notificaciones a productores que no han escrito quedan como `needs_template` hasta configurar una plantilla aprobada.
- Docker Compose no se pudo ejecutar en el entorno de desarrollo (sin acceso al registro de imágenes). Se verificó el mismo stack con PostgreSQL 16 + PostGIS 3.4, Redis y el worker RQ nativos, y la sintaxis del Compose con `docker compose config`.
- El mapa usa teselas públicas de OpenStreetMap; sin conexión se muestra un fondo liso con las capas propias.

## Verificaciones necesarias antes de un piloto real (Ley 1581 de 2012)

- Aviso de privacidad y política de tratamiento revisados por un abogado; registro de bases de datos ante la SIC si aplica.
- Procedimiento para consultas, correcciones y supresión de datos de titulares.
- Acuerdos de transmisión de datos con Meta y Microsoft y evaluación de transferencia internacional.
- Retención de evidencias y audios, cifrado de respaldos y gestión de accesos del personal.
- Verificación de que ningún dato de productores se use para entrenar modelos (configuración de los servicios de Azure).

## Backlog (fuera del alcance del MVP)

- Pasaporte digital público con QR y portal para consumidores.
- Módulo financiero, facturación, suscripciones, costos de exportación y rentabilidad.
- Predicciones climáticas, caracterización de suelos y correlaciones clima-calidad.
- Tostión, empaque, sensores IoT y GPS de vehículos.
- Aplicaciones móviles independientes.
- Integraciones con DIAN, RNDC, VUCE, SICA y el sistema de información de la Unión Europea.
- Respuestas por texto a voz.
- Opcionales no implementados: temperatura y precipitación, altitud, edición de polígonos en el mapa, alertas de volumen atípico por finca, exportación a PDF, estimación económica de faltantes.
- Implementados de los opcionales: exportación GeoJSON de fincas y estimación de costos operativos con tarifas configurables (`/api/metrics/usage`).
