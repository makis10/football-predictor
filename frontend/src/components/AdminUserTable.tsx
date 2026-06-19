"use client";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface UserStats {
  id:             number;
  email:          string;
  name:           string | null;
  provider:       string | null;
  is_admin:       boolean;
  created_at:     string;
  last_login_at:  string | null;
  login_count:    number;
  tracked_count:  number;
  bets_count:     number;
  bets_won:       number;
  total_profit:   number;
  roi_pct:        number;
}

const providerBadge: Record<string, string> = {
  google:      "bg-blue-500/20 text-blue-400",
  credentials: "bg-gray-500/20 text-gray-400",
};

export default function AdminUserTable({ users }: { users: UserStats[] }) {
  const { data: session } = useSession();
  const router = useRouter();
  const [selected, setSelected]   = useState<Set<number>>(new Set());
  const [deleting, setDeleting]   = useState(false);
  const [confirm, setConfirm]     = useState(false);

  const userId = (session?.user as any)?.id;

  const toggle = (id: number) =>
    setSelected((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const toggleAll = () => {
    const deletable = users.filter((u) => !u.is_admin && String(u.id) !== String(userId));
    if (selected.size === deletable.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(deletable.map((u) => u.id)));
    }
  };

  const handleDelete = async () => {
    if (!confirm) { setConfirm(true); return; }
    setDeleting(true);
    setConfirm(false);
    await Promise.all(
      Array.from(selected).map((id) =>
        fetch(`${API}/admin/users/${id}`, { method: "DELETE" })
      )
    );
    setSelected(new Set());
    setDeleting(false);
    router.refresh();
  };

  const deletable = users.filter((u) => !u.is_admin && String(u.id) !== String(userId));
  const allSelected = deletable.length > 0 && selected.size === deletable.length;

  return (
    <div className="space-y-3">
      {/* Delete toolbar */}
      {selected.size > 0 && (
        <div className="flex items-center gap-3 px-4 py-2 rounded-lg bg-red-900/20 border border-red-800">
          <span className="text-sm text-red-300 flex-1">
            {selected.size} user{selected.size > 1 ? "s" : ""} selected
          </span>
          {confirm ? (
            <>
              <span className="text-sm text-red-300">Sure?</span>
              <button
                onClick={handleDelete}
                disabled={deleting}
                className="rounded-lg px-3 py-1 text-sm font-semibold bg-red-600 hover:bg-red-500 text-white disabled:opacity-50 transition-colors"
              >
                {deleting ? "Deleting…" : "Yes, delete"}
              </button>
              <button
                onClick={() => setConfirm(false)}
                className="rounded-lg px-3 py-1 text-sm text-gray-400 hover:text-white transition-colors"
              >
                Cancel
              </button>
            </>
          ) : (
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="rounded-lg px-3 py-1 text-sm font-semibold bg-red-600 hover:bg-red-500 text-white disabled:opacity-50 transition-colors"
            >
              🗑 Delete selected
            </button>
          )}
        </div>
      )}

      <div className="rounded-xl border border-pitch-700 bg-pitch-900 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-pitch-700 text-gray-500 text-xs uppercase tracking-wider">
                <th className="px-4 py-3 text-left w-8">
                  <input
                    type="checkbox"
                    checked={allSelected}
                    onChange={toggleAll}
                    className="rounded border-pitch-600 bg-pitch-800 accent-red-500"
                  />
                </th>
                <th className="px-4 py-3 text-left">User</th>
                <th className="px-4 py-3 text-left">Provider</th>
                <th className="px-4 py-3 text-left">Joined</th>
                <th className="px-4 py-3 text-left">Last Login</th>
                <th className="px-4 py-3 text-right">Logins</th>
                <th className="px-4 py-3 text-right">Tracked</th>
                <th className="px-4 py-3 text-right">Bets</th>
                <th className="px-4 py-3 text-right">Won</th>
                <th className="px-4 py-3 text-right">P&amp;L</th>
                <th className="px-4 py-3 text-right">ROI</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-pitch-700">
              {users.map((u) => {
                const isMe        = String(u.id) === String(userId);
                const canDelete   = !u.is_admin && !isMe;
                const isSelected  = selected.has(u.id);
                const joined      = new Date(u.created_at).toLocaleDateString("el-GR", {
                  day: "numeric", month: "short", year: "numeric",
                  timeZone: "Europe/Athens",
                });
                const winRate = u.bets_count > 0
                  ? Math.round((u.bets_won / u.bets_count) * 100)
                  : null;
                const roiColor = u.roi_pct > 0 ? "text-green-400" : u.roi_pct < 0 ? "text-red-400" : "text-gray-500";

                return (
                  <tr
                    key={u.id}
                    className={`transition-colors ${isSelected ? "bg-red-900/10" : "hover:bg-pitch-800/50"}`}
                  >
                    <td className="px-4 py-3">
                      {canDelete ? (
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggle(u.id)}
                          className="rounded border-pitch-600 bg-pitch-800 accent-red-500"
                        />
                      ) : (
                        <span className="w-4 h-4 block" />
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-full bg-green-800 flex items-center justify-center text-xs font-bold text-white shrink-0">
                          {(u.name ?? u.email)[0].toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="font-medium text-white truncate max-w-[160px]">
                            {u.name ?? <span className="text-gray-500 italic">—</span>}
                            {u.is_admin && (
                              <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-amber-500/20 text-amber-400 font-semibold">
                                ADMIN
                              </span>
                            )}
                            {isMe && (
                              <span className="ml-1.5 text-[10px] px-1.5 py-0.5 rounded bg-pitch-700 text-gray-400">
                                you
                              </span>
                            )}
                          </p>
                          <p className="text-xs text-gray-500 truncate max-w-[160px]">{u.email}</p>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${providerBadge[u.provider ?? ""] ?? "bg-gray-500/20 text-gray-400"}`}>
                        {u.provider ?? "—"}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-gray-400 text-xs">{joined}</td>
                    <td className="px-4 py-3 text-gray-400 text-xs">
                      {u.last_login_at
                        ? new Date(u.last_login_at).toLocaleDateString("el-GR", {
                            day: "numeric", month: "short", year: "numeric",
                            timeZone: "Europe/Athens",
                          })
                        : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-xs">
                      {u.login_count > 0
                        ? <span className="text-white font-medium">{u.login_count}</span>
                        : <span className="text-gray-600">0</span>}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {u.tracked_count > 0
                        ? <span className="text-white font-medium">{u.tracked_count}</span>
                        : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums">
                      {u.bets_count > 0
                        ? <span className="text-white font-medium">{u.bets_count}</span>
                        : <span className="text-gray-600">—</span>}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-xs">
                      {winRate !== null
                        ? <span className="text-green-400">{winRate}%</span>
                        : <span className="text-gray-600">—</span>}
                    </td>
                    <td className={`px-4 py-3 text-right tabular-nums text-xs ${roiColor}`}>
                      {u.bets_count > 0
                        ? `${u.total_profit >= 0 ? "+" : ""}${u.total_profit.toFixed(2)}u`
                        : <span className="text-gray-600">—</span>}
                    </td>
                    <td className={`px-4 py-3 text-right tabular-nums text-xs font-semibold ${roiColor}`}>
                      {u.bets_count > 0
                        ? `${u.roi_pct >= 0 ? "+" : ""}${u.roi_pct}%`
                        : <span className="text-gray-600 font-normal">—</span>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
