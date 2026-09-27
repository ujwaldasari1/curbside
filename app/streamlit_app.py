"""Curbside console: `streamlit run app/streamlit_app.py`."""

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root: governance, evals, agents

st.set_page_config(page_title="Curbside", page_icon=":wastebasket:", layout="wide")

pages = st.navigation(
    {
        "Platform": [
            st.Page("views/overview.py", title="Overview", icon=":material/dashboard:", default=True),
            st.Page("views/ask.py", title="Ask the analyst", icon=":material/chat:"),
        ],
        "Operations": [
            st.Page("views/incidents.py", title="Incidents", icon=":material/emergency:"),
            st.Page("views/approvals.py", title="Approvals", icon=":material/fact_check:"),
            st.Page("views/chaos.py", title="Chaos lab", icon=":material/science:"),
        ],
        "Quality": [
            st.Page("views/scorecards.py", title="Agent evals", icon=":material/rule:"),
        ],
    }
)
pages.run()
