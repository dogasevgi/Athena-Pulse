"""Owner-facing dashboard.  Run:  streamlit run dashboard.py"""
from __future__ import annotations
import pandas as pd
import streamlit as st

from aiso.config import RESTAURANT
from aiso.discovery import scorecard
from aiso.extract import norm
from aiso.storage import DB

ALIASES = [norm(RESTAURANT["name"])] + RESTAURANT["aliases"]
st.set_page_config(page_title=f"{RESTAURANT['name']}: AI search visibility", layout="wide")
db = DB("out/aiso.db")
runs = db.runs()
if not runs:
    st.info("No runs yet. Run `python cli.py discover` (or `python cli.py demo`) to collect data.")
    st.stop()

st.title(f"How often AI assistants recommend {RESTAURANT['name']}")
labels = {f"{r['label']} ({r['kind']}, {r['run_id']})": r["run_id"] for r in runs}
choice = st.selectbox("Run", list(labels), index=len(labels) - 1)
run_id = labels[choice]
if next(r for r in runs if r["run_id"] == run_id)["kind"] in ("demo", "sim"):
    st.warning("This run is a demo or simulation, not live assistant answers.")
sc = scorecard(db.results(run_id), ALIASES)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Mentioned in", f"{sc['mention_rate']:.0%} of answers")
c2.metric("In the top 3", f"{sc['top3_rate']:.0%}")
c3.metric("Average position", sc["avg_rank"] or "not mentioned")
c4.metric("Share of voice", f"{sc['share_of_voice']:.0%}")

left, right = st.columns(2)
with left:
    st.subheader("Where you show up, by type of question")
    cat = pd.DataFrame(sc["by_category"]).T[["mention_rate", "top_competitor", "n"]]
    st.bar_chart(cat["mention_rate"])
    st.dataframe(cat, use_container_width=True)
with right:
    st.subheader("Who gets recommended instead")
    st.dataframe(pd.DataFrame(sc["competitors"]), use_container_width=True)

st.subheader("Visibility over time")
trend = []
for r in runs:
    s = scorecard(db.results(r["run_id"]), ALIASES)
    if s.get("n"):
        trend.append({"run": f"{r['label']} {r['run_id'][:13]}", "kind": r["kind"],
                      "mention rate": s["mention_rate"], "top-3 rate": s["top3_rate"]})
tdf = pd.DataFrame(trend).set_index("run")
st.line_chart(tdf[["mention rate", "top-3 rate"]])
st.caption("Live runs show real progress; 'sim' runs are controlled before/after estimates.")

st.subheader("Questions where you were left out")
st.dataframe(pd.DataFrame(sc["lost_queries"]), use_container_width=True, height=320)
