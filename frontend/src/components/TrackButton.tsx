"use client";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { CLIENT_API_URL as API } from "@/lib/api";

interface Props {
  matchId: number;
}

export default function TrackButton({ matchId }: Props) {
  const { data: session, status } = useSession();
  const router = useRouter();
  const [tracked, setTracked] = useState<boolean | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const userId = session?.user?.id;

  useEffect(() => {
    if (!userId) return;
    fetch(`${API}/users/tracked/${matchId}/status`)
      .then((r) => r.json())
      .then((d) => setTracked(d.tracked))
      .catch(() => setTracked(false));
  }, [userId, matchId]);

  const handleClick = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();

    if (status !== "authenticated") {
      router.push("/login");
      return;
    }

    if (!userId) {
      setError("Session missing — please refresh");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${API}/users/tracked`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify({ match_id: matchId }),
      });
      if (!res.ok) {
        const msg = await res.text().catch(() => "Unknown error");
        setError(msg);
        return;
      }
      const data = await res.json();
      setTracked(data.tracked);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setLoading(false);
    }
  };

  if (status === "loading") return null;

  return (
    <>
      <button
        onClick={handleClick}
        disabled={loading}
        title={tracked ? "Untrack match" : "Track match"}
        className={`
          absolute top-2 right-2 z-10
          w-7 h-7 rounded-full flex items-center justify-center text-base
          transition-all
          ${tracked
            ? "bg-green-500/20 text-green-400 hover:bg-red-500/20 hover:text-red-400"
            : "bg-pitch-700/60 text-gray-400 hover:bg-green-500/20 hover:text-green-400 opacity-40 hover:opacity-100 md:opacity-0 md:group-hover:opacity-100"
          }
          ${loading ? "opacity-50 cursor-not-allowed" : ""}
        `}
      >
        {tracked ? "🔖" : "＋"}
      </button>
      {error && (
        <span className="absolute top-10 right-2 z-20 text-xs text-red-400 bg-pitch-900/90 rounded px-1 py-0.5 max-w-[120px] text-right">
          {error}
        </span>
      )}
    </>
  );
}
