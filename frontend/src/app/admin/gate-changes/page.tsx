import { redirect } from "next/navigation";
import { getSession, fetchWithAuth } from "@/lib/auth";
import { type GateChange } from "@/lib/api";
import { getServerT } from "@/lib/i18n-server";

export const dynamic = "force-dynamic";

function fmtWhen(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString("en-GB", {
    day: "numeric", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

export default async function GateChangesPage() {
  const t = await getServerT();
  const session = await getSession();
  if (!(session?.user as any)?.isAdmin) redirect("/");

  const res = await fetchWithAuth("/admin/gate-changes?limit=200");
  const events: GateChange[] = res.ok ? (await res.json()).events ?? [] : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Gate Changes</h1>
        <p className="text-sm text-chalk-3 mt-1">
          {t("gate.descPre")} <code>GATE_ALERT_URL</code>{" "}
          {t("gate.descPost")}
        </p>
      </div>

      {events.length === 0 ? (
        <div className="rounded-xl border border-line bg-ink-800 p-8 text-center text-chalk-3">
          {t("gate.empty")}
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-line">
          <table className="w-full text-sm">
            <thead className="bg-ink-700 text-chalk-2 text-xs uppercase tracking-wide">
              <tr>
                <th className="text-left px-4 py-2">When</th>
                <th className="text-left px-3 py-2">Source</th>
                <th className="text-left px-3 py-2">Change</th>
                <th className="text-left px-4 py-2">Now proven</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line-soft">
              {events.map((e, i) => (
                <tr key={`${e.at}-${i}`} className="hover:bg-ink-700/40 align-top">
                  <td className="px-4 py-2 text-chalk-2 whitespace-nowrap tabular-nums">{fmtWhen(e.at)}</td>
                  <td className="px-3 py-2">
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-ink-600 text-chalk-2">{e.source}</span>
                  </td>
                  <td className="px-3 py-2 space-y-1">
                    {e.promoted.map((m) => (
                      <div key={`p-${m}`} className="text-[11px] px-2 py-0.5 rounded bg-win/10 text-win inline-block mr-1">
                        ↑ {m}
                      </div>
                    ))}
                    {e.demoted.map((m) => (
                      <div key={`d-${m}`} className="text-[11px] px-2 py-0.5 rounded bg-lose/10 text-lose inline-block mr-1">
                        ↓ {m}
                      </div>
                    ))}
                  </td>
                  <td className="px-4 py-2 text-chalk-2">{e.now.join(", ") || "∅"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
