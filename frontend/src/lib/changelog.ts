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
    id: "2026-09-13-every-fixture",
    date: "2026-09-13",
    tag: "fix",
    title: {
      en: "The home page showed at most 100 of a weekend's fixtures",
      el: "Η αρχική σελίδα έδειχνε το πολύ 100 από τους αγώνες ενός Σαββατοκύριακου",
    },
    body: {
      en: "On a Friday the next three days can hold 180 club fixtures. The page asked for 100 and silently dropped the rest — usually the whole of Sunday — so Top Picks never saw them, while the league filters counted fixtures the page did not show. It now loads every fixture in the window.",
      el: "Μια Παρασκευή οι επόμενες τρεις ημέρες μπορεί να έχουν 180 αγώνες συλλόγων. Η σελίδα ζητούσε 100 και έχανε σιωπηλά τους υπόλοιπους — συνήθως ολόκληρη την Κυριακή — οπότε τα Top Picks δεν τους έβλεπαν ποτέ, ενώ τα φίλτρα λιγκών μετρούσαν αγώνες που η σελίδα δεν έδειχνε. Τώρα φορτώνει κάθε αγώνα του διαστήματος.",
    },
  },
  {
    id: "2026-09-13-stats-right-floor",
    date: "2026-09-13",
    tag: "fix",
    title: {
      en: "/stats measured the model against the wrong floor in some leagues",
      el: "Το /stats σύγκρινε το μοντέλο με λάθος μέτρο σε κάποιες λίγκες",
    },
    body: {
      en: "Over/Under and BTTS accuracy were compared with always betting Over and always betting GG. Where Under or NG is more common that is the wrong floor: Serie A's Over/Under read '+6.7pp vs always OVER' in green, when always betting Under would have done 2.2 points better. Every figure is now set against the better of the two constants, and the league and version tables colour each row against its own. The value-strategy ROI counts only the picks its gate chose, the EV and fair-value figures use the model's own probabilities, and national accuracy is graded the same way on every page.",
      el: "Η ακρίβεια Over/Under και BTTS συγκρινόταν με το να παίζεις πάντα Over και πάντα GG. Όπου το Under ή το NG είναι συχνότερο, αυτό είναι λάθος μέτρο: το Over/Under της Serie A έγραφε «+6.7pp έναντι πάντα OVER» με πράσινο, ενώ το να παίζεις πάντα Under θα έβγαζε 2,2 μονάδες περισσότερο. Κάθε νούμερο συγκρίνεται πλέον με την καλύτερη από τις δύο σταθερές, και οι πίνακες λιγκών και εκδόσεων χρωματίζουν κάθε γραμμή απέναντι στη δική της. Το ROI της value στρατηγικής μετράει μόνο τις επιλογές που διάλεξε το φίλτρο της, τα EV και fair-value χρησιμοποιούν τις δικές του πιθανότητες του μοντέλου, και η ακρίβεια των εθνικών βαθμολογείται με τον ίδιο τρόπο σε κάθε σελίδα.",
    },
  },
  {
    id: "2026-09-13-match-page-honest",
    date: "2026-09-13",
    tag: "fix",
    title: {
      en: "Match pages say what the site actually published",
      el: "Οι σελίδες αγώνων λένε ό,τι δημοσίευσε πραγματικά ο ιστότοπος",
    },
    body: {
      en: "The analysis panel showed the model before its blend with the market as 'our model', and its 'model pick' was a different selection from the one on the card beside it; both now match the card. The accuracy under each prediction was a hardcoded '~52%' while the record said 49% — it now reads the record. A backend restart no longer turns real match pages into 'page not found', and an old match page no longer produces a prediction after the result.",
      el: "Το πάνελ ανάλυσης έδειχνε το μοντέλο πριν από τη μίξη του με την αγορά ως «το μοντέλο μας», και το «model pick» ήταν διαφορετική επιλογή από αυτή της κάρτας δίπλα του· τώρα ταιριάζουν και τα δύο με την κάρτα. Η ακρίβεια κάτω από κάθε πρόβλεψη ήταν ένα σταθερό «~52%» ενώ το ιστορικό έλεγε 49% — τώρα διαβάζει το ιστορικό. Μια επανεκκίνηση του backend δεν κάνει πια πραγματικές σελίδες αγώνων «δεν βρέθηκε», και μια παλιά σελίδα αγώνα δεν παράγει πια πρόβλεψη μετά το αποτέλεσμα.",
    },
  },
  {
    id: "2026-09-13-ninety-minutes",
    date: "2026-09-13",
    tag: "fix",
    title: {
      en: "Knockout ties are graded at 90 minutes, as the bookmakers settle them",
      el: "Οι νοκ-άουτ αγώνες κρίνονται στο 90', όπως τους κλείνουν τα γραφεία",
    },
    body: {
      en: "A tie level after 90 minutes and won in extra time was stored with its extra-time score, so our 1×2, Over 2.5 and BTTS calls — and every slip carrying it — were graded against a result no bookmaker settles on. 27 club ties are re-scored, the 2026 Champions League final among them: it was stored as 5-4 with the penalty shootout folded in, and was 1-1 after 90 minutes. Two slip legs changed verdict; no slip did. National matches keep the score after extra time, which is what that model is built on.",
      el: "Ένας αγώνας ισόπαλος στο 90' που κρίθηκε στην παράταση αποθηκευόταν με το σκορ της παράτασης, οπότε οι προβλέψεις μας για 1×2, Over 2,5 και BTTS — και κάθε δελτίο που τον περιείχε — κρίνονταν με αποτέλεσμα που κανένα γραφείο δεν χρησιμοποιεί. Διορθώθηκαν 27 αγώνες συλλόγων, ανάμεσά τους ο τελικός του Champions League 2026: είχε αποθηκευτεί 5-4 με τα πέναλτι μέσα, ενώ στο 90' ήταν 1-1. Δύο σκέλη δελτίων άλλαξαν ετυμηγορία· κανένα δελτίο. Οι αγώνες εθνικών κρατούν το σκορ μετά την παράταση, πάνω στο οποίο είναι χτισμένο εκείνο το μοντέλο.",
    },
  },
  {
    id: "2026-09-13-your-bets-stay",
    date: "2026-09-13",
    tag: "fix",
    title: {
      en: "Bets you log and matches you track no longer disappear",
      el: "Τα στοιχήματα που καταγράφετε και οι αγώνες που παρακολουθείτε δεν χάνονται πια",
    },
    body: {
      en: "They were tied to our prediction for the fixture, and predictions are rewritten on schedule — every upcoming match on Mondays, today's every afternoon, newly priced ones every eight hours — so each rewrite quietly deleted them, and /my-roi computed your ROI over whatever had survived. They now belong to the fixture itself. If a fixture is cancelled, an open bet on it is voided rather than deleted, and /my-roi shows the teams instead of a match number.",
      el: "Ήταν δεμένα με την πρόβλεψή μας για τον αγώνα, και οι προβλέψεις ξαναγράφονται προγραμματισμένα — όλοι οι επερχόμενοι αγώνες κάθε Δευτέρα, οι σημερινοί κάθε απόγευμα, όσοι πήραν τιμές κάθε οκτώ ώρες — οπότε κάθε ξαναγράψιμο τα έσβηνε σιωπηλά και το /my-roi υπολόγιζε το ROI σας πάνω σε ό,τι είχε απομείνει. Τώρα ανήκουν στον ίδιο τον αγώνα. Αν ένας αγώνας ακυρωθεί, ένα ανοιχτό στοίχημα γίνεται άκυρο αντί να σβηστεί, και το /my-roi δείχνει τις ομάδες αντί για αριθμό αγώνα.",
    },
  },
  {
    id: "2026-09-13-unplayed-matches",
    date: "2026-09-13",
    tag: "fix",
    title: {
      en: "Awarded, cancelled and abandoned matches are no longer graded",
      el: "Αγώνες που κατακυρώθηκαν, ακυρώθηκαν ή διακόπηκαν δεν κρίνονται πια",
    },
    body: {
      en: "An awarded 3-0 was graded as if it had been played, against our calls and on slips; no bookmaker settles a match that was not played. A match abandoned on the day stayed open for ever instead — out of the accuracy record, and 'still running' on any slip carrying it. Both are now recorded as void: an awarded score still counts in the league table, but nothing grades it. A daily check asks the feed about fixtures left without a result; its first run settled one and voided four.",
      el: "Ένα 3-0 στα χαρτιά κρινόταν σαν να είχε παιχτεί, απέναντι στις προβλέψεις μας και στα δελτία· κανένα γραφείο δεν κλείνει αγώνα που δεν παίχτηκε. Ένας αγώνας που διακόπηκε την ημέρα του έμενε αντίθετα ανοιχτός για πάντα — εκτός στατιστικών, και «σε εξέλιξη» σε κάθε δελτίο που τον είχε. Και οι δύο καταγράφονται πλέον ως άκυροι: το σκορ στα χαρτιά μετράει στη βαθμολογία, αλλά τίποτα δεν το κρίνει. Ένας καθημερινός έλεγχος ρωτά την πηγή για αγώνες που έμειναν χωρίς αποτέλεσμα· στην πρώτη του εκτέλεση έκλεισε έναν και ακύρωσε τέσσερις.",
    },
  },
  {
    id: "2026-09-13-national-model-recent",
    date: "2026-09-13",
    tag: "improvement",
    title: {
      en: "The national-team model no longer stops learning in 2018",
      el: "Το μοντέλο των εθνικών δεν σταματά πια να μαθαίνει στο 2018",
    },
    body: {
      en: "Its training windows were fixed dates, so a model retrained every morning had not learned from a single international played after 2022 — and a shortcut in its training meant its trees actually stopped in mid-2018. The windows now move with the data: every morning it is built on every match up to two years back, calibrated on the year after that and checked on the latest twelve months. On a year of internationals neither version had seen, the new model's probabilities were better for the result, for goals and for both teams to score; how often its single most likely outcome came true did not change beyond noise. The first national predictions made with it appear after tomorrow morning's update.",
      el: "Τα παράθυρα εκπαίδευσής του ήταν σταθερές ημερομηνίες, οπότε ένα μοντέλο που ξαναεκπαιδευόταν κάθε πρωί δεν είχε μάθει από κανέναν διεθνή αγώνα μετά το 2022 — και μια συντόμευση στην εκπαίδευση έκανε τα δέντρα του να σταματούν στα μέσα του 2018. Τώρα τα παράθυρα κινούνται με τα δεδομένα: κάθε πρωί χτίζεται σε όλους τους αγώνες έως δύο χρόνια πίσω, βαθμονομείται στον επόμενο χρόνο και ελέγχεται στους πιο πρόσφατους δώδεκα μήνες. Σε έναν χρόνο διεθνών αγώνων που δεν είχε δει καμία από τις δύο εκδοχές, οι πιθανότητες του νέου ήταν καλύτερες για αποτέλεσμα, γκολ και BTTS· το πόσο συχνά βγήκε η πιο πιθανή του έκβαση δεν άλλαξε πέρα από τον θόρυβο. Οι πρώτες προβλέψεις εθνικών με αυτό εμφανίζονται μετά την αυριανή πρωινή ενημέρωση.",
    },
  },
  {
    id: "2026-09-13-correct-score-grid",
    date: "2026-09-13",
    tag: "fix",
    title: {
      en: "0-0 is no longer the 'most likely score' on one match in five",
      el: "Το 0-0 δεν είναι πια το «πιθανότερο σκορ» σε έναν στους πέντε αγώνες",
    },
    body: {
      en: "The score grid behind the analysis panel's correct scores, Over/Under 1.5 and 3.5 and combo markets had to hit four headline numbers exactly, and to hit them it piled the whole draw probability onto 0-0: on settled matches it called 0-0 the most likely score more than half the time, and where it gave 0-0 12% or more, it happened 7.7% of the time. It now keeps the goals line and the favourite's edge exact and treats the other two as targets it may miss slightly: 0-0 leads on 8 of about 2,000 upcoming fixtures, and its exact-score forecasts are measurably better. The headline 1×2, Over 2.5 and BTTS probabilities do not change.",
      el: "Ο πίνακας σκορ πίσω από τα πιθανά σκορ, τα Over/Under 1,5 και 3,5 και τις συνδυαστικές αγορές του πάνελ ανάλυσης έπρεπε να πετυχαίνει ακριβώς τέσσερα βασικά νούμερα, και για να τα πετύχει φόρτωνε όλη την πιθανότητα ισοπαλίας στο 0-0: σε αγώνες που κρίθηκαν έβγαζε το 0-0 πιθανότερο σκορ πάνω από τις μισές φορές, και όπου του έδινε 12% ή περισσότερο, βγήκε το 7,7% των φορών. Τώρα κρατά ακριβή τη γραμμή των γκολ και το προβάδισμα του φαβορί και αντιμετωπίζει τα άλλα δύο ως στόχους που μπορεί να χάσει ελάχιστα: το 0-0 προηγείται σε 8 από περίπου 2.000 επερχόμενους αγώνες, και οι προβλέψεις ακριβούς σκορ είναι μετρήσιμα καλύτερες. Οι βασικές πιθανότητες 1×2, Over 2,5 και BTTS δεν αλλάζουν.",
    },
  },
  {
    id: "2026-09-13-tables-and-projections",
    date: "2026-09-13",
    tag: "fix",
    title: {
      en: "League tables and season projections: three fixes",
      el: "Βαθμολογίες και προβολές σεζόν: τρεις διορθώσεις",
    },
    body: {
      en: "Leagues we added mid-season — the Nordic, Irish, Brazilian and other expansion leagues — had tables built only from the games since they were added: Norway showed 4–6 games per club with some twenty rounds played. Their full seasons are now loaded. Projections for leagues where the same clubs meet more than once at the same ground (Finland, Scotland, Ireland, Greece's play-offs) dropped those repeat meetings, and could call a season finished with a third still to play. And the European projection paired the top seed with the strongest play-off winner instead of the weakest; it now follows UEFA's bracket.",
      el: "Τα πρωταθλήματα που προσθέσαμε στη μέση της σεζόν — τα σκανδιναβικά, το ιρλανδικό, η Βραζιλία και τα υπόλοιπα της επέκτασης — είχαν βαθμολογίες μόνο από τους αγώνες μετά την προσθήκη τους: η Νορβηγία έδειχνε 4–6 αγώνες ανά ομάδα ενώ είχαν παιχτεί καμιά εικοσαριά αγωνιστικές. Φορτώθηκαν πλέον ολόκληρες οι σεζόν τους. Οι προβολές για πρωταθλήματα όπου οι ίδιες ομάδες συναντιούνται ξανά στην ίδια έδρα (Φινλανδία, Σκωτία, Ιρλανδία, πλέι-οφ της Ελλάδας) έχαναν αυτά τα επαναλαμβανόμενα ματς και μπορούσαν να δηλώσουν τη σεζόν τελειωμένη με το ένα τρίτο να απομένει. Και η προβολή των ευρωπαϊκών διοργανώσεων έβαζε τον πρώτο να παίζει με τον πιο δυνατό νικητή των πλέι-οφ αντί για τον πιο αδύναμο· τώρα ακολουθεί το ταμπλό της UEFA.",
    },
  },
  {
    id: "2026-09-13-one-sided-market",
    date: "2026-09-13",
    tag: "fix",
    title: {
      en: "A price quoted on one side only is no longer shown as a 100% market",
      el: "Μια τιμή που δίνεται μόνο στη μία πλευρά δεν εμφανίζεται πια ως αγορά 100%",
    },
    body: {
      en: "When a bookmaker quoted Over 2.5 but not Under — or a 1×2 without the draw — the comparison card divided the price by itself and read 'market: 100%'. The market's probability is now shown only when every side is quoted; otherwise you see the price alone.",
      el: "Όταν ένα γραφείο έδινε Over 2,5 αλλά όχι Under — ή 1×2 χωρίς ισοπαλία — η κάρτα σύγκρισης διαιρούσε την τιμή με τον εαυτό της και έγραφε «αγορά: 100%». Η πιθανότητα της αγοράς εμφανίζεται πλέον μόνο όταν δίνονται όλες οι πλευρές· αλλιώς βλέπετε μόνο την τιμή.",
    },
  },
  {
    id: "2026-09-13-list-page-recent",
    date: "2026-09-13",
    tag: "fix",
    title: {
      en: "The match list, the match page and /recent now agree",
      el: "Η λίστα αγώνων, η σελίδα του αγώνα και το /recent συμφωνούν πλέον",
    },
    body: {
      en: "A card could read high confidence beside 'unknown teams' while its match page said low; at exactly 50% the card said Over and the page Under; and the Medium+/High filter hid cards the site itself labelled medium. All of it now comes from one computation. /recent showed the first day of each page twice and, in a busy week, left out every match past the 200th — its accuracy summary was computed without them. Each page is now exactly one week, and complete.",
      el: "Μια κάρτα μπορούσε να γράφει υψηλή σιγουριά δίπλα στο «άγνωστες ομάδες» ενώ η σελίδα του αγώνα έλεγε χαμηλή· στο ακριβώς 50% η κάρτα έλεγε Over και η σελίδα Under· και το φίλτρο Medium+/High έκρυβε κάρτες που ο ίδιος ο ιστότοπος χαρακτήριζε μέτριες. Όλα βγαίνουν πλέον από έναν υπολογισμό. Το /recent έδειχνε την πρώτη μέρα κάθε σελίδας δύο φορές και, σε μια φορτωμένη εβδομάδα, άφηνε έξω κάθε αγώνα μετά τον 200ό — και η σύνοψη ακρίβειας υπολογιζόταν χωρίς αυτούς. Κάθε σελίδα είναι πλέον ακριβώς μία εβδομάδα, και πλήρης.",
    },
  },
  {
    id: "2026-09-13-stats-draw-cards",
    date: "2026-09-13",
    tag: "improvement",
    title: {
      en: "Draw figures on /stats are shown against their baselines",
      el: "Τα νούμερα ισοπαλίας στο /stats εμφανίζονται απέναντι στο σημείο αναφοράς τους",
    },
    body: {
      en: "Draw recall and precision were coloured on the scale used for overall accuracy, where they are red whatever happens. They are now neutral, each beside the number that gives it meaning: how many draws a random guess at our draw-call rate would catch, and how often any match ends level.",
      el: "Το recall και το precision ισοπαλίας χρωματίζονταν με την κλίμακα της συνολικής ακρίβειας, όπου είναι κόκκινα ό,τι κι αν συμβεί. Τώρα είναι ουδέτερα, το καθένα δίπλα στο νούμερο που του δίνει νόημα: πόσες ισοπαλίες θα έπιανε μια τυχαία πρόβλεψη με τη δική μας συχνότητα προβλέψεων ισοπαλίας, και πόσο συχνά λήγει ισόπαλος ένας αγώνας.",
    },
  },
  {
    id: "2026-09-07-impossible-certainty",
    date: "2026-09-07",
    tag: "fix",
    title: {
      en: "Four matches were shown as a 100% certainty. Nothing is.",
      el: "Τέσσερις αγώνες εμφανίζονταν ως 100% βεβαιότητα. Τίποτα δεν είναι.",
    },
    body: {
      en: "Bayern v Union Berlin, PSV v Heerenveen, Bayern v Leipzig and PSV v Willem II were all published with a 100% chance of over 2.5 goals — which also means a 0% chance of under, and that is not a claim anyone should make about football. The model never believed it: its own numbers for those four were 78–81%. The certainty was introduced by the step meant to make our probabilities honest, which had learned from a handful of high-scoring matches that everything above a certain point goes over. It had already been wrong once, on Club Brugge 1–0 Cercle Brugge. That step can no longer turn a small sample into a certainty, and nothing we publish can be a 0 or a 100 again.",
      el: "Μπάγερν–Ούνιον Βερολίνου, PSV–Χέρενφεν, Μπάγερν–Λειψία και PSV–Βίλεμ ΙΙ δημοσιεύτηκαν όλοι με 100% πιθανότητα για over 2,5 γκολ — που σημαίνει και 0% για under, κάτι που κανείς δεν πρέπει να ισχυρίζεται για ποδόσφαιρο. Το μοντέλο δεν το πίστεψε ποτέ: τα δικά του νούμερα για τους τέσσερις ήταν 78–81%. Τη βεβαιότητα την εισήγαγε το βήμα που υποτίθεται κάνει τις πιθανότητές μας τίμιες, το οποίο είχε μάθει από μια χούφτα αγώνες με πολλά γκολ ότι ό,τι περνά ένα σημείο πάει over. Είχε ήδη πέσει έξω μία φορά, στο Κλαμπ Μπριζ 1–0 Σερκλ Μπριζ. Αυτό το βήμα δεν μπορεί πια να κάνει μικρό δείγμα βεβαιότητα, και τίποτα από όσα δημοσιεύουμε δεν μπορεί να είναι 0 ή 100.",
    },
  },
  {
    id: "2026-09-07-goals-anchoring",
    date: "2026-09-07",
    tag: "improvement",
    title: {
      en: "Our goals and BTTS numbers were a coin flip, so we stopped pretending otherwise",
      el: "Τα νούμερά μας για γκολ και BTTS ήταν κορώνα-γράμματα, οπότε σταματήσαμε να προσποιούμαστε",
    },
    body: {
      en: "The 1×2 probabilities have been blended toward the bookmakers' line since 1 September, because measuring showed that is more accurate. Over/Under and BTTS were left as pure model output — and when we finally measured their ability to tell one match from another it came to 0.52 and 0.51, against a coin's 0.50. In plain terms they were well-calibrated numbers carrying almost no information about which match would go over. Both are now blended the same way and at the same weight, which lifts Over/Under's ranking ability from 0.52 to 0.58 on the matches we can check. The value gate still reads our own unblended numbers, so it measures a real disagreement rather than the market against itself.",
      el: "Οι πιθανότητες 1×2 αναμειγνύονται με τη γραμμή των γραφείων από την 1η Σεπτεμβρίου, επειδή η μέτρηση έδειξε ότι είναι πιο ακριβές. Το Over/Under και το BTTS έμεναν καθαρό μοντέλο — και όταν επιτέλους μετρήσαμε την ικανότητά τους να ξεχωρίζουν έναν αγώνα από τον άλλον, βγήκε 0,52 και 0,51 έναντι 0,50 του κέρματος. Απλά: ήταν καλά βαθμονομημένα νούμερα που δεν έλεγαν σχεδόν τίποτα για το ποιος αγώνας θα πάει over. Τώρα αναμειγνύονται και τα δύο με τον ίδιο τρόπο και το ίδιο βάρος, που ανεβάζει την ικανότητα κατάταξης του Over/Under από 0,52 σε 0,58 στους αγώνες που μπορούμε να ελέγξουμε. Το value gate εξακολουθεί να διαβάζει τα δικά μας ΜΗ ανάμεικτα νούμερα, ώστε να μετρά πραγματική διαφωνία και όχι την αγορά με τον εαυτό της.",
    },
  },
  {
    id: "2026-09-07-ticket-chance-is-the-markets",
    date: "2026-09-07",
    tag: "fix",
    title: {
      en: "The chance printed on a ticket implied a profit. There never was one.",
      el: "Η πιθανότητα πάνω στο δελτίο υπονοούσε κέρδος. Ποτέ δεν υπήρχε.",
    },
    body: {
      en: "Each slip showed a chance of landing next to a payout, and multiplying the two came to +64% on average — a claim that these are profitable bets. They are not, and this page has always said so in words: over 114 settled slips the record is −23%, which is almost exactly the bookmakers' compounded margin. The +64% came from multiplying our own probabilities, which run high on the legs a ranking picks, by real prices that carry a margin. The chance shown is now the bookmakers' own with their margin removed, so the two numbers multiply out to a negative — which is what a parlay is. Our model's figure sits underneath it, where nothing multiplies it.",
      el: "Κάθε δελτίο έδειχνε μια πιθανότητα επιτυχίας δίπλα στην απόδοση, και ο πολλαπλασιασμός τους έβγαζε +64% κατά μέσο όρο — δηλαδή ισχυρισμό ότι είναι κερδοφόρα. Δεν είναι, και η σελίδα πάντα το έλεγε με λόγια: σε 114 κριθέντα δελτία το ρεκόρ είναι −23%, σχεδόν ακριβώς η σύνθετη γκανιότα. Το +64% προέκυπτε πολλαπλασιάζοντας τις δικές μας πιθανότητες, που τρέχουν ψηλά στα σκέλη που διαλέγει μια κατάταξη, επί πραγματικές τιμές με περιθώριο μέσα. Η πιθανότητα που δείχνουμε τώρα είναι της ίδιας της αγοράς χωρίς το περιθώριό της, ώστε τα δύο νούμερα να βγάζουν αρνητικό — που είναι ό,τι είναι ένα παρολί. Το νούμερο του μοντέλου μας κάθεται από κάτω, όπου κανείς δεν το πολλαπλασιάζει.",
    },
  },
  {
    id: "2026-09-07-baselines-everywhere",
    date: "2026-09-07",
    tag: "improvement",
    title: {
      en: "Every accuracy figure now says what it beat",
      el: "Κάθε ποσοστό ακρίβειας λέει πλέον τι νίκησε",
    },
    body: {
      en: "A percentage on its own cannot be judged. 58% on over/under sounds better than 50% on the result, but 57% of these matches went over anyway — so the first is worth about one point and the second nearly six. The page was even colouring them the wrong way round, green for the weaker number and yellow for the stronger, because the threshold had been picked by hand and happened to land on the baseline. Each figure now carries the score the same matches would have produced with no model at all, and the colour follows the gap. Where that gap is negative it says so: our BTTS accuracy is half a point below simply saying both teams score, every time. The calibration charts now print how well each forecast separates matches, because a flat forecast can sit perfectly on the diagonal and still tell you nothing.",
      el: "Ένα ποσοστό μόνο του δεν κρίνεται. Το 58% στο over/under ακούγεται καλύτερο από το 50% στο αποτέλεσμα, αλλά το 57% αυτών των αγώνων πήγε over ούτως ή άλλως — άρα το πρώτο αξίζει περίπου μία μονάδα και το δεύτερο σχεδόν έξι. Η σελίδα μάλιστα τα χρωμάτιζε ανάποδα, πράσινο το ασθενέστερο και κίτρινο το ισχυρότερο, επειδή το κατώφλι είχε επιλεγεί στο χέρι και έτυχε να πέσει πάνω στη βάση. Κάθε νούμερο κουβαλάει τώρα τι θα έβγαζαν οι ίδιοι αγώνες χωρίς κανένα μοντέλο, και το χρώμα ακολουθεί τη διαφορά. Όπου η διαφορά είναι αρνητική, το λέει: η ακρίβειά μας στο BTTS είναι μισή μονάδα κάτω από το να λες απλώς ότι σκοράρουν και οι δύο, κάθε φορά. Τα διαγράμματα βαθμονόμησης δείχνουν πλέον και πόσο καλά ξεχωρίζει αγώνες η κάθε πρόβλεψη, γιατί μια επίπεδη πρόβλεψη μπορεί να κάθεται τέλεια πάνω στη διαγώνιο και να μη λέει τίποτα.",
    },
  },
  {
    id: "2026-09-07-national-rows-separated",
    date: "2026-09-07",
    tag: "fix",
    title: {
      en: "National-team matches were quietly inflating the club record",
      el: "Οι αγώνες εθνικών ομάδων φούσκωναν αθόρυβα το ρεκόρ των συλλόγων",
    },
    body: {
      en: "International fixtures are predicted by a separate model with a much better record, and their results were being pooled into the site-wide accuracy without saying so. That moved the headline from 48% to 50%. One row of the model-history table read \"68.8% over 80 matches\" — 79 of those 80 were internationals, and a reader would fairly have taken it for the club model. Every slice now states how many of its matches came from the national model. Separately, the international page was counting 2,632 matches as tracked predictions when 2,424 of them were scored after the fact, replaying the model over fixtures that were already history. Those are results, not predictions, and they no longer appear as a record.",
      el: "Οι διεθνείς αγώνες προβλέπονται από ξεχωριστό μοντέλο με πολύ καλύτερο ρεκόρ, και τα αποτελέσματά τους ανακατεύονταν στη γενική ακρίβεια της σελίδας χωρίς να το λέμε. Αυτό μετακινούσε το βασικό νούμερο από 48% σε 50%. Μια γραμμή στον πίνακα ιστορικού μοντέλου έγραφε «68,8% σε 80 αγώνες» — οι 79 από τους 80 ήταν διεθνείς, και δίκαια θα το εκλάμβανε κανείς ως το μοντέλο συλλόγων. Κάθε τμήμα δηλώνει πλέον πόσοι από τους αγώνες του προέρχονται από το εθνικό μοντέλο. Χωριστά, η διεθνής σελίδα μετρούσε 2.632 αγώνες ως παρακολουθούμενες προβλέψεις ενώ οι 2.424 βαθμολογήθηκαν εκ των υστέρων, ξαναπαίζοντας το μοντέλο πάνω σε αγώνες που ήταν ήδη ιστορία. Αυτά είναι αποτελέσματα, όχι προβλέψεις, και δεν εμφανίζονται πια ως ρεκόρ.",
    },
  },
  {
    id: "2026-09-03-european-ties-clubelo",
    date: "2026-09-03",
    tag: "fix",
    title: {
      en: "European ties were priced by the wrong yardstick",
      el: "Οι ευρωπαϊκές τιμολογούνταν με λάθος μέτρο",
    },
    body: {
      en: "Our internal strength rating is built from results inside each league, and leagues barely play one another — so on a Champions League or Europa League tie it was close to meaningless. Checked against 296 finished European matches, picking the side our own rating preferred was right 44.3% of the time, which is worse than simply backing the home team (50.7%). European ties now take the home/away balance from ClubElo, a rating maintained across every UEFA country on one scale, while keeping our own draw probability. On 373 matches held back from the fitting, accuracy went from 48.3% to 53.1% — in the Europa League, from 39.2% to 55.4%.",
      el: "Η εσωτερική μας βαθμολογία ισχύος χτίζεται από αποτελέσματα μέσα σε κάθε πρωτάθλημα, και τα πρωταθλήματα σχεδόν δεν παίζουν μεταξύ τους — οπότε σε έναν αγώνα Champions ή Europa League ήταν σχεδόν χωρίς νόημα. Σε 296 κριμένους ευρωπαϊκούς αγώνες, η ομάδα που προτιμούσε η δική μας βαθμολογία κέρδιζε στο 44,3%, δηλαδή χειρότερα από το να ποντάρεις απλώς στον γηπεδούχο (50,7%). Οι ευρωπαϊκές παίρνουν πλέον την ισορροπία γηπεδούχου/φιλοξενούμενου από το ClubElo, που συντηρείται σε μία κλίμακα για όλες τις χώρες της UEFA, κρατώντας τη δική μας πιθανότητα ισοπαλίας. Σε 373 αγώνες που κρατήθηκαν εκτός, η ακρίβεια πήγε από 48,3% σε 53,1% — στο Europa League από 39,2% σε 55,4%.",
    },
  },
  {
    id: "2026-09-03-draws-ceiling",
    date: "2026-09-03",
    tag: "improvement",
    title: {
      en: "What we found when we went looking for better draw predictions",
      el: "Τι βρήκαμε ψάχνοντας καλύτερες προβλέψεις ισοπαλίας",
    },
    body: {
      en: "Draws are the outcome everyone wants predicted and the one nobody predicts well — including the professional market. Across the matches we can check against a sharp bookmaker's own prices, their ability to rank draws scores 0.569 where a coin flip is 0.500; ours scores 0.565. We are at 97% of what the entire market manages, so there is very little room left, and we would rather say so than sell you a number we cannot back. We also switched off a dedicated draw model that had been running for months: measured properly, it ranked draws worse than the main model it was supposed to help.",
      el: "Οι ισοπαλίες είναι το αποτέλεσμα που όλοι θέλουν να προβλέπεται και κανείς δεν προβλέπει καλά — ούτε η επαγγελματική αγορά. Στους αγώνες που μπορούμε να ελέγξουμε απέναντι στις τιμές ενός sharp γραφείου, η ικανότητά τους να ξεχωρίζουν ισοπαλίες βαθμολογείται 0,569 εκεί που το κορώνα-γράμματα δίνει 0,500· η δική μας 0,565. Είμαστε στο 97% όσων καταφέρνει ολόκληρη η αγορά, άρα το περιθώριο είναι ελάχιστο — και προτιμάμε να το πούμε παρά να σου πουλήσουμε νούμερο που δεν στηρίζεται. Απενεργοποιήσαμε επίσης ένα ειδικό μοντέλο ισοπαλιών που έτρεχε μήνες: μετρημένο σωστά, ξεχώριζε τις ισοπαλίες χειρότερα από το κύριο μοντέλο που υποτίθεται βοηθούσε.",
    },
  },
  {
    id: "2026-09-03-ticket-legs-need-a-real-price",
    date: "2026-09-03",
    tag: "fix",
    title: {
      en: "Accumulator legs now need a real bookmaker price",
      el: "Τα σκέλη των δελτίων θέλουν πλέον πραγματική τιμή γραφείου",
    },
    body: {
      en: "When a fixture carries no bookmaker line, our percentages are entirely our own — fine for the leagues we know well, but the ready-made slips rank legs by probability, and the unpriced fixtures are systematically the obscure ones. Across 532 graded legs, the ones containing a draw on unpriced matches claimed 78% and landed 66%; the same bets on priced matches were accurate. Those legs are no longer offered. Goals and both-teams-to-score are unaffected — they hold up with or without a market.",
      el: "Όταν ένας αγώνας δεν έχει τιμή γραφείου, τα ποσοστά είναι αποκλειστικά δικά μας — εντάξει για τα πρωταθλήματα που ξέρουμε καλά, αλλά τα έτοιμα δελτία κατατάσσουν τα σκέλη με βάση την πιθανότητα, και οι αγώνες χωρίς τιμή είναι συστηματικά οι δυσεύρετοι. Σε 532 κριμένα σκέλη, όσα περιείχαν ισοπαλία σε αγώνες χωρίς τιμή δήλωναν 78% και έβγαιναν 66%· τα ίδια σε αγώνες με τιμή ήταν σωστά. Αυτά τα σκέλη δεν προσφέρονται πλέον. Γκολ και BTTS δεν επηρεάζονται — στέκουν με ή χωρίς αγορά.",
    },
  },
  {
    id: "2026-09-03-honest-accuracy-numbers",
    date: "2026-09-03",
    tag: "fix",
    title: {
      en: "Our published accuracy was measured against the wrong thing",
      el: "Η δημοσιευμένη μας ακρίβεια μετριόταν με λάθος μέτρο",
    },
    body: {
      en: "Our internal benchmark compared the model against bookmaker prices — except that on the 59% of matches with no price stored, it silently substituted our own estimate and compared us to ourselves. It reported that we beat the market. Restricted to matches carrying a genuine price, we do not: we are behind by a small but real margin. The published result accuracy is now 50.1% rather than the 53.1% shown before, which was hand-written a year ago and never updated. The model did not get worse; the measurement got honest.",
      el: "Ο εσωτερικός μας δείκτης σύγκρινε το μοντέλο με τις τιμές των γραφείων — μόνο που στο 59% των αγώνων χωρίς αποθηκευμένη τιμή έβαζε σιωπηλά τη δική μας εκτίμηση και μας σύγκρινε με τον εαυτό μας. Ανέφερε ότι κερδίζουμε την αγορά. Περιορισμένο στους αγώνες με πραγματική τιμή, δεν την κερδίζουμε: υστερούμε με μικρή αλλά υπαρκτή διαφορά. Η δημοσιευμένη ακρίβεια αποτελέσματος είναι πλέον 50,1% αντί για το 53,1% που έδειχνε πριν, γραμμένο στο χέρι πριν από έναν χρόνο και ποτέ ενημερωμένο. Το μοντέλο δεν χειροτέρεψε — η μέτρηση έγινε έντιμη.",
    },
  },
  {
    id: "2026-09-01-market-anchored-probabilities",
    date: "2026-09-01",
    tag: "improvement",
    title: {
      en: "More accurate probabilities — and we tested it",
      el: "Πιο ακριβείς πιθανότητες — και το μετρήσαμε",
    },
    body: {
      en: "The 1×2 percentages became a blend on this date: at the time, 43% our model and 57% the bookmakers' line with its margin stripped out. That weight has since moved — see the September 7th entry and the note at the top of the stats page for what is served now. We did not assume this was better — we replayed every match we had already been graded on and checked. Accuracy went from 51.7% to about 54%, and improved at every step toward the market, with no point where our model alone did better. Being partly the market, these numbers are not an edge over it and we do not present them as one. At the time, goals, both-teams-to-score and the long-term projections were untouched model output; goals and BTTS joined the blend on 7 September. The value gate has always run on our unblended model.",
      el: "Τα ποσοστά 1×2 έγιναν μίγμα αυτή την ημερομηνία: τότε, 43% το μοντέλο μας και 57% η γραμμή των γραφείων χωρίς το περιθώριό τους. Δεν το υποθέσαμε — ξανατρέξαμε κάθε αγώνα που είχε ήδη κριθεί και το ελέγξαμε. Η ακρίβεια πήγε από 51,7% σε περίπου 54%, και βελτιωνόταν σε κάθε βήμα προς την αγορά, χωρίς σημείο όπου το μοντέλο μόνο του τα πήγαινε καλύτερα. Επειδή είναι εν μέρει η ίδια η αγορά, δεν αποτελούν πλεονέκτημα απέναντί της και δεν τα παρουσιάζουμε έτσι. Τότε, γκολ, BTTS και μακροχρόνιες προβλέψεις ήταν καθαρή έξοδος του μοντέλου· τα γκολ και το BTTS μπήκαν στο μίγμα στις 7 Σεπτεμβρίου. Το value gate έτρεχε πάντα στο μη ανάμεικτο μοντέλο μας. Το βάρος έχει έκτοτε αλλάξει — δες την καταχώριση της 7ης Σεπτεμβρίου.",
    },
  },
  {
    id: "2026-09-01-european-projections-fixed",
    date: "2026-09-01",
    tag: "fix",
    title: {
      en: "European projections had the wrong teams on top",
      el: "Οι ευρωπαϊκές προβλέψεις είχαν λάθος ομάδες στην κορυφή",
    },
    body: {
      en: "The Europa League table put Levski Sofia and Omonia above Milan and Juventus, and the Conference League was led by Riga with Ajax, Monaco and Atalanta below. The cause: our team ratings are built from results within each league, and the leagues barely play each other — so a club that dominates a small league climbs against opponents whose ratings never had a reason to fall. European simulations now use a rating maintained across all 55 federations on one scale. Bournemouth, Leverkusen and Benfica now lead the Europa League; Brighton and Atalanta the Conference.",
      el: "Το Europa League έβαζε Λέφσκι Σόφιας και Ομόνοια πάνω από Μίλαν και Γιουβέντους, και το Conference League το οδηγούσε η Ρίγα με Άγιαξ, Μονακό και Αταλάντα από κάτω. Η αιτία: οι βαθμολογίες μας χτίζονται από αποτελέσματα μέσα σε κάθε πρωτάθλημα, και τα πρωταθλήματα σχεδόν δεν παίζουν μεταξύ τους — οπότε μια ομάδα που κυριαρχεί σε μικρό πρωτάθλημα ανεβαίνει κόντρα σε αντιπάλους που δεν είχαν ποτέ λόγο να πέσουν. Οι ευρωπαϊκές προσομοιώσεις χρησιμοποιούν πλέον βαθμολογία κοινή για όλες τις 55 ομοσπονδίες.",
    },
  },
  {
    id: "2026-09-01-longshot-rebuilt",
    date: "2026-09-01",
    tag: "improvement",
    title: {
      en: "The Long shot slip, rebuilt",
      el: "Το δελτίο Long shot, ξαναχτισμένο",
    },
    body: {
      en: "It had gone 0 for 13, and looking at every leg we have ever graded told us why: its selections were priced at a stated 53.7% and landed 25.8%. The problem was not long odds — it was the draw. Every market containing one is overstated by our model, while markets that exclude it, and the goals markets, hold up almost exactly. The slip now takes only markets whose stated probability has survived contact with results, and reaches its payout with five fairly-priced legs instead of four improbable ones. The number printed beside it is now the truth.",
      el: "Είχε πάει 0 στα 13, και κοιτώντας κάθε σκέλος που έχει κριθεί ποτέ φάνηκε γιατί: οι επιλογές του δίνονταν με δηλωμένο 53,7% και έβγαιναν 25,8%. Το πρόβλημα δεν ήταν οι μεγάλες αποδόσεις — ήταν η ισοπαλία. Κάθε αγορά που την περιέχει υπερεκτιμάται από το μοντέλο, ενώ όσες την αποκλείουν, και οι αγορές γκολ, στέκουν σχεδόν ακριβώς. Το δελτίο παίρνει πλέον μόνο αγορές που άντεξαν στα αποτελέσματα, και φτάνει στην απόδοσή του με πέντε δίκαια τιμολογημένα σκέλη αντί για τέσσερα απίθανα.",
    },
  },
  {
    id: "2026-08-19-odds-second-source",
    date: "2026-08-19",
    tag: "fix",
    title: {
      en: "Bookmaker odds are back on every card",
      el: "Οι αποδόσεις γραφείων επέστρεψαν σε κάθε κάρτα",
    },
    body: {
      en: "Our odds provider ran out of monthly credits on 13 August, and for eighteen days no upcoming match carried a bookmaker price — which also meant no ready-made slips. There is now a second, independent source that fills whatever the first one misses, so a single provider running dry can no longer take the feature down. Coverage is back above 90%.",
      el: "Ο πάροχος αποδόσεων εξάντλησε τα μηνιαία credits στις 13 Αυγούστου, και για δεκαοκτώ μέρες κανένας επερχόμενος αγώνας δεν είχε τιμή γραφείου — που σήμαινε και κανένα έτοιμο δελτίο. Υπάρχει πλέον δεύτερη, ανεξάρτητη πηγή που καλύπτει ό,τι λείπει από την πρώτη, οπότε ένας πάροχος που στερεύει δεν μπορεί πια να ρίξει τη λειτουργία. Η κάλυψη είναι ξανά πάνω από 90%.",
    },
  },
  {
    id: "2026-08-19-members-only",
    date: "2026-08-19",
    tag: "new",
    title: {
      en: "Slips and long-term projections need an account",
      el: "Δελτία και μακροχρόνιες προβλέψεις θέλουν λογαριασμό",
    },
    body: {
      en: "Today's accumulators and the full projection tables are now for signed-in members — free, as everything here is. What stays open to everyone: the title race three teams deep in every competition, live league tables, and the complete settled record of every slip we have ever cut, graded once all its matches finished. That record is the only evidence a visitor has that any of this works, so it will not go behind a login.",
      el: "Τα σημερινά δελτία και οι πλήρεις πίνακες προβλέψεων είναι πλέον για συνδεδεμένα μέλη — δωρεάν, όπως όλα εδώ. Ανοιχτά για όλους μένουν: η κούρσα τίτλου τρεις ομάδες βαθιά σε κάθε διοργάνωση, οι ζωντανές βαθμολογίες, και ολόκληρο το κριμένο ιστορικό κάθε δελτίου που κόψαμε ποτέ. Αυτό το ιστορικό είναι η μόνη απόδειξη που έχει ένας επισκέπτης ότι κάτι από αυτά δουλεύει, οπότε δεν πάει πίσω από login.",
    },
  },
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
