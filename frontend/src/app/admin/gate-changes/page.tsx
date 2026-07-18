import { redirect } from "next/navigation";
import { getSession, fetchWithAuth } from "@/lib/auth";
import { type GateChange } from "@/lib/api";

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
  const session = await getSession();
  if (!(session?.user as any)?.isAdmin) redirect("/");

  const res = await fetchWithAuth("/admin/gate-changes?limit=200");
  const events: GateChange[] = res.ok ? (await res.json()).events ?? [] : [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Gate Changes</h1>
        <p className="text-sm text-gray-500 mt-1">
          Κάθε φορά που ένα market μπαίνει (promoted) ή βγαίνει (demoted) από το suggestable
          set, καταγράφεται εδώ — το ίδιο συμβάν που στέλνει το <code>GATE_ALERT_URL</code>{" "}
          webhook. Πιο πρόσφατα πρώτα.
        </p>
      </div>

      {events.length === 0 ? (
        <div className="rounded-xl border border-pitch-700 bg-pitch-900 p-8 text-center text-gray-500">
          Καμία αλλαγή ακόμα. Οι base markets (Home Win / Draw) ξεκινούν proven· εδώ
          εμφανίζονται προβιβασμοί/υποβιβασμοί καθώς μαζεύεται record.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-pitch-700">
          <table className="w-full text-sm">
            <thead className="bg-pitch-800 text-gray-400 text-xs uppercase tracking-wide">
              <tr>
                <th className="text-left px-4 py-2">When</th>
                <th className="text-left px-3 py-2">Source</th>
                <th className="text-left px-3 py-2">Change</th>
                <th className="text-left px-4 py-2">Now proven</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-pitch-800">
              {events.map((e, i) => (
                <tr key={`${e.at}-${i}`} className="hover:bg-pitch-800/40 align-top">
                  <td className="px-4 py-2 text-gray-400 whitespace-nowrap tabular-nums">{fmtWhen(e.at)}</td>
                  <td className="px-3 py-2">
                    <span className="text-[11px] px-2 py-0.5 rounded-full bg-pitch-700 text-gray-300">{e.source}</span>
                  </td>
                  <td className="px-3 py-2 space-y-1">
                    {e.promoted.map((m) => (
                      <div key={`p-${m}`} className="text-[11px] px-2 py-0.5 rounded bg-green-900/40 text-green-300 inline-block mr-1">
                        ↑ {m}
                      </div>
                    ))}
                    {e.demoted.map((m) => (
                      <div key={`d-${m}`} className="text-[11px] px-2 py-0.5 rounded bg-rose-900/40 text-rose-300 inline-block mr-1">
                        ↓ {m}
                      </div>
                    ))}
                  </td>
                  <td className="px-4 py-2 text-gray-400">{e.now.join(", ") || "∅"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
