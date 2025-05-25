import os
import json
import requests
import datetime
from pymongo import MongoClient
import pandas as pd
from utils.email_sender import EmailSender 
from utils.whatsapp_sender import WhatsappSender  
import pywhatkit as kit
from notification.notification_manager import NotificationManager

class Publisher:
    def __init__(self, mongo_uri="mongodb://localhost:27017/", db_name="your_database_name", notification_publisher = None):
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        self.products_collection = self.db["products"]
        self.published_collection = self.db["published_products"]
        self.config = self.load_config()
        self.whatsapp = WhatsappSender()
        self.email_sender = EmailSender()
        self.products_collection = self.db["products"]
        self.notification_publisher = notification_publisher
        self.config = self.load_config()

    def load_config(self):
        try:
            with open("config.json", "r") as f:
                return json.load(f)
        except Exception as e:
            print("Failed to load config:", e)
            return {}

    def telegram_push(self, product_data):
        try:
            bot_token = self.config["telegram"]["bot_token"]
            chat_id = self.config["telegram"]["chat_id"]

            message = (
                f"🔥 *{product_data['title']}*\n"
                f"💰 *Current Price:* ₹{product_data['current_price']}\n"
                f"💸 *MRP:* ₹{product_data['mrp']}\n"
                f"🛒 [Buy Now]({product_data['buy_now_url']})"
            )

            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                data={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
            )

            if response.status_code != 200:
                raise Exception(f"Telegram API error: {response.text}")
        except Exception as e:
            print(f"❌ Telegram push failed: {e}")

    def whatsapp_push(self, product_data):
        """
        Send a WhatsApp message using NotificationManager.
        """
        try:
            message = (
                f"*{product_data['title']}*\n"
                f"💰 *Current Price:* ₹{product_data['current_price']}\n"
                f"💸 *MRP:* ₹{product_data['mrp']}\n"
                f"🔗 {product_data['buy_now_url']}"
            )
            notification_manager = NotificationManager()
            group_name = "Your WhatsApp Group Name"  # Replace with your group name
            notification_manager.send_whatsapp_channel_message(group_name, message)
        except Exception as e:
            print(f"❌ WhatsApp push failed: {e}")

    def generate_report(self, period="daily"):
        """
        period can be 'daily', 'weekly', 'monthly'
        """
        now = datetime.datetime.now()
        if period == "daily":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "weekly":
            start = now - datetime.timedelta(days=now.weekday())
            start = start.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "monthly":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            raise ValueError("Invalid period")

        end = now
        query = {"published_at": {"$gte": start, "$lte": end}}
        published_products = list(self.published_collection.find(query))

        if not published_products:
            print(f"📭 No {period} products found.")
            return None

        df = pd.DataFrame(published_products)
        filename = f"{period}_report_{now.strftime('%Y%m%d_%H%M%S')}.csv"
        df.to_csv(filename, index=False)
        return filename

    def send_scheduled_report(self):
        try:
            for period in ["daily", "weekly", "monthly"]:
                file_path = self.generate_report(period)
                if file_path:
                    self.email_sender.send_email(
                        subject=f"{period.capitalize()} Product Report",
                        body="Please find the attached report.",
                        attachments=[file_path]
                    )
                    os.remove(file_path)
        except Exception as e:
            print("❌ Report email sending failed:", e)
