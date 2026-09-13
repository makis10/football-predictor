"use client";
import { useSession } from "next-auth/react";
import { useState } from "react";
import { CLIENT_API_URL as API } from "@/lib/api";

interface Profile {
  id:                number;
  name:              string | null;
  preferred_leagues: string[];
}

export default function ProfileForm({ profile }: { profile: Profile }) {
  const { data: session } = useSession();
  const userId = session?.user?.id;

  const [name,    setName]    = useState(profile.name ?? "");
  const [saving,  setSaving]  = useState(false);
  const [saved,   setSaved]   = useState(false);
  const [error,   setError]   = useState<string | null>(null);

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
        body:    JSON.stringify({ name: name || null }),
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
        <label className="block text-xs text-chalk-2 mb-1">Display name</label>
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Your name"
          className="w-full rounded-lg border border-line bg-ink-700 px-3 py-2 text-sm text-chalk placeholder-gray-500 focus:outline-none focus:ring-2 focus:ring-win"
        />
      </div>

      {/* "Preferred leagues" lived here. It saved football-data file codes
          (E0, SP1…) that no page ever read, under copy saying it filtered
          what you see. It returns when a page honours it. */}

      {error && (
        <p className="text-xs text-lose">{error}</p>
      )}

      <button
        type="submit"
        disabled={saving}
        className="w-full rounded-xl bg-win hover:bg-win disabled:opacity-50 px-4 py-2.5 text-sm font-medium text-chalk transition-colors"
      >
        {saving ? "Saving…" : saved ? "✓ Saved!" : "Save changes"}
      </button>
    </form>
  );
}
