import streamlit as st
import requests
import pandas as pd
from pymongo import MongoClient
from datetime import datetime
import os
import time

st.set_page_config(page_title="Data Processing Dashboard", layout="wide", initial_sidebar_state="collapsed")

def local_css(file_name):
    if os.path.exists(file_name):
        with open(file_name) as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)

local_css("styles.css")

@st.cache_resource
def get_db():
    return MongoClient("mongodb://localhost:27017")["socl_db"]

db = get_db()

# --- FETCH GLOBAL METRICS ---
total_records = db.records.count_documents({})
total_runs = db.runs.count_documents({})

# Calculate TOTAL duplicates across all runs for the KPI bar
total_dupes = sum(r.get("counters", {}).get("duplicates", 0) for r in db.runs.find({}))

# Get the single most recent run for the Tab 3 buttons
latest_run = db.runs.find_one(sort=[("created_at", -1)])
latest_cost = latest_run.get("report", {}).get("total_cost_usd", 0.0) if latest_run else 0.0
latest_dupes = latest_run.get("counters", {}).get("duplicates", 0) if latest_run else 0
latest_collected = latest_run.get("counters", {}).get("collected", 0) if latest_run else 0


# --- CUSTOM HEADER ---
st.markdown("""
<div class="header-container">
    <h1 class="header-title">Data Processing & Delivery Engine</h1>
</div>
""", unsafe_allow_html=True)

# --- KPI DASHBOARD ---
st.markdown(f"""
<div class="kpi-container">
    <div class="kpi-card">
        <div class="kpi-title">Total Clean Records in DB</div>
        <div class="kpi-value">{total_records:,}</div>
    </div>
    <div class="kpi-card green">
        <div class="kpi-title">Successful Runs</div>
        <div class="kpi-value">{total_runs}</div>
    </div>
    <div class="kpi-card purple">
        <div class="kpi-title">Latest Run Cost</div>
        <div class="kpi-value">${latest_cost:.2f}</div>
    </div>
        <div class="kpi-card orange">
        <div class="kpi-title">Total Duplicates Removed</div>
        <div class="kpi-value">{total_dupes}</div>
    </div>
</div>
""", unsafe_allow_html=True)

# --- FAILED RUN WARNING BANNER ---
if latest_run and str(latest_run.get("status", "")).lower() in ["failed", "partial"]:
    st.error(f"⚠️ **Warning:** The last scheduled run (`{latest_run.get('run_id')}`) failed or was incomplete.")
    
    col_warn1, col_warn2 = st.columns([3, 1])
    with col_warn1:
        st.write("Please rerun the job to fetch the missing data and advance the checkpoints.")
    with col_warn2:
        if st.button("🔄 Rerun Failed Job Now", use_container_width=True):
            with st.spinner("Triggering rerun..."):
                res = requests.post(f"http://localhost:8000/api/v1/runs/{latest_run.get('run_id')}/rerun")
                if res.status_code == 200:
                    st.success("Rerun successfully triggered! Updating dashboard...")
                    time.sleep(1.5) # Wait for backend to update
                    st.rerun() # Reload page to clear the banner
                else:
                    st.error("Failed to trigger rerun.")
# --------------------------------------

tab1, tab2, tab3, tab4 = st.tabs(["📤 Process Data", "📄 Records Explorer", "📊 Run Metrics & Rerun", "⏱️ Checkpoints"])

# --- TAB 1: Process Data ---
with tab1:
    st.markdown("<h3 style='color: #1E293B;'>Upload Handoff Files</h3>", unsafe_allow_html=True)
    
    # Removed the custom form-container to get rid of the white box
    col1, col2 = st.columns(2)
    with col1:
        m_file = st.file_uploader("Mentions JSONL", type="jsonl")
    with col2:
        a_file = st.file_uploader("Attempts JSONL", type="jsonl")
    
    industry = st.text_input("Industry JSON Mapping (Optional)", '{"Acme":"Technology"}')
    
    st.write("")
    if st.button("🚀 Start Processing Pipeline", use_container_width=True):
        if m_file and a_file:
            files = {
                "mentions_file": (m_file.name, m_file, "application/json"),
                "attempts_file": (a_file.name, a_file, "application/json")
            }
            data = {"industry_json": industry}
            with st.spinner("Processing data (Masking, Deduplicating, Saving)..."):
                try:
                    res = requests.post("http://localhost:8000/process", files=files, data=data)
                    if res.status_code == 200:
                        st.success("✅ Processing Complete! Data saved to MongoDB.")
                        st.rerun() # Refresh UI to update KPIs
                    else:
                        st.error(f"Error {res.status_code}: {res.text}")
                except Exception as e:
                    st.error(f"Failed to connect to backend: {e}")
        else:
            st.warning("⚠️ Please upload both files before processing.")

# --- TAB 2: Records Explorer ---
with tab2:
    st.markdown("<h3 style='color: #1E293B;'>Clean Records (Masked)</h3>", unsafe_allow_html=True)
    
    records = list(db.records.find({}, {"_id": 0, "text": 1, "author": 1, "industry": 1, "run_id": 1}))
    
    if records:
        df = pd.DataFrame(records)
        # Fill missing industries with "Unknown" for a cleaner look
        df['industry'] = df['industry'].fillna("Unknown")
        
        # Display clean table
        st.data_editor(df, use_container_width=True, hide_index=True, disabled=True, height=400)
    else:
        st.info("No records found in database.")

# --- TAB 3: Run Metrics (Receipts) & Rerun ---
with tab3:
    st.markdown("<h3 style='color: #1E293B;'>Run History & Metrics</h3>", unsafe_allow_html=True)
    
    runs = list(db.runs.find({}, {"_id": 0}).sort("created_at", -1))
    
    if runs:
        st.write("**Latest Run Quick Metrics**")
        col_btn1, col_btn2, col_btn3 = st.columns(3)
        
        if "show_cost" not in st.session_state: st.session_state.show_cost = False
        if "show_dupes" not in st.session_state: st.session_state.show_dupes = False
        if "show_records" not in st.session_state: st.session_state.show_records = False

        with col_btn1:
            if st.button("💰 Get Latest Cost", use_container_width=True):
                st.session_state.show_cost = not st.session_state.show_cost
        with col_btn2:
            if st.button("🗑️ Get Latest Duplicates", use_container_width=True):
                st.session_state.show_dupes = not st.session_state.show_dupes
        with col_btn3:
            if st.button("📄 Get Latest Records Collected", use_container_width=True):
                st.session_state.show_records = not st.session_state.show_records

        res_col1, res_col2, res_col3 = st.columns(3)
        
        if st.session_state.show_cost:
            res_col1.metric(label="Latest Run Cost", value=f"${latest_cost:.2f}")
        else: res_col1.empty()
            
        if st.session_state.show_dupes:
            res_col2.metric(label="Latest Run Duplicates", value=f"{latest_dupes}")
        else: res_col2.empty()
            
        if st.session_state.show_records:
            res_col3.metric(label="Latest Run Collected", value=f"{latest_collected}")
        else: res_col3.empty()

        st.write("---")
        st.write("**Detailed Run History (All Runs)**")
        
        df_runs = pd.DataFrame([{
            "Run ID": r.get("run_id"),
            "Date": r.get("created_at").strftime("%Y-%m-%d %H:%M") if isinstance(r.get("created_at"), datetime) else r.get("created_at"),
            "Status": r.get("status").capitalize() if r.get("status") else "Unknown",
            "Cost (USD)": r.get("report", {}).get("total_cost_usd", 0.0),
            "Duplicates": r.get("counters", {}).get("duplicates", 0),
            "Quarantined": r.get("counters", {}).get("quarantined", 0),
            "Collected": r.get("counters", {}).get("collected", 0)
        } for r in runs])
        
        st.data_editor(df_runs, use_container_width=True, hide_index=True, disabled=True, height=250)
        
        st.write("---")
        st.markdown("<h3 style='color: #1E293B;'>🔄 Manual Run</h3>", unsafe_allow_html=True)
        
        col1, col2 = st.columns([3, 1])
        with col1:
            run_to_rerun = st.selectbox("Select Run ID to Rerun", df_runs["Run ID"].tolist(), label_visibility="collapsed")
        with col2:
            if st.button("Rerun Job", use_container_width=True):
                with st.spinner("Triggering rerun..."):
                    res = requests.post(f"http://localhost:8000/api/v1/runs/{run_to_rerun}/rerun")
                    if res.status_code == 200:
                        st.success(res.json()["message"])
                    else:
                        st.error("Failed to trigger rerun.")
    else:
        st.info("No runs found yet.")

# --- TAB 4: Checkpoints ---
with tab4:
    st.markdown("<h3 style='color: #1E293B;'>System Memory (Checkpoints)</h3>", unsafe_allow_html=True)
    
    cps = list(db.checkpoints.find({}, {"_id": 0}))
    if cps:
        df_cps = pd.DataFrame(cps)
        st.data_editor(df_cps, use_container_width=True, hide_index=True, disabled=True, height=400)
    else:
        st.info("No checkpoints found yet.")