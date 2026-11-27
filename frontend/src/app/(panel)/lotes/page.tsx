"use client";

import Link from "next/link";
import { Badge, ErrorBox, Loading, PageHeader, Section, toneFor } from "@/components/ui";
import { EVENT_LABEL, kg, LOT_STATUS, STATE_LABEL, when } from "@/services/format";
import { useApi } from "@/services/useApi";
import type { LotSummary } from "@/types/api";

export default function LotsPage() {
  const { data, error, loading } = useApi<LotSummary[]>("/lots");
  return (
    <>
      <PageHeader
        title="Lotes"
        subtitle="Peso inicial y actual por lote, origen consolidado y última ubicación confirmada."
      />
      {error ? <ErrorBox message={error} /> : null}
      {loading && !data ? <Loading /> : null}
      {data ? (
        <Section title={`${data.length} lote(s)`}>
          {data.length === 0 ? (
            <p className="text-sm text-ink/70">Aún no hay lotes. Se crean desde WhatsApp al consolidar compras.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Código</th>
                  <th>Estado del café</th>
                  <th>Estado</th>
                  <th>Peso inicial</th>
                  <th>Peso actual</th>
                  <th>Fincas</th>
                  <th>Último evento confirmado</th>
                  <th>Alertas</th>
                </tr>
              </thead>
              <tbody>
                {data.map((l) => (
                  <tr key={l.id}>
                    <td>
                      <Link className="font-medium text-forest underline-offset-2 hover:underline" href={`/lotes/${l.code}`}>
                        {l.code}
                      </Link>
                      {l.parent_code ? <div className="text-xs text-ink/60">Derivado de {l.parent_code}</div> : null}
                    </td>
                    <td>{STATE_LABEL[l.coffee_state] ?? l.coffee_state}</td>
                    <td>
                      <Badge tone={toneFor(l.status)}>{LOT_STATUS[l.status] ?? l.status}</Badge>
                    </td>
                    <td>{kg(l.initial_weight_kg)}</td>
                    <td>{kg(l.current_weight_kg)}</td>
                    <td>
                      {l.farms} {l.origin_complete ? <Badge tone="ok">Origen completo</Badge> : <Badge tone="warn">Origen incompleto</Badge>}
                    </td>
                    <td>
                      {l.last_event ? (
                        <>
                          {EVENT_LABEL[l.last_event.type] ?? l.last_event.type} en {l.last_event.location}
                          <div className="text-xs text-ink/60">{when(l.last_event.occurred_at)}</div>
                        </>
                      ) : (
                        "-"
                      )}
                    </td>
                    <td>{l.open_alerts > 0 ? <Badge tone="risk">{l.open_alerts} abierta(s)</Badge> : <Badge>Sin alertas abiertas</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Section>
      ) : null}
    </>
  );
}
