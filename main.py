import streamlit as st
from ui.dashboard_page import DashboardPage
from ui.product_page import ProductPage
from ui.config_page import ConfigPage
from ui.login_page import show_login
from ui.monitor_page import ProductMonitorPage
from ui.publish_page import PublishPage  
from scheduler import Scheduler
from config_manager import ConfigManager
from notification_publisher import NotificationPublisher
from publisher import Publisher
from handsoff_mode_controller import HandsOffModeController
from price_monitor import PriceMonitor
import pymongo
import os


os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"  

if "mongo_client" not in st.session_state:
    st.session_state["mongo_client"] = pymongo.MongoClient("mongodb://localhost:27017/")

def main():

    if not st.session_state.get("logged_in", False):
        show_login()
        return
    
    if st.sidebar.button("🚪 Logout"):
        st.session_state["logged_in"] = False
        st.session_state["username"] = None
        show_login()
        st.rerun()

    config_page = ConfigPage()
    config = config_page.load_config()

    config_manager = ConfigManager()
    notification_publisher = NotificationPublisher(config_manager)


    with st.sidebar:
        st.markdown("### Navigation")
        page = st.radio(
        "Select Page",
        options=["Dashboard", "Products", "Configuration", "Product Monitor", "Publish"],
        index=0
        )


    client = st.session_state["mongo_client"]
    db = client["ramesh"]
    products_collection = db["products"]
    published_collection = client["ramesh"]["published_products"]


    publisher = Publisher(
        mongo_uri="mongodb://localhost:27017/",
        db_name="ramesh",
        notification_publisher=notification_publisher
    )
    hands_off_controller = HandsOffModeController(
        products_collection=products_collection,
        published_collection=published_collection,
        notification_publisher=notification_publisher
    )
    price_monitor = PriceMonitor(
        products_collection=products_collection,
        amazon_config=config_manager.get_amazon_config()
    )
    scheduler = Scheduler(
        products_collection=products_collection,
        published_collection=published_collection,
        notification_publisher=notification_publisher,
        hands_off_controller=hands_off_controller,
        config_manager=config_manager
    )


    if page == "Dashboard":
        DashboardPage().render()
    elif page == "Products":
        ProductPage(config).render()
    elif page == "Configuration":
        ConfigPage().render()
    elif page == "Product Monitor":
        ProductMonitorPage().render()
    elif page == "Publish":
        PublishPage(config_manager).render()

if __name__ == "__main__":
    main()