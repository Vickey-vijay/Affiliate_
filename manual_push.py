import streamlit as st
from notification_publisher import NotificationPublisher
from config_manager import ConfigManager

def manual_push_page():
    st.header("📢 Manual Push")
    message = st.text_area("Enter your message")
    channels = st.multiselect("Select channels", ["Telegram"])

    if st.button("Send"):
        config_manager = ConfigManager()
        notification_publisher = NotificationPublisher(config_manager)

        if "Telegram" in channels:
            success, error_message = notification_publisher.telegram_push(message)
            if success:
                st.success("✅ Message sent successfully!")
            else:
                st.error(f"❌ Failed to send message: {error_message}")