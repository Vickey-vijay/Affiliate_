from datetime import datetime
from notification.email_notifier import EmailNotifier
from notification.telegram_notifier import TelegramNotifier
from notification.whatsapp_notifier import WhatsAppNotifier
import json
import os
import time
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import telegram
import requests  # For fallback method
import asyncio  # For handling async operations

class NotificationManager:
    def __init__(self):
        self.config = self.load_config()
        
        self.email_notifier = None
        self.telegram_notifier = None
        self.whatsapp_notifier = None
        
        if self.config.get("smtp_user") and self.config.get("smtp_pass"):
            self.email_notifier = EmailNotifier(
                self.config["smtp_user"], 
                self.config["smtp_pass"]
            )
            
        if self.config.get("telegram_bot_token") and self.config.get("telegram_chat_id"):
            self.telegram_notifier = TelegramNotifier(
                self.config["telegram_bot_token"], 
                self.config["telegram_chat_id"]
            )
            
        if self.config.get("whatsapp_api_key"):
            self.whatsapp_notifier = WhatsAppNotifier(
                self.config["whatsapp_api_key"]
            )
    
    def load_config(self):
        try:
            with open("secrets.json", 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
    
    def send_whatsapp_channel_message(self, channel_name, message):
        """
        Send a message to a WhatsApp channel using Edge browser with persistent session.
        """
        app_data = os.path.join(os.environ['APPDATA'], 'WhatsAppAutomation')
        os.makedirs(app_data, exist_ok=True)
        
        edge_options = Options()
        edge_options.add_argument(f"--user-data-dir={app_data}")
        edge_options.add_argument("--profile-directory=Default")
        edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])  
        edge_options.add_experimental_option("useAutomationExtension", False)
        
        driver = webdriver.Edge(options=edge_options)
        success = False
        try:
            driver.get("https://web.whatsapp.com/")
            print("Loading WhatsApp Web...")
            
            qr_code_selector = "//div[@data-ref]"
            side_panel_selector = "//div[@id='side']"
            # newsletter_tab_selector = "//span[@data-icon='newsletter-tab']"
            newsletter_tab_selector = "//span[@data-icon='newsletter-outline']"
            
            wait = WebDriverWait(driver, 30)
            driver.maximize_window()
            # time.sleep(50)  
            try:
                side_panel = wait.until(EC.presence_of_element_located((By.XPATH, side_panel_selector)))
                print("Already logged in!")
            except:
                qr_code = wait.until(EC.presence_of_element_located((By.XPATH, qr_code_selector)))
                print("Please scan the QR code with your phone to log in...")
                side_panel = WebDriverWait(driver, 90).until(
                    EC.presence_of_element_located((By.XPATH, side_panel_selector))
                )
                print("Login successful!")
            
            # Click the newsletter tab after successful login
            try:
                # time.sleep(5)
                newsletter_tab = wait.until(EC.element_to_be_clickable((By.XPATH, newsletter_tab_selector)))
                newsletter_tab.click()
                print("Clicked on the newsletter tab.")
            except Exception as e:
                print(f"Failed to click on the newsletter tab: {e}")
                return False
            
            time.sleep(3)
            search_box = wait.until(EC.presence_of_element_located(
                (By.XPATH, '//div[@contenteditable="true"][@aria-label="Search input textbox"][@data-tab="3"]')
            ))
            search_box.clear()
            search_box.send_keys(channel_name)
            print(f"Searching for channel: {channel_name}")
            time.sleep(2)
            
            channel_title = wait.until(EC.element_to_be_clickable(
                (By.XPATH, f'//span[@title="{channel_name}"]')
            ))
            channel_title.click()
            print(f"Channel '{channel_name}' found and selected")
            
            message_box = wait.until(EC.presence_of_element_located(
                (By.XPATH, '//div[@contenteditable="true"][@data-tab="10"]')
            ))
            message_box.clear()
            message_box.send_keys(message)
            message_box.send_keys(Keys.ENTER)
            
            print(f"Message sent to '{channel_name}' successfully!")
            time.sleep(2)
            success = True
            
        except Exception as e:
            print(f"Error occurred: {e}")
            success = False
            
        
    
    def notify_price_change(self, product, old_price, new_price):
        """Send notification for price change"""
        message = f"🔔 Price Change Alert!\n\n"
        message += f"Product: {product.get('product_name', 'Unknown')}\n"
        message += f"ASIN: {product.get('Product_unique_ID', 'Unknown')}\n"
        message += f"Old Price: ₹{old_price}\n"
        message += f"New Price: ₹{new_price}\n"
        message += f"Discount: {round((1 - new_price/old_price) * 100, 2)}%\n"
        
        if self.telegram_notifier and "On Price Change" in self.config.get("notification_schedule", []):
            self.telegram_notifier.send_message(message)
            
        if self.whatsapp_notifier and "On Price Change" in self.config.get("notification_schedule", []):
            recipient = self.config.get("whatsapp_group_id")
            if recipient:
                self.send_whatsapp_channel_message(recipient, message)
                
        if self.email_notifier and "On Price Change" in self.config.get("notification_schedule", []):
            recipient = self.config.get("notification_email")
            if recipient:
                self.email_notifier.send_email(
                    recipient,
                    "Price Change Alert",
                    message
                )
    
    def publish_product(self, product):
        """Publish product to configured channels"""
        message = f"🛍️ Deal Alert!\n\n"
        message += f"Product: {product.get('product_name', 'Unknown')}\n"
        message += f"Price: ₹{product.get('Product_current_price', 'Unknown')}\n"
        message += f"Category: {product.get('product_major_category', 'Unknown')}\n"
        message += f"Link: https://www.amazon.in/dp/{product.get('Product_unique_ID', '')}\n"
        
        if self.telegram_notifier:
            self.telegram_notifier.send_message(message)
            
        if self.whatsapp_notifier:
            recipient = self.config.get("whatsapp_group_id")
            if recipient:
                self.send_whatsapp_channel_message(recipient, message)
                
        return True
    
    def send_telegram_notification(self, message, image_path=None):
        """Send notification to Telegram channel(s)"""
        try:
            # Get Telegram configuration
            config = self.load_config()
            bot_token = config.get("telegram_bot_token")
            
            # Process channels in multiple formats
            channels = []
            
            # First check for array of channels (new format)
            if "telegram_channels" in config and isinstance(config["telegram_channels"], list):
                channels = config["telegram_channels"]
            # Then check for legacy single channel
            elif "telegram_chat_id" in config:
                channels = [config["telegram_chat_id"]]
            
            # Clean up channel list
            channels = [ch.strip() for ch in channels if ch.strip()]
            
            if not bot_token:
                return False, "Telegram bot token not configured"
            
            if not channels:
                return False, "No Telegram channels configured"
                
            # Initialize Telegram bot (handle both sync and async APIs)
            success = False
            errors = []
            
            # Handle each channel with REST API approach (more reliable than bot library)
            for channel in channels:
                try:
                    # Ensure channel format is correct
                    if channel and not channel.startswith("@") and not channel.lstrip('-').isdigit():
                        channel = f"@{channel}"
                    
                    api_url = f"https://api.telegram.org/bot{bot_token}/"
                    
                    # Send message based on whether we have an image or not
                    if image_path and os.path.exists(image_path):
                        # Send with image
                        with open(image_path, 'rb') as photo:
                            response = requests.post(
                                api_url + "sendPhoto",
                                files={'photo': photo},
                                data={
                                    'chat_id': channel,
                                    'caption': message,
                                    'parse_mode': 'HTML'
                                }
                            )
                    else:
                        # Text-only message
                        response = requests.post(
                            api_url + "sendMessage",
                            json={
                                'chat_id': channel,
                                'text': message,
                                'parse_mode': 'HTML',
                                'disable_web_page_preview': False
                            }
                        )
                    
                    if response.status_code == 200:
                        success = True
                    else:
                        error_data = response.json()
                        errors.append(f"{channel}: {error_data.get('description', 'Unknown error')}")
                        
                except Exception as e:
                    errors.append(f"{channel}: {str(e)}")
            
            if success:
                if errors:
                    return True, f"Sent to some channels. Errors: {'; '.join(errors)}"
                return True, "Message sent successfully to all channels"
            else:
                return False, '; '.join(errors)
                
        except Exception as e:
            return False, f"Error sending Telegram notification: {str(e)}"



