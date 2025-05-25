import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json
import os
from notification.notification_manager import NotificationManager
from utils.whatsapp_sender import WhatsappSender
import shutil
import tempfile
from email.mime.application import MIMEApplication


class NotificationPublisher:
    """
    Handles notifications for publishing products by sending messages via Telegram, WhatsApp,
    and sending email reports.
    """
    def __init__(self, config_manager):
        self.config_manager = config_manager
        self._whatsapp_sender = None  # Lazy initialization
        self.driver = None
        self.email_config = self.load_email_config()  
        self.telegram_config = self.load_telegram_config()
        
        # Initialize config from telegram config for backward compatibility
        self.config = self.telegram_config
        
        self._temp_dir = os.path.join(tempfile.gettempdir(), f'whatsapp_{os.getpid()}')
        os.makedirs(self._temp_dir, exist_ok=True)
        self.lock_file = os.path.join(self._temp_dir, "whatsapp_sender.lock")

    @property
    def whatsapp_sender(self):
        """Lazy initialize WhatsApp sender."""
        if self._whatsapp_sender is None:
            self._whatsapp_sender = WhatsappSender()
        return self._whatsapp_sender

    def load_email_config(self):
        """
        Load email configuration from the latest config.json file.
        """
        try:
            with open("config.json", "r") as f:
                config = json.load(f)
                return config.get("email", {})
        except Exception as e:
            print(f"[Email] Failed to load email configuration: {e}")
            return {}

    def __del__(self):
        """Ensure cleanup when object is destroyed"""
        self.close()

    def get_recipients(self):
        """
        Retrieve recipients from the email configuration.
        """
        recipients = self.email_config.get("recipients", [])
        if not recipients:
            print("❌ No recipients configured. Please configure them in config.json.")
        return recipients

    def load_telegram_config(self):
        """
        Dynamically load the Telegram configuration from the latest secrets.json file.
        """
        try:
            with open("config.json", "r") as f:
                config = json.load(f)
                return {
                    "bot_token": config.get("telegram_bot_token"),
                    "channel_name": config.get("telegram_channel_name", "")
                }
        except Exception as e:
            print(f"[Telegram] Failed to load configuration: {e}")
            return {"bot_token": None, "channel_name": None}

    def telegram_push(self, message, image_path=None):
        """Send notification to Telegram channel"""
        try:
            if not self.telegram_config:
                return False, "No configuration available"
            
            # Extract Telegram configuration - use correct field names based on your config structure
            bot_token = self.telegram_config.get("bot_token", "")
            chat_id = self.telegram_config.get("channel_name", "")
            
            if not bot_token or not chat_id:
                return False, "Telegram configuration is missing"
            
            # Send the message
            if image_path and os.path.exists(image_path):
                # Send with image
                with open(image_path, 'rb') as image:
                    files = {'photo': image}
                    response = requests.post(
                        f"https://api.telegram.org/bot{bot_token}/sendPhoto",
                        data={"chat_id": chat_id, "caption": message, "parse_mode": "HTML"},
                        files=files
                    )
            else:
                # Send text only
                response = requests.post(
                    f"https://api.telegram.org/bot{bot_token}/sendMessage",
                    data={"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
                )
            
            if response.status_code != 200:
                return False, f"Error {response.status_code}: {response.text}"
            
            return True, "Message sent successfully"
        except Exception as e:
            return False, str(e)

    def test_telegram_config(self, bot_token: str, channel_names: str):
        """
        Tests the Telegram bot token and channel names by sending a test message.
        :param bot_token: The Telegram bot token.
        :param channel_names: Comma-separated Telegram channel names.
        :return: Tuple (success: bool, error_message: str or None)
        """
        errors = []
        for channel_name in channel_names.split(","):
            channel_name = channel_name.strip()
            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            payload = {"chat_id": channel_name, "text": "Test message from Affiliate Product Monitor"}

            try:
                response = requests.post(url, data=payload)
                if response.status_code == 200:
                    print(f"[Telegram] Test message sent successfully to {channel_name}.")
                else:
                    error_message = response.json().get("description", "Unknown error")
                    print(f"[Telegram] Test failed for {channel_name}: {error_message}")
                    errors.append(f"{channel_name}: {error_message}")
            except Exception as e:
                print(f"[Telegram] Exception occurred during test for {channel_name}: {e}")
                errors.append(f"{channel_name}: {str(e)}")

        if errors:
            return False, "; ".join(errors)
        return True, None

    def whatsapp_push(self, product, recipient_name, message=None, is_channel=False):
        """
        Send a WhatsApp message with product details and image.
        
        Args:
            product (dict): Product information dictionary
            recipient_name (str): WhatsApp group or channel name to send to
            message (str, optional): Custom message (if None, builds from product)
            is_channel (bool): Whether recipient is a channel (True) or group (False)
            
        Returns:
            bool: Success status
        """
        try:
            # Create the message if not provided
            if not message:
                message = (
                    f"🛍️ {product.get('product_name', 'Product')}\n"
                    f"💰 Deal Price: ₹{product.get('Product_current_price', 'N/A')}\n"
                    f"💸 MRP       : ₹{product.get('Product_Buy_box_price', 'N/A')}\n"
                    f"🔗 [Buy Now]({product.get('product_Affiliate_url', '#')})"
                )
                
            # Convert HTML tags to WhatsApp markdown (basic conversion)
            # Replace <b> with * for bold in WhatsApp
            whatsapp_message = message.replace("<b>", "*").replace("</b>", "*")
            
            # Get image path
            image_path = product.get("Product_image_path")
            
            # Check and convert image_path to string if it's a number
            if image_path is not None:
                if isinstance(image_path, (int, float)):
                    print(f"[WhatsApp] Warning: image_path was a number ({image_path}), converting to string")
                    image_path = str(image_path)
            
            # Rest of the method remains the same
            local_image_path = None
            
            # Process image if available
            if image_path:
                # If it's a URL, download it first
                if image_path.startswith(('http://', 'https://')):
                    os.makedirs("temp_images", exist_ok=True)
                    local_image_path = f"temp_images/{os.path.basename(image_path)}"
                    
                    if self.whatsapp_sender.download_image(image_path, local_image_path):
                        image_path = local_image_path
                    else:
                        print(f"⚠️ Could not download image from {image_path}")
                        image_path = None
                # If it's a local path, verify it exists
                elif not os.path.exists(image_path):
                    print(f"⚠️ Image file not found: {image_path}")
                    image_path = None
            
            print(f"Attempting to send WhatsApp message to {('channel' if is_channel else 'group')}: {recipient_name}")
            
            # Send the message with image
            success, status_msg = self.whatsapp_sender.send_message(recipient_name, whatsapp_message, image_path, is_channel)
            
            if success:
                print(f"✅ WhatsApp message sent to {recipient_name}")
            else:
                print(f"❌ WhatsApp message failed: {status_msg}")
            
            return success
            
        except Exception as e:
            print(f"❌ WhatsApp push failed: {str(e)}")
            return False
        finally:
            # Clean up temporary files
            if local_image_path and os.path.exists(local_image_path):
                try:
                    os.remove(local_image_path)
                except:
                    pass

    def _cleanup_lock(self):
        """Clean up the lock file"""
        try:
            if os.path.exists(self.lock_file):
                os.remove(self.lock_file)
        except Exception as e:
            print(f"Warning: Failed to clean up lock file: {e}")

    def format_product_message(self, product: dict) -> str:
        """
        Formats the product details into a message string with improved formatting.
        :param product: Dictionary containing product information.
        :return: Formatted message string.
        """
        title = product.get("product_name", "Unnamed Product")
        
        # Convert prices to integers by removing decimal part
        try:
            current_price = int(float(product.get("Product_current_price", 0)))
        except (ValueError, TypeError):
            current_price = "N/A"
        
        try:
            buy_box_price = int(float(product.get("Product_Buy_box_price", 0)))
        except (ValueError, TypeError):
            buy_box_price = "N/A"
            
        buy_now_url = product.get("product_Affiliate_url", "#")
        
        # Format message with aligned colons and proper spacing
        message = (
            f"🛍️ {title}\n\n"
            f"💰 Deal Price  : ₹ <b>{current_price}</b> ✅\n"
            f"💸 MRP         : ₹ {buy_box_price} ❌\n\n"
            f"🔗 <b>Buy Now</b>    : {buy_now_url}"
        )
        return message

    def send_email_report(self, recipients, subject, body, csv_file=None):
        """
        Sends an email with an optional CSV file attached.
        :param recipients: List of recipient email addresses.
        :param subject: Subject of the email.
        :param body: Email body text.
        :param csv_file: Path to the CSV file to attach (optional).
        """
        smtp_server = self.email_config.get("smtp_server", "smtp.gmail.com")
        smtp_port = int(self.email_config.get("smtp_port", 587))
        smtp_user = self.email_config.get("sender_email")
        smtp_password = self.email_config.get("smtp_password")

        if not smtp_user or not smtp_password:
            print("❌ Email configuration is incomplete.")
            return

        msg = MIMEMultipart()
        msg["From"] = smtp_user
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        if csv_file:
            try:
                with open(csv_file, "rb") as f:
                    
                    attachment = MIMEApplication(f.read(), Name=os.path.basename(csv_file))
                    attachment.add_header("Content-Disposition", f'attachment; filename="{os.path.basename(csv_file)}"')
                    msg.attach(attachment)
            except Exception as e:
                print(f"⚠️ Failed to attach file {csv_file}: {e}")

        try:
            with smtplib.SMTP(smtp_server, smtp_port) as server:
                server.starttls()
                server.login(smtp_user, smtp_password)
                server.send_message(msg)
                print("✅ Email sent successfully.")
        except Exception as e:
            print(f"❌ Failed to send email: {e}")

    def publish(self, product):
        """
         Publish a product by sending notifications via Telegram and WhatsApp.
        :param product: Dictionary containing product details.
        """
        message = (
            f"🛍️ *{product['product_name']}*\n"
            f"💰 *Current Price:* ₹{product['Product_current_price']}\n"
            f"💸 *MRP:* ₹{product['Product_Buy_box_price']}\n"
            f"🔗 [Buy Now]({product['product_Affiliate_url']})"
        )
        image_path = product.get("Product_image_path")
        telegram_success, telegram_error = self.telegram_push(message, image_path)
        if not telegram_success:
            print(f"❌ Telegram push failed: {telegram_error}")

        group_name = self.config_manager.get("whatsapp_channel_names", "Default Group")
        try:
            self.whatsapp_push(product, group_name)
        except Exception as e:
            print(f"❌ WhatsApp push failed: {e}")
            
    def close(self):
        """Close browser and clean up resources"""
        try:
            if self._whatsapp_sender:
                try:
                    # Try to save cookies first
                    if hasattr(self._whatsapp_sender, '_save_cookies'):
                        self._whatsapp_sender._save_cookies()
                    # Use the correct close method
                    self._whatsapp_sender.close()
                except Exception as e:
                    print(f"Warning: Error in WhatsApp sender cleanup: {e}")
                finally:
                    self._whatsapp_sender = None
        except Exception as e:
            print(f"Warning: Error closing WebDriver: {e}")
        finally:
            self._cleanup_lock()


