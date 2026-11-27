"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { api } from "@/services/api";
import type { Me } from "@/types/api";
import { IconAlert, IconChart, IconChat, IconExit, IconFile, IconLots, IconMap } from "./icons";

const ROLE_LABEL: Record<string, string> = {
  admin: "Administración",
  exporter: "Exportador",
  compliance_officer: "Cumplimiento ambiental",
};

export function Sidebar({ me, simulator }: { me: Me; simulator: boolean }) {
  const path = usePathname();
  const items = [
    { href: "/lotes", label: "Lotes", icon: IconLots },
    { href: "/alertas", label: "Alertas", icon: IconAlert },
    { href: "/mapa", label: "Mapa de fincas", icon: IconMap },
    { href: "/expediente", label: "Expediente EUDR", icon: IconFile },
    { href: "/indicadores", label: "Indicadores", icon: IconChart },
    ...(simulator ? [{ href: "/simulador", label: "Simulador WhatsApp", icon: IconChat }] : []),
  ];
  const logout = async () => {
    await api.post("/auth/logout");
    window.location.href = "/login";
  };
  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-line bg-forest text-paper">
      <div className="border-b border-paper/15 px-5 py-4">
        <div className="text-lg font-semibold tracking-tight">Ahí va mi café</div>
        <div className="text-xs text-paper/70">Trazabilidad del café colombiano</div>
      </div>
      <nav className="flex-1 py-3">
        {items.map(({ href, label, icon: Icon }) => {
          const active = path.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 border-l-2 px-5 py-2 text-sm ${
                active ? "border-sand bg-paper/10 font-medium" : "border-transparent text-paper/80 hover:bg-paper/5"
              }`}
            >
              <Icon />
              {label}
            </Link>
          );
        })}
      </nav>
      <div className="border-t border-paper/15 px-5 py-3 text-xs">
        <div className="font-medium">{me.full_name}</div>
        {me.roles.map((r) => (
          <div key={r.role + r.organization_id} className="text-paper/70">
            {ROLE_LABEL[r.role] ?? r.role} - {r.organization}
          </div>
        ))}
        <button onClick={logout} className="mt-2 flex items-center gap-2 text-paper/80 hover:text-paper">
          <IconExit /> Cerrar sesión
        </button>
      </div>
    </aside>
  );
}
