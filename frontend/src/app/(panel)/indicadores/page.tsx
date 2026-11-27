"use client";

import { Badge, ErrorBox, Loading, PageHeader, Section, Stat, toneFor } from "@/components/ui";
import { kg, pct, SHIPMENT_STATUS, STATE_LABEL } from "@/services/format";
import { useApi } from "@/services/useApi";
import type { Indicators } from "@/types/api";

function ByState({ title, values }: { title: string; values: Record<string, string> }) {
  const entries = Object.entries(values);
  return (
    <Stat
      label={title}
      value={entries.length ? entries.map(([s, v]) => <div key={s}>{kg(v)} <span className="text-xs font-normal text-ink/60">{STATE_LABEL[s]}</span></div>) : "-"}
    />
  );
}

export default function IndicatorsPage() {
  const { data, error } = useApi<Indicators>("/indicators");
  if (error) return <ErrorBox message={error} />;
  if (!data) return <Loading />;
  return (
    <>
      <PageHeader title="Indicadores" subtitle={data.notes.join(" ")} />
      <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <ByState title="Kilogramos comprados" values={data.purchased_kg_by_state} />
        <ByState title="Kilogramos despachados" values={data.dispatched_kg_by_state} />
        <ByState title="Kilogramos recibidos" values={data.received_kg_by_state} />
        <Stat label="Alertas abiertas" value={data.open_alerts} />
        <Stat label="Lotes con origen completo" value={`${data.lots_with_complete_origin} de ${data.lots_total}`} />
        <Stat label="Fincas registradas" value={data.farms_registered} />
        <Stat label="Fincas con ubicación revisada" value={`${data.farms_reviewed} de ${data.farms_registered}`} />
      </div>
      <Section title="Kilogramos por tramo">
        <table>
          <thead>
            <tr>
              <th>Traslado</th>
              <th>Tramo</th>
              <th>Estado del café</th>
              <th>Despachado</th>
              <th>Recibido</th>
              <th>Diferencia</th>
              <th>Conciliación</th>
            </tr>
          </thead>
          <tbody>
            {data.legs.map((l) => (
              <tr key={l.code}>
                <td>{l.code}</td>
                <td>
                  {l.origin} a {l.destination}
                </td>
                <td>{STATE_LABEL[l.coffee_state]}</td>
                <td>{kg(l.dispatched_kg)}</td>
                <td>{kg(l.received_kg)}</td>
                <td>{kg(l.difference_kg)}</td>
                <td>
                  <Badge tone={toneFor(l.status)}>{SHIPMENT_STATUS[l.status] ?? l.status}</Badge>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>
      <Section title="Transformaciones (no contabilizadas como pérdida)">
        <table>
          <thead>
            <tr>
              <th>Lote de origen</th>
              <th>Lote resultante</th>
              <th>Entrada</th>
              <th>Salida</th>
              <th>Rendimiento de transformación</th>
            </tr>
          </thead>
          <tbody>
            {data.transformations.map((t) => (
              <tr key={t.output_lot}>
                <td>{t.source_lot}</td>
                <td>{t.output_lot}</td>
                <td>{kg(t.input_kg)} pergamino seco</td>
                <td>{kg(t.output_kg)} café verde</td>
                <td>{pct(t.transformation_yield_pct)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-ink/60">
          Rendimiento de transformación = kg de salida / kg de entrada x 100. Es distinto del factor de rendimiento cafetero (kg de pergamino seco
          necesarios para obtener 70 kg de café excelso).
        </p>
      </Section>
    </>
  );
}
