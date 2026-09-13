import os
import re
import streamlit as st
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

    # Sanitize PDF extraction line wraps
    cleaned_text = re.sub(r'(?<!\n)\n(?!\n)', ' ', full_text)
    
    # Split profiles cleanly on 'Farce' ID markers
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
def generate_faroce_guidance(user_query: str, user_info: dict, refinement_mode: str) -> str:
    """
    Generates a high-level strategic overview (~80 words) designed to 
    answer the query briefly and drive engagement towards expert consultation.
    """
    prompt = f"""
You are Faroce AI, an expert strategic business advisor.
Client Question: "{user_query}"
Industry: {user_info.get('industry', 'General')}
Refinement Perspective: {refinement_mode}

Task: Write a high-level, practical answer to the query.
STRICT RULES:
1. Keep the total length around 70 to 80 words.
2. Provide a clear high-level direction, but do NOT give deep granular execution steps.
3. Explicitly state that true implementation requires deep-diving into specific architecture/metrics with a domain expert.
4. End with a call-to-action encouraging the user to consult our matched experts below.
"""
    if ollama:
        try:
            response = ollama.chat(model=OLLAMA_MODEL, messages=[{"role": "user", "content": prompt}])
            return response['message']['content'].strip()
        except Exception:
            pass

    # High-quality fallback answer when Ollama is offline
    industry = user_info.get('industry', 'your domain')
    return (
        f"Addressing this in {industry} requires a dual approach: streamlining baseline operational workflows "
        f"while fortifying core risk boundaries. From a {refinement_mode.split('.')[1].strip() if '.' in refinement_mode else refinement_mode} standpoint, "
        f"success hinges on establishing key performance milestones and optimizing resource allocation early. However, executing "
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

# Sidebar Status Tracker
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
        industry = st.selectbox("Target Industry *", ["Manufacturing", "Healthcare", "FinTech", "Retail & E-Commerce", "Energy & Utilities", "Technology"])
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

# STEP 2: Requirement Definition & 3-Part Refinement Selection
elif st.session_state.step == 2:
    st.title("✍️ Step 2: Requirement Definition & Refinement Mode")
    st.caption(f"Client: **{st.session_state.user_info.get('name')}** | Industry: **{st.session_state.user_info.get('industry')}**")

    user_raw_query = st.text_area(
        "Enter your core business question or consultation requirement:",
        height=120,
        placeholder="e.g., How do we optimize our supply chain architecture for scaling operations?"
    )

    if user_raw_query.strip():
        st.subheader("🎯 Refinement Options (Choose Your Perspective)")
        st.write("Select how you want Faroce AI to frame your query before searching the Vector DB:")

        opt_original = user_raw_query.strip()
        opt_strategic = (
            f"{user_raw_query.strip()} | Focus: Strategic roadmap, operational architecture, "
            f"system scalability, and functional execution for {st.session_state.user_info.get('focus_type')}."
        )
        opt_revenue = (
            f"{user_raw_query.strip()} | Focus: Revenue optimization, commercial growth strategies, "
            f"ROI maximization, cost reduction, and market expansion."
        )

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
            final_search_query = opt_original
        elif "2." in refinement_choice:
            final_search_query = opt_strategic
        else:
            final_search_query = opt_revenue

        st.markdown("**Preview of Vector Search Input:**")
        st.info(final_search_query)

        if st.button("🚀 Submit Query & Match Experts ➔"):
            if st.session_state.question_count >= MAX_QUESTIONS:
                st.error("⚠️ Free tier quota exhausted (5 queries max). Please upgrade to continue.")
            elif collection is None:
                st.error("Vector DB is unavailable. Check server source PDF file.")
            else:
                st.session_state.selected_question = user_raw_query
                st.session_state.final_query = final_search_query
                st.session_state.refinement_mode = refinement_choice
                st.session_state.question_count += 1
                
                with st.spinner("Generating Strategic Insight & Matching Experts..."):
                    # 1. Generate High-Level ~80 Word Strategic Response
                    st.session_state.ai_guidance = generate_faroce_guidance(
                        user_raw_query, st.session_state.user_info, refinement_choice
                    )
                    
                    # 2. Perform ChromaDB Vector Search
                    query_vector = embedder.encode([final_search_query]).tolist()
                    results = collection.query(
                        query_embeddings=query_vector,
                        n_results=min(3, collection.count())
                    )
                    st.session_state.matched_docs = results["documents"][0] if results["documents"] else []
                
                st.session_state.step = 3
                st.rerun()

# STEP 3: Strategic Output & Expert Recommendations
elif st.session_state.step == 3:
    st.title("🎯 Stage 3: Strategic Direction & Expert Recommendations")
    
    st.markdown(f"**Submitted Inquiry:** _{st.session_state.selected_question}_")
    st.markdown(f"**Applied Refinement Mode:** `{st.session_state.refinement_mode}`")
    
    # Dynamic ~80 Word High-Level Response
    st.subheader("💡 Faroce AI Strategic Guidance")
    st.info(st.session_state.get("ai_guidance", "Strategic overview unavailable."))

    st.divider()
    st.subheader("🏆 Matched Expert Options from ChromaDB")

    matched_docs = st.session_state.get("matched_docs", [])
    tiers = [
        {"badge": "🥇 Gold Tier Expert", "price": "₹5,000", "desc": "Associate Specialist"},
        {"badge": "🥈 Premium Tier Expert", "price": "₹10,000", "desc": "Senior Practitioner"},
        {"badge": "💎 Diamond Tier Expert", "price": "₹15,000", "desc": "Strategic Lead"}
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
                st.text_area("Profile Match Summary", value=profile_text, height=220, disabled=True, key=f"p_{idx}")
                if st.button(f"Book {tier['badge']}", key=f"b_{idx}"):
                    st.success(f"Consultation request submitted for {tier['badge']}!")

    st.divider()
    if st.button("🔄 Ask Another Question"):
        st.session_state.step = 2
        st.rerun()