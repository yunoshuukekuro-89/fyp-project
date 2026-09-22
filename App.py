import os
import json
from datetime import datetime

import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
from groq import Groq
from dotenv import load_dotenv

# -----------------------------
# CONFIG
# -----------------------------
load_dotenv()

SHEET_NAME = "FYP Workflow Submissions"
MODEL_NAME = "openai/gpt-oss-120b"
DEPARTMENTS = ["Admissions", "Records", "Finance", "IT Support", "Student Affairs"]
SHEET_HEADERS = [
    "Timestamp", "Department", "Workflow Name",
    "Step 1", "Step 2", "Step 3", "Step 4", "Step 5", "AI Report"
]

st.set_page_config(page_title="FYP Workflow Analyzer", layout="wide")

# -----------------------------
# CLIENTS (cached so we don't reconnect on every rerun)
# -----------------------------
@st.cache_resource
def get_groq_client():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        st.error("GROQ_API_KEY not found. Check your .env file.")
        st.stop()
    return Groq(api_key=api_key)


@st.cache_resource
def get_sheet():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    try:
        creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    except FileNotFoundError:
        st.error("credentials.json not found in project root. Check Step 17.")
        st.stop()

    client = gspread.authorize(creds)
    try:
        sheet = client.open(SHEET_NAME).sheet1
    except gspread.SpreadsheetNotFound:
        st.error(
            f"Sheet '{SHEET_NAME}' not found or not shared with the service account email. "
            "Check Step 16/17."
        )
        st.stop()

    # Ensure headers exist on first-ever run
    existing = sheet.row_values(1)
    if existing != SHEET_HEADERS:
        sheet.update("A1", [SHEET_HEADERS])

    return sheet


groq_client = get_groq_client()
sheet = get_sheet()

# -----------------------------
# PROMPT
# -----------------------------
SYSTEM_PROMPT = """You are a Lean process improvement analyst reviewing a workflow submitted by university Registry staff.
Analyze the workflow against the Lean 7 Wastes framework (Overproduction, Waiting, Transport, Overprocessing,
Inventory, Motion, Defects). You only have the 5 steps described below — no other context — so keep findings
grounded in what is actually described, not invented detail.

Return your analysis as valid JSON only, no markdown fences, no preamble, matching this exact structure:

{
  "step_findings": [
    {
      "step_number": 1,
      "step_text": "<copy of the step text>",
      "waste_type": "<one of the 7 wastes, or 'None identified'>",
      "severity": "High | Medium | Low | N/A",
      "suggested_fix": "<concrete, specific fix, or 'No action needed'>"
    }
  ],
  "workflow_opportunities": [
    {
      "opportunity": "<short description of an efficiency or cost-reduction opportunity>",
      "affected_steps": "<which step number(s) this relates to>",
      "priority_rank": <integer, 1 = highest priority across all opportunities listed>,
      "human_still_required": "Yes | No | Partially",
      "human_required_reason": "<brief reason why human judgment/hands is or isn't still needed after this fix>"
    }
  ]
}

Only include a step_findings entry for all 5 steps, even if waste_type is 'None identified'.
List workflow_opportunities in priority order, most impactful first. Do not exceed 5 opportunities.
"""


def generate_report(department, workflow_name, steps):
    user_content = (
        f"Department: {department}\n"
        f"Workflow Name: {workflow_name}\n"
        f"Step 1: {steps[0]}\n"
        f"Step 2: {steps[1]}\n"
        f"Step 3: {steps[2]}\n"
        f"Step 4: {steps[3]}\n"
        f"Step 5: {steps[4]}\n"
    )

    response = groq_client.chat.completions.create(
        model=MODEL_NAME,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
    )

    raw = response.choices[0].message.content.strip()

    # Defensive cleanup in case the model wraps output in markdown fences anyway
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        st.warning("The AI response wasn't valid JSON. Showing raw output instead.")
        return {"raw_output": raw}


def render_report(report):
    if "raw_output" in report:
        st.text(report["raw_output"])
        return

    st.subheader("Step-by-Step Findings")
    for f in report.get("step_findings", []):
        severity = f.get("severity", "N/A")
        color = {"High": "🔴", "Medium": "🟠", "Low": "🟡", "N/A": "⚪"}.get(severity, "⚪")
        with st.expander(f"{color} Step {f.get('step_number')} — {f.get('waste_type', 'N/A')} (Severity: {severity})"):
            st.markdown(f"**Step described:** {f.get('step_text', '')}")
            st.markdown(f"**Waste type:** {f.get('waste_type', 'N/A')}")
            st.markdown(f"**Severity:** {severity}")
            st.markdown(f"**Suggested fix:** {f.get('suggested_fix', 'N/A')}")

    st.subheader("Workflow-Wide Opportunities")
    opportunities = sorted(
        report.get("workflow_opportunities", []),
        key=lambda x: x.get("priority_rank", 99)
    )
    for o in opportunities:
        st.markdown(f"**#{o.get('priority_rank')} — {o.get('opportunity')}**")
        st.markdown(f"- Affected step(s): {o.get('affected_steps')}")
        st.markdown(f"- Human still required: {o.get('human_still_required')} — {o.get('human_required_reason')}")
        st.divider()


# -----------------------------
# UI
# -----------------------------
st.title("FYP Workflow Analyzer")
st.caption("AI-assisted Lean 7 Wastes analysis for Registry workflows. Beta — no login required yet.")

tab_submit, tab_history = st.tabs(["Submit a Workflow", "Submission History"])

with tab_submit:
    with st.form("workflow_form", clear_on_submit=False):
        department = st.selectbox("Department", DEPARTMENTS)
        workflow_name = st.text_input("Workflow Name", placeholder="e.g. Transcript Request Processing")

        st.markdown("**Describe the workflow, one step at a time:**")
        step1 = st.text_area("Step 1", height=70)
        step2 = st.text_area("Step 2", height=70)
        step3 = st.text_area("Step 3", height=70)
        step4 = st.text_area("Step 4", height=70)
        step5 = st.text_area("Step 5", height=70)

        submitted = st.form_submit_button("Analyze Workflow")

    if submitted:
        steps = [step1, step2, step3, step4, step5]
        if not workflow_name.strip() or not all(s.strip() for s in steps):
            st.error("Please fill in the workflow name and all 5 steps before submitting.")
        else:
            with st.spinner("Analyzing workflow against Lean 7 Wastes..."):
                report = generate_report(department, workflow_name, steps)
                report_text = json.dumps(report)

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                sheet.append_row(
                    [timestamp, department, workflow_name, *steps, report_text]
                )

            st.success("Analysis complete and saved.")
            render_report(report)

with tab_history:
    st.subheader("Past Submissions")
    if st.button("Refresh"):
        st.cache_resource.clear()
        st.rerun()

    records = sheet.get_all_records()
    if not records:
        st.info("No submissions yet.")
    else:
        for row in reversed(records):
            title = f"{row.get('Timestamp', '')} — {row.get('Department', '')} — {row.get('Workflow Name', '')}"
            with st.expander(title):
                st.markdown(f"**Steps:**")
                for i in range(1, 6):
                    st.markdown(f"- Step {i}: {row.get(f'Step {i}', '')}")

                raw_report = row.get("AI Report", "")
                try:
                    parsed = json.loads(raw_report)
                    render_report(parsed)
                except (json.JSONDecodeError, TypeError):
                    st.text(raw_report)