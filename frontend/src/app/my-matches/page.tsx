import { redirect } from "next/navigation";
import Link from "next/link";
import { getCurrentUserId, fetchWithAuth } from "@/lib/auth";
import { leagueFlag, leagueLabel } from "@/lib/api";

interface TrackedMatch {
  match_id:        number;
  home_team:       string;
  away_team:       string;
  league:          string;
  match_date:      string;
  tracked_at:      string;
  suggested_market: string | null;
  confidence:      string | null;
}

const marketLabel: Record<string, string> = {
  home_win:  "Home Win",
  draw:      "Draw",
  away_win:  "Away Win",
  over_2_5:  "Over 2.5",
  under_2_5: "Under 2.5",
  btts_yes:  "GG",
  btts_no:   "NG",
};

function confidenceColor(c: string | null) {
  if (!c) return "text-chalk-3";
  const m = c.toLowerCase();
  if (m.includes("high"))   return "text-win";
  if (m.includes("medium")) return "text-est";
  return "text-lose";
}

export default async function MyMatchesPage() {
  const userId = await getCurrentUserId();
  if (!userId) redirect("/login");

  const res = await fetchWithAuth("/users/tracked");
  const matches: TrackedMatch[] = res.ok ? await res.json() : [];

  const now  = new Date();
  const upcoming = matches.filter((m) => new Date(m.match_date) >= now);
  const past     = matches.filter((m) => new Date(m.match_date) <  now);

  const MatchRow = ({ m }: { m: TrackedMatch }) => {
    const date = new Date(m.match_date).toLocaleDateString("el-GR", {
      weekday: "short", day: "numeric", month: "short",
    });
    const mkt = m.suggested_market ? (marketLabel[m.suggested_market] ?? m.suggested_market) : null;

    return (
      <Link
        href={`/matches/${m.match_id}`}
        className="flex items-center gap-4 px-4 py-3 rounded-xl border border-line bg-ink-800 hover:border-line transition-colors"
      >
        <span className="text-base shrink-0">{leagueFlag(m.league)}</span>
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-chalk truncate">
            {m.home_team} <span className="text-chalk-3">vs</span> {m.away_team}
          </p>
          <p className="text-xs text-chalk-3">{leagueLabel(m.league)} · {date}</p>
        </div>
        {mkt && (
          <span className="shrink-0 text-xs px-2 py-0.5 rounded-full bg-win/20 text-win font-medium">
            ⚡ {mkt}
          </span>
        )}
        {m.confidence && (
          <span className={`shrink-0 text-xs ${confidenceColor(m.confidence)}`}>
            {m.confidence}
          </span>
        )}
      </Link>
    );
  };

  return (
    <div className="max-w-2xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold">🔖 My Matches</h1>
        <p className="text-sm text-chalk-3 mt-1">Matches you're tracking</p>
      </div>

      {matches.length === 0 && (
        <div className="rounded-xl border border-line bg-ink-800 px-6 py-12 text-center">
          <p className="text-chalk-2">No tracked matches yet.</p>
          <p className="text-sm text-chalk-3 mt-1">
            Click the bookmark icon on any match card to start tracking.
          </p>
          <Link
            href="/"
            className="inline-block mt-4 px-4 py-2 rounded-lg bg-win hover:bg-win text-sm font-medium text-chalk transition-colors"
          >
            Browse matches
          </Link>
        </div>
      )}

      {upcoming.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-chalk-2 uppercase tracking-wider">Upcoming</h2>
          {upcoming.map((m) => <MatchRow key={m.match_id} m={m} />)}
        </section>
      )}

      {past.length > 0 && (
        <section className="space-y-2">
          <h2 className="text-sm font-semibold text-chalk-2 uppercase tracking-wider">Past</h2>
          {past.map((m) => <MatchRow key={m.match_id} m={m} />)}
        </section>
      )}
    </div>
  );
}
