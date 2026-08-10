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
    id: "2026-08-11-light-theme",
    date: "2026-08-11",
    tag: "new",
    title: {
      en: "Light theme",
      el: "Φωτεινό θέμα",
    },
    body: {
      en: "A sun/moon switch next to the language flags. Your choice is remembered and applied before the page paints, so there is no flash of the wrong theme. Both themes were checked against WCAG AA on every surface — which turned up one colour in the existing dark theme that had been failing all along: captions sitting on chips and bar tracks measured 2.95:1, below even the large-text minimum. Fixed.",
      el: "Διακόπτης ήλιος/φεγγάρι δίπλα στις σημαίες. Η επιλογή σου θυμάται και εφαρμόζεται πριν ζωγραφιστεί η σελίδα, οπότε δεν βλέπεις αναλαμπή λάθος θέματος. Και τα δύο θέματα ελέγχθηκαν με WCAG AA σε κάθε επιφάνεια — κάτι που αποκάλυψε ένα χρώμα του υπάρχοντος σκούρου θέματος που αποτύγχανε από πάντα: οι λεζάντες πάνω σε chips και μπάρες μετρούσαν 2.95:1, κάτω κι από το όριο για μεγάλο κείμενο. Διορθώθηκε.",
    },
  },
  {
    id: "2026-08-10-redesign",
    date: "2026-08-10",
    tag: "improvement",
    title: {
      en: "Redesigned — and it finally works on a phone",
      el: "Ανασχεδιασμός — και επιτέλους δουλεύει στο κινητό",
    },
    body: {
      en: "The header used to force the page 740px wide on a 375px screen, so every page scrolled sideways or rendered at half size on a phone. The links now live in a menu and nothing overflows. The 42 filter buttons that sat above the first fixture are down to a single row showing only leagues that actually have games, with counts. And every probability now carries a hatched band showing how certain we are: a 55% pick we mean and a 55% pick we do not no longer look identical.",
      el: "Το header επέβαλλε πλάτος 740px σε οθόνη 375px, οπότε κάθε σελίδα έσερνε πλάγια ή έδειχνε στο μισό μέγεθος στο κινητό. Τα links μπήκαν σε μενού και τίποτα δεν ξεχειλίζει. Τα 42 κουμπιά φίλτρων πάνω από τον πρώτο αγώνα έγιναν μία γραμμή με μόνο τις λίγκες που έχουν όντως παιχνίδια, με μετρητές. Και κάθε πιθανότητα έχει πλέον ριγέ ζώνη που δείχνει πόσο σίγουροι είμαστε: ένα 55% που το εννοούμε κι ένα 55% που δεν το εννοούμε δεν φαίνονται πια ίδια.",
    },
  },
  {
    id: "2026-08-10-tickets",
    date: "2026-08-10",
    tag: "new",
    title: {
      en: "New: ready-made accumulator tickets",
      el: "Νέο: έτοιμα δελτία παρολί",
    },
    body: {
      en: "A new Tickets tab turns the day's picks into five filled-in betting slips — a banker built from many short prices, a treble, a four-fold, a five-fold and a long shot. Legs can be 1X2, double chance, over/under 1.5–3.5 or both-teams-to-score, and every slip shows its total odds next to its honest chance of landing. Selections are ranked purely by our model's probability, never by how the odds compare. Every slip is stored when it is cut and graded once its matches finish, so the track record on the page is real.",
      el: "Νέα καρτέλα Δελτία: οι επιλογές της ημέρας γίνονται πέντε έτοιμα δελτία — ένα «σίγουρο» με πολλά μικρά σκέλη, μια τριάδα, μια τετράδα, μια πεντάδα και ένα ρίσκο. Τα σκέλη μπορεί να είναι 1Χ2, διπλή ευκαιρία, over/under 1.5–3.5 ή GG/NG, και κάθε δελτίο δείχνει τη συνολική απόδοση δίπλα στην πραγματική πιθανότητα επιτυχίας. Οι επιλογές κατατάσσονται μόνο με βάση την πιθανότητα του μοντέλου μας, ποτέ με βάση τη σύγκριση με τις αποδόσεις. Κάθε δελτίο αποθηκεύεται όπως βγήκε και βαθμολογείται μόλις τελειώσουν οι αγώνες του, οπότε το ιστορικό στη σελίδα είναι αληθινό.",
    },
  },
  {
    id: "2026-08-08-club-names",
    date: "2026-08-08",
    tag: "improvement",
    title: {
      en: "Clubs now show their real names",
      el: "Οι ομάδες εμφανίζονται πλέον με το σωστό τους όνομα",
    },
    body: {
      en: "Göztepe, Beşiktaş, Raków, VfB Stuttgart, Rayo Vallecano, Deportivo La Coruña and about 145 others were displayed under the abbreviated, accent-stripped spelling our data sources use. They now appear as they are actually written.",
      el: "Göztepe, Beşiktaş, Raków, VfB Stuttgart, Rayo Vallecano, Deportivo La Coruña και άλλες ~145 εμφανίζονταν με τη συντομευμένη γραφή χωρίς τόνους που χρησιμοποιούν οι πηγές μας. Τώρα φαίνονται όπως γράφονται πραγματικά.",
    },
  },
  {
    id: "2026-08-08-one-club-one-record",
    date: "2026-08-08",
    tag: "fix",
    title: {
      en: "One club, one record — better predictions",
      el: "Μία ομάδα, ένα ιστορικό — καλύτερες προβλέψεις",
    },
    body: {
      en: "Our two data sources spelled the same club differently, so 143 clubs had their history split in two — exactly at the moment they were promoted or relegated. Each half was rated on a fraction of its real record. Their form and strength ratings are now computed from the full history.",
      el: "Οι δύο πηγές μας έγραφαν την ίδια ομάδα αλλιώς, οπότε 143 σύλλογοι είχαν το ιστορικό τους κομμένο στα δύο — ακριβώς τη στιγμή που ανέβαιναν ή έπεφταν κατηγορία. Κάθε κομμάτι βαθμολογούνταν με ένα μέρος της πραγματικής του πορείας. Η φόρμα και η δυναμική τους υπολογίζονται πλέον από όλο το ιστορικό.",
    },
  },
  {
    id: "2026-08-08-duplicate-fixtures",
    date: "2026-08-08",
    tag: "fix",
    title: {
      en: "Duplicate and phantom fixtures removed",
      el: "Αφαιρέθηκαν διπλοί και ανύπαρκτοι αγώνες",
    },
    body: {
      en: "A few European ties appeared twice with the sides swapped, each carrying its own prediction, and one listed a club that was not even in the competition. They are gone, and the check that finds them now runs every day.",
      el: "Κάποιες ευρωπαϊκές αναμετρήσεις εμφανίζονταν δύο φορές με αντίστροφη έδρα, η καθεμία με δική της πρόβλεψη, και μία έδειχνε ομάδα που δεν συμμετείχε καν στη διοργάνωση. Αφαιρέθηκαν, και ο έλεγχος που τις εντοπίζει τρέχει πλέον καθημερινά.",
    },
  },
  {
    id: "2026-08-08-more-odds",
    date: "2026-08-08",
    tag: "improvement",
    title: {
      en: "Bookmaker odds on more matches",
      el: "Αποδόσεις bookmaker σε περισσότερους αγώνες",
    },
    body: {
      en: "Twenty-seven clubs were named differently by the odds feed than by us, so their matches were served with no odds, no expected value and no value check. All but one are matched now.",
      el: "Είκοσι επτά σύλλογοι ονομάζονταν αλλιώς από το feed αποδόσεων απ' ό,τι από εμάς, οπότε οι αγώνες τους σερβίρονταν χωρίς αποδόσεις, χωρίς EV και χωρίς έλεγχο αξίας. Όλοι πλην ενός ταιριάζουν πλέον.",
    },
  },
  {
    id: "2026-08-08-ai-analysis",
    date: "2026-08-08",
    tag: "fix",
    title: {
      en: "AI analysis is back on every match",
      el: "Η ανάλυση AI επέστρεψε σε κάθε αγώνα",
    },
    body: {
      en: "About half the match analyses were coming back empty — the model was spending its whole budget on reasoning before writing a word, and the blank answer was then cached for a day. Fixed, and an empty answer is no longer stored.",
      el: "Περίπου οι μισές αναλύσεις έβγαιναν κενές — το μοντέλο ξόδευε όλο του το budget σκεπτόμενο πριν γράψει λέξη, και η κενή απάντηση αποθηκευόταν για μια μέρα. Διορθώθηκε, και μια κενή απάντηση δεν αποθηκεύεται πλέον.",
    },
  },
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
