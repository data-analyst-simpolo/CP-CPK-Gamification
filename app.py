import base64
import io
import math
import uuid
from datetime import datetime

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(
    page_title="Process Champion Challenge",
    page_icon="🏆",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -----------------------------------------------------------------------------
# DETERMINISTIC CONSTRAINED SIMULATION MODEL
# -----------------------------------------------------------------------------
# The game is intentionally deterministic. No unrelated random scenario is used.
# Every result comes from the selected actions, current state, fixed round target,
# budget constraint, and carry-over effect from the previous round.

ACTIONS = {
    "Increase Machine Speed": {
        "icon": "⚙️", "cost": 10,
        "prod": 8.0, "quality": -4.0, "mean": 0.010, "sigma_pct": 8.0,
        "description": "Raises conveyor throughput, but creates quality and variation risk.",
    },
    "Center Process Setting": {
        "icon": "🎯", "cost": 12,
        "prod": 0.0, "quality": 4.0, "center": 0.65, "sigma_pct": -5.0,
        "description": "Moves bulk-density mean toward target and improves Cpk.",
    },
    "Standardize Machine Settings": {
        "icon": "🛠️", "cost": 15,
        "prod": 2.0, "quality": 7.0, "mean": 0.0, "sigma_pct": -14.0,
        "description": "Reduces operating variation and stabilizes the process.",
    },
    "Operator Training": {
        "icon": "👷", "cost": 10,
        "prod": 3.0, "quality": 6.0, "mean": 0.0, "sigma_pct": -7.0,
        "description": "Improves adherence, quality, and operating consistency.",
    },
    "Preventive Maintenance": {
        "icon": "🔧", "cost": 18,
        "prod": -2.0, "quality": 5.0, "mean": 0.0, "sigma_pct": -18.0,
        "future_prod": 4.0,
        "description": "Consumes current time but reduces variation and adds future throughput.",
    },
    "Raw Material Control": {
        "icon": "🧱", "cost": 15,
        "prod": 0.0, "quality": 8.0, "mean": -0.004, "sigma_pct": -18.0,
        "description": "Improves powder consistency and bulk-density capability.",
    },
    "Line Balancing": {
        "icon": "🏭", "cost": 15,
        "prod": 7.0, "quality": 1.0, "mean": 0.0, "sigma_pct": -2.0,
        "description": "Raises throughput with limited quality disturbance.",
    },
    "Instrument Calibration": {
        "icon": "📏", "cost": 8,
        "prod": -1.0, "quality": 5.0, "center": 0.35, "sigma_pct": -6.0,
        "description": "Reduces measurement bias and improves Cpk confidence.",
    },
    "SMED Changeover": {
        "icon": "⏱️", "cost": 12,
        "prod": 6.0, "quality": 2.0, "mean": 0.0, "sigma_pct": -1.0,
        "description": "Recovers productive time without aggressive speed increase.",
    },
}

# Priority points determine how well an action addresses each fixed scenario.
# Each round has 25 possible points. The full-score path is shown below.
ROUND_CONFIG = {
    1: {
        "title": "Productivity Constraint",
        "scenario": "Increase productivity from 80 to at least 85 tiles/min without reducing quality below 74%.",
        "targets": {"productivity": 85.0, "quality": 74.0},
        "priority": {
            "Line Balancing": 10, "SMED Changeover": 10,
            "Increase Machine Speed": 7, "Operator Training": 5,
            "Standardize Machine Settings": 3, "Preventive Maintenance": 1,
            "Center Process Setting": 0, "Raw Material Control": 0,
            "Instrument Calibration": 0,
        },
        "optimal": ["Line Balancing", "SMED Changeover"],
    },
    2: {
        "title": "Quality Constraint",
        "scenario": "Improve quality to at least 80% while retaining productivity of at least 84 tiles/min.",
        "targets": {"quality": 80.0, "productivity": 84.0},
        "priority": {
            "Standardize Machine Settings": 10, "Operator Training": 10,
            "Raw Material Control": 8, "Instrument Calibration": 6,
            "Center Process Setting": 5, "Preventive Maintenance": 4,
            "Line Balancing": 2, "SMED Changeover": 1,
            "Increase Machine Speed": 0,
        },
        "optimal": ["Standardize Machine Settings", "Operator Training"],
    },
    3: {
        "title": "Bulk-Density Capability Constraint",
        "scenario": "Stabilize bulk density and achieve Cp ≥ 1.33 and Cpk ≥ 1.33.",
        "targets": {"cp": 1.33, "cpk": 1.33},
        "priority": {
            "Raw Material Control": 10, "Center Process Setting": 10,
            "Standardize Machine Settings": 8, "Instrument Calibration": 7,
            "Preventive Maintenance": 6, "Operator Training": 4,
            "Line Balancing": 1, "SMED Changeover": 0,
            "Increase Machine Speed": 0,
        },
        "optimal": ["Raw Material Control", "Center Process Setting"],
    },
    4: {
        "title": "Balanced Sustenance Constraint",
        "scenario": "Sustain productivity ≥ 90 tiles/min, quality ≥ 90%, and bulk-density Cpk ≥ 1.33.",
        "targets": {"productivity": 90.0, "quality": 90.0, "cpk": 1.33},
        "priority": {
            "Preventive Maintenance": 10, "Line Balancing": 10,
            "Standardize Machine Settings": 8, "SMED Changeover": 7,
            "Operator Training": 6, "Raw Material Control": 5,
            "Center Process Setting": 4, "Instrument Calibration": 3,
            "Increase Machine Speed": 2,
        },
        "optimal": ["Preventive Maintenance", "Line Balancing"],
    },
}

LEADERBOARD_PATH = "data/leaderboard.csv"
LOG_PATH = "data/simulation_log.csv"
LEADERBOARD_COLUMNS = [
    "Session ID", "Team Name", "Department", "Round", "Productivity",
    "Quality %", "Bulk Density Cp", "Bulk Density Cpk", "Budget Remaining",
    "Round Score", "Total Score", "Updated At",
]
LOG_COLUMNS = [
    "Session ID", "Team Name", "Department", "Round", "Scenario",
    "Action 1", "Action 2", "Carryover Effect", "Productivity", "Quality %",
    "Bulk Density Mean", "Bulk Density Sigma", "Cp", "Cpk", "UCL", "LCL",
    "USL", "LSL", "Budget Remaining", "Priority Score", "Constraint Score",
    "Round Score", "Total Score", "Created At",
]

st.markdown("""
<style>
.stApp{background:radial-gradient(circle at 8% 4%,#dcfce7 0,transparent 22%),linear-gradient(135deg,#f8fffa,#eef7f0)}
.block-container{max-width:1320px;padding-top:1.1rem;padding-bottom:3rem}#MainMenu,footer{visibility:hidden}
.hero{padding:1.8rem 2rem;border-radius:25px;background:linear-gradient(125deg,#103d27,#166534 52%,#16a34a);color:white;box-shadow:0 18px 48px rgba(20,83,45,.2);margin-bottom:1rem}.hero h1{margin:0}.hero p{margin:.35rem 0 0;opacity:.9}
.scenario{padding:1rem 1.15rem;border-radius:16px;background:#fff7ed;border:1px solid #fdba74;margin:.8rem 0}.carry{padding:.9rem 1rem;border-radius:14px;background:#eff6ff;border:1px solid #93c5fd;margin:.7rem 0}
.equipment{background:#fff;border:1px solid #d9e8de;border-radius:17px;padding:.9rem;height:100%;box-shadow:0 8px 22px rgba(20,83,45,.07)}.equipment.locked{opacity:.4;filter:grayscale(.8)}.equipment .ico{font-size:2rem}.equipment h4{margin:.25rem 0}.equipment p{font-size:.84rem;color:#64748b;margin:.1rem 0}.impact-box{margin-top:.55rem;padding:.55rem .65rem;border-radius:10px;background:#f8fafc;border:1px solid #dbe5df;font-size:.78rem;line-height:1.45}.impact-positive{color:#166534;font-weight:700}.impact-negative{color:#b91c1c;font-weight:700}.impact-neutral{color:#475569;font-weight:700}
.process-wrap{background:#fff;border:1px solid #b9d8c1;border-radius:22px;padding:1.1rem;overflow-x:auto}.process-line{min-width:1150px;display:flex;align-items:center;gap:8px;position:relative;padding:22px 8px 52px}.unit{width:135px;min-height:82px;border:2px solid #15803d;border-radius:13px;background:linear-gradient(180deg,#fff,#eefbf1);display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;font-weight:750}.unit span{font-size:1.8rem}.arrow{width:42px;height:12px;background:#15803d;position:relative}.arrow:after{content:"";position:absolute;right:-13px;top:-7px;border-left:14px solid #15803d;border-top:13px solid transparent;border-bottom:13px solid transparent}.belt{position:absolute;left:12px;right:12px;bottom:20px;height:10px;border-radius:6px;background:repeating-linear-gradient(90deg,#14532d 0 24px,#86efac 24px 38px);animation:beltMove .75s linear infinite}.tile{position:absolute;bottom:31px;width:34px;height:20px;border-radius:3px;background:#f59e0b;border:2px solid #9a5a06;animation:tileMove 8s linear infinite}.tile.t2{animation-delay:-2.7s}.tile.t3{animation-delay:-5.4s}.flow-label{position:absolute;left:12px;bottom:0;color:#166534;font-size:.78rem;font-weight:700}@keyframes beltMove{to{background-position:38px 0}}@keyframes tileMove{0%{left:2%}100%{left:95%}}
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{border-radius:12px;min-height:45px;font-weight:700}.stFormSubmitButton>button{background:#15803d!important;color:white!important;border:0!important}
</style>
""", unsafe_allow_html=True)


def github_configured():
    return all(str(st.secrets.get(k, "")).strip() for k in ["GITHUB_TOKEN", "GITHUB_OWNER", "GITHUB_REPO"])


def github_headers():
    return {"Authorization": f"Bearer {st.secrets['GITHUB_TOKEN']}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}


def github_url(path):
    return f"https://api.github.com/repos/{st.secrets['GITHUB_OWNER']}/{st.secrets['GITHUB_REPO']}/contents/{path}"


def read_remote_csv(path, columns):
    response = requests.get(github_url(path), headers=github_headers(), params={"ref": st.secrets.get("GITHUB_BRANCH", "main")}, timeout=30)
    if response.status_code == 404:
        return pd.DataFrame(columns=columns), None
    response.raise_for_status()
    payload = response.json()
    try:
        frame = pd.read_csv(io.BytesIO(base64.b64decode(payload["content"])))
    except pd.errors.EmptyDataError:
        frame = pd.DataFrame(columns=columns)
    for column in columns:
        if column not in frame:
            frame[column] = ""
    return frame[columns], payload["sha"]


def write_remote_csv(path, frame, columns, sha, message):
    body = {"message": message, "content": base64.b64encode(frame[columns].to_csv(index=False).encode()).decode(), "branch": st.secrets.get("GITHUB_BRANCH", "main")}
    if sha:
        body["sha"] = sha
    response = requests.put(github_url(path), headers=github_headers(), json=body, timeout=30)
    response.raise_for_status()


def append_remote_csv(path, row, columns, message):
    frame, sha = read_remote_csv(path, columns)
    frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
    write_remote_csv(path, frame, columns, sha, message)


def update_leaderboard(row):
    if github_configured():
        frame, sha = read_remote_csv(LEADERBOARD_PATH, LEADERBOARD_COLUMNS)
        frame = frame[~frame["Session ID"].astype(str).eq(str(row["Session ID"]))]
        frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
        write_remote_csv(LEADERBOARD_PATH, frame, LEADERBOARD_COLUMNS, sha, "Update constrained simulation leaderboard")
    local = st.session_state.get("local_lb", pd.DataFrame(columns=LEADERBOARD_COLUMNS))
    local = local[~local["Session ID"].astype(str).eq(str(row["Session ID"]))]
    st.session_state.local_lb = pd.concat([local, pd.DataFrame([row])], ignore_index=True)


def get_leaderboard():
    if github_configured():
        try:
            return read_remote_csv(LEADERBOARD_PATH, LEADERBOARD_COLUMNS)[0]
        except Exception as error:
            st.caption(f"Shared leaderboard temporarily unavailable: {error}")
    return st.session_state.get("local_lb", pd.DataFrame(columns=LEADERBOARD_COLUMNS))


def initial_state():
    return {
        "round": 0,
        "productivity": 80.0,
        "quality": 72.0,
        "budget": 120.0,
        "future_productivity": 0.0,
        "bulk": {"mean": 1.925, "sigma": 0.030, "target": 1.900, "lsl": 1.820, "usl": 1.980},
        "total_score": 0.0,
        "previous_actions": [],
        "carryover_text": "No previous-round carryover. The process starts at baseline.",
    }


def bulk_metrics(bulk, round_no, team_id):
    sigma = max(0.004, bulk["sigma"])
    cp = (bulk["usl"] - bulk["lsl"]) / (6 * sigma)
    cpk = min((bulk["usl"] - bulk["mean"]) / (3 * sigma), (bulk["mean"] - bulk["lsl"]) / (3 * sigma))
    ucl = bulk["mean"] + 3 * sigma
    lcl = bulk["mean"] - 3 * sigma
    # Deterministic visual observations. Seed depends only on team/session and round.
    rng = np.random.default_rng(abs(hash((team_id, round_no, "bulk"))) % (2**32))
    readings = rng.normal(bulk["mean"], sigma, 25)
    return {"cp": cp, "cpk": cpk, "ucl": ucl, "lcl": lcl, "readings": readings}


def apply_carryover(state):
    text = []
    previous = set(state["previous_actions"])
    # Deterministic progression: previous choices create the next-round starting condition.
    if "Increase Machine Speed" in previous:
        state["productivity"] += 2.0
        state["quality"] -= 3.0
        state["bulk"]["sigma"] *= 1.06
        text.append("Previous speed increase keeps productivity high, but quality and bulk-density stability are lower.")
    if "Preventive Maintenance" in previous:
        state["productivity"] += 4.0
        state["bulk"]["sigma"] *= 0.96
        text.append("Previous maintenance now provides higher throughput and lower bulk-density variation.")
    if "Raw Material Control" in previous:
        state["quality"] += 2.0
        state["bulk"]["sigma"] *= 0.95
        text.append("Previous raw-material control improves quality and bulk-density consistency.")
    if "Center Process Setting" in previous:
        state["bulk"]["mean"] += (state["bulk"]["target"] - state["bulk"]["mean"]) * 0.15
        text.append("Previous centering keeps the bulk-density mean closer to target.")
    if "Line Balancing" in previous or "SMED Changeover" in previous:
        state["productivity"] += 1.0
        text.append("Previous flow improvement provides a small sustained productivity gain.")
    if not text:
        text.append("Previous choices provide no sustained benefit; the fixed scenario starts from the current process condition.")
    state["carryover_text"] = " ".join(text)


def apply_action(state, action_name):
    action = ACTIONS[action_name]
    state["budget"] -= action["cost"]
    state["productivity"] += action.get("prod", 0.0)
    state["quality"] += action.get("quality", 0.0)
    state["bulk"]["sigma"] *= 1 + action.get("sigma_pct", 0.0) / 100
    state["bulk"]["mean"] += action.get("mean", 0.0)
    if action.get("center"):
        state["bulk"]["mean"] += (state["bulk"]["target"] - state["bulk"]["mean"]) * action["center"]
    state["future_productivity"] += action.get("future_prod", 0.0)


def constraint_score(round_no, state, metrics):
    targets = ROUND_CONFIG[round_no]["targets"]
    ratios = []
    for key, target in targets.items():
        actual = metrics[key] if key in metrics else state[key]
        ratios.append(min(1.0, actual / target))
    return 5.0 * min(ratios), all(ratio >= 1.0 for ratio in ratios)


def priority_score(round_no, selected):
    scores = ROUND_CONFIG[round_no]["priority"]
    return min(20.0, sum(scores[action] for action in selected))


def run_round():
    state = st.session_state.state.copy()
    next_round = state["round"] + 1
    if next_round > 4:
        return
    selected = {
        st.session_state.get("selected_action_1", "None"),
        st.session_state.get("selected_action_2", "None"),
    } - {"None"}
    cost = sum(ACTIONS[action]["cost"] for action in selected)
    if cost > state["budget"]:
        st.error("Selected activities exceed the available budget.")
        return

    # Carryover is applied before the fixed round scenario and current actions.
    if state["round"] > 0:
        apply_carryover(state)
    if state["future_productivity"]:
        state["productivity"] += state["future_productivity"]

    for action in selected:
        apply_action(state, action)

    state["budget"] = max(0.0, state["budget"])
    state["quality"] = max(0.0, min(100.0, state["quality"]))
    state["productivity"] = max(0.0, state["productivity"])
    state["round"] = next_round
    state["previous_actions"] = sorted(selected)

    bulk = bulk_metrics(state["bulk"], next_round, st.session_state.session_id)
    metrics = {
        "productivity": state["productivity"],
        "quality": state["quality"],
        "cp": bulk["cp"],
        "cpk": bulk["cpk"],
    }
    p_score = priority_score(next_round, selected)
    c_score, constraints_met = constraint_score(next_round, state, metrics)
    round_score = p_score + c_score
    state["total_score"] += round_score

    st.session_state.state = state
    st.session_state.bulk_result = bulk
    st.session_state.round_result = {
        "priority_score": p_score,
        "constraint_score": c_score,
        "round_score": round_score,
        "constraints_met": constraints_met,
        "selected": sorted(selected),
    }

    leaderboard_row = {
        "Session ID": st.session_state.session_id,
        "Team Name": st.session_state.team_name,
        "Department": st.session_state.department,
        "Round": next_round,
        "Productivity": round(state["productivity"], 2),
        "Quality %": round(state["quality"], 2),
        "Bulk Density Cp": round(bulk["cp"], 3),
        "Bulk Density Cpk": round(bulk["cpk"], 3),
        "Budget Remaining": round(state["budget"], 1),
        "Round Score": round(round_score, 2),
        "Total Score": round(state["total_score"], 2),
        "Updated At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    update_leaderboard(leaderboard_row)

    if github_configured():
        action_list = sorted(selected)
        log_row = {
            "Session ID": st.session_state.session_id,
            "Team Name": st.session_state.team_name,
            "Department": st.session_state.department,
            "Round": next_round,
            "Scenario": ROUND_CONFIG[next_round]["scenario"],
            "Action 1": action_list[0] if action_list else "None",
            "Action 2": action_list[1] if len(action_list) > 1 else "None",
            "Carryover Effect": state["carryover_text"],
            "Productivity": state["productivity"],
            "Quality %": state["quality"],
            "Bulk Density Mean": state["bulk"]["mean"],
            "Bulk Density Sigma": state["bulk"]["sigma"],
            "Cp": bulk["cp"], "Cpk": bulk["cpk"],
            "UCL": bulk["ucl"], "LCL": bulk["lcl"],
            "USL": state["bulk"]["usl"], "LSL": state["bulk"]["lsl"],
            "Budget Remaining": state["budget"],
            "Priority Score": p_score,
            "Constraint Score": c_score,
            "Round Score": round_score,
            "Total Score": state["total_score"],
            "Created At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            append_remote_csv(LOG_PATH, log_row, LOG_COLUMNS, f"Add constrained round {next_round}")
        except Exception as error:
            st.warning(f"Round completed; GitHub log save failed: {error}")
    st.rerun()


def process_animation(productivity):
    duration = max(3, min(14, 900 / max(productivity, 1)))
    st.markdown(f"""
<div class="process-wrap"><div class="process-line">
<div class="unit"><span>⚗️</span>Slip House</div><div class="arrow"></div>
<div class="unit"><span>🌪️</span>Spray Dryer</div><div class="arrow"></div>
<div class="unit"><span>🗄️</span>Silo</div><div class="arrow"></div>
<div class="unit"><span>🗜️</span>Press</div><div class="arrow"></div>
<div class="unit"><span>🎨</span>Glaze Line</div><div class="arrow"></div>
<div class="unit"><span>🔥</span>Kiln</div><div class="arrow"></div>
<div class="unit"><span>💎</span>Polishing</div><div class="arrow"></div>
<div class="unit"><span>📦</span>Packing</div>
<div class="belt"></div><div class="tile" style="animation-duration:{duration}s"></div><div class="tile t2" style="animation-duration:{duration}s"></div><div class="tile t3" style="animation-duration:{duration}s"></div>
<div class="flow-label">Conveyor speed linked to productivity: {productivity:.1f} tiles/min</div>
</div></div>""", unsafe_allow_html=True)


def bulk_spc_graph(state, result):
    x = list(range(1, 26))
    bulk = state["bulk"]
    figure = go.Figure(go.Scatter(x=x, y=result["readings"], mode="lines+markers", name="Bulk Density", marker=dict(size=7, color="#0f6bca")))
    for value, name, color, dash in [
        (result["ucl"], "UCL", "#dc2626", "dot"),
        (result["lcl"], "LCL", "#dc2626", "dot"),
        (bulk["usl"], "USL", "#7c3aed", "dashdot"),
        (bulk["lsl"], "LSL", "#f59e0b", "dashdot"),
        (bulk["target"], "Target", "#15803d", "dash"),
    ]:
        figure.add_trace(go.Scatter(x=x, y=[value] * 25, name=name, mode="lines", line=dict(color=color, dash=dash)))
    figure.update_layout(title="Bulk Density SPC Graph", xaxis_title="Simulated Observation", yaxis_title="Bulk Density (g/cc)")
    st.plotly_chart(figure, use_container_width=True)


def equation_panel():
    with st.expander("📐 Constrained progression model and score equations"):
        st.markdown("""
### State progression

```text
Productivity(r) = Productivity(r-1)
                + Σ Productivity_Effect(action)
                + Carryover_Productivity(previous actions)

Quality(r)      = Quality(r-1)
                + Σ Quality_Effect(action)
                + Carryover_Quality(previous actions)

Mean_BD(r)      = Mean_BD(r-1)
                + Σ Mean_Shift(action)
                + Carryover_Centering(previous actions)

Sigma_BD(r)     = Sigma_BD(r-1)
                × Π[1 + Sigma_Effect(action)]
                × Carryover_Variation(previous actions)

Budget(r)       = Budget(r-1) - Σ Cost(action) ≥ 0
```

### Capability equations

```text
Cp  = (USL - LSL) / (6 × Sigma_BD)
Cpk = min[(USL - Mean_BD)/(3 × Sigma_BD),
          (Mean_BD - LSL)/(3 × Sigma_BD)]
UCL = Mean_BD + 3 × Sigma_BD
LCL = Mean_BD - 3 × Sigma_BD
```

### Round score

```text
Priority Score   = min(20, sum of scenario-priority points)
Constraint Score = 5 × minimum achievement ratio across round constraints
Round Score      = Priority Score + Constraint Score
Maximum/Round    = 25
Maximum/Game     = 100
```

The model is deterministic. Every displayed condition comes from the fixed scenario,
selected activities, and previous-round carryover. No unrelated random event is used.
""")


def hero():
    st.markdown("<div class='hero'><h1>🏆 Process Champion Challenge</h1><p>Constraint-driven manufacturing simulation with deterministic carryover and bulk-density SPC.</p></div>", unsafe_allow_html=True)


def registration_page():
    hero()
    process_animation(80)
    _, center, _ = st.columns([1, 1.5, 1])
    with center:
        with st.form("registration"):
            team = st.text_input("Team name")
            department = st.selectbox("Department", ["Slip House", "Spray Dryer", "Press", "Glaze Line", "Kiln", "Polishing", "Quality", "Maintenance"])
            submitted = st.form_submit_button("Start Simulation →", use_container_width=True)
        if submitted:
            if not team.strip():
                st.error("Enter a team name.")
            else:
                st.session_state.update(
                    registered=True, session_id=str(uuid.uuid4()), team_name=team.strip(),
                    department=department, state=initial_state(), bulk_result=None,
                    round_result=None, local_lb=pd.DataFrame(columns=LEADERBOARD_COLUMNS),
                )
                st.rerun()


def action_impact_html(action):
    """Return every direct model effect shown on the activity tile.

    No hidden cross-parameter effect is applied. If a parameter is not listed on the
    tile, the action does not directly change that parameter.
    """
    impacts = []

    productivity = float(action.get("prod", 0.0))
    if productivity > 0:
        impacts.append(("positive", f"Productivity +{productivity:g} tiles/min"))
    elif productivity < 0:
        impacts.append(("negative", f"Productivity {productivity:g} tiles/min"))
    else:
        impacts.append(("neutral", "Productivity: no direct change"))

    quality = float(action.get("quality", 0.0))
    if quality > 0:
        impacts.append(("positive", f"Quality +{quality:g} percentage points"))
    elif quality < 0:
        impacts.append(("negative", f"Quality {quality:g} percentage points"))
    else:
        impacts.append(("neutral", "Quality: no direct change"))

    sigma_pct = float(action.get("sigma_pct", 0.0))
    if sigma_pct < 0:
        impacts.append(("positive", f"Bulk-density variation {sigma_pct:g}%"))
    elif sigma_pct > 0:
        impacts.append(("negative", f"Bulk-density variation +{sigma_pct:g}%"))
    else:
        impacts.append(("neutral", "Bulk-density variation: no direct change"))

    mean_shift = float(action.get("mean", 0.0))
    if mean_shift:
        direction = "+" if mean_shift > 0 else ""
        impacts.append(("negative", f"Bulk-density mean shift {direction}{mean_shift:.3f} g/cc"))

    center = float(action.get("center", 0.0))
    if center > 0:
        impacts.append(("positive", f"Moves bulk-density mean {center * 100:.0f}% toward target"))

    future_productivity = float(action.get("future_prod", 0.0))
    if future_productivity > 0:
        impacts.append(("positive", f"Future-round productivity +{future_productivity:g} tiles/min"))

    return "".join(
        f"<div class='impact-{kind}'>{'▲' if kind == 'positive' else '▼' if kind == 'negative' else '•'} {text}</div>"
        for kind, text in impacts
    )


def action_panel(state, next_round):
    config = ROUND_CONFIG[next_round]
    st.info(
        "Every direct effect is displayed on the activity tile. "
        "No hidden negative impact is applied to any other parameter."
    )
    columns = st.columns(3)
    for index, (name, action) in enumerate(ACTIONS.items()):
        affordable = action["cost"] <= state["budget"]
        css_class = "equipment" if affordable else "equipment locked"
        with columns[index % 3]:
            st.markdown(
                f"<div class='{css_class}'><div class='ico'>{action['icon']}</div>"
                f"<h4>{name}</h4><p>{action['description']}</p>"
                f"<div class='impact-box'>{action_impact_html(action)}</div>"
                f"<p><b>Cost: {action['cost']} | Scenario points: {config['priority'][name]}</b></p></div>",
                unsafe_allow_html=True,
            )

    affordable_1 = [name for name, action in ACTIONS.items() if action["cost"] <= state["budget"]]
    if state["budget"] <= 0 or not affordable_1:
        st.warning("Budget exhausted or insufficient. No activity can be selected.")
        st.button("Run Round", disabled=True, use_container_width=True)
        return

    left, right = st.columns(2)
    action_1 = left.selectbox("Action 1", ["None"] + affordable_1, key=f"a1_{next_round}")
    first_cost = ACTIONS[action_1]["cost"] if action_1 != "None" else 0
    affordable_2 = [name for name, action in ACTIONS.items() if action["cost"] <= state["budget"] - first_cost and name != action_1]
    action_2 = right.selectbox("Action 2", ["None"] + affordable_2, key=f"a2_{next_round}")
    st.session_state.selected_action_1 = action_1
    st.session_state.selected_action_2 = action_2
    selected = {action_1, action_2} - {"None"}
    cost = sum(ACTIONS[action]["cost"] for action in selected)
    predicted_priority = priority_score(next_round, selected)
    a, b, c = st.columns(3)
    a.metric("Current Budget", f"{state['budget']:.0f}")
    b.metric("Selected Cost", f"{cost:.0f}")
    c.metric("Visible Priority Points", f"{predicted_priority:.0f} / 20")
    st.button("Run Constrained Round ▶", type="primary", disabled=cost > state["budget"], use_container_width=True, on_click=run_round)


def full_score_path():
    with st.expander("🏆 Full-score path: how to achieve 100/100"):
        st.markdown("""
Select the following two activities in each round. The path is budget-feasible and
reaches the fixed constraints when no selection is changed.

```text
Round 1: Line Balancing + SMED Changeover
Round 2: Standardize Machine Settings + Operator Training
Round 3: Raw Material Control + Center Process Setting
Round 4: Preventive Maintenance + Line Balancing
```

Scoring on this path:

```text
Each round priority score   = 20
Each round constraint score = 5
Each round total            = 25
Four-round total            = 100
```

Different activities can still improve the process, but receive fewer or zero priority
points according to how directly the activity addresses the fixed round scenario.
""")


def leaderboard_section():
    st.subheader("🏅 Live Leaderboard")
    leaderboard = get_leaderboard()
    if leaderboard.empty:
        st.info("Complete a round to populate the leaderboard.")
        return
    for column in ["Total Score", "Round Score", "Bulk Density Cpk", "Productivity", "Quality %"]:
        leaderboard[column] = pd.to_numeric(leaderboard[column], errors="coerce")
    leaderboard = leaderboard.sort_values(["Total Score", "Bulk Density Cpk", "Productivity"], ascending=[False, False, False]).reset_index(drop=True)
    leaderboard.insert(0, "Rank", range(1, len(leaderboard) + 1))
    st.dataframe(leaderboard[["Rank", "Team Name", "Department", "Round", "Productivity", "Quality %", "Bulk Density Cp", "Bulk Density Cpk", "Budget Remaining", "Round Score", "Total Score"]], use_container_width=True, hide_index=True)


def dashboard_page():
    hero()
    state = st.session_state.state
    process_animation(state["productivity"])
    equation_panel()
    full_score_path()

    with st.sidebar:
        st.success(f"Team: {st.session_state.team_name}")
        st.metric("Round", f"{state['round']} / 4")
        st.metric("Total Score", f"{state['total_score']:.1f} / 100")
        st.metric("Budget", f"{state['budget']:.0f}")
        if st.button("Restart Simulation", use_container_width=True):
            st.session_state.clear()
            st.rerun()

    bulk = st.session_state.bulk_result or bulk_metrics(state["bulk"], max(1, state["round"]), st.session_state.session_id)
    a, b, c, d, e = st.columns(5)
    a.metric("Productivity", f"{state['productivity']:.1f} tiles/min")
    b.metric("Quality", f"{state['quality']:.1f}%")
    c.metric("Bulk Density Cp", f"{bulk['cp']:.2f}")
    d.metric("Bulk Density Cpk", f"{bulk['cpk']:.2f}")
    e.metric("Budget", f"{state['budget']:.0f}")

    if state["round"] > 0:
        st.subheader("Bulk Density SPC")
        bulk_spc_graph(state, bulk)
        if st.session_state.round_result:
            result = st.session_state.round_result
            m1, m2, m3 = st.columns(3)
            m1.metric("Priority Score", f"{result['priority_score']:.1f} / 20")
            m2.metric("Constraint Score", f"{result['constraint_score']:.1f} / 5")
            m3.metric("Round Score", f"{result['round_score']:.1f} / 25")
            if result["constraints_met"]:
                st.success("All fixed constraints for this round were achieved.")
            else:
                st.warning("One or more round constraints were not fully achieved.")

    if state["round"] < 4:
        next_round = state["round"] + 1
        config = ROUND_CONFIG[next_round]
        st.markdown(
            f"<div class='scenario'><h3>Round {next_round}: {config['title']}</h3>"
            f"<p>{config['scenario']}</p></div>",
            unsafe_allow_html=True,
        )
        if state["round"] > 0:
            # Preview deterministic carryover without mutating the current state.
            preview = state.copy()
            preview["bulk"] = state["bulk"].copy()
            apply_carryover(preview)
            st.markdown(f"<div class='carry'><b>Carryover from previous actions:</b> {preview['carryover_text']}</div>", unsafe_allow_html=True)
        action_panel(state, next_round)
    else:
        if state["total_score"] >= 99.99:
            st.balloons()
            st.success("Perfect score achieved: 100/100. Process Champion!")
        else:
            st.success(f"Simulation complete. Final score: {state['total_score']:.1f}/100")

    leaderboard_section()


if st.session_state.get("registered"):
    dashboard_page()
else:
    registration_page()
