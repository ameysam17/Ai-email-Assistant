"""Classify a pasted email, summarize it, and suggest a reply.

This module tries local Ollama first. If Ollama is down or returns
invalid JSON, it uses a keyword fallback. The pasted email stays in
memory only. It is never written to a file or printed.
"""

import json
import os
import re

import requests

# Labels the app is allowed to return.
CATEGORIES = (
    "Customer Support",
    "Sales",
    "Billing",
    "Meeting",
    "Other",
)
PRIORITIES = ("Low", "Medium", "High")

# Honest labels so the UI never claims AI was used for a fallback result.
MODE_OLLAMA = "Local AI (Ollama)"
MODE_FALLBACK = "Fallback mode"

# Change the model without editing code: set OLLAMA_MODEL in your environment.
OLLAMA_CHAT_URL = os.environ.get(
    "OLLAMA_CHAT_URL",
    "http://localhost:11434/api/chat",
)
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2")
REQUEST_TIMEOUT_SECONDS = 30

BILLING_KEYWORDS = ("invoice", "payment", "refund", "billing", "charge", "receipt")
MEETING_KEYWORDS = ("meeting", "calendar", "schedule", "appointment", "zoom", "call")
SALES_KEYWORDS = ("quote", "pricing", "demo", "purchase", "discount", "proposal", "buy")
SUPPORT_KEYWORDS = (
    "error",
    "broken",
    "help",
    "not working",
    "issue",
    "bug",
    "unable",
    "support",
)
HIGH_PRIORITY_KEYWORDS = ("urgent", "asap", "immediately", "emergency", "critical")


def analyze_email(email_text):
    """Validate input, try Ollama, then fall back if needed.

    Returns a dictionary. On success it includes category, priority,
    summary, suggested_reply, and mode. On empty input it includes
    an error message instead.
    """
    if email_text is None or not str(email_text).strip():
        return {
            "ok": False,
            "error": "Please paste an email before analyzing.",
        }

    cleaned_email = str(email_text).strip()

    ollama_result = try_analyze_with_ollama(cleaned_email)
    if ollama_result is not None:
        return ollama_result

    return analyze_with_fallback(cleaned_email)


def analyze_with_fallback(email_text):
    """Keyword rules that work offline, with no model installed."""
    lower_email = email_text.lower()
    category = choose_category(lower_email)
    priority = choose_priority(lower_email, category)
    summary = make_summary(email_text)
    suggested_reply = make_suggested_reply(category, priority)
    return {
        "ok": True,
        "category": category,
        "priority": priority,
        "summary": summary,
        "suggested_reply": suggested_reply,
        "mode": MODE_FALLBACK,
    }


def try_analyze_with_ollama(email_text):
    """Call Ollama's chat API. Return a result dict, or None to use fallback."""
    message_text = ask_ollama_chat(email_text)
    if message_text is None:
        return None

    parsed_fields = parse_and_validate_json(message_text)
    if parsed_fields is None:
        return None

    return {
        "ok": True,
        "category": parsed_fields["category"],
        "priority": parsed_fields["priority"],
        "summary": parsed_fields["summary"],
        "suggested_reply": parsed_fields["suggested_reply"],
        "mode": MODE_OLLAMA,
    }


def ask_ollama_chat(email_text):
    """POST a chat request to local Ollama. Return assistant text, or None.

    requests.post sends an HTTP POST. Connection errors, timeouts, and
    bad HTTP status codes are caught so the fallback can run instead.
    """
    request_body = {
        "model": OLLAMA_MODEL,
        "messages": [
            {
                "role": "system",
                "content": build_system_instructions(),
            },
            {
                "role": "user",
                "content": email_text,
            },
        ],
        "stream": False,
        "format": "json",
    }

    try:
        response = requests.post(
            OLLAMA_CHAT_URL,
            json=request_body,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
        message = payload.get("message") or {}
        content = message.get("content")
        if not content:
            return None
        return content
    except requests.Timeout:
        return None
    except requests.ConnectionError:
        return None
    except (requests.RequestException, ValueError, TypeError, AttributeError):
        return None


def build_system_instructions():
    """Tell the model exactly which JSON keys and labels to use."""
    allowed_categories = ", ".join(CATEGORIES)
    allowed_priorities = ", ".join(PRIORITIES)
    return (
        "You classify emails. Reply with JSON only, no extra text. "
        "Use these keys: category, priority, summary, suggested_reply. "
        f"category must be one of: {allowed_categories}. "
        f"priority must be one of: {allowed_priorities}. "
        "summary must be one or two short sentences. "
        "suggested_reply must be a polite draft a human can review."
    )


def parse_and_validate_json(raw_text):
    """Turn model text into a dict. Reject missing or invalid fields."""
    if not raw_text or not str(raw_text).strip():
        return None

    json_text = extract_json_object(str(raw_text))
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    required_fields = ("category", "priority", "summary", "suggested_reply")
    for field_name in required_fields:
        if field_name not in data:
            return None

    category = data["category"]
    priority = data["priority"]
    summary = data["summary"]
    suggested_reply = data["suggested_reply"]

    if category not in CATEGORIES:
        return None
    if priority not in PRIORITIES:
        return None
    if not isinstance(summary, str) or not summary.strip():
        return None
    if not isinstance(suggested_reply, str) or not suggested_reply.strip():
        return None

    return {
        "category": category,
        "priority": priority,
        "summary": summary.strip(),
        "suggested_reply": suggested_reply.strip(),
    }


def extract_json_object(raw_text):
    """Keep the {...} part if the model wrapped JSON in extra text."""
    stripped = raw_text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped)
        stripped = re.sub(r"```$", "", stripped).strip()

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return stripped
    return stripped[start : end + 1]


def choose_category(lower_email):
    """First matching keyword group wins. Otherwise Other."""
    if contains_any_keyword(lower_email, BILLING_KEYWORDS):
        return "Billing"
    if contains_any_keyword(lower_email, MEETING_KEYWORDS):
        return "Meeting"
    if contains_any_keyword(lower_email, SALES_KEYWORDS):
        return "Sales"
    if contains_any_keyword(lower_email, SUPPORT_KEYWORDS):
        return "Customer Support"
    return "Other"


def choose_priority(lower_email, category):
    """Urgent words are High. Support and Billing are Medium. Else Low."""
    if contains_any_keyword(lower_email, HIGH_PRIORITY_KEYWORDS):
        return "High"
    if category in ("Customer Support", "Billing"):
        return "Medium"
    return "Low"


def contains_any_keyword(lower_email, keywords):
    """Return True if any keyword appears in the lowercase email."""
    for keyword in keywords:
        if keyword in lower_email:
            return True
    return False


def make_summary(email_text, max_sentences=2, max_characters=280):
    """Use the first one or two sentences as a short summary."""
    cleaned_text = " ".join(email_text.split())
    sentences = re.split(r"(?<=[.!?])\s+", cleaned_text)
    short_sentences = [sentence for sentence in sentences if sentence][:max_sentences]
    summary = " ".join(short_sentences).strip()
    if len(summary) > max_characters:
        summary = summary[: max_characters - 3].rstrip() + "..."
    return summary


def make_suggested_reply(category, priority):
    """A clearly labelled template. A human should review it before sending."""
    return (
        "[Template reply — Fallback mode] "
        f"Thank you for your email. I have noted this as a {category} "
        f"message with {priority} priority. Please review this draft "
        "before sending. A teammate will follow up with the next step."
    )
