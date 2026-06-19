"use client";
import { useSession } from "next-auth/react";
import { useRouter } from "next/navigation";
import { useState } from "react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Props {
  betId: number;
}

export default function SettleBetButton({ betId }: Props) {
  const { data: session } = useSession();
  const router = useRouter();
  const [loading, setLoading] = useState(false);

  const userId = String((session?.user as any)?.id ?? "");

  const settle = async (outcome: "win" | "loss" | "void") => {
    if (!userId) return;
    setLoading(true);
    try {
      await fetch(`${API}/users/bets/${betId}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ outcome }),
      });
      router.refresh();
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex gap-1 shrink-0">
      <button
        onClick={() => settle("win")}
        disabled={loading}
        className="rounded px-2 py-1 text-xs font-semibold bg-green-500/20 text-green-400 hover:bg-green-500/40 disabled:opacity-40 transition-colors"
      >
        W
      </button>
      <button
        onClick={() => settle("loss")}
        disabled={loading}
        className="rounded px-2 py-1 text-xs font-semibold bg-red-500/20 text-red-400 hover:bg-red-500/40 disabled:opacity-40 transition-colors"
      >
        L
      </button>
      <button
        onClick={() => settle("void")}
        disabled={loading}
        className="rounded px-2 py-1 text-xs font-semibold bg-pitch-700 text-gray-400 hover:bg-pitch-600 disabled:opacity-40 transition-colors"
      >
        V
      </button>
    </div>
  );
}
