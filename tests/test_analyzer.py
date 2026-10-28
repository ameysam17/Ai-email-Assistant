"""Tests for email_assistant/analyzer.py.

How to run:
    pytest tests/test_analyzer.py -v

No live Ollama server is needed.  Every test that touches the network
mocks requests.post so the suite runs fully offline.

Reading guide
-------------
* Tests that call analyze_with_fallback() exercise only the built-in
  keyword logic — no HTTP at all.
* Tests that call analyze_email() go through the full function.  When
  Ollama must be involved we replace requests.post with a fake object
  so no real connection is made.
* Each test function has a short docstring that explains what it checks
  and why the assertion matters.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from email_assistant.analyzer import (
    CATEGORIES,
    MODE_FALLBACK,
    MODE_OLLAMA,
    PRIORITIES,
    analyze_email,
    analyze_with_fallback,
    extract_json_object,
    make_summary,
)

# ---------------------------------------------------------------------------
# Sample emails used across several tests.
# Keeping them as module-level constants avoids repetition and makes the
# intent of each test immediately obvious.
# ---------------------------------------------------------------------------

COMPLAINT_EMAIL = (
    "Hello, your product is completely broken and shows an error every time "
    "I try to log in.  I need help urgently or I will cancel my subscription."
)

MEETING_EMAIL = (
    "Hi team, can we schedule a meeting on Friday at 2 pm?  "
    "I will send a calendar invite once everyone confirms."
)

BILLING_EMAIL = (
    "Hi, I received an invoice this morning but it shows an extra charge "
    "that I did not authorise.  Please issue a refund at your earliest convenience."
)

SALES_EMAIL = (
    "We are interested in your product.  Could you send us a pricing quote "
    "and arrange a demo before we decide to purchase?"
)

OTHER_EMAIL = "Just writing to say hello and wish you a great weekend!"


# ---------------------------------------------------------------------------
# Helper — build the JSON body that a real Ollama server would return.
# This is the same shape the code reads at lines 140-144 of analyzer.py.
# ---------------------------------------------------------------------------

def _ollama_response(category, priority, summary, suggested_reply):
    """Return a MagicMock that looks like a successful requests.Response."""
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None   # no HTTP error
    mock_response.json.return_value = {
        "model": "llama3.2",
        "message": {
            "role": "assistant",
            "content": json.dumps({
                "category": category,
                "priority": priority,
                "summary": summary,
                "suggested_reply": suggested_reply,
            }),
        },
        "done": True,
    }
    return mock_response


# ===========================================================================
# 1. Empty / blank input is rejected before any analysis runs.
# ===========================================================================

def test_whitespace_only_input_is_rejected():
    """A string of spaces is not a real email.

    analyze_email() must catch it early and return ok=False with a
    human-readable error message.  The fallback and Ollama must never
    be called for blank input.
    """
    result = analyze_email("     ")

    assert result["ok"] is False, "ok should be False for blank input"
    assert "error" in result, "result must contain an 'error' key"
    assert "paste an email" in result["error"].lower()


def test_none_input_is_rejected():
    """Passing None instead of a string must not raise an exception.

    Streamlit can sometimes deliver None when a text area has never been
    touched.  The code converts email_text with str() so None is safe,
    but the result must still be ok=False.
    """
    result = analyze_email(None)

    assert result["ok"] is False
    assert "error" in result


def test_empty_string_is_rejected():
    """An empty string "" is another common 'nothing was typed' value."""
    result = analyze_email("")

    assert result["ok"] is False


# ===========================================================================
# 2. Customer complaint is classified by the deterministic fallback.
# ===========================================================================

def test_complaint_is_customer_support():
    """Words like 'broken', 'error', 'help', and 'unable' trigger Customer Support.

    analyze_with_fallback() never calls the network, so this test has no
    mocking and will always produce the same result regardless of whether
    Ollama is installed.
    """
    result = analyze_with_fallback(COMPLAINT_EMAIL)

    assert result["ok"] is True
    assert result["category"] == "Customer Support", (
        f"Expected 'Customer Support', got '{result['category']}'"
    )


def test_complaint_with_urgent_word_is_high_priority():
    """The word 'urgently' in the complaint email must raise priority to High.

    Any HIGH_PRIORITY_KEYWORDS match (urgent, asap, immediately, …)
    overrides the default Medium priority for Customer Support.
    """
    result = analyze_with_fallback(COMPLAINT_EMAIL)   # contains 'urgently'

    assert result["priority"] == "High", (
        f"Expected 'High' because the email contains 'urgently', "
        f"got '{result['priority']}'"
    )


def test_complaint_mode_label_is_fallback():
    """The mode field must say MODE_FALLBACK, not MODE_OLLAMA.

    This matters for the UI: if mode were wrong the app would show a
    success banner claiming AI was used when it was not.
    """
    result = analyze_with_fallback(COMPLAINT_EMAIL)

    assert result["mode"] == MODE_FALLBACK


# ===========================================================================
# 3. Ordinary meeting email is handled correctly by the fallback.
# ===========================================================================

def test_meeting_email_is_classified_as_meeting():
    """'schedule', 'meeting', and 'calendar' are all MEETING_KEYWORDS.

    The fallback must pick the Meeting category for this email.
    """
    result = analyze_with_fallback(MEETING_EMAIL)

    assert result["category"] == "Meeting"


def test_plain_meeting_email_is_low_priority():
    """A routine meeting request has no urgent keywords so priority is Low.

    High is reserved for urgency words; Medium is reserved for Billing and
    Customer Support; everything else is Low.
    """
    result = analyze_with_fallback(MEETING_EMAIL)

    assert result["priority"] == "Low"


def test_meeting_email_succeeds_end_to_end():
    """analyze_email() with a mocked Ollama that is unreachable still returns a result.

    We make requests.post raise requests.ConnectionError (the requests-library
    exception, not the built-in one) and verify the application silently switches
    to the fallback path and returns a valid, complete result rather than crashing.
    """
    import requests as req_lib

    with patch("email_assistant.analyzer.requests.post",
               side_effect=req_lib.ConnectionError("refused")):
        result = analyze_email(MEETING_EMAIL)

    assert result["ok"] is True
    assert result["category"] == "Meeting"
    assert result["mode"] == MODE_FALLBACK


# ===========================================================================
# 4. Every successful result contains the five required dictionary keys.
# ===========================================================================

REQUIRED_SUCCESS_KEYS = {"category", "priority", "summary", "suggested_reply", "mode"}


@pytest.mark.parametrize("email_text", [
    COMPLAINT_EMAIL,
    MEETING_EMAIL,
    BILLING_EMAIL,
    SALES_EMAIL,
    OTHER_EMAIL,
])
def test_result_always_has_required_keys(email_text):
    """Every email fed to analyze_with_fallback() must produce all five keys.

    Parametrize runs this single test once for each sample email so we
    check every category in one go without repeating code.
    The UI reads all five keys unconditionally, so a missing key would
    cause a KeyError at runtime.
    """
    result = analyze_with_fallback(email_text)

    missing = REQUIRED_SUCCESS_KEYS - result.keys()
    assert not missing, f"Result is missing keys: {missing}"


def test_category_value_is_from_allowed_set():
    """The category returned must be one of the five allowed labels.

    The UI renders the category verbatim; a typo or an invented label
    would confuse users.
    """
    result = analyze_with_fallback(BILLING_EMAIL)

    assert result["category"] in CATEGORIES


def test_priority_value_is_from_allowed_set():
    """The priority must be Low, Medium, or High — nothing else."""
    result = analyze_with_fallback(BILLING_EMAIL)

    assert result["priority"] in PRIORITIES


def test_summary_and_reply_are_non_empty_strings():
    """summary and suggested_reply must be non-blank strings.

    The Streamlit UI displays these directly; empty strings would show
    blank widgets with no explanation to the user.
    """
    result = analyze_with_fallback(MEETING_EMAIL)

    assert isinstance(result["summary"], str) and result["summary"].strip()
    assert isinstance(result["suggested_reply"], str) and result["suggested_reply"].strip()


# ===========================================================================
# 5. Invalid Ollama output is handled safely — fallback is used instead.
# ===========================================================================

@patch("email_assistant.analyzer.requests.post")
def test_plain_text_from_ollama_triggers_fallback(mock_post):
    """If Ollama replies with prose instead of JSON, fallback must be used.

    We make requests.post return a response whose content field is a
    plain English sentence.  parse_and_validate_json() cannot decode it,
    so try_analyze_with_ollama() returns None and analyze_email() falls
    back to keyword rules.
    """
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "message": {"role": "assistant", "content": "I cannot help with that."}
    }
    mock_post.return_value = mock_response

    result = analyze_email(MEETING_EMAIL)

    assert result["ok"] is True, "The app must not crash on bad Ollama output"
    assert result["mode"] == MODE_FALLBACK, (
        "Fallback must be used when Ollama output is not valid JSON"
    )


@patch("email_assistant.analyzer.requests.post")
def test_json_with_wrong_category_triggers_fallback(mock_post):
    """An out-of-vocabulary category value from Ollama must be rejected.

    parse_and_validate_json() checks that category is in CATEGORIES.
    If Ollama returns 'Complaint' (not an allowed label) the result
    is discarded and the fallback runs instead.
    """
    bad_content = json.dumps({
        "category": "Complaint",        # not in CATEGORIES
        "priority": "Low",
        "summary": "A complaint.",
        "suggested_reply": "We will look into it.",
    })
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "message": {"role": "assistant", "content": bad_content}
    }
    mock_post.return_value = mock_response

    result = analyze_email(COMPLAINT_EMAIL)

    assert result["ok"] is True
    assert result["mode"] == MODE_FALLBACK
    assert result["category"] in CATEGORIES   # value is valid even though Ollama was rejected


@patch("email_assistant.analyzer.requests.post")
def test_json_missing_required_key_triggers_fallback(mock_post):
    """JSON that is missing 'suggested_reply' must be rejected gracefully.

    parse_and_validate_json() requires all four keys.  A partial response
    is not good enough; the fallback must supply a complete result instead.
    """
    incomplete_content = json.dumps({
        "category": "Sales",
        "priority": "Low",
        "summary": "The customer wants a demo.",
        # 'suggested_reply' is deliberately missing
    })
    mock_response = MagicMock()
    mock_response.raise_for_status.return_value = None
    mock_response.json.return_value = {
        "message": {"role": "assistant", "content": incomplete_content}
    }
    mock_post.return_value = mock_response

    result = analyze_email(SALES_EMAIL)

    assert result["ok"] is True
    assert result["mode"] == MODE_FALLBACK


@patch("email_assistant.analyzer.requests.post")
def test_http_500_from_ollama_triggers_fallback(mock_post):
    """An HTTP 500 error from Ollama must not crash the app.

    raise_for_status() raises requests.HTTPError for 4xx/5xx responses.
    The except block in ask_ollama_chat() must catch it and return None
    so the fallback can run.
    """
    import requests as req_lib

    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = req_lib.HTTPError("500 Server Error")
    mock_post.return_value = mock_response

    result = analyze_email(BILLING_EMAIL)

    assert result["ok"] is True
    assert result["mode"] == MODE_FALLBACK


# ===========================================================================
# 6. An unavailable Ollama server does not crash the application.
# ===========================================================================

def test_connection_refused_uses_fallback():
    """If Ollama is not running, requests.post raises requests.ConnectionError.

    The except requests.ConnectionError block in ask_ollama_chat() catches
    this and returns None.  analyze_email() then calls analyze_with_fallback()
    so the user still gets a result.
    """
    import requests as req_lib

    with patch("email_assistant.analyzer.requests.post",
               side_effect=req_lib.ConnectionError("Connection refused")) as mock_post:
        result = analyze_email(COMPLAINT_EMAIL)

    assert result["ok"] is True, "App must not crash when Ollama is unavailable"
    assert result["mode"] == MODE_FALLBACK, "Fallback must be used when server is down"
    mock_post.assert_called_once()   # confirms the code did attempt the request


def test_timeout_uses_fallback():
    """A network timeout must be handled the same as a refused connection.

    requests.Timeout is caught separately in ask_ollama_chat() and causes
    the fallback to run.  We raise requests.Timeout (not the built-in
    TimeoutError) so it is caught by the right except clause.
    """
    import requests as req_lib

    with patch("email_assistant.analyzer.requests.post",
               side_effect=req_lib.Timeout("timed out")):
        result = analyze_email(MEETING_EMAIL)

    assert result["ok"] is True
    assert result["mode"] == MODE_FALLBACK


def test_fallback_result_is_valid_when_ollama_is_down():
    """When Ollama is down the fallback result must still be fully populated.

    This combines the connectivity check (case 6) with the shape check
    (case 4): an unavailable server must not cause missing keys.
    """
    import requests as req_lib

    with patch("email_assistant.analyzer.requests.post",
               side_effect=req_lib.ConnectionError):
        result = analyze_email(BILLING_EMAIL)

    missing = REQUIRED_SUCCESS_KEYS - result.keys()
    assert not missing, f"Keys missing when Ollama is down: {missing}"
    assert result["category"] in CATEGORIES
    assert result["priority"] in PRIORITIES


# ===========================================================================
# Bonus — valid Ollama output is used when the server is healthy.
# ===========================================================================

@patch("email_assistant.analyzer.requests.post")
def test_valid_ollama_response_is_used(mock_post):
    """When Ollama returns correct JSON the result must show MODE_OLLAMA.

    This is the happy-path test: a healthy server, valid JSON, all keys
    present and values within the allowed sets.  The result must come
    from Ollama (mode == MODE_OLLAMA), not the fallback.
    """
    mock_post.return_value = _ollama_response(
        category="Sales",
        priority="Low",
        summary="The customer asked for a pricing demo.",
        suggested_reply="Thank you for your interest. We will be in touch.",
    )

    result = analyze_email(SALES_EMAIL)

    assert result["ok"] is True
    assert result["mode"] == MODE_OLLAMA
    assert result["category"] == "Sales"
    assert result["summary"] == "The customer asked for a pricing demo."
    mock_post.assert_called_once()   # confirms exactly one HTTP call was made


# ===========================================================================
# D. Direct unit tests for make_summary() and extract_json_object().
#
# These helpers contain non-trivial logic.  Testing them directly makes it
# easy to spot a regression: a failing helper test points immediately at
# the broken function rather than somewhere deep in analyze_with_fallback().
# ===========================================================================

# ── make_summary() ──────────────────────────────────────────────────────────

def test_make_summary_returns_first_two_sentences():
    """summary uses the first two sentences and discards the rest.

    The function splits on sentence-ending punctuation (.!?) followed by
    whitespace.  A three-sentence email should produce a summary that
    contains only the first two.
    """
    email = "First sentence. Second sentence. Third sentence that must be cut."
    result = make_summary(email)

    assert "First sentence" in result
    assert "Second sentence" in result
    assert "Third sentence" not in result


def test_make_summary_truncates_at_280_characters():
    """A summary longer than 280 characters must be truncated to 277 + '...'.

    This protects the UI from rendering an enormous paragraph when the
    email has no sentence-ending punctuation at all.
    """
    # One very long sentence with no full stop — will not be split.
    long_email = "A " + ("word " * 100)   # well over 280 characters
    result = make_summary(long_email)

    assert len(result) <= 280
    assert result.endswith("..."), "Truncated summary must end with ellipsis"


def test_make_summary_handles_email_with_no_punctuation():
    """An email with no sentence-ending punctuation must still return something.

    The function treats the whole text as one sentence.  The result should
    be non-empty and equal to the original text (possibly truncated).
    """
    email = "No punctuation here just plain words strung together"
    result = make_summary(email)

    assert result  # non-empty
    assert "No punctuation" in result


def test_make_summary_collapses_extra_whitespace():
    """Leading, trailing, and internal whitespace must be normalised.

    The function joins split() tokens, which collapses tabs, newlines, and
    runs of spaces into single spaces.
    """
    email = "Hello   world.\n\nThis  is   a   test."
    result = make_summary(email)

    assert "  " not in result, "Double spaces must not appear in the summary"


# ── extract_json_object() ────────────────────────────────────────────────────

def test_extract_json_object_returns_bare_json_unchanged():
    """Plain JSON with no wrapping must pass through untouched.

    When Ollama returns well-formed JSON directly, extract_json_object()
    must return it as-is so json.loads() can parse it.
    """
    raw = '{"category": "Sales", "priority": "Low"}'
    result = extract_json_object(raw)

    assert result == raw


def test_extract_json_object_strips_markdown_code_fence():
    """JSON wrapped in ```json ... ``` must have the fences removed.

    Some models wrap their output in markdown code fences even when asked
    not to.  The function must strip them so json.loads() does not fail.
    """
    raw = '```json\n{"category": "Sales"}\n```'
    result = extract_json_object(raw)

    assert result.strip() == '{"category": "Sales"}'


def test_extract_json_object_extracts_braces_from_surrounding_text():
    """JSON embedded in prose must be extracted by finding { and }.

    A model occasionally adds a sentence before or after the JSON object.
    The function must find the outermost { ... } and return only that part.
    """
    raw = 'Here is the result: {"category": "Billing"} Hope that helps!'
    result = extract_json_object(raw)

    assert result == '{"category": "Billing"}'


def test_extract_json_object_returns_input_when_no_braces_found():
    """If there are no braces at all, the stripped input is returned as-is.

    parse_and_validate_json() will then fail to parse it and return None,
    which causes the fallback to run.  The function must not raise an
    exception in this situation.
    """
    raw = "This is plain text with no JSON at all."
    result = extract_json_object(raw)

    # No crash, and the text comes back (possibly stripped).
    assert isinstance(result, str)
    assert len(result) > 0
