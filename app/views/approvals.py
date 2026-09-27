import getpass
import json

import streamlit as st
from data import app_query

from governance import proposals

st.title("Approvals")
st.caption("Agents never change the catalog directly. Every description, PII tag and glossary "
           "link they propose waits here until a person approves it.")

pending = app_query("select * from ops.metadata_proposals where status = 'pending' order by id")
if pending.empty:
    st.success("Nothing waiting for review.")
reviewer = st.text_input("Reviewer", value=getpass.getuser())

for _, p in pending.iterrows():
    target = p.entity_fqn.split(".", 2)[-1] + (f" · {p.column_name}" if p.column_name else "")
    with st.container(border=True):
        st.markdown(f"**#{p.id} · {p.change_type.replace('_', ' ')}** on `{target}`  \n"
                    f"proposed by `{p.agent}`")
        st.markdown(f"> {p.proposed_value}")
        st.caption(p.rationale)
        if p.evidence:
            with st.expander("Evidence"):
                st.code(json.dumps(p.evidence, indent=2), language="json")
        approve, reject, _ = st.columns([1, 1, 6])
        if approve.button("Approve", key=f"a{p.id}", type="primary"):
            outcome = proposals.approve(int(p.id), reviewer)
            (st.toast if outcome == "applied" else st.error)(f"#{p.id}: {outcome}")
            st.rerun()
        if reject.button("Reject", key=f"r{p.id}"):
            proposals.reject(int(p.id), reviewer)
            st.rerun()

st.subheader("Recently reviewed")
st.dataframe(
    app_query("""select id, agent, change_type, column_name, proposed_value, status, reviewed_by,
                        reviewed_at, apply_error
                 from ops.metadata_proposals where status <> 'pending'
                 order by reviewed_at desc nulls last limit 25"""),
    hide_index=True, width="stretch",
)
