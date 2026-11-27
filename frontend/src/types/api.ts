export type Role = {
  role: string;
  organization: string;
  organization_id: string;
};

export type Me = { id: string; full_name: string; email: string | null; roles: Role[] };

export type Assessment = {
  result: "no_indications" | "risk_identified" | "insufficient_information";
  geometry_basis: string;
  assessed_area_ha: string | null;
  forest_2020_overlap_ha: string | null;
  loss_after_cutoff_ha: string | null;
  sources: { layer: string; source: string; is_synthetic: boolean; reference_date: string | null; resolution_m: number | null }[];
  limitations: string[];
  reasons: string[];
  uses_synthetic_layers: boolean;
  rule_version: string;
  queried_at: string;
};

export type FarmProps = {
  id: string;
  name: string;
  producer: string;
  municipality: string | null;
  vereda: string | null;
  department: string | null;
  location_status: string;
  declared_area_ha: string | null;
  has_polygon: boolean;
  is_synthetic: boolean;
  assessment: Assessment | null;
  geometry_kind: "point" | "polygon" | "none";
};

export type FeatureCollection<P> = {
  type: "FeatureCollection";
  features: { type: "Feature"; geometry: GeoJSON.Geometry | null; properties: P }[];
};

export type LotSummary = {
  id: string;
  code: string;
  coffee_state: string;
  status: string;
  initial_weight_kg: string;
  current_weight_kg: string;
  sacks: number | null;
  custodian: string | null;
  created_at: string;
  parent_code: string | null;
  farms: number;
  origin_complete: boolean;
  last_event: { type: string; occurred_at: string; location: string | null } | null;
  open_alerts: number;
};

export type CustodyEvent = {
  id: string;
  lot_code: string | null;
  event_type: string;
  occurred_at: string;
  confirmed_at: string;
  coffee_state: string | null;
  quantity_kg: string | null;
  location: string | null;
  organization: string | null;
  actor: string | null;
  details: Record<string, unknown>;
  evidence_document_id: string | null;
};

export type Shipment = {
  id: string;
  code: string;
  status: string;
  origin: string | null;
  destination: string | null;
  transporter: string | null;
  coffee_state_out: string;
  coffee_state_in: string | null;
  dispatched_kg: string;
  received_kg: string | null;
  sacks_out: number | null;
  sacks_in: number | null;
  seal_out: string | null;
  seal_in: string | null;
  vehicle_plate: string | null;
  dispatched_at: string;
  received_at: string | null;
  dispatch_document_id: string | null;
  reception_document_id: string | null;
};

export type DocumentEvidence = {
  id: string;
  kind: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  provider: string | null;
  status: string;
  extracted_fields: Record<string, string | null>;
  confidence: Record<string, number | null>;
  corrections: { field: string; from: unknown; to: unknown; at: string }[];
  transcript: string | null;
  processed_at: string | null;
  confirmed_at: string | null;
};

export type Alert = {
  id: string;
  code: string;
  status: string;
  lot_code: string | null;
  weight_diff_kg: string | null;
  discrepancy_pct: string | null;
  sacks_diff: number | null;
  seal_match: boolean | null;
  state_match: boolean;
  reasons: string[];
  thresholds: Record<string, string | number>;
  classification: string | null;
  justification_text: string | null;
  justification_by: string | null;
  suggested_classification: string | null;
  created_at: string;
  shipment: Shipment | null;
  resolutions: { classification: string; notes: string; resolved_at: string; resolved_by: string | null }[];
  documents?: DocumentEvidence[];
};

export type LotDetail = {
  lot: LotSummary;
  family: LotSummary[];
  composition: {
    purchase_code: string;
    producer: string;
    farm: string;
    contributed_kg: string;
    coffee_state: string;
    purchase_date: string;
    moisture_pct: string | null;
    document_id: string | null;
  }[];
  events: CustodyEvent[];
  shipments: Shipment[];
  alerts: Alert[];
  last_confirmed_location: { location: string | null; event: string; occurred_at: string } | null;
  note: string;
};

export type DossierFarm = {
  id: string;
  name: string;
  producer: string | null;
  municipality: string | null;
  vereda: string | null;
  declared_area_ha: string | null;
  location: GeoJSON.Point | null;
  location_status: string;
  polygon: GeoJSON.Polygon | null;
  contributed_kg: string;
  is_synthetic: boolean;
  assessment: Assessment | null;
};

export type Dossier = {
  disclaimer: string;
  ruleset: { version: string; status: string; reference: string; cutoff_date: string; rules: { id: string; text: string }[] };
  case: { id: string; status: string; computed_status: string; legality_evidence: string | null; observations: string | null; rule_version: string };
  lot: { code: string; current_code: string; product: string; coffee_state: string; initial_weight_kg: string; current_weight_kg: string; family: { code: string; coffee_state: string; status: string; initial_weight_kg: string }[] };
  exporter: string | null;
  farms: DossierFarm[];
  purchases: { code: string; producer: string | null; farm: string; net_weight_kg: string; coffee_state: string; occurred_at: string; receipt_number: string | null; document_id: string | null }[];
  events: CustodyEvent[];
  shipments: Shipment[];
  alerts: Alert[];
  documents: DocumentEvidence[];
  missing: { rule: string; farm: string | null; text: string }[];
  risk_identified: boolean;
  reviews: { decision: string; notes: string; reviewed_at: string; reviewer: string | null }[];
};

export type Indicators = {
  purchased_kg_by_state: Record<string, string>;
  dispatched_kg_by_state: Record<string, string>;
  received_kg_by_state: Record<string, string>;
  legs: { code: string; origin: string | null; destination: string | null; coffee_state: string; dispatched_kg: string; received_kg: string | null; difference_kg: string | null; status: string }[];
  transformations: { source_lot: string; output_lot: string; input_kg: string; output_kg: string; transformation_yield_pct: string }[];
  open_alerts: number;
  lots_total: number;
  lots_with_complete_origin: number;
  farms_registered: number;
  farms_reviewed: number;
  notes: string[];
};

export type ConversationItem = {
  direction: "in" | "out";
  id: string;
  type: string;
  text: string | null;
  status: string;
  at: string;
  is_late?: boolean;
  error?: string | null;
};
