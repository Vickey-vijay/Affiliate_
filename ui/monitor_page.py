import streamlit as st
from datetime import datetime
import builtins
from db.db_manager import DataManager
from notification.notification_manager import NotificationManager
from urllib.parse import urlparse
from monitors.amazon_monitor import AmazonIndiaMonitor
from utils.monitor_utils import save_logs_to_file, get_products_for_notification
from utils.scheduler_manager import start_scheduler, stop_scheduler
import os
import json
import schedule
import threading
import time
import random
import pandas as pd
from datetime import datetime, timedelta
from streamlit.runtime.scriptrunner import get_script_run_ctx
from streamlit.runtime.scriptrunner.script_run_context import add_script_run_ctx
from utils.monitor_utils import (
    save_logs_to_file, 
    get_products_for_notification, 
    restore_saved_schedule  
)


if 'monitoring_active' not in st.session_state:
    st.session_state.monitoring_active = False
if 'monitor_thread' not in st.session_state:
    st.session_state.monitor_thread = None
if 'script_run_ctx' not in st.session_state:
    st.session_state.script_run_ctx = get_script_run_ctx()

os.makedirs("logs", exist_ok=True)

def run_monitor_once_for_sites(sites):
    """
    For each site, instantiate its monitor and run it on products from that site.
    Returns the number of price changes detected.
    """
    db = DataManager()
    notification_manager = NotificationManager()
    
    log_placeholder = st.empty()
    log_text = "Starting price monitoring...\n"
    
    def update_log(message):
        nonlocal log_text
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
    
    original_print_func = builtins.print
    def ui_print(*args, **kwargs):
        message = " ".join(str(arg) for arg in args)
        update_log(message)
        original_print_func(*args, **kwargs)
    
    builtins.print = ui_print
    
    total_products_checked = 0
    price_changes = []
    successful_products = 0
    failed_products = 0
    
    try:
        for site in sites:
            domain = urlparse(site).netloc if '://' in site else site
            update_log(f"Working with site: {domain}")
            
            if 'amazon.in' in domain.lower():
                try:
                    update_log("Querying products from database...")
                    
                    all_products = list(db.products.find({"product_Affiliate_site": site}))
                    if not all_products:
                        update_log(f"No products found for site {site}. Trying with all products...")
                        all_products = list(db.products.find({}))
                    
                    product_ids = [p.get("Product_unique_ID") for p in all_products if p.get("Product_unique_ID")]
                    
                    if not product_ids:
                        update_log("⚠️ No product ASINs found in database!")
                        continue
                        
                    update_log(f"Found {len(product_ids)} products to check")
                    update_log(f"Sample ASINs: {product_ids[:5]}")
                    total_products_checked += len(product_ids)
                    
                    update_log("Initializing Amazon monitor...")
                    monitor = AmazonIndiaMonitor()
                    
                    update_log(f"Using Amazon API credentials - Access key: {monitor.access_key[:4]}***, Tag: {monitor.partner_tag}")
                    
                    batch_size = 10
                    for i in range(0, len(product_ids), batch_size):
                        batch = product_ids[i:i+batch_size]
                        update_log(f"Processing batch {i//batch_size + 1}/{(len(product_ids) + batch_size - 1)//batch_size}")
                        update_log(f"Batch ASINs: {batch}")
                        
                        try:
                            product_data = monitor.fetch_product_data(batch)
                            
                            if not product_data:
                                update_log(f"⚠️ No data returned for batch {i//batch_size + 1}")
                                failed_products += len(batch)
                                continue
                            
                            update_log(f"✅ Received data for {len(product_data)} products in batch")
                            
                            for asin, data in product_data.items():
                                current_product = db.products.find_one({"Product_unique_ID": asin})
                                old_price = current_product.get("Product_current_price") if current_product else None
                                
                                update_data = {
                                    "Product_current_price": data.get("price"),
                                    "Product_Buy_box_price": data.get("buy_box_price"),
                                    "Product_image_path": data.get("image_path", ""),
                                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "updated_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                }
                                
                                db.update_product(asin, update_data)
                                successful_products += 1
                                update_log(f"✅ Database updated for {asin}")
                                
                                if old_price and data.get("price") and float(old_price) != float(data.get("price")):
                                    update_log(f"💰 Price change detected for {asin}: {old_price} -> {data.get('price')}")
                                    if current_product:
                                        price_changes.append(current_product)
                                        notification_manager.notify_price_change(
                                            current_product,
                                            old_price,
                                            data.get("price")
                                        )
                        
                        except Exception as batch_error:
                            update_log(f"❌ Error processing batch: {str(batch_error)}")
                            failed_products += len(batch)
                            import traceback
                            update_log(traceback.format_exc())
                    
                    update_log(f"✅ Amazon monitoring completed: {successful_products} successful, {failed_products} failed")
                    
                except Exception as e:
                    update_log(f"❌ Error during Amazon monitoring: {str(e)}")
                    import traceback
                    update_log(traceback.format_exc())
            else:
                update_log(f"⚠️ Site {domain} not fully implemented yet")
        
        update_log(f"🏁 Monitoring complete! Checked {total_products_checked} products, found {len(price_changes)} price changes.")
        
        try:
            publish_candidates = get_products_for_notification(db)
            update_log(f"Found {len(publish_candidates)} products that meet publishing criteria")
            st.session_state["filter_results"] = publish_candidates
        except Exception as e:
            update_log(f"❌ Error in filtering products: {str(e)}")
            st.session_state["filter_results"] = []
        
        
                
    finally:
        builtins.print = original_print_func
        
    return len(price_changes)

class ProductMonitorPage:
    def render(self):
        st.header("🔄 Product Monitor")
        
        if not st.session_state.get("schedule_restored"):
            if restore_saved_schedule():
                st.toast("✅ Restored previous monitoring schedule")
            st.session_state["schedule_restored"] = True
        
        self.render_site_selection()
        self.render_schedule_settings()
        self.render_monitor_status()
        self.render_monitor_tabs()

    def render_site_selection(self):
        db = DataManager()
        sites = db.products.distinct("product_Affiliate_site")
        
        # Initialize with empty list if not present
        if "sites" not in st.session_state:
            st.session_state["sites"] = []
        
        # Filter the default values to ensure they exist in options
        valid_defaults = [site for site in st.session_state["sites"] if site in sites]
        
        col1, col2 = st.columns([3, 1])
        with col1:
            selected_sites = st.multiselect(
                "Select sites to monitor",
                options=sites,
                default=valid_defaults
            )
        st.session_state["sites"] = selected_sites

    def render_schedule_settings(self):
        with st.expander("🕒 Schedule Settings", expanded=True):
            schedule_type = st.radio(
                "Select Schedule Type",
                ["Simple", "Advanced", "Custom Times"]
            )

            if schedule_type == "Simple":
                frequency = st.selectbox(
                    "Select frequency",
                    ["Every 15 minutes", "Every 30 minutes", "Hourly", "Every 2 hours", "Every 6 hours"]
                )
            
            elif schedule_type == "Advanced":
                col1, col2 = st.columns(2)
                with col1:
                    hours = st.number_input("Hours", min_value=0, max_value=24)
                with col2:
                    minutes = st.number_input("Minutes", min_value=0, max_value=59)

            else:  
                times_container = st.container()
                with times_container:
                    if "daily_times" not in st.session_state:
                        st.session_state.daily_times = [datetime.now().time()]
                    
                    for i, t in enumerate(st.session_state.daily_times):
                        col1, col2 = st.columns([4, 1])
                        with col1:
                            st.session_state.daily_times[i] = st.time_input(
                                f"Time #{i+1}",
                                value=t
                            )
                        with col2:
                            if st.button("🗑️", key=f"remove_time_{i}"):
                                st.session_state.daily_times.pop(i)
                                st.rerun()
                    
                    if st.button("➕ Add Another Time"):
                        st.session_state.daily_times.append(datetime.now().time())
                        st.rerun()

            button_cols = st.columns([1, 1, 1])
            with button_cols[0]:
                start_button = st.button("▶️ Start Monitor", use_container_width=True)
            with button_cols[1]:
                stop_button = st.button("⏹️ Stop Monitor", use_container_width=True)
            with button_cols[2]:
                run_once_button = st.button("🔄 Run Once", use_container_width=True)

        status_cols = st.columns([2, 1])
        with status_cols[0]:
            if "monitoring_active" in st.session_state and st.session_state["monitoring_active"]:
                next_run_time = schedule.next_run()
                next_run = next_run_time.strftime("%H:%M:%S") if next_run_time else "Not scheduled"
                st.success(f"🔄 Monitor is running - Next check: {next_run}")
            else:
                st.warning("⏸️ Monitor is currently stopped")

        st.markdown("### 📜 Monitor Logs")
        log_cols = st.columns([6, 1])
        with log_cols[0]:
            if "log_text" in st.session_state:
                st.text_area(
                    "",
                    value=st.session_state.get("log_text", ""),
                    height=400,
                    key=f"log_viewer_{datetime.now().strftime('%H%M%S%f')}"
                )
            else:
                st.info("No logs available yet")

        if start_button:
            try:
                st.session_state.script_run_ctx = get_script_run_ctx()
                
                if schedule_type == "Simple":
                    freq_map = {
                        "Every 5 minutes": 5,
                        "Every 15 minutes": 15,
                        "Every 30 minutes": 30,
                        "Hourly": 60,
                        "Every 2 hours": 120,
                        "Every 6 hours": 360
                    }
                    if frequency is None:
                        frequency = "Every 15 minutes" 
                    
                    minutes = freq_map[frequency]
                    start_scheduler(0, minutes, [], run_monitor_once_for_sites)
                    st.toast(f"✅ Monitor started with {frequency} schedule")
                
                elif schedule_type == "Advanced":
                    if hours == 0 and minutes == 0:
                        st.error("Please set a valid interval")
                        return
                    start_scheduler(hours, minutes, [],run_monitor_once_for_sites)
                    st.toast(f"✅ Monitor started with {hours}h {minutes}m interval")
                
                else:  
                    if not st.session_state.daily_times:
                        st.error("Please add at least one time")
                        return
                    start_scheduler(0, 0, st.session_state.daily_times,run_monitor_once_for_sites)
                    times_str = ", ".join([t.strftime("%H:%M") for t in st.session_state.daily_times])
                    st.toast(f"✅ Monitor scheduled for: {times_str}")
                
                st.session_state["script_run_ctx"] = get_script_run_ctx()
                
            except Exception as e:
                st.error(f"Failed to start scheduler: {str(e)}")

        if stop_button:
            stop_scheduler()
            st.toast("✅ Monitor stopped")

        if run_once_button:
            st.toast("🔄 Starting manual check...")
            run_monitor_once_for_sites(st.session_state.sites)

    def render_monitor_status(self):
        status_cols = st.columns([2, 1])
        with status_cols[0]:
            if "monitoring_active" in st.session_state and st.session_state["monitoring_active"]:
                next_run_time = schedule.next_run()
                next_run = next_run_time.strftime("%H:%M:%S") if next_run_time else "Not scheduled"
                st.success(f"🔄 Monitor is running - Next check: {next_run}")
            else:
                st.warning("⏸️ Monitor is currently stopped")

    def render_monitor_tabs(self):
        tabs = st.tabs(["Monitor", "Notification Schedule"])
        
        with tabs[0]:
            self.render_monitor_tab()
        
        with tabs[1]:
            notification_schedule = NotificationSchedule()
            notification_schedule.render()

    def render_monitor_tab(self):
        st.markdown("### 📜 Monitor Logs")
        log_cols = st.columns([6, 1])
        with log_cols[0]:
            if "log_text" in st.session_state:
                st.text_area(
                    "",
                    value=st.session_state.get("log_text", ""),
                    height=400,
                    key=f"log_viewer_{datetime.now().strftime('%H%M%S%f')}"
                )
            else:
                st.info("No logs available yet")

class NotificationSchedule:
    def render(self):
        st.subheader("📅 Notification Schedule")
        
        with st.expander("Configure Notifications", expanded=True):
            schedule_type = st.selectbox(
                "Schedule Type",
                ["Daily", "Weekly", "Custom"]
            )
            
            if schedule_type == "Daily":
                notification_time = st.time_input("Select notification time", value=datetime.strptime("10:00", "%H:%M").time())
            
            elif schedule_type == "Weekly":
                col1, col2 = st.columns(2)
                with col1:
                    week_day = st.selectbox(
                        "Select day of week",
                        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                    )
                with col2:
                    notification_time = st.time_input("Select time")
            
            else:  
                custom_times = []
                times_container = st.container()
                with times_container:
                    if "custom_notification_times" not in st.session_state:
                        st.session_state.custom_notification_times = [datetime.now().time()]
                    
                    for i, t in enumerate(st.session_state.custom_notification_times):
                        col1, col2 = st.columns([4, 1])
                        with col1:
                            st.session_state.custom_notification_times[i] = st.time_input(
                                f"Time #{i+1}",
                                value=t
                            )
                        with col2:
                            if st.button("🗑️", key=f"remove_notification_time_{i}"):
                                st.session_state.custom_notification_times.pop(i)
                                st.rerun()
                    
                    if st.button("➕ Add Time"):
                        st.session_state.custom_notification_times.append(datetime.now().time())
                        st.rerun()

            st.markdown("### 📧 Email Settings")
            recipients = st.text_input("Recipients (comma-separated emails)")
            subject_template = st.text_input("Email Subject Template", 
                                          value="Price Alert: {product_name}")
            body_template = st.text_area("Email Body Template", 
                                       value="Product: {product_name}\nCurrent Price: ₹{current_price}\nMRP: ₹{mrp}\nDiscount: {discount}%\nBuy Now: {affiliate_link}")

            if st.button("💾 Save Schedule"):
                schedule_config = {
                    "type": schedule_type,
                    "active": True,
                    "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "email": {
                        "recipients": [r.strip() for r in recipients.split(",")],
                        "subject_template": subject_template,
                        "body_template": body_template
                    }
                }

                if schedule_type == "Daily":
                    schedule_config["time"] = notification_time.strftime("%H:%M")
                elif schedule_type == "Weekly":
                    schedule_config["day"] = week_day
                    schedule_config["time"] = notification_time.strftime("%H:%M")
                else:
                    schedule_config["custom_times"] = [
                        t.strftime("%H:%M") for t in st.session_state.custom_notification_times
                    ]

                db = DataManager()
                try:
                    db.save_notification_schedule(schedule_config)
                    st.success("✅ Notification schedule saved successfully!")
                    
                    self.setup_notification_schedule(schedule_config)
                except Exception as e:
                    st.error(f"Failed to save schedule: {str(e)}")

    def setup_notification_schedule(self, config):
        """Set up the notification schedule based on configuration"""
        schedule.clear()
        
        def send_notification():
            try:
                db = DataManager()
                notification_manager = NotificationManager()
                
                products = get_products_for_notification(db)
                
                if products:
                    for product in products:
                        notification_manager.notify_price_change(
                            product,
                            product.get("Product_current_price", "N/A"),  # Using current price as old price
                            product.get("Product_current_price", "N/A"),  # Using current price as new price
                        )
            except Exception as e:
                print(f"Error sending notification: {e}")

        if config["type"] == "Daily":
            schedule.every().day.at(config["time"]).do(send_notification)
        
        elif config["type"] == "Weekly":
            days = {
                "Monday": schedule.every().monday,
                "Tuesday": schedule.every().tuesday,
                "Wednesday": schedule.every().wednesday,
                "Thursday": schedule.every().thursday,
                "Friday": schedule.every().friday,
                "Saturday": schedule.every().saturday,
                "Sunday": schedule.every().sunday
            }
            days[config["day"]].at(config["time"]).do(send_notification)
        
        else: 
            for time in config["custom_times"]:
                schedule.every().day.at(time).do(send_notification)