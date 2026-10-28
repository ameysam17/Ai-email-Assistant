"""Streamlit user interface for the AI Email Assistant.

This file only draws the page and calls analyze_email().
It does not classify email text itself.
"""

import streamlit as st

from email_assistant.analyzer import MODE_FALLBACK, MODE_OLLAMA, analyze_email

st.set_page_config(page_title="AI Email Assistant", page_icon="✉️", layout="centered")

st.markdown(
    """
    <style>
      .hero-header {
        display: flex;
        align-items: center;
        flex-wrap: wrap;
        gap: 1rem;
        margin: 0.25rem 0 0.85rem 0;
        animation: hero-enter 0.8s ease-out;
      }
      .logo-mark {
        flex: 0 0 58px;
        width: 58px;
        height: 58px;
        animation: logo-float 3.2s ease-in-out infinite;
        filter: drop-shadow(0 0 12px rgba(56, 189, 248, 0.45));
      }
      .logo-spark {
        transform-origin: 44px 16px;
        animation: spark-pulse 1.8s ease-in-out infinite;
      }
      .hero-copy {
        min-width: 0;
        flex: 1;
      }
      .hero-copy h1 {
        margin: 0;
        font-size: clamp(1.7rem, 4.5vw, 2.2rem);
        line-height: 1.15;
        letter-spacing: -0.03em;
        background: linear-gradient(90deg, #f8fafc, #38bdf8, #a78bfa, #f8fafc);
        background-size: 280% 100%;
        -webkit-background-clip: text;
        background-clip: text;
        color: transparent;
        animation: title-shine 7s linear infinite;
      }
      .hero-copy p {
        margin: 0.35rem 0 0 0;
        color: #94a3b8;
        font-size: 1.02rem;
        line-height: 1.45;
      }
      .hero-underline {
        height: 3px;
        width: 100%;
        border-radius: 999px;
        margin: 0.15rem 0 1rem 0;
        background: linear-gradient(90deg, #38bdf8, #818cf8, transparent);
        background-size: 200% 100%;
        animation: bar-slide 4s ease-in-out infinite;
      }
      @keyframes hero-enter {
        from { opacity: 0; transform: translateY(10px); }
        to { opacity: 1; transform: translateY(0); }
      }
      @keyframes logo-float {
        0%, 100% { transform: translateY(0); }
        50% { transform: translateY(-6px); }
      }
      @keyframes spark-pulse {
        0%, 100% { opacity: 0.55; transform: scale(0.85); }
        50% { opacity: 1; transform: scale(1.15); }
      }
      @keyframes title-shine {
        0% { background-position: 0% 50%; }
        100% { background-position: 280% 50%; }
      }
      @keyframes bar-slide {
        0%, 100% { background-position: 0% 50%; opacity: 0.7; }
        50% { background-position: 100% 50%; opacity: 1; }
      }
      @media (prefers-reduced-motion: reduce) {
        .hero-header, .logo-mark, .logo-spark, .hero-copy h1, .hero-underline {
          animation: none;
        }
        .hero-copy h1 { color: #f8fafc; background: none; }
      }
    </style>
    <div class="hero-header">
      <svg class="logo-mark" viewBox="0 0 64 64" role="img" aria-label="AI Email Assistant logo">
        <defs>
          <linearGradient id="logo-bg" x1="8" y1="8" x2="56" y2="56" gradientUnits="userSpaceOnUse">
            <stop stop-color="#0ea5e9"/>
            <stop offset="1" stop-color="#6366f1"/>
          </linearGradient>
        </defs>
        <rect x="2" y="2" width="60" height="60" rx="16" fill="url(#logo-bg)"/>
        <path d="M14 22.5h36v21a3 3 0 0 1-3 3H17a3 3 0 0 1-3-3v-21z" fill="#ecfeff"/>
        <path d="M14 22.5 32 35l18-12.5" fill="none" stroke="#0369a1" stroke-width="2.4" stroke-linejoin="round"/>
        <g class="logo-spark" fill="#fef08a">
          <path d="M46 10l1.4 3.4L51 15l-3.6 1.6L46 20l-1.4-3.4L41 15l3.6-1.6z"/>
        </g>
      </svg>
      <div class="hero-copy">
        <h1 id="ai-email-assistant">AI Email Assistant</h1>
      </div>
    </div>
    <div class="hero-underline"></div>
    """,
    unsafe_allow_html=True,
)

st.write(
    "Paste an email and click Analyze Email. The app returns a category, "
    "a priority, a short summary, and a suggested reply for you to review. "
    "It does not send the message for you."
)

st.caption(
    "Privacy: the pasted text is processed by this app on your computer. "
    "If Ollama is running on this machine, it may be used. "
    "This app does not send email to an external AI provider, "
    "does not save the email to a database, and does not print it to logs."
)

pasted_email = st.text_area(
    "Paste an email",
    height=220,
    placeholder="Paste the full email here...",
    label_visibility="visible",
)

analyze_clicked = st.button("Analyze Email", type="primary")

if analyze_clicked:
    analysis_result = analyze_email(pasted_email)
    st.session_state["analysis_result"] = analysis_result
    st.session_state["reply_box_version"] = (
        st.session_state.get("reply_box_version", 0) + 1
    )

analysis_result = st.session_state.get("analysis_result")

if analysis_result is None:
    st.caption("Results will appear here after you click Analyze Email.")
elif not analysis_result.get("ok"):
    st.error(analysis_result.get("error", "Please paste an email before analyzing."))
else:
    st.subheader("Analysis mode")
    analysis_mode = analysis_result["mode"]
    st.write(analysis_mode)
    if analysis_mode == MODE_FALLBACK:
        st.info(
            "Ollama was not used. These results came from the built-in "
            "keyword fallback, not from AI."
        )
    elif analysis_mode == MODE_OLLAMA:
        st.success("These results came from local Ollama on this computer.")

    st.subheader("Category")
    st.write(analysis_result["category"])

    st.subheader("Priority")
    st.write(analysis_result["priority"])

    st.subheader("Summary")
    st.write(analysis_result["summary"])

    st.subheader("Suggested reply")
    st.caption("Select the text below and copy it (Ctrl+C or Cmd+C). This app does not send email.")
    st.text_area(
        "Suggested reply to copy",
        value=analysis_result["suggested_reply"],
        height=180,
        disabled=True,
        key=f"suggested_reply_box_{st.session_state.get('reply_box_version', 0)}",
    )
