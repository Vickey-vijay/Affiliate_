import streamlit as st
from datetime import datetime
import schedule
from db.db_manager import DataManager
from notification.notification_manager import NotificationManager

class NotificationSchedule:
    def render(self):
        st.subheader("📅 Notification Schedule")
        
        with st.expander("Configure Notifications", expanded=True):
            schedule_type = st.selectbox(
                "Schedule Type",
                ["Daily", "Weekly", "Custom"]
            )
            
            # Time Selection
            notification_time = None
            week_day = None
            
            if schedule_type == "Daily":
                notification_time = st.time_input(
                    "Select notification time", 
                    value=datetime.strptime("10:00", "%H:%M").time()
                )
            
            elif schedule_type == "Weekly":
                col1, col2 = st.columns(2)
                with col1:
                    week_day = st.selectbox(
                        "Select day of week",
                        ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                    )
                with col2:
                    notification_time = st.time_input("Select time")
            
            else:  # Custom
                self.render_custom_times()

            # Email Configuration
            self.render_email_settings()

    def render_custom_times(self):
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

    def render_email_settings(self):
        st.markdown("### 📧 Email Settings")
        recipients = st.text_input("Recipients (comma-separated emails)")
        subject_template = st.text_input(
            "Email Subject Template", 
            value="Price Alert: {product_name}"
        )
        body_template = st.text_area(
            "Email Body Template", 
            value="Product: {product_name}\nCurrent Price: ₹{current_price}\nMRP: ₹{mrp}\nDiscount: {discount}%\nBuy Now: {affiliate_link}"
        )

        if st.button("💾 Save Schedule"):
            self.save_notification_schedule(
                schedule_type, 
                notification_time, 
                week_day, 
                recipients, 
                subject_template, 
                body_template
            )

    def setup_notification_schedule(self, config):
        """Set up the notification schedule based on configuration"""
        schedule.clear()
        
        def send_notification():
            try:
                db = DataManager()
                notification_manager = NotificationManager()
                products = db.get_products_for_notification()
                
                if products:
                    for product in products:
                        notification_manager.send_email_notification(
                            product,
                            config["email"]["recipients"],
                            config["email"]["subject_template"],
                            config["email"]["body_template"]
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
        else:  # Custom
            for time in config["custom_times"]:
                schedule.every().day.at(time).do(send_notification)