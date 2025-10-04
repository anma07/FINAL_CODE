import streamlit as st
import os
import json
import pandas as pd
import smtplib
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from dotenv import load_dotenv

# ---------------------- SETUP ----------------------
load_dotenv()
api_key = os.getenv("OPENAI_API_KEY")
email_user = os.getenv("EMAIL_USER")
email_pass = os.getenv("EMAIL_PASS")

if not api_key:
    st.error("❌ Missing OpenAI API Key. Please set OPENAI_API_KEY in .env or Streamlit Secrets.")
    st.stop()

from Agents.policy_agent import answer_policy_question
from Agents.guardrails import sanitize_input
from Agents import resume_screening_app  # ✅ Integrated

# ---------------------- CONSTANTS ----------------------
LOG_FILE = "onboarding_log.csv"

# ---------------------- HELPER: Log each onboarding ----------------------
def log_onboarding(name, email, date, time, status="Sent", mode="Manual"):
    log_entry = {
        "Name": name,
        "Email": email,
        "Date": date,
        "Time": time,
        "Status": status,
        "Mode": mode,
        "Timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    # Append to CSV
    if os.path.exists(LOG_FILE):
        df = pd.read_csv(LOG_FILE)
        df = pd.concat([df, pd.DataFrame([log_entry])], ignore_index=True)
    else:
        df = pd.DataFrame([log_entry])
    df.to_csv(LOG_FILE, index=False)

# ---------------------- UI CONFIG ----------------------
st.set_page_config(page_title="AI HR Orchestrator", page_icon="🤖", layout="centered")
st.title("🤖 Unified HR AI System")

if "mode" not in st.session_state:
    st.session_state.mode = None

# ---------------------- MAIN QUERY ----------------------
query = st.text_input("What would you like to do? (e.g. 'screen resumes', 'check policy', 'create onboarding plan')")

if st.button("Submit"):
    if not query.strip():
        st.warning("Please enter a valid query.")
        st.stop()

    try:
        sanitized_query = sanitize_input(query)
    except ValueError as e:
        st.error(str(e))
        st.stop()

    q = sanitized_query.lower()

    if any(k in q for k in ["resume", "screen", "candidate", "cv"]):
        st.session_state.mode = "resume"
    elif any(k in q for k in ["policy", "leave", "vacation", "rules", "payroll", "salary"]):
        st.session_state.mode = "policy"
    elif any(k in q for k in ["onboard", "joining", "orientation", "welcome"]):
        st.session_state.mode = "onboarding"
    else:
        st.session_state.mode = "unknown"

# ---------------------- DYNAMIC UI ----------------------
# 1️⃣ Resume Screening
if st.session_state.mode == "resume":
    st.subheader("📄 Resume Screening")
    resume_screening_app.run()  # integrated Streamlit resume module

# 2️⃣ Policy Question Answering
elif st.session_state.mode == "policy":
    st.subheader("📜 HR Policy Assistant")
    question = st.text_input("Ask your HR policy question:")
    if st.button("Get Policy Answer"):
        if question:
            with st.spinner("Checking policy..."):
                answer = answer_policy_question(question)
            st.success(answer)
        else:
            st.warning("Please enter a question.")

# 3️⃣ Onboarding Assistant (CSV / Manual)
elif st.session_state.mode == "onboarding":
    st.subheader("👋 Employee Onboarding Assistant")

    onboarding_mode = st.radio("Select Onboarding Mode:", ["📁 Bulk Upload (CSV/Excel)", "🧍 Manual Entry"])

    # ---------------------- BULK UPLOAD MODE ----------------------
    if onboarding_mode == "📁 Bulk Upload (CSV/Excel)":
        st.markdown("Upload your **resume screening results** (CSV or Excel). Candidates marked as 'PASS' will get onboarding invites.")
        uploaded_results = st.file_uploader("Upload Results File", type=["csv", "xlsx"])

        if uploaded_results:
            try:
                if uploaded_results.name.endswith(".csv"):
                    df = pd.read_csv(uploaded_results)
                else:
                    df = pd.read_excel(uploaded_results)

                if "verdict" not in df.columns:
                    st.error("❌ The uploaded file must include a 'verdict' column.")
                    st.stop()

                passed = df[df["verdict"].astype(str).str.upper() == "PASS"]

                if passed.empty:
                    st.warning("No passed candidates found in this file.")
                else:
                    st.success(f"✅ Found {len(passed)} passed candidates!")
                    st.dataframe(passed)

                    start_date = st.date_input("📅 Select Onboarding Date", datetime.now().date() + timedelta(days=2))
                    start_time = st.time_input("⏰ Select Onboarding Time", datetime.now().time().replace(hour=10, minute=0))

                    email_template = st.text_area(
                        "📧 Email Message Template",
                        value=(
                            "Dear {candidate},\n\n"
                            "Congratulations! You have been shortlisted for onboarding at our company.\n"
                            "Please join us on {date} at {time}.\n\n"
                            "Best Regards,\nHR Team"
                        ),
                        height=150,
                    )

                    if st.button("📨 Send Onboarding Emails"):
                        if not email_user or not email_pass:
                            st.error("Missing email credentials. Please set EMAIL_USER and EMAIL_PASS in your .env file.")
                        else:
                            with st.spinner("Sending onboarding invitations..."):
                                success, fail = [], []
                                for _, row in passed.iterrows():
                                    candidate = row["filename"].split(".")[0]
                                    to_email = (
                                        row["email"]
                                        if "email" in row
                                        else f"{candidate.lower().replace(' ', '')}@example.com"
                                    )

                                    msg = MIMEMultipart()
                                    msg["From"] = email_user
                                    msg["To"] = to_email
                                    msg["Subject"] = "🎉 Onboarding Invitation"

                                    formatted_msg = email_template.format(
                                        candidate=candidate,
                                        date=start_date.strftime("%B %d, %Y"),
                                        time=start_time.strftime("%I:%M %p"),
                                    )

                                    msg.attach(MIMEText(formatted_msg, "plain"))

                                    try:
                                        with smtplib.SMTP("smtp.gmail.com", 587) as server:
                                            server.starttls()
                                            server.login(email_user, email_pass)
                                            server.send_message(msg)
                                        success.append(candidate)
                                        log_onboarding(candidate, to_email, start_date, start_time, "Sent", "Bulk")
                                    except Exception as e:
                                        fail.append((candidate, str(e)))
                                        log_onboarding(candidate, to_email, start_date, start_time, f"Failed: {e}", "Bulk")

                                st.success(f"✅ Emails sent successfully to {len(success)} candidates.")
                                if fail:
                                    st.error(f"❌ Failed to send {len(fail)} emails.")
                                    st.json(fail)

            except Exception as e:
                st.error(f"Error processing file: {e}")

    # ---------------------- MANUAL ENTRY MODE ----------------------
    elif onboarding_mode == "🧍 Manual Entry":
        st.markdown("Enter onboarding details for a single candidate:")

        candidate_name = st.text_input("Candidate Name:")
        candidate_email = st.text_input("Candidate Email:")
        start_date = st.date_input("📅 Onboarding Date", datetime.now().date() + timedelta(days=2))
        start_time = st.time_input("⏰ Onboarding Time", datetime.now().time().replace(hour=10, minute=0))

        email_template = st.text_area(
            "📧 Email Message Template",
            value=(
                "Dear {candidate},\n\n"
                "Congratulations! You have been shortlisted for onboarding at our company.\n"
                "Please join us on {date} at {time}.\n\n"
                "Best Regards,\nHR Team"
            ),
            height=150,
        )

        if st.button("📨 Send Onboarding Email"):
            if not (candidate_name and candidate_email):
                st.warning("Please enter both candidate name and email.")
            elif not email_user or not email_pass:
                st.error("Missing email credentials. Please set EMAIL_USER and EMAIL_PASS in your .env file.")
            else:
                with st.spinner(f"Sending onboarding invite to {candidate_name}..."):
                    msg = MIMEMultipart()
                    msg["From"] = email_user
                    msg["To"] = candidate_email
                    msg["Subject"] = "🎉 Onboarding Invitation"

                    formatted_msg = email_template.format(
                        candidate=candidate_name,
                        date=start_date.strftime("%B %d, %Y"),
                        time=start_time.strftime("%I:%M %p"),
                    )

                    msg.attach(MIMEText(formatted_msg, "plain"))

                    try:
                        with smtplib.SMTP("smtp.gmail.com", 587) as server:
                            server.starttls()
                            server.login(email_user, email_pass)
                            server.send_message(msg)
                        st.success(f"✅ Email sent successfully to {candidate_name} ({candidate_email})!")
                        log_onboarding(candidate_name, candidate_email, start_date, start_time, "Sent", "Manual")
                    except Exception as e:
                        st.error(f"❌ Failed to send email: {e}")
                        log_onboarding(candidate_name, candidate_email, start_date, start_time, f"Failed: {e}", "Manual")

# 4️⃣ Unknown Queries
elif st.session_state.mode == "unknown":
    st.info("🤔 Try asking about resumes, policies, or onboarding.")
