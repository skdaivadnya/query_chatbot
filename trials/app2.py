import sqlite3
import json
import streamlit as st
import ollama

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
            curated_question TEXT,
            brief_summary TEXT,
            full_chat_history TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def save_lead(full_name, email, industry, curated_question, brief_summary, chat_history):
    conn = sqlite3.connect("consulting_intake.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO intake_leads (full_name, email, industry, curated_question, brief_summary, full_chat_history)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (full_name, email, industry, curated_question, json.dumps(chat_history)))
    conn.commit()
    conn.close()

init_db()

# -----------------------------------------------------------------------------
# Configuration & System Prompt
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Query Refinement & Intake Assistant", page_icon="🎯", layout="centered")

MODEL_NAME = "llama3.2"

def get_system_prompt(industry):
    return f"""
You are an expert requirement-refinement assistant specializing in {industry}. 
Your ONLY goal is to help the user translate their vague ideas, challenges, or goals into a precise, well-structured query suitable for expert review.

CRITICAL RULES:
1. STRICT SCOPE: ONLY discuss topics related to {industry}. Politely decline all other topics.
2. NO DIRECT ADVICE/SOLUTIONS: Do NOT solve their problem or provide strategic consulting advice. Your job is ONLY to gather context to frame the best possible question.
3. PROBE & SCOPE: Ask 1-2 probing questions at a time to uncover underlying details (e.g., specific bottlenecks, current setup, target metrics, constraints).
4. NO APPOINTMENT/CALL TALK: Do NOT mention scheduling calls, booking sessions, or setting up meetings. Focus entirely on refining their requirement into a clear brief.

Tone: Professional, inquisitive, analytical, and structured.
"""

# -----------------------------------------------------------------------------
# App State Handling
# -----------------------------------------------------------------------------
if "step" not in st.session_state:
    st.session_state.step = "onboarding"  # Options: onboarding, chatting, confirmation, complete

if "user_info" not in st.session_state:
    st.session_state.user_info = {}

# -----------------------------------------------------------------------------
# STEP 1: Client Front Plate
# -----------------------------------------------------------------------------
if st.session_state.step == "onboarding":
    st.title("🎯 Query Refinement Assistant")
    st.caption("Translate your business context and vague requirements into a structured expert query.")

    with st.form("client_info_form"):
        full_name = st.text_input("Full Name *")
        email = st.text_input("Email Address *")
        industry = st.text_input("Industry / Domain of Concern *", placeholder="e.g., Supply Chain & Logistics, Fintech, IT Infrastructure")
        submitted = st.form_submit_button("Start Refinement Session")

        if submitted:
            if not full_name or not email or not industry:
                st.error("Please fill in all fields before proceeding.")
            else:
                st.session_state.user_info = {
                    "name": full_name,
                    "email": email,
                    "industry": industry
                }
                st.session_state.messages = [
                    {"role": "system", "content": get_system_prompt(industry)},
                    {"role": "assistant", "content": f"Hello {full_name}! I'm here to help turn your vague thoughts or challenges regarding **{industry}** into a structured, highly targeted requirement.\n\nTo get started, tell me briefly what challenge or goal you are currently facing?"}
                ]
                st.session_state.step = "chatting"
                st.rerun()

# -----------------------------------------------------------------------------
# STEP 2: Scoping Chat
# -----------------------------------------------------------------------------
elif st.session_state.step == "chatting":
    st.title(f"💬 Refining Your Requirement ({st.session_state.user_info['industry']})")
    
    with st.sidebar:
        st.header("Session Details")
        st.write(f"**User:** {st.session_state.user_info['name']}")
        st.write(f"**Domain:** {st.session_state.user_info['industry']}")
        MODEL_NAME = st.text_input("Ollama Model", value=MODEL_NAME)
        st.divider()
        if st.button("Generate Final Structured Query"):
            st.session_state.step = "confirmation"
            st.rerun()

    for message in st.session_state.messages:
        if message["role"] != "system":
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

    if prompt := st.chat_input("Describe your requirement..."):
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

# -----------------------------------------------------------------------------
# STEP 3: Curate, Review & Confirm Refined Requirement
# -----------------------------------------------------------------------------
elif st.session_state.step == "confirmation":
    st.title("📋 Review Your Structured Requirement")
    st.write("We have synthesized your conversation into a structured query and brief.")

    if "curated_question" not in st.session_state:
        conversation_text = "\n".join([f"{m['role']}: {m['content']}" for m in st.session_state.messages if m["role"] != "system"])
        
        # Generation Prompt 1: Structured Final Question
        q_prompt = f"Based on the conversation below, translate the user's vague inputs into ONE highly specific, well-structured core question suitable for a senior expert:\n\n{conversation_text}"
        res_q = ollama.chat(model=MODEL_NAME, messages=[{"role": "user", "content": q_prompt}])
        st.session_state.curated_question = res_q['message']['content']

        # Generation Prompt 2: Context Brief
        b_prompt = f"Based on the conversation below, write a brief context summary explaining the user's background, current constraints, and goals leading to their question:\n\n{conversation_text}"
        res_b = ollama.chat(model=MODEL_NAME, messages=[{"role": "user", "content": b_prompt}])
        st.session_state.brief_summary = res_b['message']['content']

    st.subheader("1. Refined Core Question")
    st.caption("You can edit this question to make sure it precisely captures what you want to ask:")
    curated_q_input = st.text_area("Final Structured Question", value=st.session_state.curated_question, height=120)

    st.subheader("2. Context Brief")
    st.caption("Background summary generated from your conversation:")
    brief_input = st.text_area("Background & Context Brief", value=st.session_state.brief_summary, height=200)

    col1, col2 = st.columns([1, 1])
    with col1:
        if st.button("Confirm & Save Structured Query"):
            save_lead(
                full_name=st.session_state.user_info["name"],
                email=st.session_state.user_info["email"],
                industry=st.session_state.user_info["industry"],
                curated_question=curated_q_input,
                brief_summary=brief_input,
                chat_history=st.session_state.messages
            )
            st.session_state.step = "complete"
            st.rerun()

    with col2:
        if st.button("Back to Refinement Chat"):
            st.session_state.step = "chatting"
            st.rerun()

# -----------------------------------------------------------------------------
# STEP 4: Completion State
# -----------------------------------------------------------------------------
elif st.session_state.step == "complete":
    st.success("🎉 Your requirement has been successfully refined and saved!")
    st.write("### What Was Accomplished?")
    st.markdown("""
    * Your requirement has been logged and converted from raw ideas into a structured, actionable query.
    * The curated summary and background brief have been routed to the **Principal Consultant** for internal evaluation.
    """)
    
    if st.button("Start New Refinement Session"):
        st.session_state.clear()
        st.rerun()