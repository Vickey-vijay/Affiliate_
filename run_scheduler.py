# run_scheduler.py

import pymongo
from config_manager import ConfigManager
from notification_publisher import NotificationPublisher
from publisher import Publisher
from handsoff_mode_controller import HandsOffModeController
from price_monitor import PriceMonitor
from scheduler import Scheduler
import schedule
import time
from threading import Thread
from ui.product_page import ProductPage
from db.db_manager import DataManager

def main():
    client = pymongo.MongoClient("mongodb://localhost:27017/")
    db = client["ramesh"]
    products_collection = db["products"]
    published_collection = client["published_data"]["products"]

    config_manager = ConfigManager()
    config = config_manager.get_config()
    scraping_freq = config.get("scraping_frequency_in_hours", 6)

    notification_publisher = NotificationPublisher(config_manager)
    publisher = Publisher(db, published_collection, notification_publisher)
    hands_off_controller = HandsOffModeController(products_collection, published_collection, notification_publisher)
    price_monitor = PriceMonitor(products_collection, amazon_config=config_manager.get_amazon_config())

    scheduler = Scheduler(
        products_collection,
        published_collection,
        notification_publisher,
        hands_off_controller,
        config_manager
    )

    scheduler.add_job(
        func=price_monitor.monitor_products,
        trigger="interval",
        hours=scraping_freq,
        name="Price Monitor"
    )

    scheduler.add_job(
        func=hands_off_controller.process_and_publish,
        trigger="interval",
        hours=scraping_freq,
        name="Hands-Off Publisher"
    )

    scheduler.add_job(
        func=publisher.send_scheduled_report,
        trigger="cron",
        hour=6,
        name="Daily Report"
    )

    scheduler.add_job(
        func=lambda: publisher.send_scheduled_report(period="weekly"),
        trigger="cron",
        day_of_week="sun",
        hour=6,
        name="Weekly Report"
    )

    scheduler.add_job(
        func=lambda: publisher.send_scheduled_report(period="monthly"),
        trigger="cron",
        day=1,
        hour=6,
        name="Monthly Report"
    )

    print("✅ Scheduler is running with all tasks set up...")
    scheduler.run()

    # Initialize additional dependencies
    db_manager = DataManager()
    notification_publisher = NotificationPublisher(config_manager)
    product_page = ProductPage(notification_publisher)

    # Define the scheduled job with mutex
    publishing_in_progress = False

    def scheduled_publishing_job():
        nonlocal publishing_in_progress
        if publishing_in_progress:
            print("[Scheduler] Previous job still running, skipping...")
            return
            
        try:
            publishing_in_progress = True
            print("[Scheduler] Running scheduled publishing job...")
            product_page.process_scheduled_publishing()
        finally:
            publishing_in_progress = False

    # Schedule the job to run every hour
    schedule.every(1).hours.do(scheduled_publishing_job)

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

# Run the scheduler in a separate thread
if __name__ == "__main__":
    main()
    scheduler_thread = Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()
    print("✅ Scheduler is running...")
