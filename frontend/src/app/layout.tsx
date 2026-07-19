import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import ChatBox from "@/components/ChatBox";
import ContactButton from "@/components/ContactButton";
import Providers from "@/components/Providers";
import UserNav from "@/components/UserNav";
import NotificationBell from "@/components/NotificationBell";
import LanguageToggle from "@/components/LanguageToggle";
import { getServerLang } from "@/lib/i18n-server";
import { getT } from "@/lib/i18n";

const SITE_URL =
  process.env.NEXT_PUBLIC_SITE_URL || "https://aitipster.net";
const SITE_NAME = "Football Predictor";
const SITE_DESC =
  "Market-independent ML predictions for football — 1×2, goals, BTTS, correct score, " +
  "player props & a live World Cup simulation, with transparent accuracy tracking.";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: `${SITE_NAME} — ML football predictions`,
    template: `%s · ${SITE_NAME}`,
  },
  description: SITE_DESC,
  applicationName: SITE_NAME,
  keywords: [
    "football predictions", "soccer predictions", "World Cup 2026",
    "xG", "Elo", "machine learning", "value bets", "correct score",
  ],
  openGraph: {
    type: "website",
    siteName: SITE_NAME,
    title: `${SITE_NAME} — ML football predictions`,
    description: SITE_DESC,
    url: SITE_URL,
  },
  twitter: {
    card: "summary_large_image",
    title: `${SITE_NAME} — ML football predictions`,
    description: SITE_DESC,
  },
  robots: { index: true, follow: true },
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const umamiId = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID;
  const lang = await getServerLang();
  const t = getT(lang);
  return (
    <html lang={lang} className="dark">
      <body className="min-h-screen bg-pitch-950">
        {/* Self-hosted umami analytics — same-origin via /u/* rewrites.
            Enabled only when NEXT_PUBLIC_UMAMI_WEBSITE_ID is set (create the
            website in the umami dashboard at localhost:3001 to get the id). */}
        {umamiId && (
          <script defer src="/u/script.js" data-website-id={umamiId} data-host-url="/u" />
        )}
        <Providers initialLang={lang}>
          {/* Header */}
          <header className="border-b border-pitch-700 bg-pitch-900/80 backdrop-blur sticky top-0 z-40">
            <div className="max-w-6xl mx-auto px-4 h-14 flex items-center gap-4">
              <span className="text-2xl">⚽</span>
              <Link href="/" className="font-bold text-lg tracking-tight hover:text-green-400 transition-colors">
                Football Predictor
              </Link>

              {/* Nav links */}
              <nav className="flex items-center gap-1 ml-4">
                <Link
                  href="/"
                  className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-pitch-800 transition-colors"
                >
                  {t("nav.upcoming")}
                </Link>
                <Link
                  href="/recent"
                  className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-pitch-800 transition-colors"
                >
                  {t("nav.recent")}
                </Link>
                {/* "Internationals" nav removed — upcoming national fixtures are
                    merged into Upcoming (+ its International filter). /national
                    route + detail pages stay (match cards link to them). */}
                <Link
                  href="/projections"
                  className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-pitch-800 transition-colors"
                >
                  {t("nav.projections")}
                </Link>
                <Link
                  href="/national/world-cup"
                  className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-pitch-800 transition-colors"
                >
                  {t("nav.worldCup")}
                </Link>
                <Link
                  href="/stats"
                  className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-pitch-800 transition-colors"
                >
                  {t("nav.stats")}
                </Link>
              </nav>

              {/* Language toggle + updates bell + user nav */}
              <div className="ml-auto flex items-center gap-1">
                <LanguageToggle />
                <NotificationBell />
                <UserNav />
              </div>
            </div>
          </header>

          {/* Page content — pb-16 leaves room for the fixed footer bar */}
          <main className="max-w-6xl mx-auto px-4 py-8 pb-20">{children}</main>

          {/* Floating chat assistant — rendered above the fixed footer */}
          <ChatBox />

          {/* Fixed footer bar — always visible at bottom of viewport */}
          <footer className="fixed bottom-0 left-0 right-0 z-30 border-t border-pitch-700 bg-pitch-900/90 backdrop-blur">
            <div className="max-w-6xl mx-auto px-4 py-2 flex flex-col sm:flex-row items-center justify-between gap-2">
              <p className="text-[11px] text-gray-600 text-center sm:text-left leading-tight">
                {t("footer.disclaimer")}{" "}
                <span className="text-gray-700">{t("footer.notFinancial")}</span>
              </p>
              <div className="flex items-center gap-2 shrink-0">
                <ContactButton />
                <a
                  href="https://www.paypal.com/donate/?hosted_button_id=RLTHVXFNMXAV4"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0070ba] hover:bg-[#005ea6] text-white text-xs font-medium transition-colors"
                >
                  <svg className="w-3.5 h-3.5" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M7.076 21.337H2.47a.641.641 0 0 1-.633-.74L4.944 3.217a.77.77 0 0 1 .761-.645h6.964c2.756 0 4.706.825 5.797 2.452.504.752.82 1.582.94 2.465.127.928.05 2.03-.232 3.27-.017.073-.033.147-.051.22-.712 3.174-3.117 4.862-7.047 4.862H9.62a.77.77 0 0 0-.76.645l-.967 5.432a.641.641 0 0 1-.633.539h-.184zm9.348-14.52c-.033.21-.072.424-.118.642-.994 4.42-4.394 5.772-8.736 5.772H5.38a.641.641 0 0 0-.633.54L3.6 21.337h3.476l.746-4.183a.77.77 0 0 1 .76-.645h1.457c3.933 0 6.338-1.688 7.047-4.862.289-1.285.229-2.352-.24-3.154a3.44 3.44 0 0 0-.422-.676z"/>
                  </svg>
                  {t("footer.coffee")}
                </a>
              </div>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
