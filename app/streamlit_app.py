"""Ask Fusion, IPEDS edition: the public web front end for the Cortex Agent.

CoWork (Snowflake Intelligence) only serves signed-in Snowflake users, so this self-hosted page
is how the public reaches the same agent: a contact gate, then a question-and-answer page that
calls the agent over REST as a low-privilege service user.

    streamlit run ipeds_demo/app/streamlit_app.py

Settings: config.py. Snowflake objects: sql/02_public_app.sql. Event parsing: answer.py.

This runs outside Snowflake, so none of the SiS API restrictions in the repo's CLAUDE.md apply.
"""

from __future__ import annotations

import html
import logging
import sys
import time
import uuid
from pathlib import Path

import pandas as pd
import requests
import streamlit as st
import yaml

APP = Path(__file__).resolve().parent
ROOT = APP.parent
sys.path.insert(0, str(ROOT / "backend"))

import agent_client  # noqa: E402
import gate  # noqa: E402
import theme  # noqa: E402
from answer import (STEP_LABELS, STEPS, TIMED_OUT, Answer, is_money_column, is_year_column, label,  # noqa: E402
                    markdown_safe, split_source)
from config import CONSENT_TEXT, ROLES, Settings  # noqa: E402
from store import lead_key, make_store  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ask_fusion_app")

SESSION_CAP = 40          # hard stop per browser session, whatever the daily counts say
AUDIENCES = (("presidents", "Presidents & cabinet"), ("enrollment", "Enrollment & admissions"),
             ("ir", "Institutional research"))
STARTERS_PER_AUDIENCE = 6

st.set_page_config(page_title="Ask Fusion | U.S. college data in plain English | Datatelligent",
                   page_icon=str(APP / "assets" / "mark.svg"), layout="centered",
                   initial_sidebar_state="collapsed")


# ---------------------------------------------------------------- resources
def settings() -> Settings:
    # Deliberately NOT cached: it is a handful of env reads. A cached Settings outlived a code update
    # on Community Cloud (an old object missing a new field crashed the page), and it would also hide
    # a change to the app's Secrets, such as APP_REQUIRE_CONTACT, until the next reboot.
    return Settings.load()


@st.cache_resource
def store():
    return make_store(settings().store)


@st.cache_resource
def agent_cfg() -> agent_client.AgentConfig:
    return agent_client.AgentConfig.from_env()


@st.cache_data
def starters() -> dict[str, list[str]]:
    """Suggested questions are the verified queries: every one has a checked answer."""
    vqs = yaml.safe_load((ROOT / "semantic" / "verified_queries.yaml").read_text())["verified_queries"]
    out: dict[str, list[str]] = {k: [] for k, _ in AUDIENCES}
    for q in vqs:
        bucket = out.get(q.get("audience"))
        if bucket is not None and len(bucket) < STARTERS_PER_AUDIENCE:
            bucket.append(q["question"])
    return out


@st.cache_data(ttl=60)
def site_questions_today() -> int:
    return store().questions_today()


S = settings()
ss = st.session_state
ss.setdefault("session_id", uuid.uuid4().hex)
ss.setdefault("messages", [])
ss.setdefault("pending", None)
ss.setdefault("lead", None)
ss.setdefault("used_today", None)


# ---------------------------------------------------------------- small helpers
def esc(s: str) -> str:
    return html.escape(s or "", quote=True)


def queue(question: str) -> None:
    """Callback for every way of asking: runs before the script, so the composer renders disabled."""
    q = (question or "").strip()
    if q and not ss.pending:
        ss.pending = q[:1000]


def on_composer() -> None:
    queue(ss.get("composer", ""))


def sign_out() -> None:
    ss.lead = None
    ss.messages = []
    ss.used_today = None
    st.query_params.clear()


def new_conversation() -> None:
    ss.messages = []


def header() -> None:
    st.html(
        f'<div class="af-topbar">'
        f'  <a class="af-brand" href="{esc(S.cta_url)}" target="_blank" rel="noopener">'
        f'    <img src="{theme.svg_data_uri("logo.svg")}" alt="Datatelligent">'
        f'    <span class="af-divider"></span>'
        f'    <span class="af-product"><b>Ask Fusion</b><span>U.S. college data, in plain English</span></span>'
        f'  </a>'
        f'  <a class="af-cta" href="{esc(S.cta_url)}" target="_blank" rel="noopener"><span class="long">Ask Fusion on your own data</span><span class="short">Your data</span> &rarr;</a>'
        f'</div>')


def footer() -> None:
    st.html(
        '<div class="af-footer"><span>Data: Integrated Postsecondary Education Data System (IPEDS), '
        'National Center for Education Statistics, collection years 2019&ndash;2023. '
        'Every figure is checked against NCES&rsquo;s published values.</span>'
        f'<span>&copy; Datatelligent &middot; <a href="{esc(S.privacy_url)}" target="_blank" rel="noopener">Privacy</a></span></div>')


# ---------------------------------------------------------------- gate
def resolve_lead() -> None:
    if ss.lead is None:
        ss.lead = gate.read_token(st.query_params.get("t"), S.app_secret)
    if ss.lead and ss.used_today is None:
        ss.used_today = store().questions_today(ss.lead["lead_key"])


def render_gate() -> None:
    left, right = st.columns([1.12, 1], gap="large")
    with left:
        st.html(
            '<div class="af-hero">'
            '<span class="af-eyebrow">Free for higher-ed leaders</span>'
            '<h1>Ask anything about <em>U.S. colleges</em>. Get the answer from federal data.</h1>'
            '<p class="lead">Ask Fusion reads IPEDS, the survey every U.S. college reports to the Department of '
            'Education, and answers in plain English: the number, the table behind it, and the query it ran.</p>'
            '<ul class="af-proof">'
            '<li><span>About 6,000 institutions a year, fall 2019 through 2023: admissions, enrollment, retention, '
            'graduation, aid and net price.</span></li>'
            '<li><span>Every figure checked against NCES&rsquo;s own published values. If the data can&rsquo;t answer, '
            'it says so instead of guessing.</span></li>'
            '<li><span>Benchmark your institution against peers, your state or your sector in seconds, '
            'not a week of spreadsheet work.</span></li>'
            f'<li class="yours"><span><b>Works on your institutional data, too.</b> The same assistant runs on '
            f'your own student data. <a href="{esc(S.cta_url)}" target="_blank" rel="noopener">'
            'See how &rarr;</a></span></li>'
            '</ul>'
            '<div class="af-sample">'
            '<div class="q">&ldquo;How do HBCU graduation rates compare with other 4-year institutions?&rdquo;</div>'
            '<div class="a">At private nonprofit 4-year colleges, HBCUs graduated <b>41.7%</b> of their fall 2017 '
            'entering students within six years, against <b>67.6%</b> at other private nonprofits. At public 4-year '
            'institutions the rates were <b>36.0%</b> and <b>59.3%</b>. Rates are pooled across institutions.</div>'
            '<div class="src">Source: IPEDS (NCES), Graduation Rates, 2023 collection</div>'
            '</div></div>')
    # Drawn before the submit is handled, so a form error (which returns early) cannot drop it.
    # The columns already exist, so it still renders below both of them.
    your_data_band("gate")
    with right:
        with st.form("lead_form", border=False):
            st.html('<p class="af-form-title">Start asking, free</p>'
                    '<p class="af-form-sub">Tell us who you are and you&rsquo;re in. It takes 20 seconds.</p>'
                    + ('' if S.require_contact else
                       '<p class="af-form-sub"><b>Optional during the preview:</b> leave it blank and press '
                       'Start asking.</p>'))
            c1, c2 = st.columns(2)
            first = c1.text_input("First name", max_chars=100, autocomplete="given-name")
            last = c2.text_input("Last name", max_chars=100, autocomplete="family-name")
            email = st.text_input("Work email", max_chars=254, autocomplete="email",
                                  placeholder="you@university.edu")
            org = st.text_input("Institution or organization", max_chars=200, autocomplete="organization")
            role = st.selectbox("Your role", ROLES, index=None, placeholder="Choose the closest")
            consent = st.checkbox(CONSENT_TEXT)
            submitted = st.form_submit_button("Start asking  →", type="primary", width="stretch")
            st.html(f'<p class="af-fineprint">We use your details to follow up about Ask Fusion. No spam, '
                    f'and we never sell contact information. <a href="{esc(S.privacy_url)}" target="_blank" '
                    f'rel="noopener">Privacy policy</a>.</p>')
        if submitted:
            form = {"first_name": first, "last_name": last, "email": email, "organization": org,
                    "job_role": role, "consent": consent}
            errors = gate.validate(form, required=S.require_contact)
            if errors:
                for msg in errors.values():
                    st.error(msg)
                return
            if not email.strip():
                # Optional form left without an email: in as an anonymous visitor, one per browser
                # session. Nothing goes to the leads table; every question is still logged, under
                # lead_key 'anon-...', and the per-person cap becomes per session (the site-wide
                # cap still bounds spend). No sign-in link, so a reload shows the form again.
                ss.lead = {"lead_id": None, "lead_key": f"anon-{ss.session_id}", "anonymous": True,
                           "first_name": first.strip()[:40], "organization": org.strip()[:80]}
                ss.used_today = store().questions_today(ss.lead["lead_key"])
                st.rerun()
            lead = {k: (v.strip() if isinstance(v, str) else v) for k, v in form.items() if k != "consent"}
            lead.update(lead_id=uuid.uuid4().hex, lead_key=lead_key(email), consent_text=CONSENT_TEXT,
                        referrer=st.context.headers.get("Referer"),
                        user_agent=(st.context.headers.get("User-Agent") or "")[:500],
                        utm={k: v for k, v in st.query_params.items() if k.startswith("utm_")})
            store().save_lead(lead)
            ss.lead = {k: lead[k] for k in ("lead_id", "lead_key", "first_name", "organization")}
            ss.used_today = store().questions_today(lead["lead_key"])
            st.query_params["t"] = gate.make_token(lead, S.app_secret)
            st.rerun()


# ---------------------------------------------------------------- answers
def progress_html(ans: Answer, elapsed: float) -> str:
    now = STEPS.index(ans.step)
    rows = []
    for i, s in enumerate(STEPS):
        if s == "chart" and now <= i and ans.step != "chart":
            continue  # not every answer draws a chart; only show the step once it happens
        cls, mark = ("done", "&#10003;") if i < now else ("now", "") if i == now else ("", "")
        rows.append(f'<div class="af-step {cls}"><i>{mark}</i>{STEP_LABELS[s]}</div>')
    hint = ("Ask Fusion writes and runs real SQL against federal data, so most answers take 30 to 60 seconds."
            if elapsed < 75 else "Still working: this one needs several queries.")
    return (f'<div class="af-progress">{"".join(rows)}</div>'
            f'<div class="af-wait">{int(elapsed)}s &middot; {hint}</div>')


def render_table(df: pd.DataFrame, key: str) -> None:
    show = df.copy()
    cfg = {}
    for col in df.columns:
        lab = label(col)
        if is_year_column(col, df[col]):
            cfg[col] = st.column_config.NumberColumn(lab, format="%d")
        elif is_money_column(col) and pd.api.types.is_numeric_dtype(df[col]):
            # A median of dollar figures can land on .5; nobody budgets in half-dollars.
            show[col] = df[col].round(0).astype("Int64")
            cfg[col] = st.column_config.NumberColumn(lab if "$" in lab else f"{lab} ($)", format="localized")
        elif pd.api.types.is_integer_dtype(df[col]):
            cfg[col] = st.column_config.NumberColumn(lab, format="localized")
        elif pd.api.types.is_float_dtype(df[col]):
            show[col] = df[col].round(1)
            cfg[col] = st.column_config.NumberColumn(lab, format="localized")
        else:
            cfg[col] = st.column_config.TextColumn(lab)
    height = min(38 + 35 * len(show), 422)
    st.dataframe(show, hide_index=True, width="stretch", column_config=cfg, height=height, key=key)


def render_blocks(ans: Answer, key: str) -> None:
    blocks = ans.ordered()
    source = None
    for i, b in enumerate(blocks):
        if b.kind == "text":
            body, src = split_source(b.text)
            source = src or source
            if body.strip():
                st.markdown(markdown_safe(body))
        elif b.kind == "table" and b.table is not None and not b.table.empty:
            render_table(b.table, key=f"{key}_t{i}")
        elif b.kind == "chart" and b.chart:
            try:
                st.vega_lite_chart(theme.brand_chart(b.chart), width="stretch", key=f"{key}_c{i}")
            except Exception:  # a malformed spec must not take the answer down with it
                log.exception("chart failed to render")
    if source:
        st.html(f'<span class="af-source">{esc(source.removeprefix("Source:").strip())}</span>')


def save_feedback(qid: str) -> None:
    rating = ss.get(f"fb_{qid}")
    if rating is not None:
        store().save_feedback({"question_id": qid, "lead_id": (ss.lead or {}).get("lead_id"), "rating": int(rating)})


def save_comment(qid: str) -> None:
    text = (ss.get(f"fbc_{qid}") or "").strip()
    if text:
        store().save_feedback({"question_id": qid, "lead_id": (ss.lead or {}).get("lead_id"),
                               "rating": ss.get(f"fb_{qid}"), "comment": text[:2000]})
        ss[f"fbc_done_{qid}"] = True


MESSAGES = {
    "timeout": "That question needed more than two minutes, so Ask Fusion stopped rather than keep you waiting. "
               "Try narrowing it to one year, one state or one sector, or pick a suggestion below.",
    "error": "Ask Fusion couldn't reach the data just now. Please try again in a moment.",
    "empty": "Ask Fusion didn't produce an answer for that one. Try rephrasing, or pick a suggestion below.",
}


def render_message(m: dict, last: bool) -> None:
    with st.chat_message("user"):
        st.markdown(markdown_safe(m["question"]))
    with st.chat_message("assistant", avatar=str(APP / "assets" / "mark.svg")):
        ans: Answer = m["answer"]
        if m["status"] == "ok":
            render_blocks(ans, key=m["qid"])
        else:
            st.html(f'<div class="af-error">{esc(m.get("message") or MESSAGES.get(m["status"], MESSAGES["error"]))}</div>')

        if m["status"] == "ok":
            fb, dl, _ = st.columns([0.9, 2.2, 3], vertical_alignment="center")
            with fb:
                st.feedback("thumbs", key=f"fb_{m['qid']}", on_change=save_feedback, args=(m["qid"],),
                            disabled=bool(ss.pending))
            tables = [b.table for b in ans.ordered() if b.kind == "table" and b.table is not None]
            if tables:
                with dl:
                    st.download_button("Download data (CSV)", tables[0].to_csv(index=False).encode(),
                                       file_name="ask-fusion-ipeds.csv", mime="text/csv", type="tertiary",
                                       key=f"dl_{m['qid']}", icon=":material/download:")
            if ss.get(f"fb_{m['qid']}") == 0 and not ss.get(f"fbc_done_{m['qid']}"):
                st.text_input("What was wrong or missing? (optional)", key=f"fbc_{m['qid']}",
                              on_change=save_comment, args=(m["qid"],),
                              placeholder="e.g. wrong year, missing an institution, number looks off")
            elif ss.get(f"fbc_done_{m['qid']}"):
                st.caption("Thanks. Someone at Datatelligent reads every one of these.")
            if ans.sql:
                with st.expander("How Ask Fusion answered this"):
                    st.markdown("Ask Fusion translated your question into SQL against Datatelligent's curated IPEDS "
                                "views and ran it. Rates across institutions are pooled (total completers / total "
                                "students), never an average of percentages.")
                    for sql in ans.sql:
                        st.code(sql, language="sql", wrap_lines=True)
        if last:
            follow = ans.suggested if m["status"] == "ok" else []
            if follow:
                st.html('<div class="af-followups-label">Ask a follow-up</div>')
                for i, q in enumerate(follow):
                    st.button(markdown_safe(q), key=f"fu_{m['qid']}_{i}", on_click=queue, args=(q,),
                              disabled=bool(ss.pending), width="stretch")


def history() -> list[dict]:
    """Prior successful turns only: a failed turn left in made the agent answer it again."""
    turns = [m for m in ss.messages if m["status"] == "ok" and m["answer"].ok][-S.history_turns:]
    out = []
    for m in turns:
        out += [{"role": "user", "content": [{"type": "text", "text": m["question"]}]},
                {"role": "assistant", "content": [{"type": "text", "text": m["answer"].text}]}]
    return out


def limit_message() -> str | None:
    if (ss.used_today or 0) >= S.per_lead_daily:
        return (f"You've asked {S.per_lead_daily} questions today, which is the daily limit for the free version. "
                "It resets at midnight UTC. Want unlimited answers on your own institution's data? "
                f"[Talk to Datatelligent]({S.cta_url}).")
    if len(ss.messages) >= SESSION_CAP:
        return "That's a long conversation. Start a new one to keep going."
    if site_questions_today() >= S.global_daily:
        return ("Ask Fusion is unusually busy today and has paused new questions until tomorrow. "
                f"Sorry about that. [Talk to Datatelligent]({S.cta_url}) for a full demo.")
    return None


def run_pending() -> None:
    q = ss.pending
    qid = uuid.uuid4().hex
    rec = {"question_id": qid, "lead_id": ss.lead["lead_id"], "lead_key": ss.lead["lead_key"],
           "session_id": ss.session_id, "turn": len(ss.messages) + 1, "question": q, "agent": S.agent}

    blocked = limit_message()
    if blocked:
        ss.messages.append({"qid": qid, "question": q, "answer": Answer(), "status": "limit", "message": blocked})
        store().log_question({**rec, "status": "refused_limit"})
        return

    with st.chat_message("user"):
        st.markdown(markdown_safe(q))
    with st.chat_message("assistant", avatar=str(APP / "assets" / "mark.svg")):
        progress = st.empty()
        live = st.empty()
        ans, t0, status, err, last_draw = Answer(), time.time(), "ok", None, 0.0
        progress.html(progress_html(ans, 0))
        try:
            for ev, d in agent_client.run(q, agent_cfg(), history=history(), timeout=S.deadline_s, agent=S.agent):
                ans.apply(ev, d)
                elapsed = time.time() - t0
                if elapsed > S.deadline_s:
                    status = "timeout"
                    break
                if time.time() - last_draw > 0.25 or ev in ("response.table", "response.chart", "response.text"):
                    last_draw = time.time()
                    if ans.step == "write" and ans.blocks:
                        progress.empty()
                        with live.container():
                            render_blocks(ans, key=f"live_{qid}_{int(last_draw * 10)}")
                    else:
                        progress.html(progress_html(ans, elapsed))
        except requests.Timeout:
            status = "timeout"
        except Exception as exc:  # shown as a friendly message, recorded in full
            status, err = "error", repr(exc)[:2000]
            log.exception("agent call failed")
        if status == "ok" and ans.error:
            status, err = "error", ans.error
        if status == "ok" and TIMED_OUT in ans.text:
            status = "timeout"
        if status == "ok" and not ans.text:
            status = "empty"
        progress.empty()
        live.empty()

    seconds = round(time.time() - t0, 1)
    ss.messages.append({"qid": qid, "question": q, "answer": ans, "status": status, "seconds": seconds})
    ss.used_today = (ss.used_today or 0) + 1
    site_questions_today.clear()
    store().log_question({**rec, "answer": ans.text, "sql": ans.sql, "status": status, "error": err,
                          "seconds": seconds, "input_tokens": ans.input_tokens, "output_tokens": ans.output_tokens})


def render_welcome() -> None:
    lead = ss.lead
    greeting = f'Welcome, {esc(lead["first_name"])}.' if lead.get("first_name") else "Ask anything about U.S. colleges."
    st.html(f'<div class="af-welcome"><h2>{greeting}</h2>'
            '<p>Ask a question the way you would ask your IR office. Start with one of these, or type your own below.</p></div>')
    tabs = st.tabs([name for _, name in AUDIENCES])
    groups = starters()
    for tab, (key, _) in zip(tabs, AUDIENCES):
        with tab:
            cols = st.columns(2)
            for i, q in enumerate(groups.get(key, [])):
                cols[i % 2].button(markdown_safe(q), key=f"st_{key}_{i}", on_click=queue, args=(q,), width="stretch",
                                   disabled=bool(ss.pending))
    with st.expander("What Ask Fusion can and can't answer"):
        st.html(
            '<div class="af-scope">'
            '<div><b>Six subjects</b><span>Institution profile (state, sector, Carnegie class, HBCU, size), '
            'admissions (applicants, admit rate, yield, test policy, SAT/ACT), fall enrollment (level, race and '
            'ethnicity, gender, online), first-year retention, graduation rates (by race, gender and Pell), '
            'and aid and net price by family income.</span></div>'
            '<div><b>Five years, defined the IPEDS way</b><span>Collection years 2019&ndash;2023. &ldquo;2023&rdquo; '
            'means fall 2023 enrollment, the fall 2022 cohort&rsquo;s retention, the fall 2017 entering cohort&rsquo;s '
            'graduation, and the 2022&ndash;23 aid year. Every answer says which period it describes.</span></div>'
            '<div><b>What it won&rsquo;t guess at</b><span>Salaries, budgets and finances, degrees by major, anything '
            'after 2023, and any individual student. It tells you plainly when a question is outside the data.</span></div>'
            '</div>')


def your_data_band(where: str) -> None:
    """The offer behind the demo: the same assistant on the institution's own data.

    Shown under the form on the landing page and on every screen of the tool. It is the
    point of the public app, so it is a filled band, not a footnote."""
    st.html(
        f'<div class="af-yourdata af-yourdata--{where}">'
        '<div class="body">'
        '<span class="kicker">For your institution</span>'
        '<div class="title">We can do this on your institutional data, too.</div>'
        '<p>This demo answers from public IPEDS data. Datatelligent runs the same assistant on your own '
        'SIS, CRM and LMS data, inside your Snowflake account: retention risk, yield, course outcomes '
        'and more, answered the same way, with the query shown.</p></div>'
        f'<a class="af-cta-solid" href="{esc(S.cta_url)}" target="_blank" rel="noopener">'
        'Talk to us about your data &rarr;</a></div>')


# ---------------------------------------------------------------- page
st.html(theme.CSS)
header()
resolve_lead()

if not ss.lead:
    render_gate()
    footer()
    st.stop()

# The composer is pinned to the bottom of the window, so a footer in the page flow ends up ABOVE
# it. The data credit goes in the pinned bar, under the composer, instead; account controls go to
# the top row. st._bottom is the container Streamlit pins st.chat_input into (version pinned).
with st._bottom:
    st.chat_input("Ask about enrollment, admissions, retention, graduation, aid or net price…", key="composer",
                  on_submit=on_composer, disabled=bool(ss.pending), max_chars=1000)
    st.html('<div class="af-bottom-note"><span class="hint">Press Enter to ask</span> &middot; Data: IPEDS (NCES), 2019&ndash;2023, '
            'checked against NCES&rsquo;s published values &middot; &copy; Datatelligent &middot; '
            f'<a href="{esc(S.privacy_url)}" target="_blank" rel="noopener">Privacy</a></div>')

top_l, top_m, top_r = st.columns([2.2, 2.6, 0.9], vertical_alignment="center")
if ss.messages:
    with top_l:
        st.button("+ New conversation", type="tertiary", on_click=new_conversation, disabled=bool(ss.pending))
with top_m:
    left_today = max(S.per_lead_daily - (ss.used_today or 0), 0)
    parts = [esc(ss.lead.get(k) or "") for k in ("first_name", "organization")]
    parts.append(f"{left_today} of {S.per_lead_daily} questions left today")
    st.html(f'<div class="af-quota">{" &middot; ".join(p for p in parts if p)}</div>')
if not ss.lead.get("anonymous"):
    with top_r:
        st.button("Sign out", type="tertiary", on_click=sign_out, key="signout", disabled=bool(ss.pending))

# The conversation is a container created here but filled at the end, so everything below it is
# drawn BEFORE the 30-60s agent call. Otherwise the previous screen's content sits under the
# progress steps, greyed out as stale, for the whole wait.
conversation = st.container()

if not ss.pending:
    your_data_band("tool")

with conversation:
    if not ss.messages and not ss.pending:
        render_welcome()
    for i, m in enumerate(ss.messages):
        render_message(m, last=(i == len(ss.messages) - 1 and not ss.pending))
    if ss.pending:
        try:
            run_pending()
        finally:
            ss.pending = None
        st.rerun()
