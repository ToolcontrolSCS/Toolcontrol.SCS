# tool_stock_app_main.py

import os
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta, timezone
import schedule
import time
import threading

# -------------------------------
# CONFIG
# -------------------------------
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

# Timezone
TZ = timezone(timedelta(hours=7))
def tz_now():
    return datetime.now(TZ)

# -------------------------------
# SUPABASE
# -------------------------------
@st.cache_resource
def get_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("⚠️ Please set SUPABASE_URL and SUPABASE_KEY in secrets.toml")
        return None
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def send_telegram(msg: str):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": msg})
    except Exception as e:
        st.warning(f"⚠️ Telegram send failed: {e}")

def get_master(sb):
    res = sb.table("tool_master").select("*").eq("is_active", True).order("tool_code").execute()
    return pd.DataFrame(res.data)

def record_txn(sb, payload: dict):
    res = sb.table("tool_stock_txn").insert(payload).execute()
    return res

# -------------------------------
# DAILY ALERT (08:00)
# -------------------------------
def send_daily_below_min():
    try:
        df_bal = pd.DataFrame(
            sb.table("v_tool_balance_with_po").select("*").execute().data
        )
    except Exception:
        return
    if df_bal.empty:
        return

    below_min_df = df_bal[df_bal["is_below_min"] == True]
    if below_min_df.empty:
        msg = f"📅 Daily Report {tz_now().strftime('%d-%m-%Y')} 08:00\n✅ ไม่มีรายการต่ำกว่า MIN"
    else:
        msg = f"📅 Daily Report {tz_now().strftime('%d-%m-%Y')} 08:00\n🚨 รายการต่ำกว่า MIN:\n"
        for _, row in below_min_df.iterrows():
            msg += (
                f"- {row['tool_code']} | {row['tool_name']} "
                f"(Process: {row.get('process','-')})\n"
                f"   On-hand: {int(row['on_hand'])} | "
                f"Min: {int(row['min_stock'])} | "
                f"On-PO: {int(row['on_po'])}\n"
            )
    send_telegram(msg)

def run_scheduler():
    schedule.every().day.at("08:00").do(send_daily_below_min)
    while True:
        schedule.run_pending()
        time.sleep(60)

# -------------------------------
# MAIN
# -------------------------------
st.title("🛠️ Tool Stock Control Dashboard")
st.caption("Production support system | Timezone: GMT+7")

sb = get_supabase()
if sb is None:
    st.stop()

# Start scheduler thread
if "scheduler_started" not in st.session_state:
    st.session_state["scheduler_started"] = True
    threading.Thread(target=run_scheduler, daemon=True).start()

# -------------------------------
# Sidebar menu
# -------------------------------
menu = st.sidebar.selectbox(
    "เลือกโหมด",
    [
        "📊 Dashboard",
        "📤 Issue / Use (OUT)",
        "📥 Return / Receive (IN)",
        "🧰 Master Data",
        "🧾 Transactions",
        "📦 PO Management"
    ]
)

# -------------------------------
# Dashboard
# -------------------------------
if menu == "📊 Dashboard":
    st.subheader("📊 Stock Dashboard")

    try:
        df_bal = pd.DataFrame(sb.table("v_tool_balance_with_po").select("*").execute().data)
    except Exception as e:
        st.error(f"Query failed: {e}")
        df_bal = pd.DataFrame()

    if not df_bal.empty:
        total_tools = len(df_bal)
        below_min = df_bal[df_bal["is_below_min"] == True].shape[0]
        total_on_hand = df_bal["on_hand"].sum()
        total_on_po = df_bal["on_po"].sum()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("🛠️ Tools", f"{total_tools}")
        c2.metric("⚠️ Below MIN", f"{below_min}")
        c3.metric("📦 On-hand Total", f"{total_on_hand:,.0f}")
        c4.metric("📝 On-PO Total", f"{total_on_po:,.0f}")

        st.divider()

        col1, col2 = st.columns([2,1])
        if "process" in df_bal.columns:
            with col1:
                process = st.selectbox(
                    "🔍 Filter by process",
                    options=["All"] + df_bal["process"].dropna().unique().tolist()
                )
        else:
            process = "All"

        with col2:
            danger_only = st.checkbox("🚨 Show only below MIN", value=False)

        view = df_bal.copy()
        if process != "All" and "process" in view.columns:
            view = view[view["process"] == process]
        if danger_only:
            view = view[view["is_below_min"] == True]

        def highlight_row(row):
            return ["background-color: #ffcccc" if row["is_below_min"] else ""] * len(row)

        styled_view = (
            view.style
            .apply(highlight_row, axis=1)
            .format({
                "min_stock": "{:,.0f}",
                "on_hand": "{:,.0f}",
                "on_po": "{:,.0f}"
            })
        )
        st.dataframe(styled_view, use_container_width=True, height=500)

# -------------------------------
# OUT Transaction
# -------------------------------
elif menu == "📤 Issue / Use (OUT)":
    st.subheader("📤 Issue / Use (OUT)")

    mdf = get_master(sb)
    if not mdf.empty:
        tool = st.selectbox("Tool", options=(mdf["tool_code"] + " | " + mdf["tool_name"]))
        tool_code = tool.split(" | ")[0] if tool else None

        qty = st.number_input("Qty OUT", min_value=0.0, step=1.0)
        dept = st.text_input("Department")
        machine = st.text_input("Machine Code")
        partno = st.text_input("Part No.")
        shift = st.text_input("Shift (01D/01N)")
        operator = st.text_input("Operator")
        reason = st.text_input("Reason", value="Issue")
        refdoc = st.text_input("Reference Doc")

        if st.button("💾 Save OUT", type="primary"):
            if tool_code and qty > 0:
                payload = {
                    "tool_code": tool_code, "direction": "OUT", "qty": qty,
                    "dept": dept or None, "machine_code": machine or None,
                    "part_no": partno or None, "shift": shift or None,
                    "reason": reason or None, "remark": None,
                    "ref_doc": refdoc or None, "operator": operator or None,
                    "txn_time": tz_now().isoformat()
                }
                record_txn(sb, payload)
                st.success("✅ OUT transaction saved")
                send_telegram(f"📤 OUT {tool_code} Qty {int(qty)} | On {tz_now().strftime('%d-%m %H:%M')}")
    else:
        st.info("⚠️ ไม่มี Tool Master")

# -------------------------------
# IN Transaction
# -------------------------------
elif menu == "📥 Return / Receive (IN)":
    st.subheader("📥 Return / Receive (IN)")

    mdf = get_master(sb)
    if not mdf.empty:
        tool = st.selectbox("Tool", options=(mdf["tool_code"] + " | " + mdf["tool_name"]))
        tool_code = tool.split(" | ")[0] if tool else None

        qty = st.number_input("Qty IN", min_value=0.0, step=1.0)
        dept = st.text_input("Department")
        machine = st.text_input("Machine Code")
        partno = st.text_input("Part No.")
        shift = st.text_input("Shift")
        operator = st.text_input("Operator")
        reason = st.text_input("Reason", value="Receive")
        remark = st.selectbox("Remark", ["New","Modify","Return"])
        refdoc = st.text_input("Reference Doc")

        if st.button("💾 Save IN", type="primary"):
            if tool_code and qty > 0:
                payload = {
                    "tool_code": tool_code, "direction": "IN", "qty": qty,
                    "dept": dept or None, "machine_code": machine or None,
                    "part_no": partno or None, "shift": shift or None,
                    "reason": reason or None, "remark": remark or None,
                    "ref_doc": refdoc or None, "operator": operator or None,
                    "txn_time": tz_now().isoformat()
                }
                record_txn(sb, payload)
                st.success("✅ IN transaction saved")
                send_telegram(f"📥 IN {tool_code} Qty {int(qty)} Remark {remark}")
    else:
        st.info("⚠️ ไม่มี Tool Master")

# -------------------------------
# Master Data
# -------------------------------
elif menu == "🧰 Master Data":
    st.subheader("🧰 Tool Master Data")
    dfm = get_master(sb)
    st.dataframe(dfm, use_container_width=True)

# -------------------------------
# Transactions
# -------------------------------
elif menu == "🧾 Transactions":
    st.subheader("🧾 Recent Transactions")
    dft = pd.DataFrame(
        sb.table("tool_stock_txn").select("*").order("txn_time", desc=True).limit(200).execute().data
    )
    if not dft.empty:
        dft["txn_time"] = pd.to_datetime(dft["txn_time"], errors="coerce")
        st.dataframe(dft, use_container_width=True)

# -------------------------------
# PO Management
# -------------------------------
elif menu == "📦 PO Management":
    st.subheader("📦 PO Management")

    action = st.radio("เลือกการทำงาน", ["📑 สร้าง PO", "➕ เพิ่ม Item", "📥 Receive PO"])

    # Create PO
    if action == "📑 สร้าง PO":
        po_number = st.text_input("PO Number")
        supplier = st.text_input("Supplier")
        approved_by = st.text_input("Approved by")
        if st.button("💾 Save PO"):
            if po_number:
                payload = {"po_number": po_number, "supplier": supplier, "approved_by": approved_by, "status": "Approved"}
                sb.table("po_header").insert(payload).execute()
                st.success("✅ PO created")

    # Add Item
    elif action == "➕ เพิ่ม Item":
        poh = pd.DataFrame(sb.table("po_header").select("*").eq("status","Approved").execute().data)
        if not poh.empty:
            po_select = st.selectbox("เลือก PO", poh["po_number"].tolist())
            po_id = poh[poh["po_number"] == po_select]["id"].iloc[0]

            mdf = get_master(sb)
            tool = st.selectbox("Tool", options=(mdf["tool_code"] + " | " + mdf["tool_name"]))
            tool_code = tool.split(" | ")[0] if tool else None
            qty = st.number_input("Request Qty", min_value=0.0, step=1.0)

            if st.button("💾 Save Item"):
                sb.table("po_items").insert({"po_id": po_id, "tool_code": tool_code, "request_qty": qty}).execute()
                st.success("✅ Item added")

    # Receive PO
    elif action == "📥 Receive PO":
        po_df = pd.DataFrame(sb.table("v_po_tracking").select("*").eq("item_status","Pending").execute().data)
        if not po_df.empty:
            st.dataframe(po_df, use_container_width=True)
            po_item_id = st.number_input("PO Item ID", min_value=0, step=1)
            qty = st.number_input("Receive Qty", min_value=0.0, step=1.0)
            if st.button("📥 Receive Item"):
                if po_item_id and qty > 0:
                    sb.rpc("receive_po_item", {"p_item_id": po_item_id, "p_qty": qty}).execute()
                    st.success("✅ Received")
