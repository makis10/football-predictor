import type { Metadata } from "next";
import Link from "next/link";
import { Manrope, Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import ChatBox from "@/components/ChatBox";
import ContactButton from "@/components/ContactButton";
import Providers from "@/components/Providers";
import UserNav from "@/components/UserNav";
import NotificationBell from "@/components/NotificationBell";
import LanguageToggle from "@/components/LanguageToggle";
import SiteNav from "@/components/SiteNav";
import ThemeToggle from "@/components/ThemeToggle";
import { getServerLang, getServerTheme } from "@/lib/i18n-server";
import { getFooterAccuracy } from "@/lib/api";
import { getT } from "@/lib/i18n";

/* Fonts, self-hosted at build time by next/font — no request to Google at
   runtime, no layout shift, no dependence on what the visitor has installed.
   Until now `--font-sans: "Inter"` was declared in CSS but Inter was never
   loaded, so the whole site silently rendered in whatever system-ui the device
   happened to ship: SF Pro on a Mac, Segoe on Windows, Roboto on Android. It
   looked like a different product on every machine.

   `subsets` MUST include greek — the UI is bilingual, and a missing subset
   degrades to a fallback face mid-sentence on every Greek string. */
const manrope = Manrope({
  subsets: ["greek", "latin"],
  weight: ["500", "700", "800"],
  variable: "--font-manrope",
  display: "swap",
});
const inter = Inter({
  subsets: ["greek", "latin"],
  weight: ["400", "500", "600"],
  variable: "--font-inter",
  display: "swap",
});
const jetbrains = JetBrains_Mono({
  subsets: ["greek", "latin"],
  weight: ["400", "600", "700"],
  variable: "--font-jetbrains",
  display: "swap",
});

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
  const theme = await getServerTheme();
  const accuracy = await getFooterAccuracy();
  const t = getT(lang);
  return (
    <html
      lang={lang}
      data-theme={theme}
      className={`${manrope.variable} ${inter.variable} ${jetbrains.variable}`}
    >
      <body className="min-h-screen bg-ink-900 font-sans">
        {/* Self-hosted umami analytics — same-origin via /u/* rewrites.
            Enabled only when NEXT_PUBLIC_UMAMI_WEBSITE_ID is set (create the
            website in the umami dashboard at localhost:3001 to get the id). */}
        {umamiId && (
          <script defer src="/u/script.js" data-website-id={umamiId} data-host-url="/u" />
        )}
        <Providers initialLang={lang}>
          {/* Header. `relative` anchors the mobile drawer, which renders
              absolutely against this row so opening it never widens the page. */}
          <header className="sticky top-0 z-40 relative border-b border-line bg-ink-800/80 backdrop-blur">
            {/* px-3 below sm, not px-4: the row is 3px over at 375px once the theme
                toggle joined the controls group, and 8px of side padding is the
                cheapest place to find it — every other element in here is either
                a tap target at its minimum or the wordmark. */}
            <div className="mx-auto flex h-14 max-w-6xl items-center gap-2 px-3 sm:gap-3 sm:px-4">
              <span className="text-xl sm:text-2xl">⚽</span>
              <Link
                href="/"
                className="font-display text-base font-extrabold tracking-tight whitespace-nowrap
                           transition-colors hover:text-win sm:text-lg"
              >
                Football Predictor
              </Link>

              <SiteNav
                items={[
                  { href: "/", label: t("nav.upcoming") },
                  { href: "/recent", label: t("nav.recent") },
                  {
                    href: "/tickets",
                    label: t("nav.tickets"),
                    children: [
                      { href: "/tickets", label: t("nav.tickets.today") },
                      { href: "/tickets/history", label: t("nav.tickets.past") },
                    ],
                  },
                  { href: "/projections", label: t("nav.projections") },
                  { href: "/stats", label: t("nav.stats") },
                ]}
                openLabel={t("nav.menu.open")}
                closeLabel={t("nav.menu.close")}
              />

              {/* Language toggle + updates bell + user nav */}
              <div className="ml-auto flex items-center gap-1">
                <ThemeToggle initial={theme} />
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
          <footer className="fixed bottom-0 left-0 right-0 z-30 border-t border-line bg-ink-800/90 backdrop-blur">
            <div className="max-w-6xl mx-auto px-4 py-2 flex flex-col sm:flex-row items-center justify-between gap-2">
              <p className="text-[11px] text-chalk-3 text-center sm:text-left leading-tight">
                {t("footer.disclaimer")}{" "}
                {accuracy && (
                  <>
                    {t("footer.accuracy", {
                      result: accuracy.result,
                      goals: accuracy.goals,
                      n: accuracy.n,
                    })}{" "}
                  </>
                )}
                <span className="text-chalk-3/70">{t("footer.notFinancial")}</span>
              </p>
              <div className="flex items-center gap-2 shrink-0">
                <ContactButton />
                <a
                  href="https://www.paypal.com/donate/?hosted_button_id=RLTHVXFNMXAV4"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="shrink-0 inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#0070ba] hover:bg-[#005ea6] text-chalk text-xs font-medium transition-colors"
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
