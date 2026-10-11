import os
import re
import streamlit as st
import pandas as pd
import chromadb
from sentence_transformers import SentenceTransformer
from pypdf import PdfReader

# Optional import for Ollama; fallback handles missing local instances
try:
    import ollama
except ImportError:
    ollama = None

# -----------------------------------------------------------------------------
# Configuration & Page Setup
# -----------------------------------------------------------------------------
st.set_page_config(page_title="Faroce AI - Expert Matchmaking Portal", page_icon="⚡", layout="wide")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_PDF_PATH = os.path.join(BASE_DIR, "ann_exp_data.pdf")
MAX_QUESTIONS = 5
OLLAMA_MODEL = "llama3.2"

# -----------------------------------------------------------------------------
# Load Intelligence & Compliance Datasets
# -----------------------------------------------------------------------------
@st.cache_data
def load_datasets():
    # Load Industrial Intelligence Database
    intel_path = os.path.join(BASE_DIR, "Faroce_Industrial_Components_Industry_Intelligence_Database_v1.xlsx")
    df_intel = pd.read_excel(intel_path, sheet_name="Industrial Components") if os.path.exists(intel_path) else pd.DataFrame()
    
    # Load Compliance Blocked Questions Library
    comp_path = os.path.join(BASE_DIR, "Faroce_Compliance_Prompt_Library_5000.xlsx")
    df_blocked = pd.read_excel(comp_path, sheet_name="Blocked_Questions") if os.path.exists(comp_path) else pd.DataFrame()
    
    return df_intel, df_blocked

df_intel, df_blocked = load_datasets()

# -----------------------------------------------------------------------------
# Compliance & Guardrail Engine (Faroce_Compliance_Prompt_Library_5000)
# -----------------------------------------------------------------------------
def check_compliance(user_query: str) -> tuple[bool, str, str]:
    """
    Checks user query against Faroce Compliance Library for restricted categories:
    Commercially confidential, customer/supplier data, trade secrets, IP, internal finance.
    """
    restricted_keywords = [
        r"\b(price|pricing|discount|cost|margin|revenue forecast)\b",
        r"\b(customer|client list|largest customer)\b",
        r"\b(supplier|preferred supplier|contract details)\b",
        r"\b(trade secret|proprietary process|source code|algorithm)\b",
        r"\b(insider trading|illegal|salary|confidential strategy)\b"
    ]
    for pattern in restricted_keywords:
        if re.search(pattern, user_query, re.IGNORECASE):
            return False, "Query flagged: Violates Enterprise Confidentiality & Compliance Policy.", "What general models or best practices apply to this area?"
    
    # Also check against exact dataframe entries if available
    if not df_blocked.empty:
        for _, row in df_blocked.head(500).iterrows():
            if str(row['Question']).strip().lower() in user_query.strip().lower():
                return False, f"Blocked Category: {row['Category']} ({row['Reason']})", str(row.get('Safe Rewrite', 'Please rephrase your inquiry.'))
                
    return True, "", ""

# -----------------------------------------------------------------------------
# Core Vectorization Logic (ChromaDB + SentenceTransformers)
# -----------------------------------------------------------------------------
@st.cache_resource
def load_embedder():
    return SentenceTransformer("all-MiniLM-L6-v2")

@st.cache_resource
def initialize_chroma_db(pdf_path: str):
    client = chromadb.Client()
    target_path = pdf_path if os.path.exists(pdf_path) else DEFAULT_PDF_PATH
    if not os.path.exists(target_path):
        return client, None, f"Source file not found at '{target_path}'"

    reader = PdfReader(target_path)
    full_text = ""
    for page in reader.pages:
        extracted = page.extract_text()
        if extracted:
            full_text += extracted + "\n"

    cleaned_text = re.sub(r'(?<!\n)\n(?!\n)', ' ', full_text)
    raw_chunks = re.split(r'(?=(?:Farce_exp_\d+|\bFarce\b))', cleaned_text)
    profiles = [chunk.strip() for chunk in raw_chunks if len(chunk.strip()) > 30]

    if not profiles:
        return client, None, "No valid expert entries starting with 'Farce' were found."

    embedder = load_embedder()
    try:
        client.delete_collection("experts_directory")
    except Exception:
        pass

    collection = client.create_collection(name="experts_directory")
    embeddings = embedder.encode(profiles).tolist()
    ids = [f"expert_{i+1}" for i in range(len(profiles))]
    
    collection.add(documents=profiles, embeddings=embeddings, ids=ids)
    return client, collection, f"Successfully indexed {len(profiles)} experts into ChromaDB."

embedder = load_embedder()
chroma_client, collection, db_status = initialize_chroma_db(DEFAULT_PDF_PATH)

# -----------------------------------------------------------------------------
# AI Response Generator (~80 Words Teaser Answer)
# -----------------------------------------------------------------------------
def generate_faroce_guidance(user_query: str, user_info: dict, refinement_mode: str, top_comps: str) -> str:
    prompt = f"""
You are Faroce AI, an expert strategic business advisor.
Client Question: "{user_query}"
Industry Sector: {user_info.get('industry', 'General')}
Top Market Leaders Context: {top_comps}
Refinement Perspective: {refinement_mode}

Task: Write a high-level, practical answer to the query.
STRICT RULES:
1. Keep the total length around 70 to 80 words.
2. Provide a clear high-level direction, referencing industry benchmark standards.
3. Explicitly state that true implementation requires deep-diving into specific architecture/metrics with a domain expert.
4. End with a call-to-action encouraging the user to consult our matched experts below.
"""
    if ollama:
        try:
            response = ollama.chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": prompt}])
            return response['message']['content'].strip()
        except Exception:
            pass

    industry = user_info.get('industry', 'your domain')
    return (
        f"Addressing this in {industry} requires benchmarking against top industry leaders. Success "
        f"hinges on establishing key performance milestones and optimizing resource allocation early. However, executing "
        f"this effectively requires customized technical roadmaps and deep architectural audits. To unpack tailored execution "
        f"strategies and mitigate implementation risks, engage directly with our matched expert specialists below."
    )

# -----------------------------------------------------------------------------
# Session State & Portal Setup
# -----------------------------------------------------------------------------
if "step" not in st.session_state:
    st.session_state.step = 1
if "question_count" not in st.session_state:
    st.session_state.question_count = 0
if "user_info" not in st.session_state:
    st.session_state.user_info = {}

st.sidebar.title("⚡ Faroce AI Portal")
remaining = MAX_QUESTIONS - st.session_state.question_count
st.sidebar.metric(label="Free Inquiries Remaining", value=f"{remaining} / {MAX_QUESTIONS}")

if collection is None:
    st.sidebar.error(f"⚠️ Vector DB Status: {db_status}")
else:
    st.sidebar.success("✅ ChromaDB Vector Search Engine Active")

# -----------------------------------------------------------------------------
# Workflow Engine
# -----------------------------------------------------------------------------

# STEP 1: Client Intake Form
if st.session_state.step == 1:
    st.title("📋 Step 1: Client Information Intake")
    st.write("Welcome to Faroce AI. Please provide your business context to help us route your request.")

    with st.form("intake_form"):
        full_name = st.text_input("Your Name / Organization *")
        email = st.text_input("Work Email Address *")
        industry_options = df_intel['Segment'].unique().tolist() if not df_intel.empty else ["Mechanical Components", "Industrial Automation", "Fluid Handling"]
        industry = st.selectbox("Target Industry / Segment *", industry_options)
        location = st.text_input("Region / Location *", placeholder="e.g., Bengaluru, India")
        focus_type = st.selectbox("Help Needed Regarding *", ["Product Strategy", "Supply Chain & Logistics", "Operations & Scale", "Compliance & Risk"])
        
        if st.form_submit_button("Proceed to Requirement Definition ➔"):
            if not all([full_name.strip(), email.strip(), location.strip()]):
                st.error("Please fill in all required fields (*).")
            else:
                st.session_state.user_info = {
                    "name": full_name, "email": email, "industry": industry,
                    "location": location, "focus_type": focus_type
                }
                st.session_state.step = 2
                st.rerun()

# STEP 2: Requirement Definition & Compliance Check
elif st.session_state.step == 2:
    st.title("✍️ Step 2: Requirement Definition & Compliance Screening")
    st.caption(f"Client: **{st.session_state.user_info.get('name')}** | Segment: **{st.session_state.user_info.get('industry')}**")

    user_raw_query = st.text_area(
        "Enter your core business question or consultation requirement:",
        height=120,
        placeholder="e.g., How do we optimize our component supply chain architecture?"
    )

    if user_raw_query.strip():
        # Compliance Gatekeeper Check
        is_safe, alert_msg, safe_rewrite = check_compliance(user_raw_query)
        if not is_safe:
            st.error(f"⚠️ **Compliance Block:** {alert_msg}")
            st.info(f"💡 **Suggested Safe Rewrite:** _{safe_rewrite}_")
        else:
            st.success("✅ Query passed enterprise compliance & safety screening.")

            st.subheader("🎯 Refinement Options (Choose Your Perspective)")
            refinement_choice = st.radio(
                "Select Refinement Mode:",
                options=[
                    "1. Own Choice (Original Question Unchanged)",
                    "2. Strategic & Functional Focus",
                    "3. Revenue & Growth Driven"
                ],
                index=1
            )

            if "1." in refinement_choice:
                base_query = user_raw_query.strip()
            elif "2." in refinement_choice:
                base_query = f"{user_raw_query.strip()} | Focus: Strategic roadmap, operational architecture, and functional execution."
            else:
                base_query = f"{user_raw_query.strip()} | Focus: Revenue optimization, ROI maximization, and cost reduction."

            # Fetch Top 5 Companies from Industry Intelligence Database
            segment = st.session_state.user_info.get('industry')
            matching_rows = df_intel[df_intel['Segment'] == segment] if not df_intel.empty else pd.DataFrame()
            top_global = "; ".join(matching_rows['Top 5 Global Companies'].dropna().unique()[:2]) if not matching_rows.empty else "Global Industry Leaders"
            top_indian = "; ".join(matching_rows['Top 5 Indian Companies'].dropna().unique()[:2]) if not matching_rows.empty else "Leading Indian Enterprises"
            
            sector_context = f"Top Global: {top_global} | Top Indian: {top_indian}"
            final_search_query = f"{base_query} Industry Benchmark Affiliation: {sector_context}"

            st.markdown("**Preview of Sector-Ranked Vector Search Input:**")
            st.info(final_search_query)

            if st.button("🚀 Submit Query & Rank Experts ➔"):
                if st.session_state.question_count >= MAX_QUESTIONS:
                    st.error("⚠️ Free tier quota exhausted (5 queries max).")
                elif collection is None:
                    st.error("Vector DB is unavailable.")
                else:
                    st.session_state.selected_question = user_raw_query
                    st.session_state.final_query = final_search_query
                    st.session_state.refinement_mode = refinement_choice
                    st.session_state.sector_context = sector_context
                    st.session_state.question_count += 1
                    
                    with st.spinner("Generating Strategic Insight & Ranking Top-5 Company Experts..."):
                        st.session_state.ai_guidance = generate_faroce_guidance(
                            user_raw_query, st.session_state.user_info, refinement_choice, sector_context
                        )
                        
                        query_vector = embedder.encode([final_search_query]).tolist()
                        results = collection.query(
                            query_embeddings=query_vector,
                            n_results=min(3, collection.count())
                        )
                        st.session_state.matched_docs = results["documents"][0] if results["documents"] else []
                    
                    st.session_state.step = 3
                    st.rerun()

# STEP 3: Strategic Output & Top-5 Sector Ranked Recommendations
elif st.session_state.step == 3:
    st.title("🎯 Stage 3: Strategic Direction & Top-Company Ranked Experts")
    
    st.markdown(f"**Submitted Inquiry:** _{st.session_state.selected_question}_")
    st.markdown(f"**Sector Intelligence Benchmarks:** `{st.session_state.get('sector_context', 'Standard Industry')}`")
    
    st.subheader("💡 Faroce AI Strategic Guidance")
    st.info(st.session_state.get("ai_guidance", "Strategic overview unavailable."))

    st.divider()
    st.subheader("🏆 Masked Expert Recommendations (Ranked by Top-5 Sector Experience)")

    matched_docs = st.session_state.get("matched_docs", [])
    tiers = [
        {"badge": "🥇 Gold Tier Expert", "price": "₹5,000", "desc": "Associate Specialist (Ex-Top 5 Tier)"},
        {"badge": "🥈 Premium Tier Expert", "price": "₹10,000", "desc": "Senior Practitioner (Ex-Top 5 Tier)"},
        {"badge": "💎 Diamond Tier Expert", "price": "₹15,000", "desc": "Strategic Lead (Ex-Top 5 Tier)"}
    ]

    cols = st.columns(3)
    for idx, col in enumerate(cols):
        tier = tiers[idx]
        profile_text = matched_docs[idx] if idx < len(matched_docs) else "No matching profile found for this tier."
        
        with col:
            with st.container(border=True):
                st.markdown(f"### {tier['badge']}")
                st.caption(f"Role level: **{tier['desc']}**")
                st.markdown(f"**Consultation Fee:** `{tier['price']}` / 60-min call")
                st.text_area("Masked Profile Summary", value=profile_text, height=220, disabled=True, key=f"p_{idx}")
                if st.button(f"Book {tier['badge']}", key=f"b_{idx}"):
                    st.success(f"Consultation request submitted for {tier['badge']}!")

    st.divider()
    if st.button("🔄 Ask Another Question"):
        st.session_state.step = 2
        st.rerun()