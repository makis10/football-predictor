"""
Chat endpoint — conversational assistant for football predictions.

The chatbot:
  1. Fetches the next 7 days of upcoming matches + predictions from the DB
  2. Injects them as structured context into the system prompt (small enough to
     fit in one context window — typically 20-60 matches × ~50 tokens each)
  3. Sends the user message (+ conversation history) to Groq Llama-3.3-70B
  4. Returns the assistant reply

No vector search or tool-calling needed: the ML model already did the hard
work.  The LLM is purely a natural-language formatter + reasoner on top of
pre-computed numbers.
"""
from __future__ import annotations

import logging
import os
from datetime import date, timedelta
from typing import List, Optional

log = logging.getLogger("chat")

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.rate_limit import client_ip, rate_limit_check

# 30 messages/min per IP — generous for human use, blocks runaway scripts.
_CHAT_RATE_LIMIT  = 30
_CHAT_RATE_WINDOW = 60  # seconds

from backend.app.cache import CACHE_MISS, cache_get, cache_set
from backend.app.database import get_db
from backend.app.models.match import Match
from backend.app.models.prediction import Prediction

_CONTEXT_TTL = 1800  # 30 min — context doesn't change that fast

router = APIRouter(prefix="/chat", tags=["chat"])

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# llama-3.3-70b-versatile is deprecated on GroqCloud (decommission 2026-08-16);
# default to its replacement, overridable via the GROQ_MODEL env var.
GROQ_MODEL   = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# Per-attempt timeout and retry budget. (1 + LLM_MAX_RETRIES) * LLM_TIMEOUT_S
# must stay below the gateway timeout in front of this service — see the call
# site. Enforced by test_chat_timeout_budget.
# Groq's on-demand tier caps TOKENS PER MINUTE, not requests. At 8,000 TPM a
# single question used to cost ~7,200 — the 3-day card is 177 matches, and
# Greek tokenises badly — so the second question inside a minute came back
# 429 with a 53-second Retry-After, the SDK slept on it, and the proxy in
# front returned 504. Capping the context by CHARACTERS is what keeps a
# conversation possible at all; the window shrinks on a heavy weekend card and
# widens again on a thin midweek one.
CONTEXT_CHAR_BUDGET = 5000
LLM_TIMEOUT_S   = 12.0
# ZERO, deliberately. The SDK honours Retry-After on a 429, so a retry is not
# a fast second attempt — it is a 53-second sleep holding the connection open
# until the gateway gives up. Failing immediately with our own message beats a
# bare 504 the user cannot interpret.
LLM_MAX_RETRIES = 0
GATEWAY_TIMEOUT_S = 30.0

_SYSTEM_PROMPT = """\
Είσαι ένας έξυπνος βοηθός πρόβλεψης ποδοσφαιρικών αγώνων που βοηθά χρήστες \
να αναλύσουν επερχόμενα παιχνίδια με βάση ένα ML μοντέλο (XGBoost).

Κάθε πρόβλεψη περιλαμβάνει:
- Πιθανότητες αποτελέσματος: 1 (νίκη γηπεδούχου) / Χ (ισοπαλία) / 2 (νίκη φιλοξενούμενου)
- Πιθανότητα Over/Under 2.5 γκολ
- Επίπεδο εμπιστοσύνης: high (υψηλό), medium (μεσαίο), low (χαμηλό)

Κανόνες συμπεριφοράς:
- Απαντάς ΠΑΝΤΑ στα Ελληνικά εκτός αν ο χρήστης γράψει σε άλλη γλώσσα
- Για στοιχηματικές προτάσεις, προτείνεις ΜΟΝΟ αγώνες με high ή medium confidence
- Προσθέτεις ΠΑΝΤΑ την αποποίηση: «Οι προβλέψεις είναι μόνο για ψυχαγωγία, δεν αποτελούν οικονομική συμβουλή.»
- Είσαι συνοπτικός: 2-4 προτάσεις ανά αγώνα, εκτός αν ζητηθεί εκτεταμένη ανάλυση
- Όταν δεν υπάρχουν δεδομένα, το λες ειλικρινά

Τα δεδομένα των επερχόμενων αγώνων παρέχονται παρακάτω.
"""


# ── Schema ─────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str     # "user" or "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None   # last N turns for context


class ChatResponse(BaseModel):
    reply: str


# ── Context builder ────────────────────────────────────────────────────────────

_DAY_NAMES = {
    0: "Δευτέρα", 1: "Τρίτη", 2: "Τετάρτη", 3: "Πέμπτη",
    4: "Παρασκευή", 5: "Σάββατο", 6: "Κυριακή",
}


def _retry_after_seconds(exc: object) -> int | None:
    """Seconds to wait, if this failure was a rate limit. None otherwise.

    Groq's on-demand tier caps TOKENS per minute, so a busy minute produces a
    429 whose message carries the wait ("Please try again in 53.2575s"). The
    SDK exposes it inconsistently across versions, so read the text — it is a
    hint for a human, and being a few seconds out costs nothing.
    """
    import re

    if getattr(exc, "status_code", None) != 429 and "429" not in str(exc):
        return None
    m = re.search(r"try again in ([\d.]+)s", str(exc))
    if m:
        try:
            return max(1, round(float(m.group(1))))
        except ValueError:
            pass
    return 60


def _build_match_context(db: Session) -> str:
    """
    Return compact upcoming matches + predictions for the next 3 days — covering
    BOTH club leagues (Match/Prediction) AND national-team / tournament matches
    (NationalPrediction). During the off-season or a World Cup the club tables are
    empty, so without the national side the assistant wrongly says "no matches".
    Only matches with predictions are included. Cached in Redis 30 min.
    """
    # Keyed by DAY: the context states today's date, so a blob cached at 23:55
    # would tell the model the wrong day for its first five minutes of life.
    _key = f"chat:context:{date.today().isoformat()}"
    cached = cache_get(_key)
    if cached is not CACHE_MISS:
        return cached  # type: ignore[return-value]

    today   = date.today()
    horizon = today + timedelta(days=3)  # 3 days — was 7, cuts context ~60%

    # ── Club matches ──────────────────────────────────────────────────────────
    club_rows = db.execute(
        select(Match, Prediction)
        .join(Prediction, Prediction.match_id == Match.id)   # INNER — skip no-pred rows
        .where(Match.result.is_(None))
        # Skip no-history fixtures: their default-derived probs are identical and
        # meaningless — the LLM must not present them as recommendations.
        .where(Prediction.insufficient_data.is_(False))
        .where(Match.match_date >= today)
        .where(Match.match_date <= horizon)
        .order_by(Match.match_date.asc(), Match.id.asc())
    ).all()

    # ── National-team / tournament matches ────────────────────────────────────
    from backend.app.models.national_prediction import NationalPrediction
    nat_rows = db.execute(
        select(NationalPrediction)
        .where(NationalPrediction.actual_home_goals.is_(None))
        .where(NationalPrediction.match_date >= today.isoformat())
        .where(NationalPrediction.match_date <= horizon.isoformat())
        .order_by(NationalPrediction.match_date.asc(),
                  NationalPrediction.kickoff_utc.asc().nullslast())
    ).scalars().all()

    if not club_rows and not nat_rows:
        result = "Δεν υπάρχουν επερχόμενοι αγώνες με προβλέψεις τις επόμενες 3 ημέρες."
        cache_set(_key, result, _CONTEXT_TTL)
        return result

    lines: list[str] = []

    # The model has no clock. Without this the day headers below ("Πέμπτη
    # 20/08") are just labels and "σήμερα" is a guess — which is how the
    # assistant came to answer "δεν υπάρχουν διαθέσιμα δεδομένα για αγώνες που
    # θα διεξαχθούν σήμερα" while holding 13 KB of today's fixtures. Stated
    # once, at the top, in the same format as the headers so they line up.
    lines.append(
        f"ΣΗΜΕΡΑ ΕΙΝΑΙ {_DAY_NAMES[today.weekday()]} {today.strftime('%d/%m/%Y')}. "
        f"Ό,τι φέρει αυτή την ημερομηνία παίζεται σήμερα· οι υπόλοιπες "
        f"ημερομηνίες είναι μελλοντικές.\n")

    # Days are added whole, and only while the budget allows — a half-listed
    # day is worse than an absent one, because the model presents what it has
    # as the complete card and "the 3 best Over games today" then quietly means
    # "of the ones that fit". Today is always included, however big it is.
    budget = CONTEXT_CHAR_BUDGET
    days_shown: set = set()

    def _room_for(day, size: int) -> bool:
        nonlocal budget
        if day in days_shown:
            return True
        if days_shown and size > budget:
            return False
        days_shown.add(day)
        budget -= size
        return True

    club_by_day: dict = {}
    for match, pred in club_rows:
        club_by_day.setdefault(match.match_date, []).append((match, pred))

    if club_rows:
        lines.append("## Αγώνες Συλλόγων\n")
        current_date = None
        for match, pred in club_rows:
            if match.match_date != current_date:
                day_size = sum(len(m.home_team) + len(m.away_team) + 60
                               for m, _ in club_by_day[match.match_date])
                if not _room_for(match.match_date, day_size):
                    continue
                current_date = match.match_date
                lines.append(f"\n### {_DAY_NAMES[current_date.weekday()]} {current_date.strftime('%d/%m')}")
            elif match.match_date not in days_shown:
                continue
            hw   = round(pred.home_win_prob * 100)
            d    = round(pred.draw_prob * 100)
            aw   = round(pred.away_win_prob * 100)
            ov   = round(pred.over_2_5_prob * 100)
            btts = round(pred.btts_prob * 100) if pred.btts_prob is not None else "?"
            lines.append(
                f"[{match.league}] {match.home_team}-{match.away_team} "
                f"1:{hw} X:{d} 2:{aw} O:{ov} GG:{btts} conf:{pred.confidence} id:{match.id}"
            )

    if nat_rows:
        lines.append("\n## Εθνικές Ομάδες / Διοργανώσεις\n")
        nat_by_day: dict = {}
        for p in nat_rows:
            nat_by_day.setdefault(p.match_date, []).append(p)

        current_date = None
        for p in nat_rows:
            if p.match_date != current_date:
                # Same budget as the club card. During a tournament the
                # national list is the big one, and letting it through
                # unbounded would put the TPM cap back exactly where it was.
                day_size = sum(len(x.home_team) + len(x.away_team) + 60
                               for x in nat_by_day[p.match_date])
                if not _room_for(p.match_date, day_size):
                    continue
                current_date = p.match_date
                try:
                    dt = date.fromisoformat(p.match_date)
                    hdr = f"{_DAY_NAMES[dt.weekday()]} {dt.strftime('%d/%m')}"
                except Exception:
                    hdr = p.match_date
                lines.append(f"\n### {hdr}")
            elif p.match_date not in days_shown:
                continue
            hw   = round(p.home_win_prob * 100)
            d    = round(p.draw_prob * 100)
            aw   = round(p.away_win_prob * 100)
            ov   = round(p.over_2_5_prob * 100)
            btts = round(p.btts_prob * 100) if p.btts_prob is not None else "?"
            lines.append(
                f"[{p.tournament}] {p.home_team}-{p.away_team} "
                f"1:{hw} X:{d} 2:{aw} O:{ov} GG:{btts} conf:{p.confidence} id:nat{p.id}"
            )

    if days_shown:
        covered = ", ".join(d.strftime("%d/%m") for d in sorted(days_shown))
        lines.insert(1, f"Έχεις δεδομένα ΜΟΝΟ για: {covered}. Για άλλη ημερομηνία "
                        f"πες ότι δεν την έχεις ακόμα — μην απαντήσεις ποτέ ότι "
                        f"δεν υπάρχουν δεδομένα για ημερομηνία που υπάρχει "
                        f"παραπάνω.\n")

    result = "\n".join(lines)
    cache_set(_key, result, _CONTEXT_TTL)
    return result


# ── Endpoint ───────────────────────────────────────────────────────────────────

@router.post("", response_model=ChatResponse)
def chat(req: ChatRequest, request: Request, db: Session = Depends(get_db)):
    # Rate limit: 30 req/min per IP — prevents runaway Groq API spend.
    if not rate_limit_check(f"chat:{client_ip(request)}", _CHAT_RATE_LIMIT, _CHAT_RATE_WINDOW):
        raise HTTPException(status_code=429, detail="Too many requests. Try again in a minute.")

    if not GROQ_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="GROQ_API_KEY not configured — add it to your .env file.",
        )
    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message is empty.")

    # Build match context once per request (fast — DB query + string formatting)
    context = _build_match_context(db)

    # System prompt = instructions + live match data
    system_content = f"{_SYSTEM_PROMPT}\n\n{context}"

    # Assemble message list: system → history (last 10 turns) → new user message
    messages: list[dict] = [{"role": "system", "content": system_content}]

    if req.history:
        for turn in req.history[-10:]:
            if turn.role in ("user", "assistant") and turn.content.strip():
                messages.append({"role": turn.role, "content": turn.content})

    messages.append({"role": "user", "content": req.message.strip()})

    try:
        from groq import Groq
        # Total time must stay under the gateway in front of us, or the caller
        # sees a 504 and we never get to send our own error.
        #
        # It did: the SDK retries twice by default, so a slow Groq turned a
        # 25s timeout into 3 x 25 = 77s of held connection while the proxy gave
        # up at 30. Measured on 2026-08-20 — a good call answers in 1.4s, a bad
        # one used to hang for 77. One retry at 12s is 24s worst case, which
        # fits, and a genuine slow spell now surfaces as our own 503 with a
        # message rather than a bare gateway error.
        client  = Groq(api_key=GROQ_API_KEY, timeout=LLM_TIMEOUT_S,
                       max_retries=LLM_MAX_RETRIES)
        resp    = client.chat.completions.create(
            model            = GROQ_MODEL,
            # Reasoning tokens come out of max_tokens first — the same budget
            # that silently emptied the match narratives. See the fix in
            # odds_analysis_service._get_llm_analysis.
            reasoning_effort = "low",
            max_tokens       = 700,  # reserved output counts against the TPM cap
            temperature      = 0.4,
            messages         = messages,
        )
        reply = (resp.choices[0].message.content or "").strip()
        if not reply:
            raise RuntimeError(
                f"empty completion (finish_reason={resp.choices[0].finish_reason})")
    except Exception as e:
        log.error("Groq chat request failed: %s", e)
        # A token-per-minute cap is not an outage, and telling the reader
        # "service unavailable" for something that clears in seconds sends them
        # away for good. Groq reports how long to wait; pass it on.
        wait = _retry_after_seconds(e)
        if wait is not None:
            raise HTTPException(
                status_code=429,
                detail=f"Πολλές ερωτήσεις αυτή τη στιγμή. Δοκίμασε ξανά σε "
                       f"{wait} δευτερόλεπτα.")
        raise HTTPException(status_code=503, detail="LLM service temporarily unavailable.")

    return ChatResponse(reply=reply)
