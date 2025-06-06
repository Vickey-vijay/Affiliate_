import streamlit as st
import json
import os
from notification_publisher import NotificationPublisher
from config_manager import ConfigManager
from monitors.amazon_monitor import AmazonIndiaMonitor
from notification.notification_manager import NotificationManager
from notification.telegram_notifier import TelegramNotifier
from datetime import datetime

class ConfigPage:
    def __init__(self):
        self.config_manager = ConfigManager() 
        self.config = self.load_config()

    def load_config(self):
        try:
            with open("config.json", "r") as file:
                return json.load(file)
        except Exception as e:
            st.error(f"Failed to load configuration: {e}")
            return {}

    def save_config(self):
        try:
            with open("config.json", "w") as file:
                json.dump(self.config, file, indent=4)
        except Exception as e:
            st.error(f"Failed to save configuration: {e}")

    def render_whatsapp_configuration(self):
        st.subheader("WhatsApp Configuration")

        col1, col2 = st.columns(2)
        
        with col1:
            st.markdown("### Channels")
            whatsapp_channels = st.text_input(
                "WhatsApp Channel Names (comma-separated)",
                self.config.get("whatsapp", {}).get("channel_names", ""),
                key="whatsapp_channel_names",
                help="Enter channel names exactly as they appear in WhatsApp"
            )

        with col2:
            st.markdown("### Groups")
            whatsapp_groups = st.text_input(
                "WhatsApp Group Names (comma-separated)",
                self.config.get("whatsapp", {}).get("group_names", ""),
                key="whatsapp_group_names",
                help="Enter group names exactly as they appear in WhatsApp"
            )

        if st.button("Save WhatsApp Configuration", key="save_whatsapp_config"):
            if not "whatsapp" in self.config:
                self.config["whatsapp"] = {}
                
            self.config["whatsapp"]["channel_names"] = whatsapp_channels
            self.config["whatsapp"]["group_names"] = whatsapp_groups
            self.save_config()
            st.success("✅ WhatsApp configuration saved successfully!")

        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("Test WhatsApp Channels", key="test_whatsapp_channels", disabled=not whatsapp_channels):
                if not whatsapp_channels:
                    st.error("Please enter at least one WhatsApp channel name.")
                else:
                    from notification_publisher import NotificationPublisher
                    publisher = NotificationPublisher(self.config_manager)
                    test_message = "This is a test message from Affiliate Product Monitor (Channel Test)."
                    success_count = 0
                    failure_count = 0
                    
                    with st.spinner("Sending test messages to channels..."):
                        for channel in whatsapp_channels.split(","):
                            channel = channel.strip()
                            if channel:
                                try:
                                    result = publisher.whatsapp_push(
                                        {"product_name": "Test Product"}, 
                                        channel, 
                                        test_message,
                                        is_channel=True
                                    )
                                    if result:
                                        success_count += 1
                                        st.success(f"✅ Test message sent to channel '{channel}'!")
                                    else:
                                        failure_count += 1
                                        st.error(f"❌ Failed to send test message to channel '{channel}'.")
                                except Exception as e:
                                    failure_count += 1
                                    st.error(f"❌ Error sending to channel '{channel}': {str(e)}")
                        
                        if success_count > 0 and failure_count == 0:
                            st.success(f"✅ All channel tests completed successfully!")
                        elif success_count > 0:
                            st.warning(f"⚠️ {success_count} successful, {failure_count} failed")
        
        with col2:
            if st.button("Test WhatsApp Groups", key="test_whatsapp_groups", disabled=not whatsapp_groups):
                if not whatsapp_groups:
                    st.error("Please enter at least one WhatsApp group name.")
                else:
                    from notification_publisher import NotificationPublisher
                    publisher = NotificationPublisher(self.config_manager)
                    test_message = "This is a test message from Affiliate Product Monitor (Group Test)."
                    success_count = 0
                    failure_count = 0
                    
                    with st.spinner("Sending test messages to groups..."):
                        for group in whatsapp_groups.split(","):
                            group = group.strip()
                            if group:
                                try:
                                    result = publisher.whatsapp_push(
                                        {"product_name": "Test Product"}, 
                                        group, 
                                        test_message,
                                        is_channel=False
                                    )
                                    if result:
                                        success_count += 1
                                        st.success(f"✅ Test message sent to group '{group}'!")
                                    else:
                                        failure_count += 1
                                        st.error(f"❌ Failed to send test message to group '{group}'.")
                                except Exception as e:
                                    failure_count += 1
                                    st.error(f"❌ Error sending to group '{group}': {str(e)}")
                        
                        if success_count > 0 and failure_count == 0:
                            st.success(f"✅ All group tests completed successfully!")
                        elif success_count > 0:
                            st.warning(f"⚠️ {success_count} successful, {failure_count} failed")

        # Add a section for managing WhatsApp data
        st.markdown("### Data Management")
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("Reset WhatsApp Login Data", type="primary", key="reset_whatsapp"):
                try:
                    from utils.whatsapp_sender import WhatsappSender
                    whatsapp = WhatsappSender()
                    if whatsapp.reset_profile():
                        st.success("✅ WhatsApp login data deleted successfully. You'll need to scan QR code again.")
                    else:
                        st.error("❌ Failed to reset WhatsApp data.")
                except Exception as e:
                    st.error(f"❌ Error: {str(e)}")

    def render(self):
        st.title("🛠️ Configuration")

        tab1, tab2, tab3, tab4, tab5 = st.tabs(["Amazon API", "Telegram", "WhatsApp", "Email", "Notification Schedule"])

        with tab1:
            st.header("Amazon API Configuration")

            amazon_config = self.config_manager.get_amazon_config()

            access_key = st.text_input("Access Key", value=amazon_config.get("access_key", ""), key="amazon_access_key")
            secret_key = st.text_input("Secret Key", value=amazon_config.get("secret_key", ""), type="password", key="amazon_secret_key")
            partner_tag = st.text_input("Partner Tag", value=amazon_config.get("partner_tag", ""), key="amazon_partner_tag")
            host = st.text_input("Host", value="webservices.amazon.in", key="amazon_host", disabled=True)  # Disabled input for host
            region = st.selectbox("Region", options=["us-east-1"], key="amazon_region", disabled=True)

            def savebtn():
                self.config_manager.update_config("Amazon", "access_key", access_key or "")
                self.config_manager.update_config("Amazon", "secret_key", secret_key or "")
                self.config_manager.update_config("Amazon", "partner_tag", partner_tag or "")
                self.config_manager.update_config("Amazon", "region", region or "")
                st.success("✅ Amazon API configuration saved successfully!")

            if st.button("Save Amazon API Configuration", key="save_amazon_config"):
                savebtn()

            if st.button("Test Amazon API"):
                try:
                    monitor = AmazonIndiaMonitor()
                    monitor.access_key = access_key
                    monitor.secret_key = secret_key
                    monitor.partner_tag = partner_tag
                    monitor.host = host  
                    monitor.region = "eu-west-1"  
                   
                    test_asins = ["B0DW48MM7C"] 

                    product_data = monitor.fetch_product_data(test_asins)

                    if product_data:
                        st.success("✅ Amazon API test successful!")
                        st.json(product_data)
                    else:
                        st.warning("⚠️ No data returned. Check your credentials or ASINs.")
                except Exception as e:
                    st.error(f"❌ Amazon API test failed: {e}")
                    import traceback
                    st.code(traceback.format_exc(), language="python")
                    

        with tab2:
            st.subheader("Telegram Notification Settings")
            bot_token = st.text_input("Telegram Bot Token", self.config.get("telegram_bot_token", ""), key="telegram_bot_token")
            
            # Replace the single chat_id field with a text area for multiple channels
            telegram_channels = st.text_area(
                "Telegram Channels (one per line)",
                value=self._get_telegram_channels_text(),
                help="Enter channel names/IDs (with @ symbol) one per line",
                key="telegram_channels"
            )

            if st.button("Save Telegram Configuration", key="save_telegram_config"):
                self.config["telegram_bot_token"] = bot_token
                
                # Parse channels and store as an array
                channels = [c.strip() for c in telegram_channels.split('\n') if c.strip()]
                self.config["telegram_channels"] = channels
                
                # Keep legacy field for backward compatibility
                if channels:
                    self.config["telegram_chat_id"] = channels[0]
                else:
                    self.config["telegram_chat_id"] = ""
                    
                self.save_config()
                st.success("✅ Telegram configuration saved successfully!")

            if st.button("Test Telegram Configuration", key="test_telegram_config"):
                if not bot_token or not telegram_channels.strip():
                    st.error("Please provide both the Telegram Bot Token and at least one channel.")
                else:
                    try:
                        config_manager = ConfigManager()
                        notification_publisher = NotificationPublisher(config_manager)
                        test_message = "This is a test message from Affiliate Product Monitor."
                        success, error_message = notification_publisher.test_telegram_config(bot_token, telegram_channels)
                        
                        if success:
                            st.success("✅ Test message sent successfully to all channels!")
                        else:
                            st.error(f"❌ Failed to send test message: {error_message}")
                    except Exception as e:
                        st.error(f"❌ An error occurred while sending the test message: {e}")

        with tab3:
            self.render_whatsapp_configuration()

        with tab4:
            st.subheader("Email Configuration")
            sender_email = st.text_input("Sender Email", self.config.get("email", {}).get("sender_email", ""), key="email_sender_email")
            smtp_server = st.text_input("SMTP Server", self.config.get("email", {}).get("smtp_server", "smtp.gmail.com"), key="email_smtp_server")
            smtp_port = st.number_input("SMTP Port", value=self.config.get("email", {}).get("smtp_port", 587), key="email_smtp_port")
            smtp_password = st.text_input("SMTP Password", type="password", value=self.config.get("email", {}).get("smtp_password", ""), key="email_smtp_password")
            recipients = st.text_area("Recipient Emails (comma-separated)", ", ".join(self.config.get("email", {}).get("recipients", [])), key="email_recipients")

            if st.button("Save Email Configuration", key="save_email_config"):
                self.config["email"] = {
                    "sender_email": sender_email,
                    "smtp_server": smtp_server,
                    "smtp_port": smtp_port,
                    "smtp_password": smtp_password,
                    "recipients": [email.strip() for email in recipients.split(",") if email.strip()]
                }
                self.save_config()
                st.success("✅ Email configuration saved successfully!")

            if st.button("Test Email Configuration", key="test_email_config"):
                try:
                    from utils.email_sender import EmailSender
                    email_sender = EmailSender()
                    email_sender.send_email(
                        subject="Test Email",
                        body="This is a test email from Affiliate Product Monitor.",
                        attachments=None
                    )
                    st.success("✅ Test email sent successfully!")
                except Exception as e:
                    st.error(f"❌ Failed to send test email: {e}")

        with tab5:
            st.subheader("📅 Notification Schedule")
            
            # Notification Types
            schedule_options = ["Daily", "Weekly", "Monthly", "On Price Change"]
            selected_schedules = st.multiselect(
                "Select Notification Types", 
                options=schedule_options,
                default=self.config.get("notification_schedule", ["On Price Change"])
            )

            # Time Settings for each type
            if "Daily" in selected_schedules:
                st.markdown("### ⏰ Daily Notification Time")
                daily_time = st.time_input(
                    "Select daily notification time",
                    value=datetime.strptime(
                        self.config.get("daily_notification_time", "09:00"), 
                        "%H:%M"
                    ).time()
                )
                self.config["daily_notification_time"] = daily_time.strftime("%H:%M")

            if "Weekly" in selected_schedules:
                st.markdown("### 📅 Weekly Notification Settings")
                week_days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
                weekly_day = st.selectbox(
                    "Select day of the week",
                    options=week_days,
                    index=week_days.index(self.config.get("weekly_notification_day", "Monday"))
                )
                weekly_time = st.time_input(
                    "Select weekly notification time",
                    value=datetime.strptime(
                        self.config.get("weekly_notification_time", "09:00"), 
                        "%H:%M"
                    ).time()
                )
                self.config["weekly_notification_day"] = weekly_day
                self.config["weekly_notification_time"] = weekly_time.strftime("%H:%M")

            if "Monthly" in selected_schedules:
                st.markdown("### 📅 Monthly Notification Settings")
                monthly_day = st.number_input(
                    "Select day of the month",
                    min_value=1,
                    max_value=28,
                    value=int(self.config.get("monthly_notification_day", 1))
                )
                monthly_time = st.time_input(
                    "Select monthly notification time",
                    value=datetime.strptime(
                        self.config.get("monthly_notification_time", "09:00"), 
                        "%H:%M"
                    ).time()
                )
                self.config["monthly_notification_day"] = monthly_day
                self.config["monthly_notification_time"] = monthly_time.strftime("%H:%M")

            if "On Price Change" in selected_schedules:
                st.markdown("### 💰 Price Change Settings")
                price_change_threshold = st.number_input(
                    "Minimum price change percentage to trigger notification",
                    min_value=1,
                    max_value=100,
                    value=int(self.config.get("price_change_threshold", 5)),
                    help="Notifications will be sent when price changes by this percentage or more"
                )
                self.config["price_change_threshold"] = price_change_threshold

            self.config["notification_schedule"] = selected_schedules

            if st.button("💾 Save Notification Settings"):
                self.save_config()
                st.success("✅ Notification schedule saved successfully!")
                st.info("Please restart the application for changes to take effect.")

            # Display current schedule
            with st.expander("View Current Schedule"):
                st.json(
                    {k: v for k, v in self.config.items() if "notification" in k.lower()}
                )

    def _get_telegram_channels_text(self):
        """Convert stored telegram channels to text format for the UI"""
        channels = []
        
        # Try to get channels from array format first
        if "telegram_channels" in self.config and isinstance(self.config["telegram_channels"], list):
            # Filter out any non-string items (like nested objects)
            channels = [ch for ch in self.config["telegram_channels"] if isinstance(ch, str)]
        
        # Fall back to single channel if array not found or empty
        if not channels and "telegram_chat_id" in self.config and self.config["telegram_chat_id"]:
            channels = [self.config["telegram_chat_id"]]
        
        return "\n".join(channels)

    def save_telegram_config(self):
        """Save telegram configuration correctly"""
        bot_token = st.session_state.get("telegram_bot_token", "")
        telegram_channels_text = st.session_state.get("telegram_channels", "")
        
        # Parse channels and store as an array
        channels = []
        for line in telegram_channels_text.split('\n'):
            for channel in line.split(','):
                channel = channel.strip()
                if channel:
                    # Ensure channels have @ prefix
                    if not channel.startswith("@") and not channel.lstrip('-').isdigit():
                        channel = f"@{channel}"
                    channels.append(channel)
        
        self.config["telegram_bot_token"] = bot_token
        self.config["telegram_channels"] = channels
        
        # Keep legacy field for backward compatibility
        if channels:
            self.config["telegram_chat_id"] = channels[0]
        else:
            self.config["telegram_chat_id"] = ""
            
        self.save_config()
        return True


