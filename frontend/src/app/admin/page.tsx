import Link from "next/link";
import { redirect } from "next/navigation";
import { getSession, fetchWithAuth } from "@/lib/auth";
import AdminUserTable from "@/components/AdminUserTable";

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


export default async function AdminPage() {
  const session = await getSession();
  if (!(session?.user as any)?.isAdmin) redirect("/");

  const res = await fetchWithAuth("/admin/users");
  const users: UserStats[] = res.ok ? await res.json() : [];

  const totalUsers    = users.length;
  const activeTrackers = users.filter((u) => u.tracked_count > 0).length;
  const activeBettors  = users.filter((u) => u.bets_count > 0).length;
  const googleUsers    = users.filter((u) => u.provider === "google").length;

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-2xl font-bold">Admin Panel</h1>
        <p className="text-sm text-gray-500 mt-1">User management &amp; statistics</p>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: "Total users",      value: totalUsers },
          { label: "Google OAuth",     value: googleUsers },
          { label: "Tracking matches", value: activeTrackers },
          { label: "Logging bets",     value: activeBettors },
        ].map(({ label, value }) => (
          <div key={label} className="rounded-xl border border-pitch-700 bg-pitch-900 p-4 text-center">
            <p className="text-xs text-gray-500 mb-1">{label}</p>
            <p className="text-2xl font-bold text-white">{value}</p>
          </div>
        ))}
      </div>

      {/* Admin sub-pages */}
      <div className="flex gap-3">
        <Link
          href="/admin/training"
          className="rounded-lg border border-pitch-700 bg-pitch-900 hover:bg-pitch-800 px-4 py-2 text-sm text-gray-300 transition-colors"
        >
          Training History →
        </Link>
      </div>

      {/* Users table with delete */}
      <AdminUserTable users={users} />
    </div>
  );
}
