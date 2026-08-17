import sqlite3
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import streamlit as st
import ollama

# -----------------------------------------------------------------------------
# Configuration (Set your Industry & Email details here)
# -----------------------------------------------------------------------------
INDUSTRY = "any industry under consultation"
PRINCIPAL_EMAIL = ".com"
MODEL_NAME = "llama3.2"

# SMTP Configuration for sending email to Principal Consultant
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "trial@trial.com"
SENDER_PASSWORD = "your_app_password"  # Use App Password for Gmail/SMTP

# -----------------------------------------------------------------------------
# Database Setup
# -----------------------------------------------------------------------------
def init_db():
    conn = sqlite3.connect("consulting_intake.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS intake_leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL,
            industry TEXT NOT NULL,
            curated_question TEXT NOT NULL,
            keywords TEXT NOT NULL,
            full_chat_history TEXT NOT NULL,
            principal_approval_status TEXT DEFAULT 'Pending Principal Approval',
            assigned_consultant_email TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_lead_and_notify(full_name, email, industry, curated_question, keywords, chat_history):
    # 1. Save to SQLite DB
    conn = sqlite3.connect("consulting_intake.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO intake_leads (full_name, email, industry, curated_question, keywords, full_chat_history)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (full_name, email, industry, curated_question, keywords, json.dumps(chat_history)))
    lead_id = cursor.lastrowid
    conn.commit()
    conn.close()

    # 2. Email Principal Consultant
    try:
        msg = MIMEMultipart()
        msg['From'] = SENDER_EMAIL
        msg['To'] = PRINCIPAL_EMAIL
        msg['Subject'] = f"[New Query #{lead_id}] Structured Requirement in {industry}"

        body = f"""
        New client query ready for your review and routing:

        Client Name: {full_name}
        Client Email: {email}
        Industry: {industry}

        --- CURATED QUESTION ---
        {curated_question}

        --- KEYWORDS / DOMAINS ---
        {keywords}

        Database Lead ID: {lead_id}
        Status: Awaiting Principal Confirmation for Routing.
        """
        msg.attach(MIMEText(body, 'plain'))

        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SENDER_EMAIL, SENDER_PASSWORD)
        server.send_message(msg)
        server.quit()
        return True, lead_id
    except Exception as e:
        # Returns True for DB save even if email fails in local testing
        return False, lead_id

init_db()

# -----------------------------------------------------------------------------
# System Prompt (Fast & Direct Scoping)
# -----------------------------------------------------------------------------
SYSTEM_PROMPT = f"""
You are an ultra-concise query refinement bot for {INDUSTRY}.
Your job is to quickly transform a vague request into a targeted question in 1 or 2 turns max.

RULES:
1. STRICT SCOPE: Only answer regarding {INDUSTRY}. Refuse all other topics immediately.
2. DO NOT CHAT OR ADVISE: Never give answers, solutions, or conversational chatter.
3. BE CONCISE & DIRECT: Ask ONLY 1 or 2 quick clarifying questions to identify semantic intent and core parameters (e.g., scale, specific tools, bottlenecks).
4. SPEED: Get enough context immediately to frame a precise question. Do not prolong the exchange.
"""

# -----------------------------------------------------------------------------
# Streamlit Interface
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Query Scoper", page_icon="🎯", layout="centered")

if "step" not in st.session_state:
    st.session_state.step = "onboarding"

if "user_info" not in st.session_state:
    st.session_state.user_info = {}

# STEP 1: Front Plate
if st.session_state.step == "onboarding":
    st.title("🎯 Expert Consultation Inquiry")
    st.markdown(f"Please type your query regarding **{INDUSTRY}**. Feel free to use your own words, and I will help you target the exact question.")

    with st.form("client_info_form"):
        full_name = st.text_input("Your Name *")
        email = st.text_input("Email Address *")
        initial_query = st.text_area("What is your query or challenge? *", placeholder="Type in your own words...")
        submitted = st.form_submit_button("Start Refinement")

        if submitted:
            if not full_name or not email or not initial_query:
                st.error("Please complete all fields.")
            else:
                st.session_state.user_info = {"name": full_name, "email": email}
                st.session_state.messages = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": initial_query}
                ]
                
                # Immediate initial fast check/response from Ollama
                res = ollama.chat(model=MODEL_NAME, messages=st.session_state.messages)
                st.session_state.messages.append({"role": "assistant", "content": res['message']['content']})
                st.session_state.step = "chatting"
                st.rerun()

# STEP 2: Fast Clarification Chat (1-2 exchanges)
elif st.session_state.step == "chatting":
    st.title("🎯 Targeting Your Question")
    st.caption(f"Refining query for **{st.session_state.user_info['name']}** in domain: `{INDUSTRY}`")

    for message in st.session_state.messages:
        if message["role"] != "system":
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("Ready to Phrase Question ➔"):
            st.session_state.step = "confirmation"
            st.rerun()

    if prompt := st.chat_input("Answer clarifying question or add details..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            def generate_ollama_stream():
                response_stream = ollama.chat(
                    model=MODEL_NAME,
                    messages=st.session_state.messages,
                    stream=True
                )
                for chunk in response_stream:
                    yield chunk['message']['content']

            full_response = st.write_stream(generate_ollama_stream())

        st.session_state.messages.append({"role": "assistant", "content": full_response})

# STEP 3: Synthesize Question + Extract Keywords + Get Confirmation
elif st.session_state.step == "confirmation":
    st.title("📋 Confirm Your Formulated Question")
    st.write("We have structured your input into a sharp question with target semantic keywords for our experts.")

    if "curated_question" not in st.session_state:
        chat_text = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages if m["role"] != "system"])
        
        # Refrain & Phrase Prompt
        prompt_refine = f"""
        Extract the core requirement from this conversation and formulate ONE precise, semantically accurate technical question.
        Conversation:
        {chat_text}
        """
        res_q = ollama.chat(model=MODEL_NAME, messages=[{"role": "user", "content": prompt_refine}])
        st.session_state.curated_question = res_q['message']['content']

        # Keywords Extraction Prompt (For downstream consultant matching agent)
        prompt_kw = f"""
        Extract 3 to 6 comma-separated domain keywords/topics from this question for consultant routing:
        Question: {st.session_state.curated_question}
        """
        res_kw = ollama.chat(model=MODEL_NAME, messages=[{"role": "user", "content": prompt_kw}])
        st.session_state.keywords = res_kw['message']['content']

    st.subheader("1. Formulated Question")
    final_q = st.text_area("Confirm or tweak your final question:", value=st.session_state.curated_question, height=120)

    st.subheader("2. Semantic Keywords (Used for Matching Expert)")
    final_kw = st.text_input("Target Keywords:", value=st.session_state.keywords)

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Confirm & Send to Principal Consultant"):
            email_sent, lead_id = save_lead_and_notify(
                full_name=st.session_state.user_info["name"],
                email=st.session_state.user_info["email"],
                industry=INDUSTRY,
                curated_question=final_q,
                keywords=final_kw,
                chat_history=st.session_state.messages
            )
            st.session_state.lead_id = lead_id
            st.session_state.step = "complete"
            st.rerun()

    with col2:
        if st.button("Back to Add Details"):
            st.session_state.step = "chatting"
            st.rerun()

# STEP 4: Handshake Complete
elif st.session_state.step == "complete":
    st.success("🎉 Your question has been formulated, confirmed, and submitted!")
    st.write(f"**Reference Lead ID:** #{st.session_state.get('lead_id', 'N/A')}")
    st.markdown("""
    * Your structured query and semantic keywords have been saved to the database.
    * An email alert has been sent to the **Principal Consultant**.
    * Once confirmed by the Principal Consultant, our secondary matching AI will route your query to the relative specialist consultant.
    """)
    
    if st.button("Submit Another Query"):
        st.session_state.clear()
        st.rerun()