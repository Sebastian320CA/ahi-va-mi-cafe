"use client";

import { useState } from "react";
import { Button, ErrorBox } from "@/components/ui";
import { api } from "@/services/api";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.post("/auth/login", { email, password });
      window.location.href = "/lotes";
    } catch (err) {
      setError(err instanceof Error ? err.message : "No fue posible iniciar sesión");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="flex min-h-screen items-center justify-center bg-sand p-6">
      <form onSubmit={submit} className="w-full max-w-sm rounded-sm border border-line bg-paper p-6">
        <h1 className="text-xl font-semibold text-forest">Ahí va mi café</h1>
        <p className="mb-5 text-sm text-ink/70">Panel del exportador y de cumplimiento ambiental</p>
        {error ? <ErrorBox message={error} /> : null}
        <label className="mb-3 block text-sm">
          Correo
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 w-full rounded-sm border border-line bg-paper px-2 py-1.5 outline-none focus:border-forest"
          />
        </label>
        <label className="mb-5 block text-sm">
          Contraseña
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 w-full rounded-sm border border-line bg-paper px-2 py-1.5 outline-none focus:border-forest"
          />
        </label>
        <Button type="submit" disabled={busy} className="w-full">
          {busy ? "Ingresando..." : "Ingresar"}
        </Button>
        <p className="mt-4 text-xs text-ink/60">Entorno de demostración con datos sintéticos.</p>
      </form>
    </main>
  );
}
