import streamlit as st
from datetime import datetime
import schedule
import threading
import time
from streamlit.runtime.scriptrunner import get_script_run_ctx

def start_scheduler(hours, minutes, daily_times, run_monitor_callback):
    """Set up a scheduler to run the monitoring at specified intervals and times."""
    if 'scheduler_config' not in st.session_state:
        st.session_state.scheduler_config = {}
    
    st.session_state.scheduler_config = {
        "type": "custom" if daily_times else "interval",
        "hours": hours,
        "minutes": minutes,
        "daily_times": [t.strftime("%H:%M") for t in daily_times] if daily_times else [],
        "sites": st.session_state.get("sites", []),
        "last_run": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }

    schedule.clear()
    ctx = get_script_run_ctx()
    
    def safe_run_monitor():
        try:
            with ctx:
                run_monitor_callback(st.session_state.sites)
                st.session_state.scheduler_config["last_run"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        except Exception as e:
            print(f"Error in monitor: {e}")

    if hours > 0:
        schedule.every(hours).hours.do(safe_run_monitor)
    if minutes > 0:
        schedule.every(minutes).minutes.do(safe_run_monitor)
    if daily_times:
        for time_slot in daily_times:
            schedule.every().day.at(time_slot.strftime("%H:%M")).do(safe_run_monitor)

    if not st.session_state.get("monitoring_active", False):
        st.session_state["monitoring_active"] = True
        t = threading.Thread(target=_scheduler_loop, daemon=True)
        t.start()
        st.session_state["monitor_thread"] = t

def stop_scheduler():
    """Stop the scheduler thread"""
    schedule.clear()
    st.session_state["monitoring_active"] = False

def _scheduler_loop():
    """Dedicated scheduler loop that maintains state"""
    while st.session_state.get("monitoring_active", False):
        try:
            schedule.run_pending()
            next_run = schedule.next_run()
            if next_run:
                st.session_state["next_scheduled_run"] = next_run.strftime("%Y-%m-%d %H:%M:%S")
            time.sleep(1)
        except Exception as e:
            print(f"Scheduler error: {e}")
            time.sleep(5)