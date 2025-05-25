import schedule
import threading
import time
from datetime import datetime, timedelta
from utils.email_sender import EmailSender


class Scheduler:
    def __init__(self, products_collection, published_collection, notification_publisher, hands_off_controller, config_manager):
        self.products_collection = products_collection
        self.published_collection = published_collection
        self.notification_publisher = notification_publisher
        self.hands_off_controller = hands_off_controller
        self.config_manager = config_manager
        self.jobs = []
        self.is_running = False  

    def start(self):
        """
        Start the scheduling in a background thread.
        """
        schedule.every(6).hours.do(self.hands_off_job)
        schedule.every().day.at("06:00").do(self.daily_report_job)
        schedule.every().sunday.at("06:00").do(self.weekly_report_job)
        schedule.every(1).month.at("06:00").do(self.monthly_report_job)

        thread = threading.Thread(target=self.run_schedule_loop, daemon=True)
        thread.start()

    def run_schedule_loop(self):
        """Continuously run scheduled tasks."""
        print("Starting scheduler loop...")
        while True:
            try:
                schedule.run_pending()
                time.sleep(30)
            except Exception as e:
                print(f"⚠️ Scheduler encountered an error: {e}")

    def hands_off_job(self):
        print(f"[{datetime.now()}] Running hands-off job...")
        self.hands_off_controller.run_hands_off()

    def daily_report_job(self):
        print(f"[{datetime.now()}] Sending daily email report...")
        self.notification_publisher.send_daily_report()

    def weekly_report_job(self):
        print(f"[{datetime.now()}] Sending weekly email report...")
        self.notification_publisher.send_weekly_report()

    def monthly_report_job(self):
        print(f"[{datetime.now()}] Sending monthly email report...")
        self.notification_publisher.send_monthly_report()

    def automatic_publisher_job(self):
        print(f"[{datetime.now()}] Running automatic publisher job...")
        products = self.products_collection.find({})  
        for product in products:
            message = (
                f"🛍️ *{product['product_name']}*\n"
                f"💰 *Current Price:* ₹{product['Product_current_price']}\n"
                f"💸 *MRP:* ₹{product['Product_Buy_box_price']}\n"
                f"🔗 [Buy Now]({product['product_Affiliate_url']})"
            )
            success, error_message = self.notification_publisher.telegram_push(message)
            if success:
                print(f"✅ Published: {product['product_name']}")
            else:
                print(f"❌ Failed to publish {product['product_name']}: {error_message}")

    def add_job(self, func, trigger, **kwargs):
        """Add a job to the scheduler.
        
        Args:
            func: The function to run
            trigger: The type of trigger ("interval", "cron")
            **kwargs: Additional arguments for the job
        """
        job = {
            "func": func,
            "trigger": trigger,
            "kwargs": kwargs
        }
        self.jobs.append(job)
        print(f"Added job: {kwargs.get('name', func.__name__)}")

    def run(self):
        """Start the scheduler and run jobs according to their schedule."""
        if self.is_running:
            print("⚠️ Scheduler is already running.")
            return
        self.is_running = True
        print("Scheduler is running...")
        

        for job in self.jobs:
            if job["trigger"] == "interval":
                hours = job["kwargs"].get("hours", 1)
                schedule.every(hours).hours.do(job["func"])
                print(f"Scheduled {job['kwargs'].get('name', job['func'].__name__)} to run every {hours} hours")
            elif job["trigger"] == "cron":
                hour = job["kwargs"].get("hour")
                day_of_week = job["kwargs"].get("day_of_week")
                day = job["kwargs"].get("day")
                
                if day_of_week:
                    if hour is not None:
                        schedule.every().day.at(f"{hour:02d}:00").do(job["func"])
                        print(f"Scheduled {job['kwargs'].get('name', job['func'].__name__)} to run at {hour:02d}:00 on {day_of_week}")
                elif day:
                    if hour is not None:
                        print(f"Scheduled {job['kwargs'].get('name', job['func'].__name__)} to run at {hour:02d}:00 on day {day} of month")
                else:
                    if hour is not None:
                        schedule.every().day.at(f"{hour:02d}:00").do(job["func"])
                        print(f"Scheduled {job['kwargs'].get('name', job['func'].__name__)} to run daily at {hour:02d}:00")

        self.run_schedule_loop()

    def schedule_product_checks(self):
        """Configure scheduled product monitoring"""
        # Daily price check schedule
        self.add_job(
            func=self.price_monitor.monitor_products,
            trigger="cron", 
            hour="*/6",  # Every 6 hours
            name="Regular Price Check"
        )
        
        # Immediate price check for specific criteria
        self.add_job(
            func=self.check_priority_products,
            trigger="interval",
            minutes=30,  # Every 30 mins
            name="Priority Product Check"  
        )