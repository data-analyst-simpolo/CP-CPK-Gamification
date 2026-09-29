import base64, io, json, math, uuid
from datetime import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

st.set_page_config(page_title="Process Champion Challenge",page_icon="🏆",layout="wide",initial_sidebar_state="expanded")
ACTIONS=json.loads(Path("config/actions.json").read_text())
LB_PATH="data/leaderboard.csv";LOG_PATH="data/simulation_log.csv"
LB_COLS=["Session ID","Team Name","Department","Round","Productivity","Cp","Cpk","Yield %","Budget Remaining","Total Score","Updated At"]
LOG_COLS=["Session ID","Team Name","Department","Round","Action 1","Action 2","Random Event","Mean","Sigma","Productivity","Good Output","Yield %","Cp","Cpk","UCL","LCL","USL","LSL","Budget Remaining","Round Score","Created At"]
EVENTS=[("🧱 Raw-material variation",0,10,.00),("⚙️ Machine vibration",0,5,.04),("👷 Experienced operator support",2,-5,.00),("🐢 Speed loss",-8,0,.00),("🌤️ Stable operating condition",0,0,.00),("📏 Measurement bias",0,0,-.03)]

st.markdown("""<style>
.stApp{background:radial-gradient(circle at 8% 4%,#dcfce7 0,transparent 22%),linear-gradient(135deg,#f8fffa,#eef7f0)}.block-container{max-width:1320px;padding-top:1.1rem;padding-bottom:3rem}#MainMenu,footer{visibility:hidden}
.hero{padding:1.8rem 2rem;border-radius:25px;background:linear-gradient(125deg,#103d27,#166534 52%,#16a34a);color:white;box-shadow:0 18px 48px rgba(20,83,45,.2);margin-bottom:1rem}.hero h1{margin:0;font-size:2.2rem}.hero p{margin:.35rem 0 0;opacity:.9}
.equipment-card{background:white;border:1px solid #d9e8de;border-radius:17px;padding:.9rem;height:100%;box-shadow:0 8px 22px rgba(20,83,45,.07)}.equipment-card .ico{font-size:2rem}.equipment-card h4{margin:.25rem 0}.equipment-card p{font-size:.85rem;color:#64748b;margin:.1rem 0}.status{background:#f0fdf4;border:1px solid #bbf7d0;border-radius:14px;padding:.8rem 1rem}
.process-wrap{background:white;border:1px solid #b9d8c1;border-radius:22px;padding:1.1rem;overflow-x:auto;box-shadow:0 10px 28px rgba(20,83,45,.08)}.process-line{min-width:1150px;display:flex;align-items:center;gap:8px;position:relative;padding:22px 8px 52px}.unit{width:135px;min-height:82px;border:2px solid #15803d;border-radius:13px;background:linear-gradient(180deg,#ffffff,#eefbf1);display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;font-weight:750;position:relative}.unit span{font-size:1.8rem}.arrow{width:42px;height:12px;background:#15803d;position:relative}.arrow:after{content:"";position:absolute;right:-13px;top:-7px;border-left:14px solid #15803d;border-top:13px solid transparent;border-bottom:13px solid transparent}.belt{position:absolute;left:12px;right:12px;bottom:20px;height:10px;border-radius:6px;background:repeating-linear-gradient(90deg,#14532d 0 24px,#86efac 24px 38px);animation:beltMove .75s linear infinite}.tile{position:absolute;bottom:31px;left:20px;width:34px;height:20px;border-radius:3px;background:#f59e0b;border:2px solid #9a5a06;box-shadow:0 3px 6px #0002;animation:tileMove 8s linear infinite;z-index:3}.tile.t2{animation-delay:-2.7s}.tile.t3{animation-delay:-5.4s}.flow-label{position:absolute;left:12px;bottom:0;color:#166534;font-size:.78rem;font-weight:700}@keyframes beltMove{to{background-position:38px 0}}@keyframes tileMove{0%{left:2%}100%{left:95%}}
.stButton>button,.stFormSubmitButton>button,.stDownloadButton>button{border-radius:12px;min-height:45px;font-weight:700}.stFormSubmitButton>button{background:#15803d!important;color:#fff!important;border:0!important}@media(max-width:760px){.hero h1{font-size:1.65rem}}
</style>""",unsafe_allow_html=True)

def configured():
    required=["GITHUB_TOKEN","GITHUB_OWNER","GITHUB_REPO"]
    return all(str(st.secrets.get(k,"")).strip() for k in required)
def headers():return {"Authorization":f"Bearer {st.secrets['GITHUB_TOKEN']}","Accept":"application/vnd.github+json","X-GitHub-Api-Version":"2022-11-28"}
def url(path):return f"https://api.github.com/repos/{st.secrets['GITHUB_OWNER']}/{st.secrets['GITHUB_REPO']}/contents/{path}"
def read_remote(path,cols):
    r=requests.get(url(path),headers=headers(),params={"ref":st.secrets.get("GITHUB_BRANCH","main")},timeout=30)
    if r.status_code==404:return pd.DataFrame(columns=cols),None
    r.raise_for_status();p=r.json()
    try:df=pd.read_csv(io.BytesIO(base64.b64decode(p["content"])))
    except pd.errors.EmptyDataError:df=pd.DataFrame(columns=cols)
    for c in cols:
        if c not in df:df[c]=""
    return df[cols],p["sha"]
def write_remote(path,df,cols,sha,msg):
    body={"message":msg,"content":base64.b64encode(df[cols].to_csv(index=False).encode()).decode(),"branch":st.secrets.get("GITHUB_BRANCH","main")}
    if sha:body["sha"]=sha
    r=requests.put(url(path),headers=headers(),json=body,timeout=30);r.raise_for_status()
def append_remote(path,row,cols,msg):
    df,sha=read_remote(path,cols);df=pd.concat([df,pd.DataFrame([row])],ignore_index=True);write_remote(path,df,cols,sha,msg)
def update_lb(row):
    if configured():
        df,sha=read_remote(LB_PATH,LB_COLS);df=df[~df["Session ID"].astype(str).eq(row["Session ID"])];df=pd.concat([df,pd.DataFrame([row])],ignore_index=True);write_remote(LB_PATH,df,LB_COLS,sha,"Update game leaderboard")
    local=st.session_state.get("local_lb",pd.DataFrame(columns=LB_COLS));local=local[~local["Session ID"].astype(str).eq(row["Session ID"])];st.session_state.local_lb=pd.concat([local,pd.DataFrame([row])],ignore_index=True)
def leaderboard_data():
    if configured():
        try:return read_remote(LB_PATH,LB_COLS)[0]
        except Exception as e:st.caption(f"Shared leaderboard temporarily unavailable: {e}")
    return st.session_state.get("local_lb",pd.DataFrame(columns=LB_COLS))

def cdf(z):return .5*(1+math.erf(z/math.sqrt(2)))
def metrics(s,rng):
    sigma=max(.008,s["sigma"]);cp=(s["usl"]-s["lsl"])/(6*sigma);cpk=min((s["usl"]-s["mean"])/(3*sigma),(s["mean"]-s["lsl"])/(3*sigma));yield_pct=max(0,min(100,(cdf((s["usl"]-s["mean"])/sigma)-cdf((s["lsl"]-s["mean"])/sigma))*100));good=s["productivity"]*60*yield_pct/100;readings=rng.normal(s["mean"],sigma,25);ucl=s["mean"]+3*sigma;lcl=s["mean"]-3*sigma;score=min(30,good/6000*30)+(0 if cpk<.67 else 10 if cpk<1 else 20 if cpk<1.33 else 25 if cpk<1.67 else 30)+yield_pct*.15+15+s["budget"]*.1-(10 if cpk<1 else 0);return dict(cp=cp,cpk=cpk,yield_pct=yield_pct,good=good,readings=readings,ucl=ucl,lcl=lcl,score=score)
def initial():return {"round":0,"mean":8.58,"sigma":.10,"productivity":80.,"target":8.50,"lsl":8.30,"usl":8.70,"budget":100.,"future":0.}
def apply(s,name):
    if name=="None":return
    a=ACTIONS[name];s["budget"]-=a["cost"];s["productivity"]*=1+a.get("prod",0)/100;s["sigma"]*=1+a.get("sigma",0)/100;s["future"]+=a.get("future",0)
    if a.get("center"):s["mean"]+=(s["target"]-s["mean"])*a["center"]
def process_animation(speed):
    duration=max(3,min(14,900/max(speed,1)))
    st.markdown(f"""<div class='process-wrap'><div class='process-line'>
    <div class='unit'><span>⚗️</span>Slip House<small>Ball Mill & Slurry</small></div><div class='arrow'></div>
    <div class='unit'><span>🌪️</span>Spray Dryer<small>Powder Formation</small></div><div class='arrow'></div>
    <div class='unit'><span>🗄️</span>Silo Storage<small>Powder Inventory</small></div><div class='arrow'></div>
    <div class='unit'><span>🗜️</span>Press<small>Green Body</small></div><div class='arrow'></div>
    <div class='unit'><span>🎨</span>Glaze Line<small>Decoration</small></div><div class='arrow'></div>
    <div class='unit'><span>🔥</span>Kiln<small>Firing</small></div><div class='arrow'></div>
    <div class='unit'><span>💎</span>Polishing<small>Surface Finish</small></div><div class='arrow'></div>
    <div class='unit'><span>📦</span>Sorting & Packing<small>Finished Goods</small></div>
    <div class='belt'></div><div class='tile' style='animation-duration:{duration}s'></div><div class='tile t2' style='animation-duration:{duration}s'></div><div class='tile t3' style='animation-duration:{duration}s'></div><div class='flow-label'>Live conveyor speed linked to productivity: {speed:.1f} tiles/min</div>
    </div></div>""",unsafe_allow_html=True)
def run_round():
    s=st.session_state.state.copy();s["round"]+=1
    if s["round"]>1:s["productivity"]*=1+s["future"]/100
    choices={st.session_state.a1,st.session_state.a2}-{"None"};cost=sum(ACTIONS[x]["cost"] for x in choices)
    if cost>s["budget"]:st.error("Selected action cost exceeds budget.");return
    for x in choices:apply(s,x)
    rng=np.random.default_rng(abs(hash((st.session_state.sid,s["round"])))%(2**32));event,prod,var,shift=EVENTS[int(rng.integers(0,len(EVENTS)))];s["productivity"]*=1+prod/100;s["sigma"]*=1+var/100;s["mean"]+=shift;m=metrics(s,rng);st.session_state.state=s;st.session_state.last=m;st.session_state.event=event
    row={"Session ID":st.session_state.sid,"Team Name":st.session_state.team,"Department":st.session_state.department,"Round":s["round"],"Productivity":round(s["productivity"],2),"Cp":round(m["cp"],3),"Cpk":round(m["cpk"],3),"Yield %":round(m["yield_pct"],2),"Budget Remaining":round(s["budget"],1),"Total Score":round(m["score"],2),"Updated At":datetime.now().strftime("%Y-%m-%d %H:%M:%S")};update_lb(row)
    if configured():
        log={"Session ID":st.session_state.sid,"Team Name":st.session_state.team,"Department":st.session_state.department,"Round":s["round"],"Action 1":st.session_state.a1,"Action 2":st.session_state.a2,"Random Event":event,"Mean":s["mean"],"Sigma":s["sigma"],"Productivity":s["productivity"],"Good Output":m["good"],"Yield %":m["yield_pct"],"Cp":m["cp"],"Cpk":m["cpk"],"UCL":m["ucl"],"LCL":m["lcl"],"USL":s["usl"],"LSL":s["lsl"],"Budget Remaining":s["budget"],"Round Score":m["score"],"Created At":datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
        try:append_remote(LOG_PATH,log,LOG_COLS,"Add simulation round")
        except Exception as e:st.warning(f"Round completed; GitHub log save failed: {e}")
    st.rerun()
def hero():st.markdown("<div class='hero'><h1>🏆 Process Champion Challenge</h1><p>Run the live tile-manufacturing process from Slip House to Polishing and maximize the balanced score.</p></div>",unsafe_allow_html=True)
def registration():
    hero();process_animation(80);_,c,_=st.columns([1,1.5,1])
    with c:
        with st.form("register"):
            team=st.text_input("Team name");dep=st.selectbox("Department",["Slip House","Spray Dryer","Press","Glaze Line","Kiln","Polishing","Quality","Maintenance"]);members=st.text_area("Members");ok=st.form_submit_button("Start Live Simulation →",use_container_width=True)
        if ok:
            if not team.strip():st.error("Enter team name.")
            else:st.session_state.update(registered=True,sid=str(uuid.uuid4()),team=team.strip(),department=dep,members=members,state=initial(),last=None,event=None,local_lb=pd.DataFrame(columns=LB_COLS));st.rerun()
def dashboard():
    hero();s=st.session_state.state;process_animation(s["productivity"])
    with st.sidebar:
        st.success(st.session_state.team);st.metric("Round",f"{s['round']} / 4");st.metric("Budget",f"{s['budget']:.0f}");st.caption("Shared leaderboard: ON" if configured() else "Shared leaderboard: OFF (local mode)")
        if st.button("Restart"):st.session_state.clear();st.rerun()
    a,b,c,d,e=st.columns(5);a.metric("Mean",f"{s['mean']:.3f}");b.metric("Sigma",f"{s['sigma']:.3f}");c.metric("Productivity",f"{s['productivity']:.1f}/min");d.metric("LSL",s["lsl"]);e.metric("USL",s["usl"])
    if st.session_state.last:
        m=st.session_state.last;st.markdown(f"<div class='status'><b>Latest event:</b> {st.session_state.event}</div>",unsafe_allow_html=True);a,b,c,d,e=st.columns(5);a.metric("Cp",f"{m['cp']:.2f}");b.metric("Cpk",f"{m['cpk']:.2f}");c.metric("Yield",f"{m['yield_pct']:.1f}%");d.metric("Good Output",f"{m['good']:.0f}");e.metric("Score",f"{m['score']:.1f}")
        x=list(range(1,26));fig=go.Figure(go.Scatter(x=x,y=m["readings"],mode="lines+markers",name="Readings"))
        for value,name,color,dash in [(m["ucl"],"UCL","#dc2626","dot"),(m["lcl"],"LCL","#dc2626","dot"),(s["usl"],"USL","#7c3aed","dashdot"),(s["lsl"],"LSL","#f59e0b","dashdot"),(s["target"],"Target","#15803d","dash")]:fig.add_trace(go.Scatter(x=x,y=[value]*25,name=name,mode="lines",line=dict(color=color,dash=dash)))
        fig.update_layout(title=f"Round {s['round']} Process Behaviour",xaxis_title="Observation",yaxis_title="Thickness (mm)");st.plotly_chart(fig,use_container_width=True)
    if s["round"]<4:
        st.subheader("Choose up to two improvement actions");cols=st.columns(3)
        for i,(name,a) in enumerate(ACTIONS.items()):
            with cols[i%3]:st.markdown(f"<div class='equipment-card'><div class='ico'>{a['icon']}</div><h4>{name}</h4><p>{a['description']}</p><p><b>Cost: {a['cost']}</b></p></div>",unsafe_allow_html=True)
        opts=["None"]+list(ACTIONS);x,y=st.columns(2);st.session_state.a1=x.selectbox("Action 1",opts,key="a1s");st.session_state.a2=y.selectbox("Action 2",opts,key="a2s");selected={st.session_state.a1,st.session_state.a2}-{"None"};cost=sum(ACTIONS[z]["cost"] for z in selected);st.info(f"Action cost: {cost} | Budget after action: {s['budget']-cost:.0f}");st.button("Run Round 🎲",type="primary",use_container_width=True,on_click=run_round)
    else:st.success("Simulation completed. Highest balanced score wins.")
    st.subheader("🏅 Live Leaderboard");lb=leaderboard_data()
    if lb.empty:st.info("Complete a round to populate the leaderboard.")
    else:
        for col in ["Total Score","Cpk","Productivity"]:lb[col]=pd.to_numeric(lb[col],errors="coerce")
        lb=lb.sort_values(["Total Score","Cpk","Productivity"],ascending=False).reset_index(drop=True);lb.insert(0,"Rank",range(1,len(lb)+1));st.dataframe(lb[["Rank","Team Name","Department","Round","Productivity","Cp","Cpk","Yield %","Budget Remaining","Total Score"]],use_container_width=True,hide_index=True);st.download_button("Download Leaderboard",lb.to_csv(index=False).encode("utf-8-sig"),"leaderboard.csv",use_container_width=True)

if st.session_state.get("registered"):dashboard()
else:registration()
