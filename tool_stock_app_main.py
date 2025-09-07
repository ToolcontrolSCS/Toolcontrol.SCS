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
    """ส่งข้อความไป Telegram"""
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

# Start scheduler thread (รันครั้งเดียว)
if "scheduler_started" not in st.session_state:
    st.session_state["scheduler_started"] = True
    threading.Thread(target=run_scheduler, daemon=True).start()

tab_dash, tab_out, tab_in, tab_master, tab_txn, tab_po = st.tabs(
    ["📊 Dashboard", "📤 Issue / Use (OUT)", "📥 Return / Receive (IN)", "🧰 Master Data", "🧾 Transactions", "📦 PO Management"]
)

# -------------------------------
# Dashboard
# -------------------------------
with tab_dash:
    st.markdown("## 📊 🛠️ Tool Stock Control Dashboard")

    try:
        df_bal = pd.DataFrame(
            sb.table("v_tool_balance_with_po").select("*").execute().data
        )
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

        st.download_button(
            "⬇️ Export Stock Balance CSV",
            data=view.to_csv(index=False),
            file_name=f"stock_balance_{tz_now().strftime('%Y%m%d_%H%M')}.csv"
        )
    else:
        st.info("No data in v_tool_balance_with_po")

# -------------------------------
# OUT Transaction
# -------------------------------
with tab_out:
    st.markdown("## 📤 Issue / Use (OUT)")
    # ... (เหมือนเดิม)

# -------------------------------
# IN Transaction
# -------------------------------
with tab_in:
    st.markdown("## 📥 Return / Receive (IN)")
    # ... (เหมือนเดิม)

# -------------------------------
# Master Data
# -------------------------------
with tab_master:
    st.markdown("## 🧰 Tool Master Data")
    # ... (เหมือนเดิม)

# -------------------------------
# Transactions
# -------------------------------
with tab_txn:
    st.markdown("## 🧾 Recent Transactions (ล่าสุด 300 รายการ)")
    # ... (เหมือนเดิม)

# -------------------------------
# PO Management
# -------------------------------
with tab_po:
    st.markdown("## 📦 PO Management")

    # Create new PO Header
    with st.expander("➕ Create PO"):
        po_number = st.text_input("PO Number")
        supplier = st.text_input("Supplier")
        approved_by = st.text_input("Approved By")

        if st.button("💾 Save PO Header", key="save_po_header"):
            payload = {
                "po_number": po_number,
                "supplier": supplier,
                "approved_by": approved_by,
                "status": "Approved",
                "created_at": tz_now().isoformat()
            }
            res = sb.table("po_header").insert(payload).execute()
            if res.data:
                st.success(f"✅ PO {po_number} created")
                send_telegram(f"📦 PO Created: {po_number} | Supplier: {supplier}")

    # Add PO Items
    with st.expander("➕ Add PO Item"):
        po_id = st.text_input("PO ID (from header)")
        mdf = get_master(sb)
        tool = st.selectbox("Tool", options=(mdf["tool_code"] + " | " + mdf["tool_name"]) if not mdf.empty else [], key="po_item_tool")
        tool_code = tool.split(" | ")[0] if tool else None
        qty = st.number_input("Request Qty", min_value=0.0, step=1.0, key="po_item_qty")

        if st.button("💾 Save PO Item", key="save_po_item"):
            if po_id and tool_code and qty > 0:
                payload = {
                    "po_id": po_id,
                    "tool_code": tool_code,
                    "request_qty": qty,
                    "status": "Pending"
                }
                sb.table("po_items").insert(payload).execute()
                st.success(f"✅ PO Item {tool_code} added to PO {po_id}")

    # Receive PO Items
    with st.expander("📥 Receive PO Item"):
        po_item_id = st.text_input("PO Item ID")
        receive_qty = st.number_input("Receive Qty", min_value=0.0, step=1.0, key="recv_qty")

        if st.button("📥 Receive", key="btn_receive"):
            if po_item_id and receive_qty > 0:
                item = sb.table("po_items").select("*").eq("id", po_item_id).execute().data[0]
                new_received = item["received_qty"] + receive_qty
                status = "Partially Received" if new_received < item["request_qty"] else "Received"

                sb.table("po_items").update({
                    "received_qty": new_received,
                    "status": status
                }).eq("id", po_item_id).execute()

                # Log to stock
                record_txn(sb, {
                    "tool_code": item["tool_code"],
                    "direction": "IN",
                    "qty": receive_qty,
                    "dept": "PURCHASE",
                    "reason": "PO Received",
                    "remark": "New",
                    "ref_doc": f"PO-ITEM#{po_item_id}",
                    "txn_time": tz_now().isoformat()
                })

                st.success(f"📥 Received {receive_qty} of {item['tool_code']}")

                msg = (
                    f"📥 PO Receive\n"
                    f"PO Item: {item['tool_code']} | Qty {int(receive_qty)}\n"
                    f"Total Received: {int(new_received)}/{int(item['request_qty'])}"
                )
                if status == "Received":
                    msg += "\n✅ Item completed"
                send_telegram(msg)

    st.divider()
    st.markdown("### 🔍 PO Tracking")

    df_po = pd.DataFrame(sb.table("v_po_tracking").select("*").limit(200).execute().data)
    if not df_po.empty:
        df_po["created_at"] = pd.to_datetime(df_po["created_at"], errors="coerce")
        styled_po = df_po.style.format({
            "request_qty": "{:,.0f}",
            "received_qty": "{:,.0f}",
            "remaining_qty": "{:,.0f}"
        })
        st.dataframe(styled_po, use_container_width=True)
    else:
        st.info("ยังไม่มี PO")
