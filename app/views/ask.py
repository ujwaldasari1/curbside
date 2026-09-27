import os

import anyio
import pandas as pd
import streamlit as st

st.title("Ask the analyst")
st.caption("Answers come only from certified metrics (dbt Semantic Layer) and Tier 1 marts, "
           "with the definitions from the OpenMetadata glossary.")

if not os.environ.get("ANTHROPIC_API_KEY"):
    st.warning("Set ANTHROPIC_API_KEY in .env to enable the analyst agent.")
    st.stop()

examples = [
    "Which borough had the highest diversion rate last month?",
    "How do snow days change 311 sanitation complaints?",
    "Which community districts have the worst missed-collection rate this year?",
]
question = st.chat_input("Ask about DSNY tonnage, recycling, organics or 311 sanitation requests")
cols = st.columns(len(examples))
for col, example in zip(cols, examples, strict=True):
    if col.button(example, width="stretch"):
        question = example

if "history" not in st.session_state:
    st.session_state.history = []

if question:
    from agents import analyst

    with st.spinner("Querying the semantic layer and catalog..."):
        result = anyio.run(analyst.ask, question, "streamlit")
    st.session_state.history.insert(0, (question, result))

for asked, result in st.session_state.history:
    output = result.output or {}
    with st.chat_message("user"):
        st.write(asked)
    with st.chat_message("assistant"):
        st.markdown(output.get("answer_markdown") or result.text or "(no answer)")
        if output.get("key_numbers"):
            st.dataframe(pd.DataFrame(output["key_numbers"]), hide_index=True)
        with st.expander("How I got this"):
            st.write({"metrics": output.get("metrics_used"), "tables": output.get("tables_used"),
                      "caveats": output.get("caveats")})
            for sql in output.get("sql") or []:
                st.code(sql, language="sql")
            st.caption(f"{result.num_turns} turns · {len(result.tool_calls)} tool calls · "
                       f"{result.duration_ms / 1000:.1f}s · ${result.cost_usd or 0:.3f}")
