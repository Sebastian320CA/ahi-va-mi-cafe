"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { Badge, Button, ErrorBox, Loading, Notice, PageHeader, Section, toneFor } from "@/components/ui";
import { api } from "@/services/api";
import { ASSESSMENT_LABEL, LOCATION_LABEL, when } from "@/services/format";
import { useApi } from "@/services/useApi";
import type { FarmProps, FeatureCollection } from "@/types/api";

const FarmMap = dynamic(() => import("@/features/map/FarmMap"), { ssr: false, loading: () => <Loading /> });

export default function MapPage() {
  const farms = useApi<FeatureCollection<FarmProps>>("/farms");
  const layers = useApi<GeoJSON.FeatureCollection>("/geo/layers");
  const [selected, setSelected] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const list = useMemo(() => {
    const byId = new Map<string, FarmProps>();
    farms.data?.features.forEach((f) => byId.set(f.properties.id, f.properties));
    return [...byId.values()];
  }, [farms.data]);
  const current = list.find((f) => f.id === selected) ?? null;
  const synthetic = layers.data?.features.some((f) => f.properties?.is_synthetic);

  const assess = async () => {
    setBusy(true);
    try {
      await api.post("/farms/assess");
      await farms.reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Error");
    } finally {
      setBusy(false);
    }
  };
  const review = async (id: string) => {
    try {
      await api.post(`/farms/${id}/review-location`, { notes: "Ubicación revisada desde el panel" });
      await farms.reload();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Error");
    }
  };

  return (
    <>
      <PageHeader
        title="Mapa de fincas"
        subtitle="Ubicaciones, polígonos de parcela, estado de verificación y evaluación ambiental preliminar."
        actions={
          <div className="flex gap-2">
            <a className="rounded-sm border border-line bg-paper px-3 py-1.5 text-sm" href="/api/farms/export.geojson">
              Exportar GeoJSON
            </a>
            <Button onClick={assess} disabled={busy}>
              {busy ? "Evaluando..." : "Ejecutar evaluación ambiental"}
            </Button>
          </div>
        }
      />
      {msg ? <ErrorBox message={msg} /> : null}
      {synthetic ? (
        <Notice tone="warn">
          Las capas de bosque 2020 y de pérdida de bosque posterior al 31/12/2020 son SINTÉTICAS de demostración. Los resultados son
          señales de apoyo, no certificaciones.
        </Notice>
      ) : null}
      {farms.error ? <ErrorBox message={farms.error} /> : null}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
        <div>
          {farms.data && layers.data ? <FarmMap farms={farms.data} layers={layers.data} onSelect={setSelected} /> : <Loading />}
          <div className="mt-2 flex flex-wrap gap-4 text-xs text-ink/70">
            <span><span className="mr-1 inline-block h-2.5 w-2.5 bg-ok" />Sin indicios</span>
            <span><span className="mr-1 inline-block h-2.5 w-2.5 bg-risk" />Riesgo identificado</span>
            <span><span className="mr-1 inline-block h-2.5 w-2.5 bg-warn" />Información insuficiente</span>
            <span><span className="mr-1 inline-block h-2.5 w-2.5 bg-[#5b6770]" />Sin evaluar</span>
            <span><span className="mr-1 inline-block h-2.5 w-2.5 bg-[#3f7a4f]/40" />Bosque 2020 (sintético)</span>
            <span><span className="mr-1 inline-block h-2.5 w-2.5 bg-risk/60" />Pérdida posterior (sintética)</span>
          </div>
        </div>
        <div>
          <Section title="Fincas">
            <table>
              <thead>
                <tr>
                  <th>Finca</th>
                  <th>Ubicación</th>
                  <th>Evaluación</th>
                </tr>
              </thead>
              <tbody>
                {list.map((f) => (
                  <tr key={f.id} onClick={() => setSelected(f.id)} className={`cursor-pointer ${selected === f.id ? "bg-sand" : ""}`}>
                    <td>
                      <div className="font-medium">{f.name}</div>
                      <div className="text-xs text-ink/60">{f.producer}</div>
                    </td>
                    <td>
                      <Badge tone={toneFor(f.location_status)}>{LOCATION_LABEL[f.location_status]}</Badge>
                      <div className="text-xs text-ink/60">{f.has_polygon ? "Con polígono" : "Solo punto"}</div>
                    </td>
                    <td>
                      {f.assessment ? <Badge tone={toneFor(f.assessment.result)}>{ASSESSMENT_LABEL[f.assessment.result]}</Badge> : <Badge>Sin evaluar</Badge>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Section>
          {current ? (
            <Section title={`Detalle: ${current.name}`}>
              <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                <dt className="text-ink/60">Productor</dt>
                <dd>{current.producer}</dd>
                <dt className="text-ink/60">Vereda / municipio</dt>
                <dd>
                  {current.vereda ?? "-"} / {current.municipality ?? "-"}
                </dd>
                <dt className="text-ink/60">Área declarada</dt>
                <dd>{current.declared_area_ha ? `${current.declared_area_ha} ha` : "No declarada"}</dd>
                <dt className="text-ink/60">Datos</dt>
                <dd>{current.is_synthetic ? "Sintéticos" : "Registrados por WhatsApp"}</dd>
              </dl>
              {current.location_status === "pending_verification" ? (
                <Button variant="secondary" className="mt-3" onClick={() => review(current.id)}>
                  Marcar ubicación como revisada
                </Button>
              ) : null}
              {current.assessment ? (
                <div className="mt-4 text-sm">
                  <div className="font-medium">Evaluación del {when(current.assessment.queried_at)}</div>
                  <ul className="mt-1 list-disc pl-5">
                    {current.assessment.reasons.map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                  <div className="mt-2 text-xs text-ink/60">
                    Base: {current.assessment.geometry_basis} | Área evaluada: {current.assessment.assessed_area_ha ?? "-"} ha | Reglas {current.assessment.rule_version}
                  </div>
                  <div className="mt-2 text-xs text-ink/60">
                    Fuentes:{" "}
                    {current.assessment.sources.map((s) => `${s.layer} (${s.source}, ${s.reference_date}, ${s.resolution_m} m${s.is_synthetic ? ", sintética" : ""})`).join("; ")}
                  </div>
                  <ul className="mt-2 list-disc pl-5 text-xs text-ink/60">
                    {current.assessment.limitations.map((l) => (
                      <li key={l}>{l}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
            </Section>
          ) : null}
        </div>
      </div>
    </>
  );
}
