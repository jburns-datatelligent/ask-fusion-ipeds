# Ask Fusion: U.S. college data, in plain English

The web front end for **Ask Fusion (IPEDS)**, a free demo by [Datatelligent](https://datatelligent.ai).
Ask a question about U.S. colleges in plain English: admissions, enrollment, retention, graduation,
financial aid or net price. You get the answer, the table behind it and the SQL that produced it,
drawn from IPEDS, the federal survey every U.S. college reports to the National Center for Education
Statistics.

This repository holds only the page. The data, the semantic model and the agent that answers run in
Datatelligent's Snowflake account and are reached with credentials that are not in this repository.

| Path | What it is |
|---|---|
| `app/streamlit_app.py` | The page: contact form, conversation, answers, charts |
| `app/theme.py`, `app/assets/` | Datatelligent brand styling |
| `app/gate.py`, `app/store.py` | Contact form validation; where leads and questions are recorded |
| `backend/agent_client.py` | Calls the Snowflake Cortex Agent over REST |
| `semantic/verified_queries.yaml` | The suggested questions shown on the page |

Deployed on Streamlit Community Cloud with main file `app/streamlit_app.py`; its settings go in the
app's Secrets.

This is a published copy of a private repository and is overwritten on every release, so pull
requests here are not merged.

Copyright © Datatelligent. All rights reserved. No license is granted to use, copy or modify this code.
