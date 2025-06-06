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
# import telegram
import requests  # For fallback method
import asyncio  # For handling async operations


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

 
    def test_telegram_config(self, bot_token: str, channel_names: str):
        """Test Telegram configuration with provided credentials"""
        try:
            # Split channel names by newlines and/or commas (to handle both formats)
            channels = []
            for line in channel_names.split('\n'):
                # Then split by commas if present
                for part in line.split(','):
                    part = part.strip()
                    if part:
                        # Make sure channel names are properly formatted
                        if not part.startswith("@") and not part.lstrip('-').isdigit():
                            part = f"@{part}"
                        channels.append(part)
                
            if not channels:
                return False, "No channels specified"
            
            errors = []
            success = False
            
            # Use direct API approach for consistent behavior
            for channel_name in channels:
                try:
                    # Use requests to send message directly via Telegram API
                    test_message = "This is a test message from Affiliate Product Monitor."
                    api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
                    
                    response = requests.post(
                        api_url,
                        json={
                            'chat_id': channel_name,
                            'text': test_message,
                            'parse_mode': 'HTML'
                        }
                    )
                    
                    if response.status_code == 200:
                        success = True
                    else:
                        error_data = response.json()
                        errors.append(f"{channel_name}: {error_data.get('description', 'Unknown error')}")
                        print(f"[Telegram] Test failed for {channel_name}: {error_data.get('description')}")
            
                except Exception as e:
                    print(f"[Telegram] Exception occurred during test for {channel_name}: {e}")
                    errors.append(f"{channel_name}: {str(e)}")

            if errors:
                return success, "; ".join(errors)
            return True, None
        except Exception as e:
            return False, f"Error testing Telegram configuration: {str(e)}"

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

        # Use Product_MRP for MRP value, fallback to Buy_box_price if not available
        try:
            # First try to get the MRP from the dedicated field
            mrp = product.get("Product_MRP")
            
            # If it's None or the same as current price, try other options
            if mrp is None or mrp == current_price:
                mrp = product.get("Product_Buy_box_price")
                
            # If still None or equal to current price, calculate it
            if mrp is None or mrp == current_price:
                mrp = int(float(current_price) * 1.2)
            else:
                # Convert to int if it's not None
                mrp = int(float(mrp))
                
        except (ValueError, TypeError):
            # Fallback if conversion fails
            mrp = int(float(current_price) * 1.2) if isinstance(current_price, (int, float)) else "N/A"
        
        buy_now_url = product.get("product_Affiliate_url", "#")
        
        # Format message with aligned colons and proper spacing
        message = (
            f"🛍️ {title}\n\n"
            f"💰 Deal Price  : ₹ {current_price} ✅\n"
            f"💸 MRP          : ₹ {mrp} ❌\n\n"
            f"🔗 Buy Now     : {buy_now_url}"
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

    def telegram_push(self, message, image_path=None):
        """
        Send a message to Telegram channel(s).
        
        Args:
            message (str): Message to send
            image_path (str, optional): Path to image file
            
        Returns:
            tuple: (success, error_message)
        """
        try:
            # Get Telegram configuration
            try:
                config = self.config_manager.get_telegram_config()
                bot_token = config.get("bot_token")
            except (AttributeError, Exception) as e:
                # Fallback to self.telegram_config
                bot_token = self.telegram_config.get("bot_token")
        
            if not bot_token:
                print("[Telegram] No bot token configured")
                return False, "No bot token configured"
        
            # Get channels - read directly from config.json for reliability
            channels = []
        
            try:
                with open("config.json", "r") as f:
                    json_config = json.load(f)
            
                # Process telegram_channels array
                if "telegram_channels" in json_config and isinstance(json_config["telegram_channels"], list):
                    for item in json_config["telegram_channels"]:
                        if isinstance(item, str):
                            # Split by commas if it contains commas
                            if "," in item:
                                for ch in item.split(","):
                                    ch = ch.strip()
                                    if ch:
                                        if not ch.startswith("@") and not ch.lstrip('-').isdigit():
                                            ch = f"@{ch}"
                                        channels.append(ch)
                            else:
                                # Add as a single item if no commas
                                ch = item.strip()
                                if ch:
                                    if not ch.startswith("@") and not ch.lstrip('-').isdigit():
                                        ch = f"@{ch}"
                                    channels.append(ch)
                    
                # Also check for comma-separated telegram_chat_id 
                if "telegram_chat_id" in json_config:
                    chat_id = json_config["telegram_chat_id"]
                    if isinstance(chat_id, str) and "," in chat_id:
                        for ch in chat_id.split(","):
                            ch = ch.strip()
                            if ch and ch not in channels:
                                if not ch.startswith("@") and not ch.lstrip('-').isdigit():
                                    ch = f"@{ch}"
                                channels.append(ch)
                    elif chat_id and chat_id not in channels:
                        if not chat_id.startswith("@") and not chat_id.lstrip('-').isdigit():
                            chat_id = f"@{chat_id}"
                        channels.append(chat_id)
            except Exception as e:
                print(f"[Telegram] Error reading config.json: {e}")
    
            if not channels:
                print("[Telegram] No channels configured")
                return False, "No channels configured"
                
            print(f"[DEBUG] Sending to {len(channels)} channels: {channels}")
        
            successful_channels = []
            errors = []
        
            # Process all channels
            for channel in channels:
                try:
                    print(f"[Telegram] Sending message to channel: {channel}")
                
                    # Prepare API URL
                    api_url = f"https://api.telegram.org/bot{bot_token}/"
                
                    # If we have an image, send photo with caption
                    if image_path and os.path.exists(image_path):
                        with open(image_path, 'rb') as photo:
                            # Send photo with caption
                            url = api_url + "sendPhoto"
                            files = {'photo': photo}
                            data = {
                                'chat_id': channel,
                                'caption': message,
                                'parse_mode': 'HTML'
                            }
                            print(f"[DEBUG] Sending photo with caption to {url}")
                            response = requests.post(url, files=files, data=data)
                    else:
                        # Send just text message
                        url = api_url + "sendMessage"
                        data = {
                            'chat_id': channel,
                            'text': message,
                            'parse_mode': 'HTML',
                            'disable_web_page_preview': False
                        }
                        print(f"[DEBUG] Sending text message to {url}")
                        response = requests.post(url, json=data)
                
                    # Check response
                    print(f"[DEBUG] Response status code: {response.status_code}")
                    print(f"[DEBUG] Response content: {response.text[:200]}")
                
                    if response.status_code == 200:
                        print(f"[Telegram] Successfully sent message to {channel}")
                        successful_channels.append(channel)
                    else:
                        error_message = response.json().get("description", f"Error {response.status_code}")
                        print(f"[Telegram] Failed to send to {channel}: {error_message}")
                        print(f"[Telegram] Response: {response.text}")
                        errors.append(f"{channel}: {error_message}")
                    
                except Exception as e:
                    print(f"[Telegram] Exception while sending to {channel}: {str(e)}")
                    import traceback
                    traceback.print_exc()
                    errors.append(f"{channel}: {str(e)}")

        except Exception as errors:
            return False, str(errors)
        return True, None


    def publish(self, product):
        """
        Publish a product by sending notifications via Telegram and WhatsApp.
        
        Args:
            product (dict): Dictionary containing product details.
            
        Returns:
            tuple: (success, message) - True if published to at least one platform
        """
        success = False
        channels_published = []
        errors = []
        
        # Format the message using our formatter method for consistency
        message = self.format_product_message(product)
        image_path = product.get("Product_image_path")
        
        # Try Telegram first
        telegram_success, telegram_error = self.telegram_push(message, image_path)
        if telegram_success:
            channels_published.append("Telegram")
            success = True
        else:
            error_msg = f"❌ Telegram push failed: {telegram_error}"
            print(error_msg)
            errors.append(error_msg)

        # Try WhatsApp
        try:
            # Get WhatsApp configuration
            whatsapp_groups = []
            
            # Try to get group from self.config_manager (should be there)
            try:
                group_name = self.config_manager.get("whatsapp_channel_names", "")
                if group_name:
                    whatsapp_groups.append(group_name)
            except Exception as e:
                print(f"Warning: Could not get WhatsApp group from config: {e}")
                
            # If no groups configured, use default
            if not whatsapp_groups:
                whatsapp_groups.append("Default Group")
            
            # Send to all configured groups
            whatsapp_success = False
            for group_name in whatsapp_groups:
                if self.whatsapp_push(product, group_name):
                    channels_published.append(f"WhatsApp ({group_name})")
                    whatsapp_success = True
                    success = True
            
            if not whatsapp_success:
                errors.append("❌ WhatsApp: Failed to send to any groups")
                
        except Exception as e:
            error_msg = f"❌ WhatsApp push failed: {str(e)}"
            print(error_msg)
            errors.append(error_msg)

        # Return overall status
        result_message = ""
        if channels_published:
            result_message += f"Published to: {', '.join(channels_published)}. "
        if errors:
            result_message += f"Errors: {'; '.join(errors)}"
            
        return success, result_message
