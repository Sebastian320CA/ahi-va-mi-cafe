"use client";

import Link from "next/link";
import { use } from "react";
import { Badge, ErrorBox, Loading, PageHeader, Section, Stat, toneFor } from "@/components/ui";
import { documentUrl } from "@/services/api";
import { ALERT_STATUS, EVENT_LABEL, kg, pct, SHIPMENT_STATUS, STATE_LABEL, when } from "@/services/format";
import { useApi } from "@/services/useApi";
import type { LotDetail } from "@/types/api";

export default function LotDetailPage({ params }: { params: Promise<{ code: string }> }) {
  const { code } = use(params);
  const { data, error } = useApi<LotDetail>(`/lots/${encodeURIComponent(code)}`);
  if (error) return <ErrorBox message={error} />;
  if (!data) return <Loading />;
  const totalOrigin = data.composition.reduce((s, c) => s + Number(c.contributed_kg), 0);
  return (
    <>
      <PageHeader
        title={`Lote ${data.lot.code}`}
        subtitle={data.note}
        actions={
          <Link href={`/expediente?lote=${data.family[0]?.code ?? data.lot.code}`} className="text-sm text-forest underline">
            Ver expediente
          </Link>
        }
      />
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Estado del café" value={STATE_LABEL[data.lot.coffee_state] ?? data.lot.coffee_state} />
        <Stat label="Peso inicial" value={kg(data.lot.initial_weight_kg)} />
        <Stat label="Peso actual" value={kg(data.lot.current_weight_kg)} />
        <Stat
          label="Última ubicación confirmada"
          value={data.last_confirmed_location?.location ?? "-"}
          hint={data.last_confirmed_location ? `${EVENT_LABEL[data.last_confirmed_location.event]} - ${when(data.last_confirmed_location.occurred_at)}` : undefined}
        />
      </div>

      <Section title="Genealogía del lote">
        <div className="flex flex-wrap items-center gap-2 text-sm">
          {data.family.map((l, i) => (
            <span key={l.id} className="flex items-center gap-2">
              {i > 0 ? <span className="text-ink/50">transformado en</span> : null}
              <Link href={`/lotes/${l.code}`} className="rounded-sm border border-line bg-sand px-2 py-1 font-medium text-forest">
                {l.code} - {STATE_LABEL[l.coffee_state]} - {kg(l.initial_weight_kg)}
              </Link>
            </span>
          ))}
        </div>
      </Section>

      <Section title="Composición de origen (aportes originales)" aside={<span className="text-xs text-ink/60">Total {kg(totalOrigin)}</span>}>
        <table>
          <thead>
            <tr>
              <th>Compra</th>
              <th>Productor</th>
              <th>Finca</th>
              <th>Aporte</th>
              <th>Estado</th>
              <th>Humedad</th>
              <th>Fecha</th>
              <th>Evidencia</th>
            </tr>
          </thead>
          <tbody>
            {data.composition.map((c) => (
              <tr key={c.purchase_code}>
                <td>{c.purchase_code}</td>
                <td>{c.producer}</td>
                <td>{c.farm}</td>
                <td>{kg(c.contributed_kg)}</td>
                <td>{STATE_LABEL[c.coffee_state]}</td>
                <td>{pct(c.moisture_pct)}</td>
                <td>{when(c.purchase_date)}</td>
                <td>{c.document_id ? <a className="text-forest underline" href={documentUrl(c.document_id)} target="_blank">Recibo</a> : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-ink/60">
          Las pérdidas y transformaciones posteriores no se atribuyen a una finca específica; los aportes originales se conservan.
        </p>
      </Section>

      <Section title="Línea de tiempo logística">
        <ol className="relative ml-2 border-l border-line">
          {data.events.map((e) => (
            <li key={e.id} className="mb-4 ml-4">
              <span className="absolute -left-[5px] mt-1.5 h-2.5 w-2.5 border border-forest bg-paper" />
              <div className="text-sm font-medium">
                {EVENT_LABEL[e.event_type] ?? e.event_type} <span className="text-ink/60">- {e.lot_code}</span>
              </div>
              <div className="text-xs text-ink/70">
                {when(e.occurred_at)} | {e.location} | {e.actor} | {kg(e.quantity_kg)} {e.coffee_state ? `de ${STATE_LABEL[e.coffee_state]}` : ""}
              </div>
              {e.event_type === "transformacion" && e.details.output_lot === e.lot_code ? (
                <div className="mt-1 text-xs text-info">
                  Rendimiento de transformación {String(e.details.transformation_yield_pct)} %. Reducción de {kg(String(e.details.weight_reduction_kg))} por trilla, no es pérdida logística.
                </div>
              ) : null}
              {e.evidence_document_id ? (
                <a className="text-xs text-forest underline" href={documentUrl(e.evidence_document_id)} target="_blank">
                  Ver evidencia
                </a>
              ) : null}
            </li>
          ))}
        </ol>
      </Section>

      <Section title="Traslados y conciliación">
        <table>
          <thead>
            <tr>
              <th>Traslado</th>
              <th>Tramo</th>
              <th>Salida</th>
              <th>Llegada</th>
              <th>Sacos</th>
              <th>Sellos</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {data.shipments.map((s) => (
              <tr key={s.id}>
                <td>{s.code}</td>
                <td>
                  {s.origin} a {s.destination}
                  <div className="text-xs text-ink/60">{s.transporter ?? ""} {s.vehicle_plate ?? ""}</div>
                </td>
                <td>{kg(s.dispatched_kg)}</td>
                <td>{kg(s.received_kg)}</td>
                <td>
                  {s.sacks_out ?? "-"} / {s.sacks_in ?? "-"}
                </td>
                <td>
                  {s.seal_out ?? "-"} / {s.seal_in ?? "-"}
                </td>
                <td>
                  <Badge tone={toneFor(s.status)}>{SHIPMENT_STATUS[s.status] ?? s.status}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {data.alerts.length > 0 ? (
          <div className="mt-3 text-sm">
            {data.alerts.map((a) => (
              <div key={a.id}>
                Alerta {a.code}: <Badge tone={toneFor(a.status)}>{ALERT_STATUS[a.status]}</Badge>{" "}
                <Link className="text-forest underline" href="/alertas">
                  Gestionar
                </Link>
              </div>
            ))}
          </div>
        ) : null}
      </Section>
    </>
  );
}
