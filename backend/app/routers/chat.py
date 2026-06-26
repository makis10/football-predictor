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
GROQ_MODEL   = "llama-3.3-70b-versatile"

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


def _build_match_context(db: Session) -> str:
    """
    Return compact upcoming matches + predictions for the next 3 days — covering
    BOTH club leagues (Match/Prediction) AND national-team / tournament matches
    (NationalPrediction). During the off-season or a World Cup the club tables are
    empty, so without the national side the assistant wrongly says "no matches".
    Only matches with predictions are included. Cached in Redis 30 min.
    """
    cached = cache_get("chat:context")
    if cached is not CACHE_MISS:
        return cached  # type: ignore[return-value]

    today   = date.today()
    horizon = today + timedelta(days=3)  # 3 days — was 7, cuts context ~60%

    # ── Club matches ──────────────────────────────────────────────────────────
    club_rows = db.execute(
        select(Match, Prediction)
        .join(Prediction, Prediction.match_id == Match.id)   # INNER — skip no-pred rows
        .where(Match.result.is_(None))
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
        cache_set("chat:context", result, _CONTEXT_TTL)
        return result

    lines: list[str] = []

    if club_rows:
        lines.append("## Αγώνες Συλλόγων (επόμενες 3 ημέρες)\n")
        current_date = None
        for match, pred in club_rows:
            if match.match_date != current_date:
                current_date = match.match_date
                lines.append(f"\n### {_DAY_NAMES[current_date.weekday()]} {current_date.strftime('%d/%m')}")
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
        lines.append("\n## Εθνικές Ομάδες / Διοργανώσεις (επόμενες 3 ημέρες)\n")
        current_date = None
        for p in nat_rows:
            if p.match_date != current_date:
                current_date = p.match_date
                try:
                    dt = date.fromisoformat(p.match_date)
                    hdr = f"{_DAY_NAMES[dt.weekday()]} {dt.strftime('%d/%m')}"
                except Exception:
                    hdr = p.match_date
                lines.append(f"\n### {hdr}")
            hw   = round(p.home_win_prob * 100)
            d    = round(p.draw_prob * 100)
            aw   = round(p.away_win_prob * 100)
            ov   = round(p.over_2_5_prob * 100)
            btts = round(p.btts_prob * 100) if p.btts_prob is not None else "?"
            lines.append(
                f"[{p.tournament}] {p.home_team}-{p.away_team} "
                f"1:{hw} X:{d} 2:{aw} O:{ov} GG:{btts} conf:{p.confidence} id:nat{p.id}"
            )

    result = "\n".join(lines)
    cache_set("chat:context", result, _CONTEXT_TTL)
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
        client  = Groq(api_key=GROQ_API_KEY, timeout=25.0)
        resp    = client.chat.completions.create(
            model       = GROQ_MODEL,
            max_tokens  = 450,  # was 700 — chat answers don't need essays
            temperature = 0.4,
            messages    = messages,
        )
        reply = resp.choices[0].message.content.strip()
    except Exception as e:
        log.error("Groq chat request failed: %s", e)
        raise HTTPException(status_code=503, detail="LLM service temporarily unavailable.")

    return ChatResponse(reply=reply)
