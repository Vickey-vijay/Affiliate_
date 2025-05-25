import streamlit as st
from datetime import datetime
import os
from db.db_manager import DataManager
from utils.scheduler_manager import start_scheduler

def save_logs_to_file(log_text):
    """Save the current log text to a timestamped file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = f"logs/monitor_log_{timestamp}.txt"
    try:
        with open(log_file, "w") as f:
            f.write(log_text)
        return log_file
    except Exception as e:
        print(f"Error saving logs to file: {e}")
        return None

def restore_saved_schedule():
    """Restore previously saved monitoring schedule"""
    try:
        db = DataManager()
        saved_schedule = db.get_monitor_schedule()
        
        if saved_schedule and saved_schedule.get("active"):
            # Get run_monitor_callback function from session state
            from ui.monitor_page import run_monitor_for_sites
            
            # Restore schedule configuration
            if saved_schedule["type"] == "interval":
                start_scheduler(
                    saved_schedule.get("hours", 0),
                    saved_schedule.get("minutes", 0),
                    [],
                    run_monitor_for_sites  # Pass the callback function
                )
            else:  # Custom times
                daily_times = saved_schedule.get("daily_times", [])
                start_scheduler(0, 0, daily_times, run_monitor_for_sites)
            
            st.session_state["sites"] = saved_schedule.get("sites", [])
            return True
            
    except Exception as e:
        print(f"Error restoring schedule: {e}")
    return False

def update_monitor_log(message, log_placeholder, log_text):
    """Update monitor logs in the UI"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_text += f"[{timestamp}] {message}\n"
    st.session_state["log_text"] = log_text
    
    unique_key = f"log_area_{datetime.now().strftime('%H%M%S%f')}"
    
    log_placeholder.text_area(
        "Logs", 
        log_text, 
        height=500,
        key=unique_key
    )
    
    st.markdown("""
        <script>
            const textarea = document.querySelector('.stTextArea textarea:last-child');
            if (textarea) {
                textarea.scrollTop = textarea.scrollHeight;
            }
        </script>
        """, 
        unsafe_allow_html=True
    )
    
    return log_text

def get_products_for_notification(db):
    """Apply advanced filters to find products for notification"""
    import pandas as pd
    from datetime import datetime, timedelta
    
    products = db.get_all_products()
    
    df = pd.DataFrame(products)
    if df.empty:
        return []
    
    # Filter products with price changes
    if "Product_current_price" in df.columns and "Product_Buy_box_price" in df.columns:
        df["Product_current_price"] = pd.to_numeric(df["Product_current_price"], errors='coerce')
        df["Product_Buy_box_price"] = pd.to_numeric(df["Product_Buy_box_price"], errors='coerce')
        df = df[df["Product_current_price"] < df["Product_Buy_box_price"]]
    
    if not hasattr(db, 'published'):
        db.published = db.db.published
    
    try:
        published_asins = list(db.published.distinct("asin"))
    except Exception as e:
        print(f"Error querying published collection: {e}")
        published_asins = []
    
    if "Product_unique_ID" in df.columns:
        never_published = df[~df["Product_unique_ID"].isin(published_asins)]
    else:
        never_published = df
    
    return never_published.to_dict('records')