"use client";

import { useEffect, useState, type ReactNode } from "react";
import { Sidebar } from "@/components/Sidebar";
import { Loading } from "@/components/ui";
import { api } from "@/services/api";
import type { Me } from "@/types/api";

export default function PanelLayout({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [simulator, setSimulator] = useState(false);

  useEffect(() => {
    api
      .get<Me>("/auth/me")
      .then(setMe)
      .catch(() => (window.location.href = "/login"));
    // The simulator only exists when the backend runs in development mode.
    api
      .get("/dev/simulator/contacts")
      .then(() => setSimulator(true))
      .catch(() => setSimulator(false));
  }, []);

  if (!me) {
    return (
      <div className="p-8">
        <Loading />
      </div>
    );
  }
  return (
    <div className="flex min-h-screen">
      <Sidebar me={me} simulator={simulator} />
      <main className="min-w-0 flex-1 px-8 py-6">{children}</main>
    </div>
  );
}
