# tool_stock_app_main.py

import os
import requests
import pandas as pd
import streamlit as st
from datetime import datetime, timedelta, timezone

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
def tz_now():
    return datetime.now(TZ)

@st.cache_resource
def get_supabase():
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("⚠️ Please set SUPABASE_URL and SUPABASE_KEY in environment/secrets.")
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

st.title("🛠️ Tool Stock Control")
st.caption("Prevent production stop by monitoring actual tool stock (GMT+7).")

sb = get_supabase()
if sb is None:
    st.stop()

tab_dash, tab_out, tab_in, tab_master, tab_txn = st.tabs(
    ["📊 Dashboard", "⬇️ Issue / Use (OUT)", "⬆️ Return / Receive (IN)", "🧰 Master Data", "🧾 Transactions"]
)

# -------------------------------
# Dashboard
# -------------------------------
with tab_dash:
    st.subheader("Stock Health / Reorder Suggestion")

    try:
        df_bal = pd.DataFrame(
            sb.table("v_tool_balance_with_po").select("*").execute().data
        )
    except Exception as e:
        st.error(f"Query failed: {e}")
        df_bal = pd.DataFrame()

    if not df_bal.empty:
        col1, col2 = st.columns(2)
        # เช็คก่อนว่ามี process ไหม
        if "process" in df_bal.columns:
            with col1:
                process = st.selectbox(
                    "Filter by process",
                    options=["All"] + df_bal["process"].dropna().unique().tolist()
                )
        else:
            process = "All"
            st.info("⚠️ Column 'process' not found in view")

        with col2:
            danger_only = st.checkbox("Show only below MIN", value=False)

        view = df_bal.copy()
        if process != "All" and "process" in view.columns:
            view = view[view["process"] == process]
        if danger_only:
            view = view[view["is_below_min"] == True]

        st.dataframe(view, use_container_width=True)
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
    st.subheader("Issue / Use (OUT)")

    mdf = get_master(sb)
    tool = st.selectbox("Tool", options=(mdf["tool_code"] + " | " + mdf["tool_name"]) if not mdf.empty else [])
    tool_code = tool.split(" | ")[0] if tool else None

    c1, c2, c3 = st.columns(3)
    qty = c1.number_input("Qty OUT", min_value=0.0, step=1.0)
    dept = c2.text_input("Department")
    machine = c3.text_input("Machine Code")

    c4, c5, c6 = st.columns(3)
    partno = c4.text_input("Part No.")
    shift = c5.text_input("Shift (01D/01N)")
    operator = c6.text_input("Operator")

    reason = st.text_input("Reason", value="Issue")
    refdoc = st.text_input("Reference Doc")

    if st.button("💾 Save OUT"):
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

            # ตรวจสอบ min
            bal = sb.table("v_tool_balance_with_po").select("*").eq("tool_code", tool_code).execute()
            if bal.data and bal.data[0].get("is_below_min"):
                item = bal.data[0]
                msg = f"""⚠️ Below MIN
Tool: {item['tool_code']} | {item.get('tool_name','')}
On-hand: {item.get('on_hand')} < Min {item.get('min_stock')}
On-PO: {item.get('on_po')}"""
                send_telegram(msg)
        else:
            st.warning("กรุณาเลือก Tool และ Qty > 0")

# -------------------------------
# IN Transaction
# -------------------------------
with tab_in:
    st.subheader("Return / Receive (IN)")

    mdf = get_master(sb)
    tool = st.selectbox("Tool ", options=(mdf["tool_code"] + " | " + mdf["tool_name"]) if not mdf.empty else [], key="in_tool")
    tool_code = tool.split(" | ")[0] if tool else None

    c1, c2, c3 = st.columns(3)
    qty = c1.number_input("Qty IN", min_value=0.0, step=1.0, key="qty_in")
    dept = c2.text_input("Department", key="dept_in")
    machine = c3.text_input("Machine Code", key="mc_in")

    c4, c5, c6 = st.columns(3)
    partno = c4.text_input("Part No.", key="pn_in")
    shift = c5.text_input("Shift", key="shift_in")
    operator = c6.text_input("Operator", key="op_in")

    reason = st.text_input("Reason", value="Receive/Return", key="reason_in")
    remark = st.selectbox("Remark", options=["New","Modify","Return"], key="remark_in")
    refdoc = st.text_input("Reference Doc", key="ref_in")

    if st.button("💾 Save IN"):
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
        else:
            st.warning("กรุณาเลือก Tool และ Qty > 0")

# -------------------------------
# Master Data
# -------------------------------
with tab_master:
    st.subheader("Tool Master Data")
    dfm = get_master(sb)
    st.dataframe(dfm, use_container_width=True)
    st.download_button("⬇️ Export Tool Master CSV", data=dfm.to_csv(index=False), file_name="tool_master_export.csv")

# -------------------------------
# Transactions
# -------------------------------
with tab_txn:
    st.subheader("Recent Transactions (ล่าสุด 300 รายการ)")
    dft = pd.DataFrame(
        sb.table("tool_stock_txn").select("*").order("txn_time", desc=True).limit(300).execute().data
    )
    if not dft.empty:
        dft["txn_time"] = pd.to_datetime(dft["txn_time"]).dt.tz_convert("Asia/Bangkok")
    st.dataframe(dft, use_container_width=True)
    st.download_button("⬇️ Export Transactions CSV", data=dft.to_csv(index=False), file_name="transactions_export.csv")
