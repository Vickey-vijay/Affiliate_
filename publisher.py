import os
import json
import requests
import datetime
from pymongo import MongoClient
import pandas as pd
from utils.email_sender import EmailSender 
from utils.whatsapp_sender import WhatsappSender  
# import pywhatkit as kit
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
            # First, check if product_data is a string (already formatted message)
            if isinstance(product_data, str):
                message = product_data
            else:
                # If not, check if it's a product dictionary
                if 'product_name' in product_data:
                    # Format for database product structure
                    message = (
                        f"🛍️ *{product_data.get('product_name', 'Unknown Product')}*\n\n"
                        f"💰 *Deal Price:* ₹{product_data.get('Product_current_price', 'N/A')} ✅\n"
                        f"💸 *MRP:* ₹{product_data.get('Product_MRP', product_data.get('Product_Buy_box_price', 'N/A'))} ❌\n\n"
                        f"🔗 [Buy Now]({product_data.get('product_Affiliate_url', '#')})"
                    )
                elif 'title' in product_data:
                    # Format for direct scraper result structure
                    message = (
                        f"🛍️ *{product_data.get('title', 'Unknown Product')}*\n\n"
                        f"💰 *Deal Price:* ₹{product_data.get('current_price', 'N/A')} ✅\n"
                        f"💸 *MRP:* ₹{product_data.get('mrp', product_data.get('current_price', 0) * 1.2 if product_data.get('current_price') else 'N/A')} ❌\n\n"
                        f"🔗 [Buy Now]({product_data.get('buy_now_url', '#')})"
                    )
                else:
                    raise ValueError("Unknown product data format")

            # Check if Telegram configuration exists in the flat structure
            bot_token = self.config.get("telegram_bot_token")
            chat_id = self.config.get("telegram_chat_id")
            
            # If not found in flat structure, try nested structure
            if not bot_token or not chat_id:
                if "telegram" in self.config:
                    telegram_config = self.config["telegram"]
                    bot_token = telegram_config.get("bot_token")
                    chat_id = telegram_config.get("chat_id")

            # If still not found, raise exception
            if not bot_token or not chat_id:
                print("Telegram configuration is missing in config.json. Please add telegram_bot_token and telegram_chat_id.")
                
                # Create a sample config structure to show in logs
                sample_config = {
                    "telegram_bot_token": "YOUR_BOT_TOKEN_HERE",
                    "telegram_chat_id": "YOUR_CHAT_ID_HERE"
                }
                print(f"Sample config: {json.dumps(sample_config, indent=2)}")
                raise Exception("Telegram configuration is missing")
                
            print(f"[DEBUG] Sending to Telegram with bot_token: {bot_token[:5]}... and chat_id: {chat_id}")
            print(f"[DEBUG] Message: {message[:100]}...")

            response = requests.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                data={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
            )

            print(f"[DEBUG] Telegram API response: {response.status_code} - {response.text[:200]}")

            if response.status_code != 200:
                raise Exception(f"Telegram API error: {response.text}")
            print("✅ Telegram message sent successfully")
            return True
        except Exception as e:
            print(f"❌ Telegram push failed: {e}")
            import traceback
            traceback.print_exc()
            return False

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

    def fetch_amazon_product(self, product_url):
        """
        Fetch product information from Amazon including MRP price
        
        Args:
            product_url: Amazon product URL
            
        Returns:
            dict: Product information including title, current_price, mrp, url
        """
        try:
            # Use headers to avoid being blocked
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(product_url, headers=headers)
            response.raise_for_status()
            
            # Here you would typically use a library like BeautifulSoup or a scraping service to parse the page
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Extract product details
            product_title = soup.select_one('#productTitle')
            if product_title is None:
                raise Exception("Could not find product title element")
            product_title = product_title.get_text().strip()

            # Extract current price
            current_price_element = soup.select_one('.a-price .a-offscreen')
            current_price = float(current_price_element.get_text().replace('₹', '').replace(',', '').strip()) if current_price_element else None

            # Extract MRP price - try multiple possible selectors with better pattern matching
            mrp = None

            # Check for multiple possible MRP patterns
            mrp_patterns = [
                # Standard MRP pattern
                '.a-price.a-text-price .a-offscreen',
                # Alternative location
                '#corePriceDisplay_desktop_feature_div .a-text-price .a-offscreen',
                # List price pattern
                '.a-price.a-text-price[data-a-strike="true"] .a-offscreen',
                # Another common pattern
                'span.a-price.a-text-price[data-a-strike="true"] span.a-offscreen'
            ]

            for pattern in mrp_patterns:
                mrp_element = soup.select_one(pattern)
                if mrp_element:
                    price_text = mrp_element.get_text().strip()
                    try:
                        mrp = float(price_text.replace('₹', '').replace(',', '').strip())
                        break
                    except ValueError:
                        continue

            # If still not found, try finding MRP in text content
            if mrp is None:
                import re
                # Look for text containing M.R.P.
                for element in soup.find_all(['span', 'div', 'p']):
                    text = element.get_text().strip()
                    if "M.R.P.:" in text or "MRP:" in text or "M.R.P" in text:
                        price_match = re.search(r'₹\s*(\d+(?:,\d+)*(?:\.\d+)?)', text)
                        if price_match:
                            try:
                                mrp = float(price_match.group(1).replace(',', ''))
                                break
                            except ValueError:
                                continue

            # Special case for "with X percent savings" pattern
            if mrp is None and current_price:
                for element in soup.find_all(['span', 'div']):
                    text = element.get_text().strip()
                    savings_match = re.search(r'with\s+(\d+)\s*percent\s+savings', text, re.IGNORECASE)
                    if savings_match:
                        try:
                            savings_percent = int(savings_match.group(1))
                            if savings_percent > 0 and savings_percent < 100:
                                mrp = round(current_price * 100 / (100 - savings_percent), 2)
                                break
                        except (ValueError, ZeroDivisionError):
                            continue

            # If MRP is still not found, fall back to other methods
            if mrp is None:
                # Last resort: Look for any text with "₹" that's higher than the current price
                for element in soup.find_all(['span', 'div']):
                    text = element.get_text().strip()
                    price_match = re.search(r'₹\s*(\d+(?:,\d+)*(?:\.\d+)?)', text)
                    if price_match:
                        try:
                            possible_mrp = float(price_match.group(1).replace(',', ''))
                            # Fix for line 225
                            if current_price is not None and possible_mrp > current_price * 1.05:  # At least 5% higher
                                mrp = possible_mrp
                                break
                        except ValueError:
                            continue

            # Final fallback
            # Fix for line 233
            if mrp is None or (current_price is not None and mrp <= current_price):
                if current_price is not None:
                    mrp = round(current_price * 1.2, 2)  # Fallback: assume 20% higher than current price
                else:
                    mrp = None  # If we don't have a current price, we can't calculate an MRP

            product_data = {
                'title': product_title,
                'current_price': current_price,
                'mrp': mrp,  # Added MRP price
                'url': product_url,
                'buy_now_url': product_url,  # You might want to add affiliate tags here
                'fetched_at': datetime.datetime.now()
            }
            
            return product_data
        
        except Exception as e:
            print(f"Error fetching Amazon product: {e}")
            return None
