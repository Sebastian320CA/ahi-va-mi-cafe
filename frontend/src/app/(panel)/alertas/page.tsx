"use client";

import { useState } from "react";
import { Badge, Button, ErrorBox, Loading, Notice, PageHeader, Section, toneFor } from "@/components/ui";
import { api, documentUrl } from "@/services/api";
import { ALERT_STATUS, CLASSIFICATIONS, kg, pct, REASONS, STATE_LABEL, when } from "@/services/format";
import { useApi } from "@/services/useApi";
import type { Alert } from "@/types/api";

function AlertDetail({ id, onResolved }: { id: string; onResolved: () => void }) {
  const { data, error, reload } = useApi<Alert>(`/alerts/${id}`);
  const [classification, setClassification] = useState("");
  const [notes, setNotes] = useState("");
  const [msg, setMsg] = useState<string | null>(null);
  if (error) return <ErrorBox message={error} />;
  if (!data) return <Loading />;
  const s = data.shipment;
  const resolve = async () => {
    try {
      await api.post(`/alerts/${id}/resolve`, { classification, notes });
      setMsg(null);
      await reload();
      onResolved();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "No se pudo resolver");
    }
  };
  return (
    <Section title={`Alerta ${data.code} - lote ${data.lot_code}`} aside={<Badge tone={toneFor(data.status)}>{ALERT_STATUS[data.status]}</Badge>}>
      <Notice tone="neutral">
        Una diferencia de peso no constituye por sí sola evidencia de fraude o robo. La recepción quedó registrada; la decisión de
        conciliación la toma una persona autorizada.
      </Notice>
      {s ? (
        <table className="mb-4">
          <thead>
            <tr>
              <th></th>
              <th>Salida</th>
              <th>Llegada</th>
              <th>Diferencia</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>Peso neto</td>
              <td>{kg(s.dispatched_kg)}</td>
              <td>{kg(s.received_kg)}</td>
              <td className="font-medium">
                {kg(data.weight_diff_kg)} ({pct(data.discrepancy_pct)})
              </td>
            </tr>
            <tr>
              <td>Sacos</td>
              <td>{s.sacks_out ?? "-"}</td>
              <td>{s.sacks_in ?? "-"}</td>
              <td>{data.sacks_diff ?? "-"}</td>
            </tr>
            <tr>
              <td>Sello</td>
              <td>{s.seal_out ?? "-"}</td>
              <td>{s.seal_in ?? "-"}</td>
              <td>{data.seal_match === null ? "-" : data.seal_match ? "Coincide" : "No coincide"}</td>
            </tr>
            <tr>
              <td>Estado del café</td>
              <td>{STATE_LABEL[s.coffee_state_out]}</td>
              <td>{s.coffee_state_in ? STATE_LABEL[s.coffee_state_in] : "-"}</td>
              <td>{data.state_match ? "Mismo estado" : "Estados distintos: no se compara como pérdida"}</td>
            </tr>
          </tbody>
        </table>
      ) : null}
      <div className="mb-3 text-sm">
        <span className="text-ink/70">Traslado:</span> {s?.code} de {s?.origin} a {s?.destination} | {when(s?.dispatched_at)} a {when(s?.received_at)}
        <div className="text-xs text-ink/60">
          Motivos: {data.reasons.map((r) => REASONS[r] ?? r).join(", ")} | Umbral de peso {String(data.thresholds.weight_pct)} % (supuesto de demostración)
        </div>
      </div>
      <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
        {(data.documents ?? []).map((d) => (
          <a key={d.id} href={documentUrl(d.id)} target="_blank" className="block rounded-sm border border-line p-2 text-xs">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={documentUrl(d.id)} alt="Evidencia documental" className="mb-1 max-h-56 w-full object-contain" />
            Evidencia {d.extracted_fields.document_number ?? ""} | lector: {d.provider} | SHA-256 {d.sha256.slice(0, 12)}...
          </a>
        ))}
      </div>
      <div className="mb-4 rounded-sm border border-line bg-sand p-3 text-sm">
        <div className="font-medium">Justificación</div>
        {data.justification_text ? (
          <>
            <p className="mt-1">{data.justification_text}</p>
            <p className="mt-1 text-xs text-ink/60">
              Registrada por {data.justification_by}. Sugerencia automática (no vinculante):{" "}
              {data.suggested_classification ? CLASSIFICATIONS[data.suggested_classification] : "sin sugerencia"}
            </p>
          </>
        ) : (
          <p className="mt-1 text-ink/70">Solicitada por WhatsApp; aún no se ha recibido.</p>
        )}
      </div>
      {data.status === "resolved" ? (
        data.resolutions.map((r) => (
          <Notice key={r.resolved_at} tone="ok">
            Resuelta como {CLASSIFICATIONS[r.classification]} por {r.resolved_by} el {when(r.resolved_at)}: {r.notes}
          </Notice>
        ))
      ) : (
        <div className="space-y-2">
          {msg ? <ErrorBox message={msg} /> : null}
          <select value={classification} onChange={(e) => setClassification(e.target.value)} className="w-full rounded-sm border border-line bg-paper px-2 py-1.5 text-sm">
            <option value="">Selecciona una clasificación</option>
            {Object.entries(CLASSIFICATIONS).map(([k, v]) => (
              <option key={k} value={k}>
                {v}
              </option>
            ))}
          </select>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Nota de resolución (obligatoria)"
            className="h-20 w-full rounded-sm border border-line bg-paper px-2 py-1.5 text-sm"
          />
          <Button disabled={!classification || notes.trim().length < 5} onClick={resolve}>
            Registrar resolución autorizada
          </Button>
        </div>
      )}
    </Section>
  );
}

export default function AlertsPage() {
  const { data, error, reload } = useApi<Alert[]>("/alerts");
  const [selected, setSelected] = useState<string | null>(null);
  return (
    <>
      <PageHeader title="Alertas de conciliación" subtitle="Discrepancias de peso, sacos, sellos o estado del café entre despacho y recepción." />
      {error ? <ErrorBox message={error} /> : null}
      {!data ? (
        <Loading />
      ) : (
        <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
          <Section title={`${data.length} alerta(s)`}>
            {data.length === 0 ? (
              <p className="text-sm text-ink/70">No hay alertas.</p>
            ) : (
              <table>
                <thead>
                  <tr>
                    <th>Alerta</th>
                    <th>Lote</th>
                    <th>Diferencia</th>
                    <th>Sacos</th>
                    <th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  {data.map((a) => (
                    <tr key={a.id} onClick={() => setSelected(a.id)} className={`cursor-pointer ${selected === a.id ? "bg-sand" : "hover:bg-sand/60"}`}>
                      <td className="font-medium">{a.code}</td>
                      <td>{a.lot_code}</td>
                      <td>
                        {kg(a.weight_diff_kg)} ({pct(a.discrepancy_pct)})
                      </td>
                      <td>{a.sacks_diff ?? "-"}</td>
                      <td>
                        <Badge tone={toneFor(a.status)}>{ALERT_STATUS[a.status]}</Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Section>
          {selected ? <AlertDetail id={selected} onResolved={reload} /> : <p className="text-sm text-ink/60">Selecciona una alerta para ver evidencias y resolverla.</p>}
        </div>
      )}
    </>
  );
}
