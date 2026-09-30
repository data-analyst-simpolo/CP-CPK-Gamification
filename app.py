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

st.set_page_config(page_title="Process Champion Challenge", page_icon="🏆", layout="wide", initial_sidebar_state="expanded")

ACTIONS = {
    "Increase Machine Speed": {"icon":"⚙️","cost":10,"prod":8.0,"quality":-4.0,"mean":0.010,"sigma_pct":8.0,"description":"Raises conveyor throughput, with a visible quality and variation trade-off."},
    "Center Process Setting": {"icon":"🎯","cost":12,"prod":0.0,"quality":4.0,"center":0.65,"sigma_pct":-5.0,"description":"Moves bulk-density mean toward target and improves Cpk."},
    "Standardize Machine Settings": {"icon":"🛠️","cost":15,"prod":2.0,"quality":7.0,"sigma_pct":-14.0,"description":"Reduces operating variation and stabilizes the process."},
    "Operator Training": {"icon":"👷","cost":10,"prod":3.0,"quality":6.0,"sigma_pct":-7.0,"description":"Improves adherence, quality, and operating consistency."},
    "Preventive Maintenance": {"icon":"🔧","cost":18,"prod":-2.0,"quality":5.0,"sigma_pct":-18.0,"future_prod":4.0,"description":"Consumes current time but reduces variation and adds future throughput."},
    "Raw Material Control": {"icon":"🧱","cost":15,"prod":0.0,"quality":8.0,"mean":-0.004,"sigma_pct":-18.0,"description":"Improves powder consistency and bulk-density capability."},
    "Line Balancing": {"icon":"🏭","cost":15,"prod":7.0,"quality":1.0,"sigma_pct":-2.0,"description":"Raises throughput with limited process disturbance."},
    "Instrument Calibration": {"icon":"📏","cost":8,"prod":-1.0,"quality":5.0,"center":0.35,"sigma_pct":-6.0,"description":"Reduces measurement bias and improves Cpk confidence."},
    "SMED Changeover": {"icon":"⏱️","cost":12,"prod":6.0,"quality":2.0,"sigma_pct":-1.0,"description":"Recovers productive time without aggressive speed increase."},
}

ROUND_CONFIG = {
    1:{"title":"Productivity Constraint","scenario":"Increase productivity from 80 to at least 85 tiles/min without reducing quality below 74%.","targets":{"productivity":85.0,"quality":74.0},"priority":{"Line Balancing":10,"SMED Changeover":10,"Increase Machine Speed":7,"Operator Training":5,"Standardize Machine Settings":3,"Preventive Maintenance":1,"Center Process Setting":0,"Raw Material Control":0,"Instrument Calibration":0}},
    2:{"title":"Quality Constraint","scenario":"Improve quality to at least 80% while retaining productivity of at least 84 tiles/min.","targets":{"quality":80.0,"productivity":84.0},"priority":{"Standardize Machine Settings":10,"Operator Training":10,"Raw Material Control":8,"Instrument Calibration":6,"Center Process Setting":5,"Preventive Maintenance":4,"Line Balancing":2,"SMED Changeover":1,"Increase Machine Speed":0}},
    3:{"title":"Bulk-Density Capability Constraint","scenario":"Stabilize bulk density and achieve Cp ≥ 1.33 and Cpk ≥ 1.33.","targets":{"cp":1.33,"cpk":1.33},"priority":{"Raw Material Control":10,"Center Process Setting":10,"Standardize Machine Settings":8,"Instrument Calibration":7,"Preventive Maintenance":6,"Operator Training":4,"Line Balancing":1,"SMED Changeover":0,"Increase Machine Speed":0}},
    4:{"title":"Balanced Sustenance Constraint","scenario":"Sustain productivity ≥ 90 tiles/min, quality ≥ 90%, and bulk-density Cpk ≥ 1.33.","targets":{"productivity":90.0,"quality":90.0,"cpk":1.33},"priority":{"Preventive Maintenance":10,"Line Balancing":10,"Standardize Machine Settings":8,"SMED Changeover":7,"Operator Training":6,"Raw Material Control":5,"Center Process Setting":4,"Instrument Calibration":3,"Increase Machine Speed":2}},
}

LEADERBOARD_PATH = "data/leaderboard.csv"
LOG_PATH = "data/simulation_log.csv"
LEADERBOARD_COLUMNS = ["Session ID","Team Name","Team Members","Round","Productivity","Quality %","Bulk Density Cp","Bulk Density Cpk","Budget Remaining","Round Score","Total Score","Updated At"]
LOG_COLUMNS = ["Session ID","Team Name","Team Members","Round","Scenario","Action 1","Action 2","Carryover Effect","Productivity","Quality %","Bulk Density Mean","Bulk Density Sigma","Cp","Cpk","UCL","LCL","USL","LSL","Budget Remaining","Priority Score","Constraint Score","Round Score","Total Score","Created At"]

st.markdown("""<style>
.stApp{background:radial-gradient(circle at 8% 4%,#dcfce7 0,transparent 22%),linear-gradient(135deg,#f8fffa,#eef7f0)}.block-container{max-width:1320px;padding-top:1.1rem;padding-bottom:3rem}#MainMenu,footer{visibility:hidden}.hero{padding:1.8rem 2rem;border-radius:25px;background:linear-gradient(125deg,#103d27,#166534 52%,#16a34a);color:white;box-shadow:0 18px 48px rgba(20,83,45,.2);margin-bottom:1rem}.hero h1{margin:0}.hero p{margin:.35rem 0 0;opacity:.9}.scenario{padding:1rem 1.15rem;border-radius:16px;background:#fff7ed;border:1px solid #fdba74;margin:.8rem 0}.carry{padding:.9rem 1rem;border-radius:14px;background:#eff6ff;border:1px solid #93c5fd;margin:.7rem 0}.equipment{background:#fff;border:1px solid #d9e8de;border-radius:17px;padding:.9rem;height:100%;box-shadow:0 8px 22px rgba(20,83,45,.07)}.equipment.locked{opacity:.4;filter:grayscale(.8)}.equipment .ico{font-size:2rem}.equipment h4{margin:.25rem 0}.equipment p{font-size:.84rem;color:#64748b;margin:.1rem 0}.impact-box{margin-top:.55rem;padding:.55rem .65rem;border-radius:10px;background:#f8fafc;border:1px solid #dbe5df;font-size:.78rem;line-height:1.45}.impact-positive{color:#166534;font-weight:700}.impact-negative{color:#b91c1c;font-weight:700}.impact-neutral{color:#475569;font-weight:700}.process-wrap{background:#fff;border:1px solid #b9d8c1;border-radius:22px;padding:1.1rem;overflow-x:auto}.process-line{min-width:1150px;display:flex;align-items:center;gap:8px;position:relative;padding:22px 8px 52px}.unit{width:135px;min-height:82px;border:2px solid #15803d;border-radius:13px;background:linear-gradient(180deg,#fff,#eefbf1);display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;font-weight:750}.unit span{font-size:1.8rem}.arrow{width:42px;height:12px;background:#15803d;position:relative}.arrow:after{content:"";position:absolute;right:-13px;top:-7px;border-left:14px solid #15803d;border-top:13px solid transparent;border-bottom:13px solid transparent}.belt{position:absolute;left:12px;right:12px;bottom:20px;height:10px;border-radius:6px;background:repeating-linear-gradient(90deg,#14532d 0 24px,#86efac 24px 38px);animation:beltMove .75s linear infinite}.tile{position:absolute;bottom:31px;width:34px;height:20px;border-radius:3px;background:#f59e0b;border:2px solid #9a5a06;animation:tileMove 8s linear infinite}.tile.t2{animation-delay:-2.7s}.tile.t3{animation-delay:-5.4s}.flow-label{position:absolute;left:12px;bottom:0;color:#166534;font-size:.78rem;font-weight:700}@keyframes beltMove{to{background-position:38px 0}}@keyframes tileMove{0%{left:2%}100%{left:95%}}.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{border-radius:12px;min-height:45px;font-weight:700}.stFormSubmitButton>button{background:#15803d!important;color:white!important;border:0!important}</style>""",unsafe_allow_html=True)


def github_configured():
    return all(str(st.secrets.get(k, "")).strip() for k in ["GITHUB_TOKEN","GITHUB_OWNER","GITHUB_REPO"])

def github_headers():
    return {"Authorization":f"Bearer {st.secrets['GITHUB_TOKEN']}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}

def github_url(path):
    return f"https://api.github.com/repos/{st.secrets['GITHUB_OWNER']}/{st.secrets['GITHUB_REPO']}/contents/{path}"

def read_remote_csv(path, columns):
    r=requests.get(github_url(path),headers=github_headers(),params={"ref":st.secrets.get("GITHUB_BRANCH","main")},timeout=30)
    if r.status_code==404:return pd.DataFrame(columns=columns),None
    r.raise_for_status();p=r.json()
    try:df=pd.read_csv(io.BytesIO(base64.b64decode(p["content"])))
    except pd.errors.EmptyDataError:df=pd.DataFrame(columns=columns)
    for column in columns:
        if column not in df:df[column]=""
    return df[columns],p["sha"]

def write_remote_csv(path,frame,columns,sha,message):
    body={"message":message,"content":base64.b64encode(frame[columns].to_csv(index=False).encode()).decode(),"branch":st.secrets.get("GITHUB_BRANCH","main")}
    if sha:body["sha"]=sha
    r=requests.put(github_url(path),headers=github_headers(),json=body,timeout=30);r.raise_for_status()

def append_remote_csv(path,row,columns,message):
    frame,sha=read_remote_csv(path,columns);frame=pd.concat([frame,pd.DataFrame([row])],ignore_index=True);write_remote_csv(path,frame,columns,sha,message)

def update_leaderboard(row):
    if github_configured():
        frame,sha=read_remote_csv(LEADERBOARD_PATH,LEADERBOARD_COLUMNS);frame=frame[~frame["Session ID"].astype(str).eq(str(row["Session ID"]))];frame=pd.concat([frame,pd.DataFrame([row])],ignore_index=True);write_remote_csv(LEADERBOARD_PATH,frame,LEADERBOARD_COLUMNS,sha,"Update simulation leaderboard")
    local=st.session_state.get("local_lb",pd.DataFrame(columns=LEADERBOARD_COLUMNS));local=local[~local["Session ID"].astype(str).eq(str(row["Session ID"]))];st.session_state.local_lb=pd.concat([local,pd.DataFrame([row])],ignore_index=True)

def get_leaderboard():
    if github_configured():
        try:return read_remote_csv(LEADERBOARD_PATH,LEADERBOARD_COLUMNS)[0]
        except Exception as error:st.caption(f"Shared leaderboard temporarily unavailable: {error}")
    return st.session_state.get("local_lb",pd.DataFrame(columns=LEADERBOARD_COLUMNS))


def initial_state():
    return {"round":0,"productivity":80.0,"quality":72.0,"budget":120.0,"future_productivity":0.0,"bulk":{"mean":1.925,"sigma":0.030,"target":1.900,"lsl":1.820,"usl":1.980},"total_score":0.0,"previous_actions":[],"carryover_text":"No previous-round carryover."}

def bulk_metrics(bulk,round_no,team_id):
    sigma=max(.004,bulk["sigma"]);cp=(bulk["usl"]-bulk["lsl"])/(6*sigma);cpk=min((bulk["usl"]-bulk["mean"])/(3*sigma),(bulk["mean"]-bulk["lsl"])/(3*sigma));rng=np.random.default_rng(abs(hash((team_id,round_no,"bulk")))%(2**32));return {"cp":cp,"cpk":cpk,"ucl":bulk["mean"]+3*sigma,"lcl":bulk["mean"]-3*sigma,"readings":rng.normal(bulk["mean"],sigma,25)}

def apply_carryover(state):
    text=[];previous=set(state["previous_actions"])
    if "Increase Machine Speed" in previous:state["productivity"]+=2;state["quality"]-=3;state["bulk"]["sigma"]*=1.06;text.append("Previous speed increase keeps productivity high, but quality and bulk-density stability are lower.")
    if "Preventive Maintenance" in previous:state["productivity"]+=4;state["bulk"]["sigma"]*=.96;text.append("Previous maintenance provides higher throughput and lower variation.")
    if "Raw Material Control" in previous:state["quality"]+=2;state["bulk"]["sigma"]*=.95;text.append("Previous material control improves quality and bulk-density consistency.")
    if "Center Process Setting" in previous:state["bulk"]["mean"]+=(state["bulk"]["target"]-state["bulk"]["mean"])*.15;text.append("Previous centering keeps the bulk-density mean closer to target.")
    if "Line Balancing" in previous or "SMED Changeover" in previous:state["productivity"]+=1;text.append("Previous flow improvement provides a sustained productivity gain.")
    state["carryover_text"]=" ".join(text) if text else "Previous choices provide no sustained benefit."

def apply_action(state,name):
    action=ACTIONS[name];state["budget"]-=action["cost"];state["productivity"]+=action.get("prod",0);state["quality"]+=action.get("quality",0);state["bulk"]["sigma"]*=1+action.get("sigma_pct",0)/100;state["bulk"]["mean"]+=action.get("mean",0)
    if action.get("center"):state["bulk"]["mean"]+=(state["bulk"]["target"]-state["bulk"]["mean"])*action["center"]
    state["future_productivity"]+=action.get("future_prod",0)

def priority_score(round_no,selected):
    return min(20.0,sum(ROUND_CONFIG[round_no]["priority"][a] for a in selected))

def constraint_score(round_no,state,metrics):
    ratios=[]
    for key,target in ROUND_CONFIG[round_no]["targets"].items():
        actual=metrics.get(key,state.get(key));ratios.append(min(1.0,actual/target))
    return 5*min(ratios),all(r>=1 for r in ratios)


def run_round():
    state=st.session_state.state.copy();state["bulk"]=state["bulk"].copy();next_round=state["round"]+1
    if next_round>4:return
    selected={st.session_state.get("selected_action_1","None"),st.session_state.get("selected_action_2","None")}-{ "None" }
    cost=sum(ACTIONS[a]["cost"] for a in selected)
    if cost>state["budget"]:st.error("Selected activities exceed the available budget.");return
    if state["round"]>0:apply_carryover(state)
    if state["future_productivity"]:state["productivity"]+=state["future_productivity"]
    for action in selected:apply_action(state,action)
    state["budget"]=max(0,state["budget"]);state["quality"]=max(0,min(100,state["quality"]));state["round"]=next_round;state["previous_actions"]=sorted(selected)
    bulk=bulk_metrics(state["bulk"],next_round,st.session_state.session_id);metrics={"productivity":state["productivity"],"quality":state["quality"],"cp":bulk["cp"],"cpk":bulk["cpk"]};p_score=priority_score(next_round,selected);c_score,met=constraint_score(next_round,state,metrics);round_score=p_score+c_score;state["total_score"]+=round_score
    st.session_state.state=state;st.session_state.bulk_result=bulk;st.session_state.round_result={"priority_score":p_score,"constraint_score":c_score,"round_score":round_score,"constraints_met":met}
    row={"Session ID":st.session_state.session_id,"Team Name":st.session_state.team_name,"Team Members":st.session_state.team_members,"Round":next_round,"Productivity":round(state["productivity"],2),"Quality %":round(state["quality"],2),"Bulk Density Cp":round(bulk["cp"],3),"Bulk Density Cpk":round(bulk["cpk"],3),"Budget Remaining":round(state["budget"],1),"Round Score":round(round_score,2),"Total Score":round(state["total_score"],2),"Updated At":datetime.now().strftime("%Y-%m-%d %H:%M:%S")};update_leaderboard(row)
    if github_configured():
        acts=sorted(selected);log={"Session ID":st.session_state.session_id,"Team Name":st.session_state.team_name,"Team Members":st.session_state.team_members,"Round":next_round,"Scenario":ROUND_CONFIG[next_round]["scenario"],"Action 1":acts[0] if acts else "None","Action 2":acts[1] if len(acts)>1 else "None","Carryover Effect":state["carryover_text"],"Productivity":state["productivity"],"Quality %":state["quality"],"Bulk Density Mean":state["bulk"]["mean"],"Bulk Density Sigma":state["bulk"]["sigma"],"Cp":bulk["cp"],"Cpk":bulk["cpk"],"UCL":bulk["ucl"],"LCL":bulk["lcl"],"USL":state["bulk"]["usl"],"LSL":state["bulk"]["lsl"],"Budget Remaining":state["budget"],"Priority Score":p_score,"Constraint Score":c_score,"Round Score":round_score,"Total Score":state["total_score"],"Created At":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        try:append_remote_csv(LOG_PATH,log,LOG_COLUMNS,f"Add constrained round {next_round}")
        except Exception as error:st.warning(f"Round completed; GitHub log save failed: {error}")
    st.rerun()


def process_animation(productivity):
    duration=max(3,min(14,900/max(productivity,1)))
    st.markdown(f"""<div class='process-wrap'><div class='process-line'><div class='unit'><span>⚗️</span>Slip House</div><div class='arrow'></div><div class='unit'><span>🌪️</span>Spray Dryer</div><div class='arrow'></div><div class='unit'><span>🗄️</span>Silo</div><div class='arrow'></div><div class='unit'><span>🗜️</span>Press</div><div class='arrow'></div><div class='unit'><span>🎨</span>Glaze Line</div><div class='arrow'></div><div class='unit'><span>🔥</span>Kiln</div><div class='arrow'></div><div class='unit'><span>💎</span>Polishing</div><div class='arrow'></div><div class='unit'><span>📦</span>Packing</div><div class='belt'></div><div class='tile' style='animation-duration:{duration}s'></div><div class='tile t2' style='animation-duration:{duration}s'></div><div class='tile t3' style='animation-duration:{duration}s'></div><div class='flow-label'>Conveyor speed: {productivity:.1f} tiles/min</div></div></div>""",unsafe_allow_html=True)

def bulk_spc_graph(state,result):
    x=list(range(1,26));bulk=state["bulk"];fig=go.Figure(go.Scatter(x=x,y=result["readings"],mode="lines+markers",name="Bulk Density",marker=dict(size=7,color="#0f6bca")))
    for value,name,color,dash in [(result["ucl"],"UCL","#dc2626","dot"),(result["lcl"],"LCL","#dc2626","dot"),(bulk["usl"],"USL","#7c3aed","dashdot"),(bulk["lsl"],"LSL","#f59e0b","dashdot"),(bulk["target"],"Target","#15803d","dash")]:fig.add_trace(go.Scatter(x=x,y=[value]*25,name=name,mode="lines",line=dict(color=color,dash=dash)))
    fig.update_layout(title="Bulk Density SPC Graph",xaxis_title="Simulated Observation",yaxis_title="Bulk Density (g/cc)");st.plotly_chart(fig,use_container_width=True)

def action_impact_html(action):
    impacts=[]
    for key,label in [("prod","Productivity"),("quality","Quality")]:
        value=float(action.get(key,0));unit=" tiles/min" if key=="prod" else " percentage points";kind="positive" if value>0 else "negative" if value<0 else "neutral";text=f"{label} {'+' if value>0 else ''}{value:g}{unit}" if value else f"{label}: no direct change";impacts.append((kind,text))
    sigma=float(action.get("sigma_pct",0));impacts.append(("positive" if sigma<0 else "negative" if sigma>0 else "neutral",f"Bulk-density variation {'+' if sigma>0 else ''}{sigma:g}%" if sigma else "Bulk-density variation: no direct change"))
    if action.get("mean"):impacts.append(("negative",f"Bulk-density mean shift {action['mean']:+.3f} g/cc"))
    if action.get("center"):impacts.append(("positive",f"Moves mean {action['center']*100:.0f}% toward target"))
    if action.get("future_prod"):impacts.append(("positive",f"Future productivity +{action['future_prod']:g} tiles/min"))
    return "".join(f"<div class='impact-{kind}'>{'▲' if kind=='positive' else '▼' if kind=='negative' else '•'} {text}</div>" for kind,text in impacts)


def hero():st.markdown("<div class='hero'><h1>🏆 Process Champion Challenge</h1><p>Constraint-driven manufacturing simulation with deterministic carryover and bulk-density SPC.</p></div>",unsafe_allow_html=True)

def registration_page():
    hero();process_animation(80);_,center,_=st.columns([1,1.5,1])
    with center:
        with st.form("registration"):
            st.subheader("Register Your Team")
            team_name=st.text_input("Team Name *",placeholder="Enter a unique team name")
            team_members=st.text_area("Team Members *",placeholder="Enter team-member names separated by commas",height=120)
            submitted=st.form_submit_button("Start Simulation →",use_container_width=True)
        if submitted:
            if not team_name.strip():st.error("Please enter the team name.")
            elif not team_members.strip():st.error("Please enter at least one team member.")
            else:st.session_state.update(registered=True,session_id=str(uuid.uuid4()),team_name=team_name.strip(),team_members=team_members.strip(),state=initial_state(),bulk_result=None,round_result=None,local_lb=pd.DataFrame(columns=LEADERBOARD_COLUMNS));st.rerun()

def action_panel(state,next_round):
    st.info("Every direct effect is displayed on the activity tile. Scenario-priority points are used internally and are not shown to participants.")
    cols=st.columns(3)
    for i,(name,action) in enumerate(ACTIONS.items()):
        affordable=action["cost"]<=state["budget"];css="equipment" if affordable else "equipment locked"
        with cols[i%3]:st.markdown(f"<div class='{css}'><div class='ico'>{action['icon']}</div><h4>{name}</h4><p>{action['description']}</p><div class='impact-box'>{action_impact_html(action)}</div><p><b>Cost: {action['cost']} points</b></p></div>",unsafe_allow_html=True)
    affordable=[name for name,a in ACTIONS.items() if a["cost"]<=state["budget"]]
    if not affordable:st.warning("Budget exhausted or insufficient.");st.button("Run Round",disabled=True,use_container_width=True);return
    left,right=st.columns(2);a1=left.selectbox("Action 1",["None"]+affordable,key=f"a1_{next_round}");cost1=ACTIONS[a1]["cost"] if a1!="None" else 0;a2opts=[n for n,a in ACTIONS.items() if a["cost"]<=state["budget"]-cost1 and n!=a1];a2=right.selectbox("Action 2",["None"]+a2opts,key=f"a2_{next_round}");st.session_state.selected_action_1=a1;st.session_state.selected_action_2=a2;selected={a1,a2}-{ "None" };cost=sum(ACTIONS[a]["cost"] for a in selected)
    x,y=st.columns(2);x.metric("Current Budget",f"{state['budget']:.0f}");y.metric("Budget After Activities",f"{state['budget']-cost:.0f}");st.button("Run Constrained Round ▶",type="primary",disabled=cost>state["budget"],use_container_width=True,on_click=run_round)

def leaderboard_section():
    st.subheader("🏅 Live Leaderboard");lb=get_leaderboard()
    if lb.empty:st.info("Complete a round to populate the leaderboard.");return
    for c in ["Total Score","Round Score","Bulk Density Cpk","Productivity","Quality %"]:lb[c]=pd.to_numeric(lb[c],errors="coerce")
    lb=lb.sort_values(["Total Score","Bulk Density Cpk","Productivity"],ascending=[False,False,False]).reset_index(drop=True);lb.insert(0,"Rank",range(1,len(lb)+1));st.dataframe(lb[["Rank","Team Name","Team Members","Round","Productivity","Quality %","Bulk Density Cp","Bulk Density Cpk","Budget Remaining","Round Score","Total Score"]],use_container_width=True,hide_index=True)

def dashboard_page():
    hero();state=st.session_state.state;process_animation(state["productivity"])
    with st.sidebar:
        st.success(f"Team: {st.session_state.team_name}");st.write("**Team Members**");st.write(st.session_state.team_members);st.metric("Round",f"{state['round']} / 4");st.metric("Total Score",f"{state['total_score']:.1f} / 100");st.metric("Budget",f"{state['budget']:.0f}")
        if st.button("Restart Simulation",use_container_width=True):st.session_state.clear();st.rerun()
    bulk=st.session_state.bulk_result or bulk_metrics(state["bulk"],max(1,state["round"]),st.session_state.session_id);a,b,c,d,e=st.columns(5);a.metric("Productivity",f"{state['productivity']:.1f} tiles/min");b.metric("Quality",f"{state['quality']:.1f}%");c.metric("Bulk Density Cp",f"{bulk['cp']:.2f}");d.metric("Bulk Density Cpk",f"{bulk['cpk']:.2f}");e.metric("Budget",f"{state['budget']:.0f}")
    if state["round"]>0:
        bulk_spc_graph(state,bulk);r=st.session_state.round_result;m1,m2,m3=st.columns(3);m1.metric("Activity Fit Score",f"{r['priority_score']:.1f} / 20");m2.metric("Constraint Score",f"{r['constraint_score']:.1f} / 5");m3.metric("Round Score",f"{r['round_score']:.1f} / 25")
    if state["round"]<4:
        nr=state["round"]+1;cfg=ROUND_CONFIG[nr];st.markdown(f"<div class='scenario'><h3>Round {nr}: {cfg['title']}</h3><p>{cfg['scenario']}</p></div>",unsafe_allow_html=True)
        if state["round"]>0:
            preview=state.copy();preview["bulk"]=state["bulk"].copy();apply_carryover(preview);st.markdown(f"<div class='carry'><b>Carryover from previous actions:</b> {preview['carryover_text']}</div>",unsafe_allow_html=True)
        action_panel(state,nr)
    else:
        if state["total_score"]>=99.99:st.balloons();st.success("Perfect score achieved: 100/100. Process Champion!")
        else:st.success(f"Simulation complete. Final score: {state['total_score']:.1f}/100")
    leaderboard_section()

if st.session_state.get("registered"):dashboard_page()
else:registration_page()
