import base64
import io
import json
import random
import uuid
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(page_title="Process Champion Challenge", page_icon="🏆", layout="wide", initial_sidebar_state="expanded")
ACTIONS = json.loads(Path("config/actions.json").read_text(encoding="utf-8"))
LEADERBOARD_PATH = "data/leaderboard.csv"
LOG_PATH = "data/simulation_log.csv"
LEADERBOARD_COLUMNS = ["Session ID","Team Name","Department","Team Members","Round","Productivity","Cp","Cpk","Yield %","Stability Score","Budget Remaining","Total Score","Updated At"]
LOG_COLUMNS = ["Session ID","Team Name","Department","Round","Action 1","Action 2","Random Event","Mean","Sigma","Productivity","Total Output","Good Output","Yield %","Cp","Cpk","UCL","LCL","USL","LSL","Budget Remaining","Round Score","Created At"]
ROUND_NAMES = {1:"Understand the Process",2:"Productivity Pressure",3:"Process Disturbance",4:"Final Optimization"}
EVENTS = [
    ("🧱 Raw-material variation",0,10,0),
    ("⚙️ Machine vibration",0,5,0.04),
    ("👷 Experienced operator support",2,-5,0),
    ("🐢 Speed loss",-8,0,0),
    ("🌤️ Stable operating conditions",0,0,0),
    ("📏 Measurement-system bias",0,0,-0.03),
]

st.markdown("""<style>
.stApp{background:radial-gradient(circle at 10% 5%,#dcfce7 0,transparent 22%),linear-gradient(135deg,#f8fffa,#eef7f0)}
.block-container{max-width:1250px;padding-top:1.2rem;padding-bottom:3rem}#MainMenu,footer{visibility:hidden}
.hero{position:relative;overflow:hidden;padding:2rem 2.2rem;border-radius:26px;background:linear-gradient(125deg,#103d27,#166534 48%,#16a34a);color:white;box-shadow:0 20px 55px rgba(20,83,45,.22);margin-bottom:1rem}.hero h1{margin:0;font-size:2.25rem}.hero p{margin:.45rem 0 0;opacity:.9}.hero-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:.7rem;margin-top:1.3rem}.hero-pill{background:rgba(255,255,255,.11);border:1px solid rgba(255,255,255,.17);border-radius:14px;padding:.75rem}
.equipment{background:white;border:1px solid #d9e8de;border-radius:18px;padding:1rem;box-shadow:0 9px 24px rgba(20,83,45,.07);height:100%}.equipment .icon{font-size:2rem}.equipment h4{margin:.3rem 0}.equipment p{color:#607268;font-size:.88rem;margin:0}.score-card{padding:.9rem 1rem;border-radius:15px;background:#f0fdf4;border:1px solid #bbf7d0}.round-card{padding:1rem;border-radius:16px;background:white;border:1px solid #d9e8de;margin:.6rem 0}.stButton>button,.stDownloadButton>button,.stFormSubmitButton>button{border-radius:12px;min-height:45px;font-weight:700}.stFormSubmitButton>button{background:linear-gradient(90deg,#15803d,#22a447)!important;color:white!important;border:0!important}
@media(max-width:760px){.hero-grid{grid-template-columns:1fr 1fr}.hero h1{font-size:1.7rem}}
</style>""",unsafe_allow_html=True)


def gh_headers():
    return {"Authorization":f"Bearer {st.secrets['GITHUB_TOKEN']}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}

def gh_url(path):
    return f"https://api.github.com/repos/{st.secrets['GITHUB_OWNER']}/{st.secrets['GITHUB_REPO']}/contents/{path}"

def read_csv(path, columns):
    response=requests.get(gh_url(path),headers=gh_headers(),params={"ref":st.secrets.get("GITHUB_BRANCH","main")},timeout=30)
    if response.status_code==404:return pd.DataFrame(columns=columns),None
    response.raise_for_status(); payload=response.json()
    try:frame=pd.read_csv(io.BytesIO(base64.b64decode(payload["content"])))
    except pd.errors.EmptyDataError:frame=pd.DataFrame(columns=columns)
    for column in columns:
        if column not in frame:frame[column]=""
    return frame[columns],payload["sha"]

def write_csv(path, frame, columns, sha, message):
    content=base64.b64encode(frame[columns].to_csv(index=False).encode("utf-8")).decode()
    body={"message":message,"content":content,"branch":st.secrets.get("GITHUB_BRANCH","main")}
    if sha:body["sha"]=sha
    response=requests.put(gh_url(path),headers=gh_headers(),json=body,timeout=30);response.raise_for_status()

def append_csv(path, row, columns, message):
    frame,sha=read_csv(path,columns);frame=pd.concat([frame,pd.DataFrame([row])],ignore_index=True);write_csv(path,frame,columns,sha,message)

def update_leaderboard(row):
    frame,sha=read_csv(LEADERBOARD_PATH,LEADERBOARD_COLUMNS)
    frame=frame[~frame["Session ID"].astype(str).eq(str(row["Session ID"]))]
    frame=pd.concat([frame,pd.DataFrame([row])],ignore_index=True)
    write_csv(LEADERBOARD_PATH,frame,LEADERBOARD_COLUMNS,sha,f"Update leaderboard for {row['Team Name']}")

def normal_cdf(z):
    import math
    return 0.5*(1+math.erf(z/(2**0.5)))

def compute_metrics(state, rng):
    mean=state["mean"];sigma=max(.008,state["sigma"]);lsl=state["lsl"];usl=state["usl"]
    cp=(usl-lsl)/(6*sigma);cpk=min((usl-mean)/(3*sigma),(mean-lsl)/(3*sigma))
    yield_pct=max(0,min(100,(normal_cdf((usl-mean)/sigma)-normal_cdf((lsl-mean)/sigma))*100))
    total_output=state["productivity"]*60;good_output=total_output*yield_pct/100
    readings=rng.normal(mean,sigma,25);ucl=mean+3*sigma;lcl=mean-3*sigma
    signals=int(((readings>ucl)|(readings<lcl)).sum());stability=max(0,15-signals*5)
    productivity_score=min(30,good_output/6000*30);capability_score=0 if cpk<.67 else 10 if cpk<1 else 20 if cpk<1.33 else 25 if cpk<1.67 else 30
    quality_score=yield_pct*.15;budget_score=max(0,state["budget"])/100*10;penalty=(10 if cpk<1 else 0)+(5 if state["productivity"]>90 and yield_pct<95 else 0)
    total_score=productivity_score+capability_score+quality_score+stability+budget_score-penalty
    return dict(cp=cp,cpk=cpk,yield_pct=yield_pct,total_output=total_output,good_output=good_output,ucl=ucl,lcl=lcl,stability=stability,total_score=total_score,readings=readings)

def start_state():
    return {"mean":8.58,"sigma":.10,"productivity":80.0,"target":8.50,"lsl":8.30,"usl":8.70,"budget":100.0,"maintenance_bonus":0.0,"round":0}

def apply_action(state, action_name):
    if action_name=="None":return
    action=ACTIONS[action_name];state["budget"]-=action["cost"];state["productivity"]*=1+action.get("productivity_pct",0)/100;state["sigma"]*=1+action.get("sigma_pct",0)/100
    shift=action.get("mean_shift",0)
    if shift=="toward_target":state["mean"]+=(state["target"]-state["mean"])*.70
    elif shift=="small_toward_target":state["mean"]+=(state["target"]-state["mean"])*.35
    elif isinstance(shift,(int,float)):state["mean"]+=shift
    state["maintenance_bonus"]+=action.get("future_productivity_pct",0)

def run_round():
    state=st.session_state.sim_state.copy();state["round"]+=1
    if state["round"]>1 and state["maintenance_bonus"]:state["productivity"]*=1+state["maintenance_bonus"]/100
    action1=st.session_state.action1;action2=st.session_state.action2
    cost=sum(ACTIONS[action]["cost"] for action in {action1,action2} if action!="None")
    if cost>state["budget"]:st.error("Selected actions exceed the remaining budget.");return
    apply_action(state,action1)
    if action2!=action1:apply_action(state,action2)
    rng=np.random.default_rng(abs(hash((st.session_state.session_id,state["round"])))%(2**32))
    event_name,prod_pct,sigma_pct,mean_shift=EVENTS[int(rng.integers(0,len(EVENTS)))]
    state["productivity"]*=1+prod_pct/100;state["sigma"]*=1+sigma_pct/100;state["mean"]+=mean_shift
    metrics=compute_metrics(state,rng);st.session_state.sim_state=state;st.session_state.last_metrics=metrics
    action_names=[x for x in [action1,action2] if x!="None"]
    log_row={"Session ID":st.session_state.session_id,"Team Name":st.session_state.team_name,"Department":st.session_state.department,"Round":state["round"],"Action 1":action_names[0] if action_names else "None","Action 2":action_names[1] if len(action_names)>1 else "None","Random Event":event_name,"Mean":round(state["mean"],5),"Sigma":round(state["sigma"],5),"Productivity":round(state["productivity"],2),"Total Output":round(metrics["total_output"],1),"Good Output":round(metrics["good_output"],1),"Yield %":round(metrics["yield_pct"],2),"Cp":round(metrics["cp"],3),"Cpk":round(metrics["cpk"],3),"UCL":round(metrics["ucl"],4),"LCL":round(metrics["lcl"],4),"USL":state["usl"],"LSL":state["lsl"],"Budget Remaining":round(state["budget"],1),"Round Score":round(metrics["total_score"],2),"Created At":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    leaderboard_row={"Session ID":st.session_state.session_id,"Team Name":st.session_state.team_name,"Department":st.session_state.department,"Team Members":st.session_state.members,"Round":state["round"],"Productivity":round(state["productivity"],2),"Cp":round(metrics["cp"],3),"Cpk":round(metrics["cpk"],3),"Yield %":round(metrics["yield_pct"],2),"Stability Score":metrics["stability"],"Budget Remaining":round(state["budget"],1),"Total Score":round(metrics["total_score"],2),"Updated At":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    try:append_csv(LOG_PATH,log_row,LOG_COLUMNS,f"Round {state['round']} for {st.session_state.team_name}");update_leaderboard(leaderboard_row)
    except Exception as error:st.warning(f"Round calculated, but GitHub save failed: {error}")
    st.session_state.last_event=event_name;st.rerun()


def hero():
    st.markdown("""<div class='hero'><h1>🏆 Process Champion Challenge</h1><p>Balance productivity, stability and capability. The highest balanced score wins.</p><div class='hero-grid'><div class='hero-pill'>⚙️ Productivity</div><div class='hero-pill'>📊 UCL / LCL</div><div class='hero-pill'>🎯 Cp / Cpk</div><div class='hero-pill'>📏 USL / LSL</div></div></div>""",unsafe_allow_html=True)

def registration():
    hero();_,center,_=st.columns([1,1.5,1])
    with center:
        with st.form("registration"):
            st.subheader("Register your team")
            team=st.text_input("Team name")
            department=st.selectbox("Department",["Slip House","Press","Spray Dryer","Kiln","Quality","Maintenance","Other"])
            members=st.text_area("Team members",placeholder="Enter names separated by commas")
            submitted=st.form_submit_button("Start Simulation →",use_container_width=True)
        if submitted:
            if not team.strip():st.error("Enter a team name.")
            else:
                st.session_state.update(registered=True,session_id=str(uuid.uuid4()),team_name=team.strip(),department=department,members=members.strip(),sim_state=start_state(),last_metrics=None,last_event=None);st.rerun()

def equipment_cards():
    st.subheader("Choose improvement actions")
    cols=st.columns(3)
    for index,(name,action) in enumerate(ACTIONS.items()):
        with cols[index%3]:
            st.markdown(f"<div class='equipment'><div class='icon'>{action['icon']}</div><h4>{name}</h4><p>{action['description']}</p><p><b>Cost: {action['cost']} points</b></p></div>",unsafe_allow_html=True)

def dashboard():
    hero();state=st.session_state.sim_state
    with st.sidebar:
        st.success(f"Team: {st.session_state.team_name}");st.write(f"Department: {st.session_state.department}");st.metric("Round",f"{state['round']} / 4");st.metric("Budget",f"{state['budget']:.0f}")
        if st.button("Restart Simulation",use_container_width=True):
            for key in ["registered","session_id","team_name","department","members","sim_state","last_metrics","last_event"]:st.session_state.pop(key,None)
            st.rerun()
    a,b,c,d,e=st.columns(5);a.metric("Mean",f"{state['mean']:.3f}");b.metric("Sigma",f"{state['sigma']:.3f}");c.metric("Productivity",f"{state['productivity']:.1f}/min");d.metric("LSL",f"{state['lsl']:.2f}");e.metric("USL",f"{state['usl']:.2f}")
    if st.session_state.last_metrics:
        m=st.session_state.last_metrics
        st.markdown(f"<div class='score-card'><b>Latest event:</b> {st.session_state.last_event}</div>",unsafe_allow_html=True)
        p,q,r,s,t=st.columns(5);p.metric("Cp",f"{m['cp']:.2f}");q.metric("Cpk",f"{m['cpk']:.2f}");r.metric("Yield",f"{m['yield_pct']:.1f}%");s.metric("Good Output",f"{m['good_output']:.0f}");t.metric("Score",f"{m['total_score']:.1f}")
        fig=go.Figure();x=list(range(1,26));fig.add_trace(go.Scatter(x=x,y=m["readings"],mode="lines+markers",name="Process readings"));
        for value,name,color,dash in [(m['ucl'],'UCL','#dc2626','dot'),(m['lcl'],'LCL','#dc2626','dot'),(state['usl'],'USL','#7c3aed','dashdot'),(state['lsl'],'LSL','#f59e0b','dashdot'),(state['target'],'Target','#15803d','dash')]:fig.add_trace(go.Scatter(x=x,y=[value]*25,name=name,mode="lines",line=dict(color=color,dash=dash)))
        fig.update_layout(title=f"Round {state['round']} Process Simulation",xaxis_title="Simulated observation",yaxis_title="Thickness (mm)");st.plotly_chart(fig,use_container_width=True)
    if state["round"]>=4:
        st.success("Simulation complete. Check the live leaderboard below.")
    else:
        st.markdown(f"<div class='round-card'><h3>Round {state['round']+1}: {ROUND_NAMES[state['round']+1]}</h3><p>Select up to two actions. The same action selected twice is applied once.</p></div>",unsafe_allow_html=True)
        equipment_cards();options=["None"]+list(ACTIONS);left,right=st.columns(2);st.session_state.action1=left.selectbox("Action 1",options,key="action_1");st.session_state.action2=right.selectbox("Action 2",options,key="action_2")
        selected={x for x in [st.session_state.action1,st.session_state.action2] if x!="None"};cost=sum(ACTIONS[x]["cost"] for x in selected);st.info(f"Selected action cost: {cost} | Remaining budget after action: {state['budget']-cost:.0f}")
        st.button("Run Round 🎲",type="primary",use_container_width=True,on_click=run_round)
    leaderboard()

def leaderboard():
    st.subheader("🏅 Live Leaderboard")
    try:frame,_=read_csv(LEADERBOARD_PATH,LEADERBOARD_COLUMNS)
    except Exception as error:st.warning(f"Leaderboard unavailable: {error}");return
    if frame.empty:st.info("The leaderboard will appear after the first completed round.");return
    for column in ["Total Score","Cpk","Cp","Productivity","Yield %"]:frame[column]=pd.to_numeric(frame[column],errors="coerce")
    frame=frame.sort_values(["Total Score","Cpk","Productivity"],ascending=[False,False,False]).reset_index(drop=True);frame.insert(0,"Rank",range(1,len(frame)+1));st.dataframe(frame[["Rank","Team Name","Department","Round","Productivity","Cp","Cpk","Yield %","Budget Remaining","Total Score"]],use_container_width=True,hide_index=True)
    st.download_button("Download Leaderboard",frame.to_csv(index=False).encode("utf-8-sig"),"process_champion_leaderboard.csv",use_container_width=True)

if not st.session_state.get("registered"):
    registration()
else:
    dashboard()
