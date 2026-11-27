const kgFormat = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 2 });
const dateFormat = new Intl.DateTimeFormat("es-CO", {
  timeZone: "America/Bogota",
  day: "2-digit",
  month: "2-digit",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});

export const kg = (v: string | number | null | undefined) => (v === null || v === undefined ? "-" : `${kgFormat.format(Number(v))} kg`);
export const pct = (v: string | number | null | undefined) => (v === null || v === undefined ? "-" : `${kgFormat.format(Number(v))} %`);
export const when = (v: string | null | undefined) => (v ? dateFormat.format(new Date(v)) : "-");

export const STATE_LABEL: Record<string, string> = {
  cereza: "Café cereza",
  pergamino_humedo: "Pergamino húmedo",
  pergamino_seco: "Pergamino seco",
  verde: "Café verde",
};

export const LOT_STATUS: Record<string, string> = {
  in_storage: "En bodega",
  in_transit: "En tránsito",
  transformed: "Transformado",
};

export const EVENT_LABEL: Record<string, string> = {
  compra_en_acopio: "Compra en acopio",
  creacion_lote: "Creación de lote",
  consolidacion: "Consolidación",
  despacho: "Despacho",
  recepcion: "Recepción",
  transformacion: "Transformación",
  correccion: "Corrección",
};

export const ALERT_STATUS: Record<string, string> = {
  open: "Abierta",
  justification_requested: "Justificación solicitada",
  in_review: "En revisión",
  resolved: "Resuelta",
};

export const CLASSIFICATIONS: Record<string, string> = {
  error_registro: "Error de registro",
  variacion_humedad: "Variación de humedad",
  merma_natural: "Merma natural",
  transformacion: "Transformación",
  faltante_justificado: "Faltante justificado",
  faltante_sin_justificar: "Faltante sin justificar",
  excedente_pendiente: "Excedente pendiente de explicación",
};

export const REASONS: Record<string, string> = {
  faltante_peso: "Faltante de peso",
  excedente_peso: "Excedente de peso",
  diferencia_sacos: "Diferencia de sacos",
  sello_distinto: "Sello distinto",
  estado_distinto: "Estado del café distinto",
};

export const ASSESSMENT_LABEL: Record<string, string> = {
  no_indications: "Sin indicios detectados",
  risk_identified: "Riesgo identificado",
  insufficient_information: "Información insuficiente",
};

export const LOCATION_LABEL: Record<string, string> = {
  declared: "Declarada",
  pending_verification: "Pendiente de verificación",
  reviewed: "Revisada",
};

export const CASE_STATUS: Record<string, string> = {
  incomplete: "Información incompleta",
  pending_review: "Pendiente de revisión",
  risk_identified: "Riesgo identificado",
  reviewed: "Revisado",
  approved_internal: "Aprobado internamente",
  not_approved: "No aprobado",
};

export const SHIPMENT_STATUS: Record<string, string> = {
  in_transit: "En tránsito",
  reconciled: "Conciliado",
  discrepancy: "Con discrepancia",
  resolved: "Discrepancia resuelta",
};
