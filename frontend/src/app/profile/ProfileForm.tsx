"use client";
import { useSession } from "next-auth/react";
import { useState } from "react";

const ALL_LEAGUES = [
  { value: "E0",  label: "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Premier League" },
  { value: "E1",  label: "🏴󠁧󠁢󠁥󠁮󠁧󠁿 Championship" },
  { value: "SP1", label: "🇪🇸 La Liga" },
  { value: "D1",  label: "🇩🇪 Bundesliga" },
  { value: "I1",  label: "🇮🇹 Serie A" },
  { value: "F1",  label: "🇫🇷 Ligue 1" },
  { value: "P1",  label: "🇵🇹 Primeira Liga" },
  { value: "N1",  label: "🇳🇱 Eredivisie" },
  { value: "G1",  label: "🇬🇷 Super League" },
];

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Profile {
  id:                number;
  name:              string | null;
  preferred_leagues: string[];
}

export default function ProfileForm({ profile }: { profile: Profile }) {
  const { data: session } = useSession();
  const userId = (session?.user as any)?.id;

  const [name,    setName]    = useState(profile.name ?? "");
  const [leagues, setLeagues] = useState<string[]>(profile.preferred_leagues);
  const [saving,  setSaving]  = useState(false);
  const [saved,   setSaved]   = useState(false);
  const [error,   setError]   = useState<string | null>(null);

  const toggleLeague = (val: string) =>
    setLeagues((prev) =>
      prev.includes(val) ? prev.filter((l) => l !== val) : [...prev, val]
    );

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId) return;
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      const res = await fetch(`${API}/users/me`, {
        method:  "PATCH",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ name: name || null, preferred_leagues: leagues }),
      });
      if (!res.ok) throw new Error("Save failed");
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSave} className="space-y-5">
      {/* Name */}
      <div>
        <label className="block text-xs text-gray-400 mb-1">Display name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Your name"
          className="w-full rounded-lg border border-pitch-600 bg-pitch-800 px-3 py-2 text-sm text-white placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-green-500"
        />
      </div>

      {/* Preferred leagues */}
      <div>
        <label className="block text-xs text-gray-400 mb-2">Preferred leagues</label>
        <div className="flex flex-wrap gap-2">
          {ALL_LEAGUES.map((lg) => {
            const active = leagues.includes(lg.value);
            return (
              <button
                key={lg.value}
                type="button"
                onClick={() => toggleLeague(lg.value)}
                className={`
                  text-xs px-3 py-1.5 rounded-full border transition-colors
                  ${active
                    ? "border-green-500 bg-green-500/20 text-green-400"
                    : "border-pitch-600 bg-pitch-800 text-gray-400 hover:border-gray-500"
                  }
                `}
              >
                {lg.label}
              </button>
            );
          })}
        </div>
        <p className="text-xs text-gray-600 mt-1">
          {leagues.length === 0 ? "All leagues shown" : `${leagues.length} selected`}
        </p>
      </div>

      {error && (
        <p className="text-xs text-red-400">{error}</p>
      )}

      <button
        type="submit"
        disabled={saving}
        className="w-full rounded-xl bg-green-600 hover:bg-green-500 disabled:opacity-50 px-4 py-2.5 text-sm font-medium text-white transition-colors"
      >
        {saving ? "Saving…" : saved ? "✓ Saved!" : "Save changes"}
      </button>
    </form>
  );
}
