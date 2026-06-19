# Football Predictor — Ανάλυση Αλγορίθμων

Έγγραφο για μαθηματική αναθεώρηση και πιθανή βελτίωση του συστήματος πρόβλεψης αποτελεσμάτων ποδοσφαίρου.

---

## 1. Επισκόπηση Συστήματος

Το σύστημα απαντά σε δύο ερωτήματα για κάθε αγώνα:

1. **Αποτέλεσμα**: P(Home Win), P(Draw), P(Away Win)
2. **Γκολ**: P(Over 2.5 goals)

Αρχιτεκτονική pipeline:

```
Ιστορικά δεδομένα (CSV)
        ↓
Feature Engineering (Elo, Pi-Ratings, Poisson, rolling stats, odds)
        ↓
XGBoost (δύο ξεχωριστά μοντέλα)
        ↓
Isotonic Calibration
        ↓
Injury Adjustment (rule-based, serve-time only)
        ↓
Τελικές πιθανότητες
```

---

## 2. Δεδομένα

### 2.1 Πηγές

| Πηγή | Περιεχόμενο | Διαθεσιμότητα |
|------|-------------|---------------|
| football-data.co.uk (CSV) | Αποτελέσματα, γκολ, shots, Pinnacle odds | 2005–σήμερα |
| Understat (CSV) | xG (expected goals) ανά αγώνα | 2014/15–σήμερα, top-5 leagues |
| API-Football | Fixtures, European competition schedule | Τρέχουσα σεζόν |
| The Odds API | Live Pinnacle odds πριν κάθε αγώνα | Real-time |

### 2.2 Leagues

EPL, LaLiga, Serie A, Bundesliga, Ligue 1, Greek Super League

### 2.3 Στήλες που χρησιμοποιούμε

Από κάθε αγώνα διαβάζουμε:
- `home_team`, `away_team`, `Date`, `League`
- `home_goals` (FTHG), `away_goals` (FTAG)
- `home_shots_ot` (HST), `away_shots_ot` (AST)
- Pinnacle 1×2 odds: `PSH`, `PSD`, `PSA`
- Pinnacle O/U 2.5 odds: `P>2.5`, `P<2.5`
- Referee, yellow/red cards (EPL μόνο)

### 2.4 Αποκλεισμός COVID σεζόν

Η σεζόν 2020/21 αποκλείεται πλήρως από training. Αγώνες χωρίς κοινό αλλοιώνουν το home advantage signal — ένα από τα ισχυρότερα patterns στα δεδομένα.

---

## 3. Feature Engineering

Όλα τα features υπολογίζονται σε **expanding window** — για κάθε αγώνα χρησιμοποιούμε μόνο δεδομένα αγώνων που έγιναν **πριν** από αυτόν. Zero data leakage.

### 3.1 Rolling Statistics (Sliding Windows)

Για κάθε ομάδα διατηρούμε `deque` με τις τελευταίες N=5 και N=10 αγώνες:

**Γκολ (venue-split και συνολικά):**
```
h_goals_scored_5   = mean(home_team last 5 goals scored, any venue)
h_home_scored_5    = mean(home_team last 5 goals scored AT HOME only)
a_away_conceded_5  = mean(away_team last 5 goals conceded AWAY only)
```

**Φόρμα (points):**
```
h_form_5  = mean(home_team last 5 match points: 3=win, 1=draw, 0=loss)
h_form_10 = mean(home_team last 10 match points)
```

**Expected goals (naive rolling average):**
```
expected_home_goals_5 = (h_goals_scored_5 + a_goals_conceded_5) / 2
```
Αυτό συνδυάζει την επιθετική δύναμη της γηπεδούχου με την αμυντική αδυναμία της φιλοξενούμενης.

**Over 2.5 rate, draw rate, shots on target, xG rolling:**
Αντίστοιχα για κάθε window.

### 3.2 Elo Rating

Κλασικό Elo σύστημα (Arpad Elo, 1960). Κάθε ομάδα έχει ένα rating, αρχικό = 1500.

**Αναμενόμενο αποτέλεσμα:**
```
E_home = 1 / (1 + 10^((R_away - R_home) / 400))
```

**Ενημέρωση μετά αγώνα:**
```
R_home_new = R_home + K × (S_home - E_home)
R_away_new = R_away + K × (S_away - E_away)
```
όπου K=32, S=1 (νίκη), S=0.5 (ισοπαλία), S=0 (ήττα).

**Αδυναμία Elo:** Χρησιμοποιεί μόνο win/draw/loss — αγνοεί το σκορ. 3-0 και 1-0 αντιμετωπίζονται ίδια.

**Features από Elo:**
- `h_elo`, `a_elo`: absolute ratings
- `elo_diff = h_elo - a_elo`
- `elo_home_win_prob = E_home` (η αναμενόμενη πιθανότητα)

### 3.3 Pi-Ratings (Constantinou & Fenton, 2012)

Πιο πλούσιο από Elo — χρησιμοποιεί **περιθώριο γκολ** και χωρίζει **home/away × attack/defense** σε 4 ξεχωριστά ratings per ομάδα.

**Αναμενόμενα γκολ:**
```
π_exp_home = π_BASE × 10^((h_att - a_def) / π_K)
π_exp_away = π_BASE × 10^((a_att - h_def) / π_K)
```

Παράμετροι:
- `π_BASE = 1.5` (baseline expected goals όταν ratings ίσα)
- `π_K = 3.0` (scaling — ευαισθησία σε διαφορές ratings)
- `π_C = 0.1` (learning rate — πόσο γρήγορα προσαρμόζεται)

**Ενημέρωση μετά αγώνα:**
```
err_h = actual_home_goals - π_exp_home
err_a = actual_away_goals - π_exp_away

pi_home_att[h] += π_C × err_h   # γηπεδούχος σκόραρε περισσότερο/λιγότερο
pi_away_def[a] -= π_C × err_h   # φιλοξ. άμυνα δέχτηκε περισσότερο/λιγότερο
pi_away_att[a] += π_C × err_a
pi_home_def[h] -= π_C × err_a
```

**Decay στα season boundaries:**
Στην αρχή κάθε σεζόν, όλα τα Pi-Ratings πολλαπλασιάζονται με `π_DECAY = 0.85`. Αυτό μοντελοποιεί αβεβαιότητα pre-season (μεταγραφές, νέοι παίκτες).

**Features από Pi-Ratings:**
- `h_pi_att`, `h_pi_def`, `a_pi_att`, `a_pi_def`: τα 4 ratings
- `pi_att_diff = h_att - a_def` (πλεονέκτημα επίθεσης)
- `pi_def_diff = a_att - h_def` (πλεονέκτημα επίθεσης φιλοξενούμενης)
- `pi_exp_home`, `pi_exp_away`: model-implied expected goals
- `pi_exp_diff = pi_exp_home - pi_exp_away` (home advantage σε γκολ)
- `pi_exp_total = pi_exp_home + pi_exp_away` (total — signal για Over/Under)

**Γιατί Pi + Elo μαζί;** Elo είναι cumulative cross-season. Pi-Ratings reset με decay. XGBoost βλέπει και τα δύο και μαθαίνει πότε να εμπιστεύεται το καθένα.

### 3.4 Poisson Model (Dixon & Coles, 1997)

Ανεξάρτητο από Pi-Ratings γιατί κάνει **season-specific normalization** — υπολογίζει strengths σχετικά με τον μέσο όρο της **τρέχουσας** σεζόν, και επαναρχικοποιείται κάθε σεζόν.

**Βασική θεωρία:**

Αν θεωρήσουμε τα γκολ Poisson-κατανεμημένα και ανεξάρτητα:
```
λ_home = home_attack × away_defense × avg_home_goals(league, season)
λ_away = away_attack × home_defense × avg_away_goals(league, season)

P(home scores i, away scores j) = Poisson(i; λ_home) × Poisson(j; λ_away)
```

**Attack/Defense strengths (season-specific):**
```
home_attack[team]  = (goals_scored_at_home / home_matches) / avg_home_goals_in_league
away_defense[team] = (goals_conceded_away / away_matches) / avg_away_goals_in_league
```

Τιμή > 1.0 σημαίνει πάνω από τον μέσο όρο. Neutral fallback = 1.0 για ομάδες χωρίς venue-specific data ακόμα.

**Πιθανότητες αποτελέσματος:**

Κτίζουμε 9×9 πίνακα σκορ (0-0 έως 8-8) και αθροίζουμε:
```python
for i in range(9):
    for j in range(9):
        p = Poisson(i; λ_h) × Poisson(j; λ_a)
        if i > j: p_home_win += p
        if i == j: p_draw += p
        if j > i: p_away_win += p
        if i+j > 2.5: p_over += p
        if i >= 1 and j >= 1: p_btts += p
```

**Constraint:** Ελάχιστα 5 αγώνες στη league/season πριν επιστρέψουν μη-NaN features.

**Features από Poisson:**
- `poisson_lambda_home`, `poisson_lambda_away`: οι λ τιμές (expected goals)
- `poisson_home_attack`, `poisson_away_defense`: intermediate strengths
- `poisson_home_win`, `poisson_draw`, `poisson_away_win`
- `poisson_over_2_5`, `poisson_btts`

**Γιατί Poisson ΚΑΙ Pi-Ratings;**
- Pi-Ratings: cumulative, cross-season, goal-margin based
- Poisson: season-specific normalization, proper probability distribution
- XGBoost μαθαίνει πότε κάθε μοντέλο είναι πιο αξιόπιστο

### 3.5 Market Odds (Pinnacle)

Τα Pinnacle odds θεωρούνται από τη βιβλιογραφία η καλύτερη "αγορά" για αποτελέσματα ποδοσφαίρου — χαμηλό vig, sharp money.

**Μετατροπή σε fair probabilities (αφαίρεση vig):**
```
inv_h = 1/PSH,  inv_d = 1/PSD,  inv_a = 1/PSA
total = inv_h + inv_d + inv_a   (>1 λόγω vig)

market_home_prob = inv_h / total
market_draw_prob = inv_d / total
market_away_prob = inv_a / total
```

Αντίστοιχα για O/U 2.5: `market_over_prob = (1/P>2.5) / ((1/P>2.5) + (1/P<2.5))`

**Διαθεσιμότητα:** ~2012/13+. Παλαιότερες σεζόν → NaN.

**Market dropout κατά training (35%):**
Τυχαία masked σε NaN για 35% των training rows. Εξαναγκάζει το μοντέλο να μάθει robust fallback (Poisson/xG/Pi-Ratings) αντί να εξαρτάται πάντα από odds. Κρίσιμο για GreekSL και αγώνες χωρίς live odds.

### 3.6 Expected Goals (xG) από Understat

xG = πιθανότητα να μπει γκολ από μια συγκεκριμένη ευκαιρία, βάσει θέσης, γωνίας, τύπου σουτ.

Rolling windows xG scored/conceded (5 και 10 αγώνες) per ομάδα. Διαθέσιμο top-5 leagues, 2014/15+. NaN για GreekSL — XGBoost handles natively.

### 3.7 Head-to-Head (H2H)

Τελευταίες 5 συναντήσεις μεταξύ των δύο ομάδων (ανεξάρτητα venue):
- `h2h_home_wins`, `h2h_away_wins`, `h2h_draws`
- `h2h_draw_rate` (fraction που τελείωσαν ισοπαλία)

### 3.8 Season Phase

Η ευρωπαϊκή σεζόν ξεκινά Αύγουστο:
```
week 0-11  → phase 1 (early season)
week 12-23 → phase 2 (mid season)
week 24+   → phase 3 (late season / run-in)
```

Features: `season_week`, `season_phase`, `days_since_season_start`.

### 3.9 European Fatigue

Για ομάδες που παίζουν σε Champions/Europa League:
- `h_eur_fatigue`: ημέρες από τελευταίο ευρωπαϊκό αγώνα (κανονικοποιημένο)
- `h_eur_away`: αν ο τελευταίος ευρωπαϊκός ήταν εκτός έδρας
- `h_eur_result`: αποτέλεσμα τελευταίου ευρωπαϊκού

### 3.10 Referee Features (EPL μόνο)

Για διαιτητές με ≥20 αγώνες στο training:
- `ref_home_win_rate`: ιστορικό % αγώνων όπου κερδίζει η γηπεδούχος
- `ref_draw_rate`: ιστορικό % ισοπαλιών
- `ref_cards_per_game`: μέσος αριθμός καρτών (κίτρινη=1, κόκκινη=2)

NaN για άλλα leagues και για άγνωστο διαιτητή — XGBoost handles natively.

---

## 4. Σύνολο Features

Συνολικά **~90 features** ανά αγώνα:

| Κατηγορία | Features | Count |
|-----------|----------|-------|
| Rolling goals (5+10, home/away split) | h_goals_scored_5, ... | 20 |
| Rolling form, goal diff, over25, draw rate | h_form_5, ... | 18 |
| Shots on target rolling | h_shots_ot_5, ... | 4 |
| Elo | h_elo, a_elo, elo_diff, elo_home_win_prob | 4 |
| Pi-Ratings | h_pi_att, h_pi_def, a_pi_att, a_pi_def + derived | 10 |
| xG rolling (5+10) | h_xg_scored_5, ... | 8 |
| Poisson | lambda_h/a, attack/defense, probs, btts | 9 |
| Market odds | home/draw/away/over fair probs | 4 |
| H2H | wins, draws, draw_rate | 4 |
| Season phase | week, phase, days | 3 |
| League one-hot | EPL, LaLiga, SerieA, Bundesliga, Ligue1, GreekSL | 6 |
| European fatigue | fatigue, away, result × 2 teams | 6 |
| Referee | home_win_rate, draw_rate, cards/game | 3 |

---

## 5. XGBoost — Τα Δύο Μοντέλα

Χρησιμοποιούμε **XGBoost** (gradient boosted decision trees) γιατί:
- Φυσικά χειρίζεται NaN τιμές (tree_method='hist')
- Εξαιρετικό σε tabular data με mixed features
- Ordered boosting μειώνει overfitting σε sports data

### 5.1 Result Model (3-class)

**Target:** 0=HomeWin, 1=Draw, 2=AwayWin

```python
XGBClassifier(
    n_estimators=800,      # αριθμός δέντρων
    max_depth=4,           # βάθος κάθε δέντρου
    learning_rate=0.03,    # shrinkage
    subsample=0.75,        # row sampling per tree
    colsample_bytree=0.7,  # feature sampling per tree
    min_child_weight=5,    # min samples per leaf
    gamma=0.1,             # min loss reduction για split
    reg_alpha=0.1,         # L1 regularization
    reg_lambda=1.5,        # L2 regularization
    eval_metric="mlogloss",
)
```

**Sample weights** = class_balance_weight × time_decay_weight

Class balance: draws (~25% base rate) παίρνουν ~1.8× βάρος.

Time decay (3-year half-life):
```
w(t) = exp(-k × days_ago)   όπου k = ln(2) / (365×3)
```
Αγώνας 3 χρόνια πριν → 0.5× βάρος. Αγώνας 2015/16 (~10 χρόνια) → ~0.1× βάρος.

### 5.2 Goals Model (Binary: Over/Under 2.5)

**Target:** 1=Over 2.5 goals, 0=Under

```python
XGBClassifier(
    n_estimators=1000,
    max_depth=5,
    learning_rate=0.02,
    subsample=0.8,
    colsample_bytree=0.75,
    colsample_bylevel=0.75,  # additional column sampling per level
    min_child_weight=3,
    gamma=0.05,
    reg_alpha=0.05,
    reg_lambda=1.0,
    eval_metric="logloss",
)
```

Ίδια sample weights με result model.

---

## 6. Train/Calibration/Test Split

Χρησιμοποιούμε **temporal 3-way split** (όχι random) — αναγκαίο για time-series με data leakage risk:

```
Αγώνες < 2023-07-01  → XGBoost training set  (~80%)
Αγώνες 2023/24 season → Calibration set       (~10%)
Αγώνες 2024/25 season → Test set              (~10%)
```

Calibration set **δεν βλέπει** το XGBoost κατά training. Test set **δεν βλέπει** ούτε calibration.

---

## 7. Isotonic Calibration

XGBoost δίνει raw probabilities που μπορεί να είναι over/under-confident. Isotonic regression (monotone non-parametric) διορθώνει αυτό.

**Result model (3-class, One-vs-Rest):**

Τρεις ξεχωριστοί isotonic regressors, ένας ανά class:
```
iso_HomeWin.fit(raw_p_HomeWin, y_binary_HomeWin)  # y=1 αν πραγματικά HomeWin
iso_Draw.fit(raw_p_Draw, y_binary_Draw)
iso_AwayWin.fit(raw_p_AwayWin, y_binary_AwayWin)
```

Μετά calibration, renormalize ώστε να αθροίζουν σε 1:
```
cal_h, cal_d, cal_a = iso_H(raw_h), iso_D(raw_d), iso_A(raw_a)
total = cal_h + cal_d + cal_a
final = (cal_h/total, cal_d/total, cal_a/total)
```

**Goals model (binary):**

Ένας global isotonic regressor + per-league regressors (για leagues με ≥80 calibration rows). Inference χρησιμοποιεί per-league αν υπάρχει, αλλιώς global.

**Reference:** Zadrozny & Elkan (2002) — "Transforming classifier scores into accurate multiclass probability estimates."

---

## 8. Draw Specialist Classifier (currently disabled)

Ξεχωριστό binary XGBoost: target = (result == Draw). Trained σε subset features σχετικά με draws (draw rates, H2H draws, elo_diff, pi_exp_total, market_draw_prob).

Blend formula:
```
final_draw = α × draw_clf_prob + (1-α) × result_draw_prob
```

Αυτή τη στιγμή **disabled** γιατί το scale_pos_weight=3.0 προκαλεί inflation των draw probs (~37% vs market-implied ~25%). Ο calibrated result model είναι πιο accurate.

---

## 9. Injury Adjustment (Rule-Based, Serve-Time)

Εφαρμόζεται **μετά** calibration, μόνο για το API response (όχι stored στη DB).

**Γιατί rule-based και όχι ML feature:**
- Injuries γνωστές μόνο ~6-12h πριν αγώνα — ανέφικτο να train
- Bookmaker odds (top features) ήδη pricing injuries — αποφεύγουμε double-counting
- Conservative nudges: `_NUDGE_PER_UNIT = 0.033` (3.3% per "key player equivalent")
- Max impact: 13% total per team

**Position-based impact:**
- Attacker out → fewer home goals → over_2_5 decreases
- Defender/GK out → opponent scores more → over_2_5 increases

**Diminishing returns:** 1st injured player → 100% weight, 2nd → 65%, 3rd+ → 40%

---

## 10. Πλήρης Ροή Prediction

```
1. Φόρτωση ιστορικών δεδομένων (όλοι αγώνες πριν το match_date)

2. Υπολογισμός team snapshot:
   - Elo ratings για κάθε ομάδα
   - Pi-Ratings (4 per ομάδα)
   - Poisson state (season-specific)
   - Rolling deques (goals, form, xG, shots)
   - H2H history
   - Referee stats

3. Υπολογισμός features για τον αγώνα (χωρίς ενημέρωση snapshot)

4. XGBoost Result Model → [P(H), P(D), P(A)] raw

5. XGBoost Goals Model → P(Over) raw

6. Isotonic Calibration → calibrated probabilities

7. (Optional) Injury Adjustment → final probabilities

8. Confidence: "high" αν max(H,D,A) ≥ 0.55 ΚΑΙ |over_prob - 0.5| ≥ 0.05
```

---

## 11. Ανοιχτά Ερωτήματα / Πιθανές Βελτιώσεις

Σημεία όπου μαθηματική γνώμη θα ήταν χρήσιμη:

### 11.1 Independence assumption στο Poisson

Το Dixon-Coles model υποθέτει ανεξαρτησία home/away goals. Ωστόσο υπάρχει γνωστή correlation — low-scoring matches (0-0, 1-1) εμφανίζονται πιο συχνά από ό,τι προβλέπει το independent Poisson model. Ο αρχικός Dixon-Coles paper προτείνει correction factor `ρ` για σκορ {0-0, 1-0, 0-1, 1-1}. Δεν το έχουμε υλοποιήσει.

**Ερώτηση:** Αξίζει το overhead; Πόσο σημαντική είναι η correlation στα leagues μας;

### 11.2 Pi-Rating παράμετροι

Οι παράμετροι `π_C=0.1`, `π_K=3.0`, `π_BASE=1.5`, `π_DECAY=0.85` ορίστηκαν από το paper. Δεν τις έχουμε optimized για τα συγκεκριμένα leagues μας.

**Ερώτηση:** Τι method θα χρησιμοποιούσατε για να βρείτε βέλτιστες παραμέτρους; Bayesian optimization; Grid search με CV;

### 11.3 Temporal split vs walk-forward validation

Χρησιμοποιούμε single temporal split. Walk-forward cross-validation (train on seasons 1-N, test on N+1, repeat) θα έδινε πιο robust εκτίμηση απόδοσης.

### 11.4 Calibration stability

Calibration γίνεται σε μία μόνο σεζόν (2023/24). Αν η κατανομή αποτελεσμάτων αλλάξει (π.χ. αύξηση γκολ), calibrators γίνονται stale.

### 11.5 Poisson vs Negative Binomial

Football goals έχουν μερικές φορές overdispersion (variance > mean). Negative Binomial distribution generalizes Poisson για αυτή την περίπτωση. Αξίζει comparison;

### 11.6 Feature importance και multicollinearity

Πολλά features είναι correlated (π.χ. `pi_exp_home` και `expected_home_goals_10` και `poisson_lambda_home` μετράνε παρόμοια πράγματα). XGBoost handles αυτό αλλά ίσως υπάρχει redundancy.

---

## 12. Αρχεία Κώδικα

| Αρχείο | Περιεχόμενο |
|--------|-------------|
| `backend/app/ml/features.py` | Elo, Pi-Ratings, rolling stats, feature engineering |
| `backend/app/ml/poisson.py` | Poisson model, Dixon-Coles λ computation, probability matrix |
| `backend/app/ml/train.py` | XGBoost training, time splits, sample weights |
| `backend/app/ml/calibration.py` | Isotonic calibration, per-league goals calibration |
| `backend/app/ml/predict.py` | Inference pipeline, confidence scoring |
| `backend/app/ml/draw_classifier.py` | Draw specialist (disabled) |
| `backend/app/ml/injury_adjustment.py` | Rule-based injury nudges |
| `backend/app/ml/pipeline.py` | Orchestration: download → train |
| `scripts/compute_predictions.py` | Batch predictions για upcoming fixtures |
