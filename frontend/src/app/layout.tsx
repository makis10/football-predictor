import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import ChatBox from "@/components/ChatBox";
import ContactButton from "@/components/ContactButton";
import Providers from "@/components/Providers";
import UserNav from "@/components/UserNav";

export const metadata: Metadata = {
  title: "Football Predictor",
  description: "ML-powered football match outcome predictions",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen bg-pitch-950">
        <Providers>
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
                  Upcoming
                </Link>
                <Link
                  href="/recent"
                  className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-pitch-800 transition-colors"
                >
                  Recent Results
                </Link>
                {/* "Internationals" nav removed — upcoming national fixtures are
                    merged into Upcoming (+ its International filter). /national
                    route + detail pages stay (match cards link to them). */}
                <Link
                  href="/national/world-cup"
                  className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-pitch-800 transition-colors"
                >
                  🏆 World Cup
                </Link>
                <Link
                  href="/stats"
                  className="px-3 py-1.5 rounded-lg text-sm text-gray-400 hover:text-white hover:bg-pitch-800 transition-colors"
                >
                  📊 Stats
                </Link>
              </nav>

              {/* User nav — sign in / avatar menu */}
              <div className="ml-auto">
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
                ML predictions for entertainment only · ~52% result / ~58% O/U accuracy ·{" "}
                <span className="text-gray-700">Not financial advice</span>
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
                  ☕ Buy me a coffee
                </a>
              </div>
            </div>
          </footer>
        </Providers>
      </body>
    </html>
  );
}
