/**
 * Locked match-detail panel — freemium gate for logged-out visitors.
 *
 * Rendered server-side INSTEAD of the prediction/analysis sections for
 * upcoming matches, so none of the premium numbers ever reach the HTML.
 * Finished matches stay public (they're the transparency/accuracy proof).
 */
import Link from "next/link";

export default function LockedDetailPanel({
  home,
  away,
}: {
  home: string;
  away: string;
}) {
  return (
    <div className="card p-8 text-center space-y-4">
      <p className="text-4xl">🔒</p>
      <div>
        <p className="text-lg font-semibold text-gray-100">
          Η πλήρης πρόβλεψη για το {home} – {away} είναι διαθέσιμη μόνο σε μέλη
        </p>
        <p className="text-sm text-gray-400 mt-2 max-w-md mx-auto">
          Πιθανότητες 1×2, goals, BTTS, πιθανά σκορ, σύγκριση με 25 bookmakers και AI
          ανάλυση — όλα δωρεάν με έναν λογαριασμό. Τα 3 κορυφαία picks της ημέρας μένουν
          πάντα ανοιχτά στην αρχική.
        </p>
      </div>
      <div className="flex items-center justify-center gap-3">
        <Link
          href="/register"
          className="px-5 py-2.5 rounded-lg bg-green-600 hover:bg-green-500 text-white text-sm font-semibold transition-colors"
        >
          Δωρεάν εγγραφή
        </Link>
        <Link
          href="/login"
          className="px-5 py-2.5 rounded-lg border border-pitch-700 hover:bg-pitch-800 text-gray-300 text-sm font-medium transition-colors"
        >
          Σύνδεση
        </Link>
      </div>
      <p className="text-xs text-gray-600">
        Δες την <Link href="/stats" className="text-sky-400 hover:underline">ακρίβεια του μοντέλου</Link>{" "}
        και τα <Link href="/recent" className="text-sky-400 hover:underline">πρόσφατα αποτελέσματα</Link> — δημόσια, χωρίς εγγραφή.
      </p>
    </div>
  );
}
