"""
Agents/onboarding_agent.py

Usage:
- import functions in main.py and call `run_onboarding_ui()` from your Streamlit app,
  passing `st.session_state.get("results", [])` or letting the UI load session results itself.

Environment variables (recommended in .env or Streamlit Secrets):
- OPENAI_API_KEY
- SMTP_HOST
- SMTP_PORT
- SMTP_USER
- SMTP_PASS
- FROM_EMAIL

This module:
- finds PASS candidates in screening results
- generates a 7-day onboarding plan using OpenAI
- sends onboarding emails via SMTP
"""

import os
import re
import smtplib
import json
import traceback
from typing import List, Dict, Optional
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()
OPENAI_KEY = os.getenv("OPENAI_API_KEY")

# Initialize OpenAI client (if available)
client = None
if OPENAI_KEY:
    client = OpenAI(api_key=OPENAI_KEY)


# -------------------------
# Utilities
# -------------------------
def extract_email_from_text(text: str) -> Optional[str]:
    """Find first email in a blob of text, or None."""
    if not text:
        return None
    m = re.search(r"[a-zA-Z0-9.\-_+]+@[a-zA-Z0-9\-_]+\.[a-zA-Z0-9.\-_]+", text)
    return m.group(0) if m else None


def guess_email_from_filename(filename: str, domain: str = "example.com") -> str:
    """If no email found, guess one using filename before first dot."""
    username = str(filename).split("@")[0].split(".")[0]
    username = re.sub(r"[^a-zA-Z0-9\-_]", "", username).lower() or "candidate"
    return f"{username}@{domain}"


# -------------------------
# OpenAI onboarding plan
# -------------------------
def generate_onboarding_plan_text(name: str, role: str, start_date: Optional[str] = None) -> str:
    """
    Generate a 7-day onboarding plan for the candidate using OpenAI.
    If OpenAI not configured, returns a deterministic template.
    """
    header = f"Onboarding Plan for {name} — {role}\n"
    if client is None:
        # No OpenAI key — return template
        plan = header + "\n".join([
            "Welcome! (automatically generated template because OpenAI not configured)",
            "",
            "Day 1: Welcome, paperwork, access setup, team intro.",
            "Day 2: Product overview, onboarding docs, basic training.",
            "Day 3: Tools & environment setup, pairing with buddy.",
            "Day 4: Role-specific training sessions.",
            "Day 5: Meet cross-functional team, small task assigned.",
            "Day 6: Feedback session, Q&A with manager.",
            "Day 7: End-of-week review, next steps, goals.",
        ])
        if start_date:
            plan = f"{header}Start date (reported): {start_date}\n\n" + plan
        return plan

    prompt = f"""
You are an HR Onboarding Assistant. Create a concise 7-day onboarding plan for a new hire.

Name: {name}
Role: {role}
Start date (if known): {start_date or 'Not provided'}

Instructions:
- Provide a short welcome note.
- Provide Day 1 through Day 7 bullets with times or time windows where appropriate.
- Include tasks, meetings, documents to read, and one manager/buddy check-in per day.
- Keep it actionable and concise (use bullets).
Return plain text only.
"""
    try:
        # Attempt new-style responses API; fallback to chat if needed
        try:
            resp = client.responses.create(
                model="gpt-4o-mini",
                input=prompt,
                temperature=0.3
            )
            text = resp.output_text
        except TypeError:
            chat = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3
            )
            text = chat.choices[0].message.content
        return text.strip()
    except Exception as e:
        # On failure, return a safe template with an error note
        return (f"(Could not generate plan via OpenAI: {e})\n\n" +
                f"Day 1: Welcome, paperwork, access setup, team intro.\n"
                "Day 2: Product overview, onboarding docs, basic training.\n"
                "Day 3: Tools & environment setup, pairing with buddy.\n"
                "Day 4: Role-specific training sessions.\n"
                "Day 5: Meet cross-functional team, small task assigned.\n"
                "Day 6: Feedback session, Q&A with manager.\n"
                "Day 7: End-of-week review, next steps, goals.")


# -------------------------
# SMTP Email sender
# -------------------------
def send_email_smtp(to_email: str, subject: str, body_text: str,
                    smtp_host: Optional[str] = None, smtp_port: Optional[int] = None,
                    smtp_user: Optional[str] = None, smtp_pass: Optional[str] = None,
                    from_email: Optional[str] = None, use_tls: bool = True) -> Dict:
    """
    Send a plain-text onboarding email via SMTP.
    Pulls defaults from environment if arguments not provided.
    Returns dict with status and message.
    """

    smtp_host = smtp_host or os.getenv("SMTP_HOST")
    smtp_port = int(smtp_port or os.getenv("SMTP_PORT", 587))
    smtp_user = smtp_user or os.getenv("SMTP_USER")
    smtp_pass = smtp_pass or os.getenv("SMTP_PASS")
    from_email = from_email or os.getenv("FROM_EMAIL") or smtp_user

    if not smtp_host or not smtp_port:
        return {"ok": False, "error": "SMTP host/port not configured."}

    # Build message
    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body_text, "plain"))

    try:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=15)
        if use_tls:
            server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.sendmail(from_email, [to_email], msg.as_string())
        server.quit()
        return {"ok": True, "message": f"Email sent to {to_email}"}
    except Exception as e:
        return {"ok": False, "error": str(e), "trace": traceback.format_exc()}


# -------------------------
# Main onboarding function
# -------------------------
def onboard_selected_candidates(screening_results: List[Dict],
                                default_start_date: Optional[str] = None,
                                send_email: bool = True,
                                email_subject_template: Optional[str] = None,
                                email_body_template: Optional[str] = None) -> List[Dict]:
    """
    Given screening_results (list of dicts), find PASS candidates, generate onboarding plan,
    and optionally send emails. Returns list of status dicts for each candidate processed.
    Expected screening_result item keys: 'filename', 'verdict', optionally 'email' or 'contact'.
    """
    processed = []
    for item in screening_results:
        try:
            verdict = str(item.get("verdict", "")).upper()
            if verdict != "PASS":
                continue  # skip non-selected

            filename = item.get("filename", "unknown_file")
            name_guess = item.get("name") or filename.split(".")[0].replace("_", " ").title()
            role = item.get("role") or item.get("applied_role") or "the role"

            # find candidate email if present
            candidate_email = item.get("email") or item.get("contact") or extract_email_from_text(item.get("text", ""))
            if not candidate_email:
                candidate_email = guess_email_from_filename(filename)

            # build onboarding plan
            plan_text = generate_onboarding_plan_text(name_guess, role, default_start_date)

            # build email
            subject = email_subject_template or f"Onboarding: Welcome to {role} at Company"
            # email body: use template if provided; else compose
            if email_body_template:
                body = email_body_template.format(name=name_guess, role=role, start_date=default_start_date or "TBD", plan=plan_text)
            else:
                body = (f"Dear {name_guess},\n\n"
                        f"Congratulations — you have been selected for {role}.\n\n"
                        f"Reporting date/time: {default_start_date or 'Please confirm availability'}\n\n"
                        f"{plan_text}\n\n"
                        "Please reply to confirm your availability and if you have any questions.\n\n"
                        "Best,\nHR Team")

            send_result = None
            if send_email:
                send_result = send_email_smtp(candidate_email, subject, body)
                status = "email_sent" if send_result.get("ok") else "email_failed"
            else:
                status = "plan_generated"

            processed.append({
                "filename": filename,
                "name": name_guess,
                "email": candidate_email,
                "role": role,
                "plan": plan_text,
                "email_status": send_result,
                "status": status
            })

        except Exception as e:
            processed.append({
                "filename": item.get("filename", "unknown"),
                "status": "error",
                "error": str(e)
            })

    return processed


# -------------------------
# Streamlit UI wrapper
# -------------------------
def run_onboarding_ui(screening_results: Optional[List[Dict]] = None):
    """
    Streamlit-friendly UI. If screening_results is None, tries to read from st.session_state["results"].
    Call this inside main.py when onboarding mode is active.
    """
    import streamlit as st

    if screening_results is None:
        screening_results = st.session_state.get("results", [])

    st.subheader("👋 Onboarding Manager")

    if not screening_results:
        st.info("No screening results found in session. Upload or run resume screening first.")
        return

    # Show summary of PASS candidates
    pass_candidates = [r for r in screening_results if str(r.get("verdict","")).upper() == "PASS"]
    st.write(f"Found {len(pass_candidates)} candidate(s) with verdict=PASS.")

    if not pass_candidates:
        st.info("No candidates passed screening.")
        return

    # allow manager to set start date/time and email options
    default_start = st.text_input("Reporting date/time (e.g. 2025-10-15 09:30):", "")
    send_email = st.checkbox("Send onboarding emails via SMTP", value=True)
    subject_template = st.text_input("Email subject (optional):", "")
    body_template = st.text_area("Email body template (optional). Use {name}, {role}, {start_date}, {plan} placeholders.", height=120)

    # Show a table of PASS candidates and allow per-candidate override of email
    st.markdown("### Selected candidates")
    table_rows = []
    for c in pass_candidates:
        # show filename, allow editing email
        default_email = c.get("email") or extract_email_from_text(c.get("text","")) or guess_email_from_filename(c.get("filename",""))
        new_email = st.text_input(f"Email for {c.get('filename')}", value=default_email, key=f"email_{c.get('filename')}")
        c["email"] = new_email
        table_rows.append({"filename": c.get("filename"), "email": new_email, "verdict": c.get("verdict"), "weighted_average": c.get("weighted_average")})

    st.table(table_rows)

    if st.button("Generate Plans & (Optionally) Send Emails"):
        with st.spinner("Generating onboarding plans and sending emails..."):
            results = onboard_selected_candidates(pass_candidates, default_start_date=default_start,
                                                 send_email=send_email,
                                                 email_subject_template=subject_template if subject_template else None,
                                                 email_body_template=body_template if body_template else None)
        st.success("Done — see results below.")
        st.json(results)
