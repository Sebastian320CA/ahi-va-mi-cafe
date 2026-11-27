# Guion de demostración (5 minutos)

Preparación: `docker compose up --build`, abrir http://localhost:3000 e ingresar con `exportador@demo.cafe` / `Cafe2026!`. Abrir el Simulador WhatsApp en una pestaña y el panel en otra. Los documentos de `data/documents` se regeneran con la fecha del día al iniciar.

Alternativa automática: `python scripts/demo_scenario.py` ejecuta los pasos 1 a 7 y 10 contra la API y muestra la conversación.

| Tiempo | Paso | Acción | Qué mostrar |
|---|---|---|---|
| 0:00 | Problema | Panel, Lotes vacío | Origen que se pierde al consolidar, discrepancias en traslados, evidencias EUDR, caficultor sin herramientas. |
| 0:30 | 1. Registro | Simulador, número 573001110101, Nota de voz: "Buenos días, soy Rosa Méndez y mi finca se llama La Esperanza, en la vereda El Cedro de Pitalito". Responder `Sí acepto`. Ubicación 1.8521, -76.0512 y `si`. | Consentimiento Ley 1581 antes de guardar datos. Ubicación pendiente de verificación. |
| 1:15 | 2. Compras | Número Marta Acopio. Foto `01_recibo...` y `si`. Foto `02_recibo..._ilegible`: el asistente pide solo el peso; responder `Fueron 350 kilos` y `si`. Foto `03_recibo..._error`: leyó 207; responder `No, ese peso está mal. Fueron 270 kilos` y `si`. | Nada se registra sin confirmación. Correcciones con historial. Notificación a Rosa. |
| 2:00 | 3. Lote | `Arma el lote con las tres compras de hoy` y `si` | CAF-001 con 1.000 kg y tres fincas. |
| 2:15 | 4-5. Traslado | Foto `04_planilla_despacho` y `si`. Número Andrés Trilladora: foto `05_planilla_recepcion` y `si`. | Alerta automática: 48 kg (4,8 %) y 1 saco. Recepción no bloqueada. Solicitud de justificación. |
| 2:45 | Justificación y resolución | Trilladora: `ALR-001 Un saco se rompió en el cargue` y `si`. Panel, Alertas: ver planillas, clasificar como faltante justificado. | El LLM no decide; resuelve una persona autorizada. |
| 3:15 | 6-7. Trilla y puerto | Trilladora: fotos `06_registro_trilla`, `07_planilla_despacho_caf001v` con `si`. Sofía Puerto: `08_planilla_recepcion_caf001v` y `si`. | 238 kg de trilla no son pérdida. Puerto sin alertas. Genealogía en Lotes, CAF-001. |
| 3:50 | 8. Mapa | Mapa de fincas, Ejecutar evaluación ambiental | Sin indicios (Los Andes), riesgo (El Paraíso), información insuficiente (La Esperanza). Capas sintéticas identificadas. |
| 4:20 | 9. Expediente | Expediente EUDR, CAF-001. Intentar Aprobado internamente: bloqueado. Registrar Revisado. | Faltantes por regla versionada, evidencias, aviso legal. |
| 4:45 | 10. Caficultor | Rosa: `¿Dónde va mi café?` | Respuesta desde la base de datos: ya llegó al puerto. |

Extras si hay tiempo: botón reenviar duplicado (no crea operaciones), casilla de mensaje tardío, Indicadores separados por estado del café.
