import os
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta, timezone
import schedule, time, threading

st.set_page_config(page_title="Tool Stock Control", page_icon="🛠️", layout="wide")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

try:
    from supabase import create_client
except ImportError:
    st.error("❌ Missing dependency: run `pip install supabase`")
    st.stop()

TZ = timezone(timedelta(hours=7))
def tz_now(): return datetime.now(TZ)

@st.cache_resource
def get_supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def send_telegram(msg: str):
    if TELEGRAM_TOKEN and TELEGRAM_CHAT_ID:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        try: requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
        except: pass

sb = get_supabase()
if sb is None: st.stop()

# -------- Scheduler for Daily Report --------
def send_daily_below_min():
    df_bal = pd.DataFrame(sb.table("v_tool_balance_with_po").select("*").execute().data)
    if df_bal.empty: return
    below = df_bal[df_bal["is_below_min"]==True]
    if below.empty:
        msg = f"📅 {tz_now().strftime('%d-%m-%Y')} 08:00\n✅ ไม่มี Tool ต่ำกว่า MIN"
    else:
        msg = f"📅 {tz_now().strftime('%d-%m-%Y')} 08:00\n🚨 Tool ต่ำกว่า MIN\n"
        for _,r in below.iterrows():
            msg+=f"- {r['tool_code']} | {r['tool_name']} | On-hand {int(r['on_hand'])} / Min {int(r['min_stock'])}\n"
    send_telegram(msg)

if "scheduler_started" not in st.session_state:
    st.session_state["scheduler_started"]=True
    threading.Thread(target=lambda: (schedule.every().day.at("08:00").do(send_daily_below_min),
                                     [schedule.run_pending() or time.sleep(60) for _ in iter(int,1)]),daemon=True).start()

# -------- Sidebar Menu --------
menu = st.sidebar.selectbox("เลือกโหมด", [
    "📊 Dashboard","📤 Issue / Use (OUT)","📥 Return / Receive (IN)",
    "🧰 Master Data","🧾 Transactions","📦 PO Management"
])

# -------- Dashboard --------
if menu=="📊 Dashboard":
    st.header("📊 Dashboard")
    df=pd.DataFrame(sb.table("v_tool_balance_with_po").select("*").execute().data)
    if not df.empty:
        c1,c2,c3,c4=st.columns(4)
        c1.metric("🛠️ Tools",len(df)); c2.metric("⚠️ Below Min",df[df['is_below_min']==True].shape[0])
        c3.metric("📦 On-hand",f"{df['on_hand'].sum():,.0f}"); c4.metric("📝 On-PO",f"{df['on_po'].sum():,.0f}")
        st.dataframe(df.style.format({"min_stock":"{:,.0f}","on_hand":"{:,.0f}","on_po":"{:,.0f}"}),use_container_width=True)

# -------- OUT --------
elif menu=="📤 Issue / Use (OUT)":
    st.header("📤 Issue / Use (OUT)")
    mdf=pd.DataFrame(sb.table("tool_master").select("*").eq("is_active",True).execute().data)
    tool=st.selectbox("Tool",mdf["tool_code"]+" | "+mdf["tool_name"] if not mdf.empty else [])
    qty=st.number_input("Qty OUT",min_value=0.0,step=1.0)
    if st.button("💾 Save OUT") and tool and qty>0:
        code=tool.split(" | ")[0]
        sb.table("tool_stock_txn").insert({"tool_code":code,"direction":"OUT","qty":qty,"txn_time":tz_now().isoformat()}).execute()
        st.success("บันทึกแล้ว"); send_telegram(f"📤 OUT {code} {int(qty)} pcs")

# -------- IN --------
elif menu=="📥 Return / Receive (IN)":
    st.header("📥 Return / Receive (IN)")
    mdf=pd.DataFrame(sb.table("tool_master").select("*").eq("is_active",True).execute().data)
    tool=st.selectbox("Tool",mdf["tool_code"]+" | "+mdf["tool_name"] if not mdf.empty else [])
    qty=st.number_input("Qty IN",min_value=0.0,step=1.0)
    remark=st.selectbox("Remark",["New","Modify","Return"])
    if st.button("💾 Save IN") and tool and qty>0:
        code=tool.split(" | ")[0]
        sb.table("tool_stock_txn").insert({"tool_code":code,"direction":"IN","qty":qty,"remark":remark,"txn_time":tz_now().isoformat()}).execute()
        st.success("บันทึกแล้ว"); send_telegram(f"📥 IN {code} {int(qty)} pcs ({remark})")

# -------- Master Data --------
elif menu=="🧰 Master Data":
    st.header("🧰 Master Data")
    df=pd.DataFrame(sb.table("tool_master").select("*").execute().data)
    st.dataframe(df,use_container_width=True)

# -------- Transactions --------
elif menu=="🧾 Transactions":
    st.header("🧾 Recent Transactions")
    df=pd.DataFrame(sb.table("tool_stock_txn").select("*").order("txn_time",desc=True).limit(200).execute().data)
    st.dataframe(df,use_container_width=True)

# -------- PO Management --------
elif menu=="📦 PO Management":
    st.header("📦 PO Management")
    choice=st.radio("เลือกการทำงาน",["➕ New PO","📋 View PO"])
    if choice=="➕ New PO":
        po_num=st.text_input("PO Number"); sup=st.text_input("Supplier")
        if st.button("✅ Create PO") and po_num:
            sb.table("po_header").insert({"po_number":po_num,"supplier":sup,"status":"Approved"}).execute()
            st.success("สร้าง PO แล้ว")
    else:
        df=pd.DataFrame(sb.table("v_po_tracking").select("*").execute().data)
        st.dataframe(df,use_container_width=True)
