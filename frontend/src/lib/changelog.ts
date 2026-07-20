/**
 * Platform changelog — surfaced through the header notification bell.
 *
 * Newest first. `id` must be unique and stable (used for the "read" marker).
 * Keep entries short and user-facing — what changed and why it matters, not
 * internal implementation detail. Bump the list when something user-visible
 * ships; the bell shows a badge for entries newer than the reader's last visit.
 *
 * Each entry's title/body is bilingual ({ en, el }) so it follows the active
 * language, like the rest of the site.
 */
import type { Lang } from "@/lib/i18n";

export type ChangeTag = "new" | "fix" | "improvement";

type Localized = Record<Lang, string>;

export interface ChangelogEntry {
  id: string;        // stable unique id, e.g. "2026-06-30-eliminated-teams"
  date: string;      // ISO "YYYY-MM-DD"
  tag: ChangeTag;
  title: Localized;
  body: Localized;
}

export const CHANGELOG: ChangelogEntry[] = [
  {
    id: "2026-07-19-bilingual",
    date: "2026-07-19",
    tag: "new",
    title: {
      en: "The site is now in English & Greek",
      el: "Ο ιστότοπος τώρα σε Αγγλικά & Ελληνικά",
    },
    body: {
      en: "Switch language any time with the 🇬🇧 / 🇬🇷 flags next to the notifications bell — every page, prediction and chart follows your choice, and it's remembered for next time.",
      el: "Άλλαξε γλώσσα όποτε θες με τις σημαίες 🇬🇧 / 🇬🇷 δίπλα στο καμπανάκι — κάθε σελίδα, πρόβλεψη και γράφημα ακολουθεί την επιλογή σου και θυμάται την προτίμησή σου.",
    },
  },
  {
    id: "2026-07-19-roi-clarity",
    date: "2026-07-19",
    tag: "improvement",
    title: {
      en: "Clearer ROI & EV panel",
      el: "Πιο καθαρό ROI & EV panel",
    },
    body: {
      en: "The ROI tracker's fair-value section is tidied up — one clean breakdown of where the money goes (model result vs bookmaker margin), no repeated text. The EV chart's real-P&L line and its legend now always share the same colour (green in profit, red in loss).",
      el: "Το fair-value κομμάτι του ROI tracker καθαρίστηκε — μία ξεκάθαρη ανάλυση για το πού πάνε τα λεφτά (αποτέλεσμα μοντέλου vs προμήθεια πράκτορα), χωρίς επαναλήψεις. Η γραμμή πραγματικού P&L στο γράφημα EV και το υπόμνημά της έχουν πλέον πάντα το ίδιο χρώμα (πράσινο στο κέρδος, κόκκινο στη ζημιά).",
    },
  },
  {
    id: "2026-07-05-freemium",
    date: "2026-07-05",
    tag: "new",
    title: {
      en: "Free daily Top-3 picks — full predictions for members",
      el: "Δωρεάν καθημερινά Top-3 picks — πλήρεις προβλέψεις για μέλη",
    },
    body: {
      en: "The 3 best picks of the day are free for everyone, along with stats, recent results and the World Cup pages. The full prediction breakdown for every upcoming fixture is now a (free) member feature — register to unlock.",
      el: "Τα 3 καλύτερα picks της ημέρας είναι δωρεάν για όλους, μαζί με τα στατιστικά, τα πρόσφατα αποτελέσματα και τις σελίδες του Παγκοσμίου. Η πλήρης ανάλυση πρόβλεψης για κάθε προσεχή αγώνα είναι πλέον (δωρεάν) λειτουργία μελών — κάνε εγγραφή για να την ξεκλειδώσεις.",
    },
  },
  {
    id: "2026-07-05-wc-review",
    date: "2026-07-05",
    tag: "new",
    title: {
      en: "World Cup review page",
      el: "Σελίδα ανασκόπησης Παγκοσμίου Κυπέλλου",
    },
    body: {
      en: "A permanent retrospective of the tournament: result accuracy, high-confidence calls and the model's title favourite — see /national/world-cup/review.",
      el: "Μια μόνιμη ανασκόπηση του τουρνουά: ακρίβεια αποτελεσμάτων, high-confidence κλήσεις και το φαβορί του μοντέλου για τον τίτλο — δες το /national/world-cup/review.",
    },
  },
  {
    id: "2026-06-30-watch-markets",
    date: "2026-06-30",
    tag: "improvement",
    title: {
      en: "Value markets now earn their place on data",
      el: "Οι value αγορές τώρα κερδίζουν τη θέση τους με δεδομένα",
    },
    body: {
      en: "Markets like GG/Over that the model rates higher than the bookmaker are no longer hidden — they appear as “tracking (unproven)” and get recorded, then promote to a real suggestion only once the current model's own settled record backs them. No more permanent bans inherited from the old model.",
      el: "Αγορές όπως GG/Over που το μοντέλο βαθμολογεί υψηλότερα από τον πράκτορα δεν κρύβονται πλέον — εμφανίζονται ως «υπό παρακολούθηση (αναπόδεικτο)» και καταγράφονται, και προβιβάζονται σε πραγματική πρόταση μόνο όταν το ίδιο το record του τρέχοντος μοντέλου τις δικαιώσει. Τέλος στα μόνιμα μπλοκαρίσματα που κληρονομήθηκαν από το παλιό μοντέλο.",
    },
  },
  {
    id: "2026-06-30-fair-value-roi",
    date: "2026-06-30",
    tag: "new",
    title: {
      en: "Fair-value ROI — performance without the bookmaker margin",
      el: "Fair-value ROI — απόδοση χωρίς την προμήθεια του πράκτορα",
    },
    body: {
      en: "The ROI tracker now shows what our picks would return at fair (de-vigged) odds. At fair value the model is essentially break-even — the negative real-money ROI is the bookmaker's built-in commission, not a model error. A new amber line on the EV chart shows this fair P&L; the gap to actual P&L is the commission paid.",
      el: "Το ROI tracker δείχνει τώρα τι θα απέδιδαν τα picks μας σε δίκαιες (de-vigged) αποδόσεις. Στη δίκαιη τιμή το μοντέλο είναι ουσιαστικά στο μηδέν — το αρνητικό ROI σε πραγματικά λεφτά είναι η ενσωματωμένη προμήθεια του πράκτορα, όχι λάθος του μοντέλου. Μια νέα κεχριμπαρένια γραμμή στο γράφημα EV δείχνει αυτό το fair P&L· η διαφορά από το πραγματικό P&L είναι η προμήθεια που πληρώθηκε.",
    },
  },
  {
    id: "2026-06-30-btts-stats",
    date: "2026-06-30",
    tag: "new",
    title: {
      en: "Goal / No Goal (BTTS) stats & calibration",
      el: "Στατιστικά & calibration για Goal / No Goal (BTTS)",
    },
    body: {
      en: "The Stats page now tracks our Both-Teams-To-Score predictions — accuracy, recall, precision, ROI and a calibration chart — alongside the result and over/under markets.",
      el: "Η σελίδα Στατιστικών παρακολουθεί τώρα τις προβλέψεις μας για το Both-Teams-To-Score — ακρίβεια, recall, precision, ROI και γράφημα calibration — μαζί με τις αγορές αποτελέσματος και over/under.",
    },
  },
  {
    id: "2026-06-30-top-picks-accuracy",
    date: "2026-06-30",
    tag: "new",
    title: {
      en: "Top AI Picks accuracy",
      el: "Ακρίβεια Top AI Picks",
    },
    body: {
      en: "A dedicated Stats section shows how the 3 daily Top Picks (shown on the home page) have actually performed over time, versus the overall hit rate.",
      el: "Ένα ξεχωριστό τμήμα στα Στατιστικά δείχνει πώς έχουν αποδώσει διαχρονικά τα 3 καθημερινά Top Picks (που εμφανίζονται στην αρχική), σε σύγκριση με το γενικό ποσοστό επιτυχίας.",
    },
  },
  {
    id: "2026-06-30-live-results-source",
    date: "2026-06-30",
    tag: "improvement",
    title: {
      en: "Faster, more accurate live results",
      el: "Πιο γρήγορα και ακριβή live αποτελέσματα",
    },
    body: {
      en: "During a live tournament, final scores and penalty-shootout winners now come straight from the live data feed (instead of waiting ~1 day for the open dataset), so results, eliminations and stats update the same day.",
      el: "Σε live τουρνουά, τα τελικά σκορ και οι νικητές στα πέναλτι έρχονται τώρα κατευθείαν από το live data feed (αντί να περιμένουμε ~1 μέρα το ανοιχτό dataset), οπότε αποτελέσματα, αποκλεισμοί και στατιστικά ενημερώνονται την ίδια μέρα.",
    },
  },
  {
    id: "2026-06-30-eliminated-teams",
    date: "2026-06-30",
    tag: "fix",
    title: {
      en: "Knocked-out teams leave the title race",
      el: "Οι αποκλεισμένες ομάδες φεύγουν από τη μάχη του τίτλου",
    },
    body: {
      en: "Once a team loses a knockout match, the World Cup simulation removes it from the Champion-probability list instead of leaving it with a stray percentage.",
      el: "Μόλις μια ομάδα χάσει σε αγώνα νοκ-άουτ, η προσομοίωση του Παγκοσμίου την αφαιρεί από τη λίστα πιθανότητας κατάκτησης, αντί να την αφήνει με ένα ξεκομμένο ποσοστό.",
    },
  },
  {
    id: "2026-06-30-golden-boot-availability",
    date: "2026-06-30",
    tag: "improvement",
    title: {
      en: "Golden Boot respects injuries & suspensions",
      el: "Το Golden Boot λαμβάνει υπόψη τραυματισμούς & τιμωρίες",
    },
    body: {
      en: "Injured or suspended players (from the official injury feed) are now excluded from the top-scorer projection, refreshed daily.",
      el: "Τραυματισμένοι ή τιμωρημένοι παίκτες (από το επίσημο injury feed) εξαιρούνται πλέον από την πρόβλεψη πρώτου σκόρερ, με καθημερινή ανανέωση.",
    },
  },
  {
    id: "2026-06-30-club-form-props",
    date: "2026-06-30",
    tag: "improvement",
    title: {
      en: "Player props now weigh club form",
      el: "Τα player props ζυγίζουν τώρα τη φόρμα συλλόγου",
    },
    body: {
      en: "Scorer / shots / assist rates are anchored to each player's current club-season output, so low-cap players are no longer flattened to a league average.",
      el: "Οι ρυθμοί για σκορ / σουτ / ασίστ βασίζονται στην τρέχουσα απόδοση κάθε παίκτη στη σεζόν του συλλόγου του, οπότε οι παίκτες με λίγες συμμετοχές δεν ισοπεδώνονται πια σε έναν μέσο όρο πρωταθλήματος.",
    },
  },
  {
    id: "2026-06-30-champion-trend",
    date: "2026-06-30",
    tag: "new",
    title: {
      en: "World Cup champion-odds trend chart",
      el: "Γράφημα τάσης αποδόσεων κατάκτησης Παγκοσμίου",
    },
    body: {
      en: "The World Cup page now charts how each contender's title odds move day-by-day as real results come in.",
      el: "Η σελίδα του Παγκοσμίου δείχνει τώρα σε γράφημα πώς κινούνται μέρα-με-τη-μέρα οι αποδόσεις τίτλου κάθε διεκδικητή καθώς έρχονται τα πραγματικά αποτελέσματα.",
    },
  },
  {
    id: "2026-06-30-stats-methodology",
    date: "2026-06-30",
    tag: "improvement",
    title: {
      en: "Honest model-change note on Stats",
      el: "Ειλικρινής σημείωση αλλαγής μοντέλου στα Στατιστικά",
    },
    body: {
      en: "The accuracy page flags that all-time numbers blend an older and the current model; the rolling 7d/30d figures best reflect today's model.",
      el: "Η σελίδα ακρίβειας επισημαίνει ότι τα συνολικά νούμερα αναμειγνύουν ένα παλιότερο και το τρέχον μοντέλο· τα rolling 7d/30d νούμερα αντιπροσωπεύουν καλύτερα το σημερινό μοντέλο.",
    },
  },
  {
    id: "2026-06-30-recent-accuracy",
    date: "2026-06-30",
    tag: "fix",
    title: {
      en: "Recent-results accuracy matches Stats",
      el: "Η ακρίβεια πρόσφατων αποτελεσμάτων ταιριάζει με τα Στατιστικά",
    },
    body: {
      en: "Recent Results and the Stats page now grade predictions with one shared rule, so their accuracy figures can't drift apart.",
      el: "Τα Πρόσφατα Αποτελέσματα και η σελίδα Στατιστικών βαθμολογούν τώρα τις προβλέψεις με έναν κοινό κανόνα, ώστε τα νούμερα ακρίβειάς τους να μην αποκλίνουν.",
    },
  },
  {
    id: "2026-06-17-market-independent",
    date: "2026-06-17",
    tag: "improvement",
    title: {
      en: "Fully market-independent model",
      el: "Πλήρως ανεξάρτητο από την αγορά μοντέλο",
    },
    body: {
      en: "The match model no longer uses bookmaker odds as inputs — predictions are purely model-driven, and value is measured against the market rather than borrowed from it.",
      el: "Το μοντέλο αγώνων δεν χρησιμοποιεί πλέον τις αποδόσεις του πράκτορα ως εισόδους — οι προβλέψεις είναι καθαρά από το μοντέλο, και η αξία (value) μετριέται έναντι της αγοράς αντί να δανείζεται από αυτήν.",
    },
  },
];
