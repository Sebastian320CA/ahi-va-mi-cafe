"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Badge, Button, ErrorBox, Notice, PageHeader } from "@/components/ui";
import { api } from "@/services/api";
import { when } from "@/services/format";
import type { ConversationItem } from "@/types/api";

type Contact = { phone: string; name: string; roles: string[] };
type Mode = "text" | "audio" | "image" | "location";

const NEW_NUMBER = "573001110101";

const ROLE_ES: Record<string, string> = {
  admin: "administración",
  exporter: "exportador",
  compliance_officer: "cumplimiento",
  collection_center_operator: "centro de acopio",
  transporter: "transportador",
  mill_operator: "trilladora",
  port_operator: "puerto",
  producer: "caficultor",
};
const roles = (r: string[]) => r.map((x) => ROLE_ES[x] ?? x).join(", ");

export default function SimulatorPage() {
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [docs, setDocs] = useState<string[]>([]);
  const [phone, setPhone] = useState(NEW_NUMBER);
  const [mode, setMode] = useState<Mode>("text");
  const [text, setText] = useState("");
  const [doc, setDoc] = useState("");
  const [lat, setLat] = useState("1.8521");
  const [lon, setLon] = useState("-76.0512");
  const [late, setLate] = useState(false);
  const [conv, setConv] = useState<ConversationItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    setConv(await api.get<ConversationItem[]>(`/dev/simulator/conversation?phone=${phone}`));
  }, [phone]);

  useEffect(() => {
    api.get<Contact[]>("/dev/simulator/contacts").then(setContacts).catch((e) => setError(String(e.message)));
    api.get<string[]>("/dev/simulator/documents").then((d) => {
      setDocs(d);
      setDoc(d[0] ?? "");
    });
  }, []);
  useEffect(() => {
    void refresh();
    const t = setInterval(() => void refresh(), 1500);
    return () => clearInterval(t);
  }, [refresh]);
  useEffect(() => {
    // Newer browsers return a Promise from scrollIntoView; never return it as an effect cleanup.
    void bottom.current?.scrollIntoView({ block: "end" });
  }, [conv.length]);

  const send = async () => {
    const f = new FormData();
    f.set("phone", phone);
    f.set("type", mode);
    if (mode === "text") f.set("text", text);
    if (mode === "audio") f.set("transcript", text);
    if (mode === "image") f.set("sample_document", doc);
    if (mode === "location") {
      f.set("latitude", lat);
      f.set("longitude", lon);
    }
    if (late) f.set("timestamp", String(Math.floor(Date.now() / 1000) - 3 * 3600));
    try {
      await api.form("/dev/simulator/messages", f);
      setText("");
      setError(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Error");
    }
  };
  const redeliver = async (id: string) => {
    await api.post(`/dev/simulator/redeliver/${encodeURIComponent(id)}`);
    await refresh();
  };

  const known = contacts.find((c) => c.phone === phone);
  return (
    <>
      <PageHeader
        title="Simulador de WhatsApp"
        subtitle="Integración SIMULADA. Usa exactamente el mismo webhook firmado, worker y servicios de negocio que la integración con Meta."
      />
      <Notice tone="warn">
        Modo desarrollo. Las notas de voz usan una transcripción simulada y las fotos usan documentos sintéticos con lector simulado, salvo que se
        configuren las credenciales de Azure.
      </Notice>
      {error ? <ErrorBox message={error} /> : null}
      <div className="grid grid-cols-1 gap-5 xl:grid-cols-[18rem_minmax(0,1fr)]">
        <div className="rounded-sm border border-line bg-paper p-3 text-sm">
          <div className="mb-2 font-semibold text-coffee">Número que escribe</div>
          <select value={phone} onChange={(e) => setPhone(e.target.value)} className="mb-2 w-full rounded-sm border border-line bg-paper px-2 py-1.5">
            {!contacts.some((c) => c.phone === NEW_NUMBER) ? <option value={NEW_NUMBER}>{NEW_NUMBER} (no registrado)</option> : null}
            {contacts.map((c) => (
              <option key={c.phone + c.name} value={c.phone}>
                {c.name} ({roles(c.roles)})
              </option>
            ))}
          </select>
          <input value={phone} onChange={(e) => setPhone(e.target.value.replace(/\D/g, ""))} className="w-full rounded-sm border border-line px-2 py-1.5" />
          <div className="mt-1 text-xs text-ink/60">{known ? `${known.name}: ${roles(known.roles)}` : "Número sin usuarios registrados"}</div>
        </div>
        <div className="flex h-[640px] flex-col rounded-sm border border-line bg-[#ece5d8]">
          <div className="flex-1 space-y-2 overflow-y-auto p-4">
            {conv.map((m) => (
              <div key={m.id} className={`flex ${m.direction === "in" ? "justify-end" : "justify-start"}`}>
                <div className={`max-w-[75%] rounded-sm border px-3 py-2 text-sm ${m.direction === "in" ? "border-olive/40 bg-[#e4ecd6]" : "border-line bg-paper"}`}>
                  <div className="whitespace-pre-wrap">{m.text ?? `(${m.type})`}</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-ink/60">
                    {when(m.at)}
                    {m.direction === "in" ? <span>{{ text: "texto", audio: "nota de voz", image: "foto", location: "ubicación" }[m.type] ?? m.type}</span> : <span>{m.type.startsWith("notification") ? "notificación" : "respuesta"}</span>}
                    {m.status !== "processed" && m.status !== "sent" ? <Badge tone={m.status === "failed" ? "risk" : "warn"}>{m.status}</Badge> : null}
                    {m.is_late ? <Badge tone="warn">tardío</Badge> : null}
                    {m.direction === "in" ? (
                      <button className="underline" onClick={() => redeliver(m.id)}>
                        reenviar duplicado
                      </button>
                    ) : null}
                  </div>
                </div>
              </div>
            ))}
            <div ref={bottom} />
          </div>
          <div className="border-t border-line bg-paper p-3">
            <div className="mb-2 flex gap-2 text-sm">
              {(["text", "audio", "image", "location"] as Mode[]).map((m) => (
                <button key={m} onClick={() => setMode(m)} className={`rounded-sm border px-2 py-1 ${mode === m ? "border-forest bg-forest text-paper" : "border-line"}`}>
                  {{ text: "Texto", audio: "Nota de voz", image: "Foto", location: "Ubicación" }[m]}
                </button>
              ))}
              <label className="ml-auto flex items-center gap-1 text-xs">
                <input type="checkbox" checked={late} onChange={(e) => setLate(e.target.checked)} /> Mensaje tardío (3 h antes)
              </label>
            </div>
            <div className="flex gap-2">
              {mode === "text" || mode === "audio" ? (
                <input
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && text && send()}
                  placeholder={mode === "audio" ? "Transcripción simulada de la nota de voz" : "Escribe un mensaje"}
                  className="flex-1 rounded-sm border border-line px-2 py-1.5 text-sm"
                />
              ) : null}
              {mode === "image" ? (
                <select value={doc} onChange={(e) => setDoc(e.target.value)} className="flex-1 rounded-sm border border-line px-2 py-1.5 text-sm">
                  {docs.map((d) => (
                    <option key={d}>{d}</option>
                  ))}
                </select>
              ) : null}
              {mode === "location" ? (
                <>
                  <input value={lat} onChange={(e) => setLat(e.target.value)} className="w-32 rounded-sm border border-line px-2 py-1.5 text-sm" />
                  <input value={lon} onChange={(e) => setLon(e.target.value)} className="w-32 rounded-sm border border-line px-2 py-1.5 text-sm" />
                </>
              ) : null}
              <Button onClick={send} disabled={(mode === "text" || mode === "audio") && !text}>
                Enviar
              </Button>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
