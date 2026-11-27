"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { Badge, Button, DISCLAIMER, ErrorBox, Loading, Notice, PageHeader, Section, toneFor } from "@/components/ui";
import { api, documentUrl } from "@/services/api";
import { ALERT_STATUS, ASSESSMENT_LABEL, CASE_STATUS, EVENT_LABEL, kg, LOCATION_LABEL, STATE_LABEL, when } from "@/services/format";
import { useApi } from "@/services/useApi";
import type { Dossier, LotSummary } from "@/types/api";

function DossierView({ code }: { code: string }) {
  const { data, error, reload } = useApi<Dossier>(`/due-diligence/${encodeURIComponent(code)}`);
  const [legality, setLegality] = useState("");
  const [decision, setDecision] = useState("reviewed");
  const [notes, setNotes] = useState("");
  const [msg, setMsg] = useState<{ tone: "ok" | "risk"; text: string } | null>(null);

  useEffect(() => {
    setLegality(data?.case.legality_evidence ?? "");
  }, [data?.case.legality_evidence]);
  if (error) return <ErrorBox message={error} />;
  if (!data) return <Loading />;

  const saveLegality = async () => {
    await api.patch(`/due-diligence/${code}`, { legality_evidence: legality });
    await reload();
  };
  const review = async () => {
    try {
      await api.post(`/due-diligence/${code}/review`, { decision, notes });
      setMsg({ tone: "ok", text: "Revisión registrada." });
      setNotes("");
      await reload();
    } catch (e) {
      setMsg({ tone: "risk", text: e instanceof Error ? e.message : "Error" });
    }
  };

  return (
    <>
      <Notice tone="neutral">{DISCLAIMER}</Notice>
      <div className="mb-5 flex flex-wrap items-center gap-3 text-sm">
        <span>
          Estado del expediente: <Badge tone={toneFor(data.case.status)}>{CASE_STATUS[data.case.status]}</Badge>
        </span>
        <span>
          Resultado ambiental:{" "}
          {data.risk_identified ? <Badge tone="risk">Riesgo identificado en al menos una finca</Badge> : <Badge>Sin riesgo identificado</Badge>}
        </span>
        <span className="text-ink/60">
          {data.exporter} | {data.lot.product} | {kg(data.lot.initial_weight_kg)} de {STATE_LABEL[data.lot.family[0]?.coffee_state ?? ""]} | actual {data.lot.current_code}:{" "}
          {kg(data.lot.current_weight_kg)} de {STATE_LABEL[data.lot.coffee_state]}
        </span>
      </div>

      <Section title="Información faltante">
        {data.missing.length === 0 ? (
          <p className="text-sm text-ok">No hay información obligatoria pendiente según las reglas {data.ruleset.version}.</p>
        ) : (
          <ul className="list-disc pl-5 text-sm">
            {data.missing.map((m) => (
              <li key={m.rule + m.text}>
                <span className="font-medium">{m.rule}</span> {m.text}
              </li>
            ))}
          </ul>
        )}
        <p className="mt-2 text-xs text-ink/60">
          Reglas {data.ruleset.version}: {data.ruleset.status} Referencia: {data.ruleset.reference}. Fecha de corte {data.ruleset.cutoff_date}.
        </p>
      </Section>

      <Section title="Fincas de procedencia y evaluación ambiental">
        <table>
          <thead>
            <tr>
              <th>Finca</th>
              <th>Aporte</th>
              <th>Geolocalización</th>
              <th>Resultado ambiental</th>
              <th>Motivos</th>
            </tr>
          </thead>
          <tbody>
            {data.farms.map((f) => (
              <tr key={f.id}>
                <td>
                  <div className="font-medium">{f.name}</div>
                  <div className="text-xs text-ink/60">
                    {f.producer} | {f.vereda ?? "-"}, {f.municipality ?? "-"}
                  </div>
                </td>
                <td>{kg(f.contributed_kg)}</td>
                <td>
                  <Badge tone={toneFor(f.location_status)}>{LOCATION_LABEL[f.location_status]}</Badge>
                  <div className="text-xs text-ink/60">
                    {f.location ? `${f.location.coordinates[1].toFixed(5)}, ${f.location.coordinates[0].toFixed(5)}` : "Sin punto"}
                    {f.polygon ? " | con polígono" : " | sin polígono"}
                  </div>
                </td>
                <td>{f.assessment ? <Badge tone={toneFor(f.assessment.result)}>{ASSESSMENT_LABEL[f.assessment.result]}</Badge> : <Badge tone="warn">Sin evaluar</Badge>}</td>
                <td className="text-xs">{f.assessment?.reasons.join(" ") ?? "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section title="Compras y evidencias">
        <table>
          <thead>
            <tr>
              <th>Compra</th>
              <th>Productor / finca</th>
              <th>Peso</th>
              <th>Fecha</th>
              <th>Recibo</th>
            </tr>
          </thead>
          <tbody>
            {data.purchases.map((p) => (
              <tr key={p.code}>
                <td>{p.code}</td>
                <td>
                  {p.producer} / {p.farm}
                </td>
                <td>{kg(p.net_weight_kg)}</td>
                <td>{when(p.occurred_at)}</td>
                <td>{p.document_id ? <a className="text-forest underline" href={documentUrl(p.document_id)} target="_blank">{p.receipt_number ?? "Ver"}</a> : "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-xs text-ink/60">{data.documents.length} documento(s) de evidencia con hash SHA-256 registrado.</p>
      </Section>

      <Section title="Historial logístico, alertas y transformación">
        <table>
          <thead>
            <tr>
              <th>Fecha</th>
              <th>Evento</th>
              <th>Lote</th>
              <th>Cantidad</th>
              <th>Ubicación</th>
            </tr>
          </thead>
          <tbody>
            {data.events.map((e) => (
              <tr key={e.id}>
                <td>{when(e.occurred_at)}</td>
                <td>{EVENT_LABEL[e.event_type]}</td>
                <td>{e.lot_code}</td>
                <td>
                  {kg(e.quantity_kg)} {e.coffee_state ? STATE_LABEL[e.coffee_state] : ""}
                </td>
                <td>{e.location}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="mt-3 text-sm">
          {data.alerts.map((a) => (
            <div key={a.id}>
              Alerta {a.code}: diferencia {kg(a.weight_diff_kg)} | <Badge tone={toneFor(a.status)}>{ALERT_STATUS[a.status]}</Badge>
            </div>
          ))}
        </div>
      </Section>

      <Section title="Evidencia de legalidad de la producción">
        <textarea
          value={legality}
          onChange={(e) => setLegality(e.target.value)}
          placeholder="Describe los documentos que respaldan la legalidad de la producción (por ejemplo, soportes de tenencia o permisos)."
          className="h-20 w-full rounded-sm border border-line bg-paper px-2 py-1.5 text-sm"
        />
        <Button variant="secondary" className="mt-2" onClick={saveLegality}>
          Guardar evidencia
        </Button>
      </Section>

      <Section title="Revisión autorizada">
        {msg ? <Notice tone={msg.tone}>{msg.text}</Notice> : null}
        <div className="flex flex-col gap-2 md:flex-row">
          <select value={decision} onChange={(e) => setDecision(e.target.value)} className="rounded-sm border border-line bg-paper px-2 py-1.5 text-sm">
            <option value="reviewed">Revisado</option>
            <option value="approved_internal">Aprobado internamente</option>
            <option value="not_approved">No aprobado</option>
          </select>
          <input
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="Observaciones de la revisión"
            className="flex-1 rounded-sm border border-line bg-paper px-2 py-1.5 text-sm"
          />
          <Button onClick={review} disabled={notes.trim().length < 5}>
            Registrar revisión
          </Button>
        </div>
        <p className="mt-2 text-xs text-ink/60">La aprobación interna se bloquea mientras exista información obligatoria pendiente o riesgos identificados.</p>
        {data.reviews.length > 0 ? (
          <ul className="mt-3 text-sm">
            {data.reviews.map((r) => (
              <li key={r.reviewed_at}>
                {when(r.reviewed_at)} - {CASE_STATUS[r.decision]} por {r.reviewer}: {r.notes}
              </li>
            ))}
          </ul>
        ) : null}
      </Section>
    </>
  );
}

function ExpedienteInner() {
  const params = useSearchParams();
  const lots = useApi<LotSummary[]>("/lots");
  const roots = (lots.data ?? []).filter((l) => !l.parent_code);
  const [code, setCode] = useState<string | null>(params.get("lote"));
  useEffect(() => {
    if (!code && roots.length > 0) setCode(roots[0].code);
  }, [code, roots]);
  return (
    <>
      <PageHeader
        title="Expediente de diligencia debida"
        subtitle="Apoyo a la recopilación de evidencias del Reglamento (UE) 2023/1115. No es una declaración oficial."
        actions={
          <select value={code ?? ""} onChange={(e) => setCode(e.target.value)} className="rounded-sm border border-line bg-paper px-2 py-1.5 text-sm">
            {roots.map((l) => (
              <option key={l.code} value={l.code}>
                {l.code}
              </option>
            ))}
          </select>
        }
      />
      {lots.error ? <ErrorBox message={lots.error} /> : null}
      {code ? <DossierView key={code} code={code} /> : lots.data ? <p className="text-sm text-ink/70">No hay lotes todavía.</p> : <Loading />}
    </>
  );
}

export default function ExpedientePage() {
  return (
    <Suspense fallback={<Loading />}>
      <ExpedienteInner />
    </Suspense>
  );
}
