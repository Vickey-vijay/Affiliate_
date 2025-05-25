import time
import json
import os
import tempfile
import pickle
import logging
import subprocess
import signal
import psutil
from selenium import webdriver
from selenium.webdriver.edge.options import Options
from selenium.webdriver.edge.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains 
import requests
import streamlit as st
from pathlib import Path
import uuid
import shutil
import atexit
import pywinauto
from pywinauto.application import Application
import time
# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(os.path.join(tempfile.gettempdir(), "whatsapp_automation.log"))
    ]
)
logger = logging.getLogger("WhatsAppSender")

class WhatsappSender:

    # Class-level singleton instance
    _instance = None
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(WhatsappSender, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        # Only initialize once
        if WhatsappSender._initialized:
            return
            
        WhatsappSender._initialized = True
        self.driver = None
        
        # Setup paths with fixed, reliable persistent storage location
        user_home = os.path.expanduser("~")
        self._data_dir = os.path.join(user_home, '.whatsapp_automation')
        os.makedirs(self._data_dir, exist_ok=True)
        
        # Use a consistent profile directory
        self._user_data_dir = os.path.join(self._data_dir, 'edge_profile')
        os.makedirs(self._user_data_dir, exist_ok=True)
        
        # Files for session management
        self.lock_file = os.path.join(self._data_dir, "whatsapp_sender.lock")
        self.cookies_file = os.path.join(self._data_dir, "whatsapp_cookies.pkl")
        self.pid_file = os.path.join(self._data_dir, "edge_driver.pid")
        self.storage_path = os.path.join(self._data_dir, "whatsapp_storage.json")
        
        # Register cleanup on exit
        atexit.register(self._cleanup_all)
        
        # Clean up existing processes before initializing
        self._cleanup_processes()
        
        logger.info("WhatsApp Sender initialized")

    def initialize_driver(self):
        """Initialize the Selenium WebDriver with Edge options."""
        if self.driver:
            # Check if existing driver is still valid
            if self._verify_driver_health():
                logger.info("Reusing existing WebDriver session")
                return self.driver
            else:
                # Close invalid driver
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
                
        try:
            # First, ensure the profile directory is not locked
            self._release_profile_locks(self._user_data_dir)
            
            # Create Edge options
            edge_options = Options()
            edge_options.add_argument(f"--user-data-dir={self._user_data_dir}")
            edge_options.add_argument("--profile-directory=Default")
            edge_options.add_argument("--disable-dev-shm-usage")
            edge_options.add_argument("--disable-features=TranslateUI")
            edge_options.add_argument("--disable-extensions")
            edge_options.add_argument("--disable-popup-blocking")
            edge_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            edge_options.add_experimental_option("useAutomationExtension", False)
            
            # Create a new WebDriver instance
            self.driver = webdriver.Edge(options=edge_options)
            self.driver.maximize_window()
            
            # Store in session state for easy access
            if 'whatsapp_drivers' not in st.session_state:
                st.session_state.whatsapp_drivers = []
            st.session_state.whatsapp_drivers.append(self.driver)
            
            # Save the process ID
            self._save_pid()
            
            # Create lock file to indicate session is active
            with open(self.lock_file, 'w') as f:
                f.write(str(os.getpid()))
                
            logger.info("New WebDriver session initialized")
            return self.driver
            
        except Exception as e:
            logger.error(f"Failed to initialize WebDriver: {e}")
            if self.driver:
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
            raise e

    def send_message(self, recipient_name, message, image_path=None, is_channel=False):
        """
        Send a message to a WhatsApp group/contact/channel with optional image.
        
        Args:
            recipient_name (str): Name of the group, contact or channel
            message (str): Message text to send
            image_path (str, optional): Path to image file to send
            is_channel (bool): Whether recipient is a channel (True) or group/contact (False)
            
        Returns:
            bool: Success status
            str: Status message
        """
        max_retries = 2
        retry_count = 0
        
        while retry_count < max_retries:
            try:
                # Initialize driver if needed
                if not self.driver:
                    self.initialize_driver()
                
                # Load WhatsApp Web
                if self.driver and "web.whatsapp.com" not in self.driver.current_url:
                    self.driver.get("https://web.whatsapp.com/")
                    
                # First try to load cookies to restore session
                self._load_cookies()
                
                # Wait for login to complete (handles QR code if needed)
                if not self.wait_for_login():
                    return False, "Login failed"
                
                # Find and select the recipient based on type
                if is_channel:
                    success = self.find_and_click_channel(recipient_name)
                else:
                    success = self.find_and_click_group(recipient_name)
                    
                if not success:
                    recipient_type = "channel" if is_channel else "group/contact"
                    return False, f"Could not find {recipient_type}: {recipient_name}"
                
                time.sleep(2)  # Wait for chat to load
                
                # For channels, always enter text first and then attach image
                if is_channel:
                    # First locate and click the message input
                    input_box_xpath = '//div[@contenteditable="true" and @data-tab="10"]'
                    try:
                        if self.driver is None:
                            raise RuntimeError("WebDriver is not initialized")
                        input_box = WebDriverWait(self._ensure_driver(), 10).until(
                            EC.presence_of_element_located((By.XPATH, input_box_xpath))
                        )
                        input_box.click()
                        time.sleep(1)
                        logger.info("Found and clicked message input field")
                        
                        # Enter the message text if provided
                        if message and message.strip():
                            # Process message line by line with Shift+Enter for newlines
                            lines = message.split('\n')
                            action_chains = ActionChains(self._ensure_driver())                            
                            for i, line in enumerate(lines):
                                # Send the line text
                                action_chains.send_keys(line)
                                
                                # Add newline with Shift+Enter if not the last line
                                if i < len(lines) - 1:
                                    action_chains.key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(Keys.SHIFT)
                            
                            # Execute all accumulated actions
                            action_chains.perform()
                            time.sleep(1)
                            logger.info("Entered message text")
                        
                        # If there's an image, attach it
                        if image_path:
                            if not os.path.exists(image_path):
                                return False, f"Image file not found: {image_path}"
                            
                            try:
                                # Click attachment button
                                attachment_xpath = '//div[@title="Attach"] | //button[@title="Attach"] | //span[@data-icon="attach"]/.. | //span[@data-testid="clip"]/..'
                                if self.driver is None:
                                    raise RuntimeError("WebDriver is not initialized")
                                clip_button = WebDriverWait(self._ensure_driver(), 10).until(
                                    EC.element_to_be_clickable((By.XPATH, attachment_xpath))
                                )
                                clip_button.click()
                                time.sleep(1)
                                
                                # Click image button
                                image_button_xpath = '//input[@accept="image/*,video/mp4,video/3gpp,video/quicktime"] | //input[@type="file"]'
                                image_input = WebDriverWait(self._ensure_driver(), 10).until(
                                    EC.presence_of_element_located((By.XPATH, image_button_xpath))
                                )
                                
                                # Send the image file path
                                abs_image_path = os.path.abspath(image_path)
                                image_input.send_keys(abs_image_path)
                                time.sleep(5)
                                logger.info("Attached image")
                                
                                # No need to enter caption as we already entered the text
                            except Exception as e:
                                return False, f"Error attaching image: {str(e)}"
                        
                        # Click send button
                        send_xpath = '//div[@role="button"][@aria-label="Send"] | //span[@data-icon="send"] | //span[@data-testid="send"]/.. | //button[contains(@aria-label, "Send")]'
                        send_button = WebDriverWait(self._ensure_driver(), 10).until(
                            EC.element_to_be_clickable((By.XPATH, send_xpath))
                        )
                        send_button.click()
                        time.sleep(3)
                        logger.info(f"Message sent to channel: {recipient_name}")
                        
                    except Exception as e:
                        return False, f"Error sending to channel: {str(e)}"
                    
                # For groups/contacts, follow the original approach
                else:
                    # If we have an image, send it with caption
                    if image_path:
                        if not os.path.exists(image_path):
                            return False, f"Image file not found: {image_path}"
                        
                        try:
                            logger.info(f"Preparing to send image to group: {recipient_name}")
                            
                            # First make sure we have a message input (confirms we're in chat)
                            input_box_xpath = '//div[@contenteditable="true" and @data-tab="10"]'
                            input_box = WebDriverWait(self._ensure_driver(), 10).until(
                                EC.presence_of_element_located((By.XPATH, input_box_xpath))
                            )
                            logger.info("Message input box found, chat is active")
                            
                            # Click to make sure chat is fully loaded
                            input_box.click()
                            time.sleep(1)
                            
                            # Click attachment button - using a more reliable method
                            logger.info("Trying to click attachment button...")
                            attachment_xpath = '//div[@title="Attach"] | //button[@title="Attach"] | //span[@data-icon="attach"]/.. | //span[@data-testid="clip"]/..'
                            
                            # Scroll to make sure it's visible
                            attachment_button = WebDriverWait(self._ensure_driver(), 10).until(
                                EC.presence_of_element_located((By.XPATH, attachment_xpath))
                            )
                            
                            # Scroll into view and ensure it's clickable
                            self._ensure_element_clickable(attachment_button)
                            time.sleep(1)
                            
                            # Now try to click it
                            attachment_button = WebDriverWait(self._ensure_driver(), 10).until(
                                EC.element_to_be_clickable((By.XPATH, attachment_xpath))
                            )
                            attachment_button.click()
                            logger.info("Attachment button clicked")
                            time.sleep(2)
                            
                            # Debug to see what options are available
                            self._debug_capture_ui_state("after_attachment_click")
                            
                            # IMPORTANT CHANGE: Use the same approach as channels - direct file input
                            # Look for the file input element directly
                            logger.info("Looking for file input field...")

                            try:
                                # First try to click on the Photos & videos option explicitly
                                photos_xpath = '//span[text()="Photos & videos" or (contains(text(), "Photos") and contains(text(), "videos"))]'
                                photos_option = WebDriverWait(self._ensure_driver(), 5).until(
                                    EC.element_to_be_clickable((By.XPATH, photos_xpath))
                                )
                                logger.info("Found Photos & videos option")
                                
                                # Scroll it into view and click
                                self._ensure_driver().execute_script("arguments[0].scrollIntoView({block: 'center'});", photos_option)
                                time.sleep(1)
                                # photos_option.click()
                                # logger.info("Clicked on Photos & videos option")
                                time.sleep(2)
                                
                                # Now look for the file input element directly related to the Photos & videos option
                                image_button_xpath = '//span[text()="Photos & videos" or (contains(text(), "Photos") and contains(text(), "videos"))]/..//input[@type="file"]'
                                image_input = WebDriverWait(self._ensure_driver(), 10).until(
                                    EC.presence_of_element_located((By.XPATH, image_button_xpath))
                                )
                                
                            except Exception as e:
                                logger.warning(f"Could not select Photos & videos menu: {e}")
                                self._debug_capture_ui_state("photos_menu_failed")
                                
                                # Try a different approach - using direct input with the parent div to ensure we get the right input
                                try:
                                    logger.info("Trying alternative XPath for file input")
                                    # Try to find input through parent div with media icon
                                    alt_image_xpath = '//span[@data-icon="media-filled-refreshed"]/../..//input[@type="file"]'
                                    image_input = WebDriverWait(self._ensure_driver(), 5).until(
                                        EC.presence_of_element_located((By.XPATH, alt_image_xpath))
                                    )
                                    logger.info("Found file input using alternative XPath")
                                except Exception as e2:
                                    logger.error(f"Could not find file input with alternative XPath: {e2}")
                                    
                                    # Last resort - try the generic file input
                                    try:
                                        logger.info("Using generic file input as last resort")
                                        image_button_xpath = '//input[@type="file"]'
                                        image_input = WebDriverWait(self._ensure_driver(), 5).until(
                                            EC.presence_of_element_located((By.XPATH, image_button_xpath))
                                        )
                                    except Exception as e3:
                                        logger.error(f"All file input methods failed: {e3}")
                                        raise Exception(f"Failed to select image input method: {e3}")
                            
                            # Send the image file path directly to this input
                            abs_image_path = os.path.abspath(image_path)
                            logger.info(f"Sending image path directly: {abs_image_path}")
                            image_input.send_keys(abs_image_path)
                            time.sleep(5)
                            logger.info("Image file path sent")
                            
                            # Add caption if message exists
                            if message and message.strip():
                                caption_xpath = '//div[@contenteditable="true" and @data-tab="10"] | //div[@contenteditable="true" and @role="textbox"] | //div[@contenteditable="true"][@data-testid="media-caption"]'
                                try:
                                    logger.info("Looking for caption field...")
                                    caption_input = WebDriverWait(self._ensure_driver(), 10).until(
                                        EC.presence_of_element_located((By.XPATH, caption_xpath))
                                    )
                                    logger.info("Caption field found, clicking...")
                                    
                                    # Make sure it's visible and clickable
                                    self._ensure_element_clickable(caption_input)
                                    time.sleep(1)
                                    
                                    caption_input.click()
                                    time.sleep(1)
                                    logger.info("Caption field clicked")
                                    
                                    # Process caption line by line with Shift+Enter for newlines
                                    lines = message.split('\n')
                                    action_chains = ActionChains(self._ensure_driver())
                                    
                                    logger.info(f"Entering caption with {len(lines)} lines")
                                    for i, line in enumerate(lines):
                                        # Send the line text
                                        action_chains.send_keys(line)
                                        
                                        # Add newline with Shift+Enter if not the last line
                                        if i < len(lines) - 1:
                                            action_chains.key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(Keys.SHIFT)
                                    
                                    # Execute all accumulated actions
                                    action_chains.perform()
                                    time.sleep(1)
                                    logger.info("Caption entered successfully")
                                except Exception as e:
                                    logger.warning(f"Could not add caption: {str(e)}")
                            
                            # Click send button
                            logger.info("Looking for send button...")
                            send_xpath = '//div[@role="button"][@aria-label="Send"] | //span[@data-icon="send"] | //span[@data-testid="send"]/.. | //button[contains(@aria-label, "Send")]'
                            send_button = WebDriverWait(self._ensure_driver(), 10).until(
                                EC.element_to_be_clickable((By.XPATH, send_xpath))
                            )
                            
                            # Make sure it's visible
                            self._ensure_element_clickable(send_button)
                            time.sleep(1)
                            
                            logger.info("Clicking send button...")
                            send_button.click()
                            time.sleep(3)
                            logger.info(f"Image sent to group: {recipient_name}")
                        except Exception as e:
                            logger.error(f"Error sending image to group: {str(e)}")
                            return False, f"Error sending image: {str(e)}"
                    
                    # If no image, just send text message
                    elif message and message.strip():
                        try:
                            # Look for the input box
                            input_box_xpath = '//div[@contenteditable="true" and @data-tab="10"]'
                            input_box = WebDriverWait(self._ensure_driver(), 10).until(
                                EC.presence_of_element_located((By.XPATH, input_box_xpath))
                            )
                            input_box.click()
                            
                            # Process message line by line with Shift+Enter for newlines
                            lines = message.split('\n')
                            action_chains = ActionChains(self._ensure_driver())

                            for i, line in enumerate(lines):
                                # Send the line text
                                action_chains.send_keys(line)
                                
                                # Add newline with Shift+Enter if not the last line
                                if i < len(lines) - 1:
                                    action_chains.key_down(Keys.SHIFT).send_keys(Keys.ENTER).key_up(Keys.SHIFT)
                            
                            # Execute all accumulated actions
                            action_chains.perform()
                            time.sleep(1)
                            
                            # Press Enter to send
                            ActionChains(self._ensure_driver()).key_down(Keys.ENTER).key_up(Keys.ENTER).perform()
                            time.sleep(3)
                            logger.info(f"Text message sent to {recipient_name}")
                        except Exception as e:
                            return False, f"Failed to send message: {str(e)}"
                
                # Save session information for future use
                self._save_cookies()
                self._improve_session_persistence()
                
                # Optional: Return to WhatsApp home
                try:
                    if self.driver is not None:
                        self.driver.get("https://web.whatsapp.com/")
                        time.sleep(2)
                except:
                    pass
                    
                return True, "Message sent successfully"
                
            except Exception as e:
                retry_count += 1
                error_msg = f"Attempt {retry_count}/{max_retries} failed: {str(e)}"
                logger.warning(error_msg)
                
                if retry_count < max_retries:
                    # Clean up for retry
                    if self.driver:
                        try:
                            self.driver.quit()
                        except:
                            pass
                        self.driver = None
                    
                    # Clean up resources before retrying
                    self._cleanup_processes()
                    time.sleep(2)
                else:
                    return False, f"Failed after {max_retries} attempts: {str(e)}"

    def find_and_click_group(self, group_name):
        """Search for and click on a group/contact."""
        try:
            logger.info(f"Looking for group/contact: {group_name}")
            
            # Wait for side panel to be loaded
            WebDriverWait(self._ensure_driver(), 15).until(
                EC.presence_of_element_located((By.XPATH, '//div[@id="side"]'))
            )
            logger.info("Side panel loaded")
            
            # First try direct match if it's pinned or recent
            try:
                logger.info("Trying direct match first...")
                group_xpath = f'//span[@title="{group_name}"]'
                group = WebDriverWait(self._ensure_driver(), 5).until(
                    EC.element_to_be_clickable((By.XPATH, group_xpath))
                )
                group.click()
                time.sleep(2)
                logger.info(f"Found and clicked group directly: {group_name}")
                
                # Verify we're in the chat
                try:
                    WebDriverWait(self._ensure_driver(), 5).until(
                        EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true" and @data-tab="10"]'))
                    )
                    logger.info("Chat input box found, chat loaded successfully")
                    return True
                except:
                    logger.info("Chat input not found after clicking group, will try search")
                    pass
            except:
                logger.info("Group not found directly, will try search")
                pass
            
            # If direct match fails, use search
            logger.info("Using search to find group...")
            
            # Find the search box
            search_box_xpath = '//div[@contenteditable="true"][@data-tab="3"]'
            search_box = WebDriverWait(self._ensure_driver(), 10).until(
                EC.presence_of_element_located((By.XPATH, search_box_xpath))
            )
            
            # Clear any existing text
            search_box.clear()
            search_box.click()
            time.sleep(1)
            logger.info("Search box cleared and clicked")
            
            # Enter the group name
            ActionChains(self._ensure_driver()).send_keys(group_name).perform()
            time.sleep(3)
            logger.info(f"Entered group name in search: {group_name}")
            
            # Look for matching contacts/groups
            group_xpath = f'//span[@title="{group_name}"]'
            try:
                group = WebDriverWait(self._ensure_driver(), 10).until(
                    EC.element_to_be_clickable((By.XPATH, group_xpath))
                )
                group.click()
                time.sleep(2)
                
                # Verify we're in the chat
                WebDriverWait(self._ensure_driver(), 5).until(
                    EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true" and @data-tab="10"]'))
                )
                logger.info(f"Group found through search and clicked: {group_name}")
                return True
            except:
                logger.warning(f"Group/contact not found after search: {group_name}")
                return False
                
        except Exception as e:
            logger.error(f"Error finding group/contact: {e}")
            return False

    def find_and_click_channel(self, channel_name):
        """Search for and click on a channel."""
        if self.driver is None:
            logger.error("Cannot find channel: WebDriver is not initialized")
            return False
            
        try:
            # Wait for side panel to be loaded
            WebDriverWait(self._ensure_driver(), 15).until(
                EC.presence_of_element_located((By.XPATH, '//div[@id="side"]'))
            )
            
            # First try to click directly if channel is pinned
            try:
                channel_xpath = f'//span[@title="{channel_name}"]'
                channel = WebDriverWait(self._ensure_driver(), 5).until(
                    EC.presence_of_element_located((By.XPATH, channel_xpath))
                )
                channel.click()
                time.sleep(2)
                # Verify we're in channel chat and not search results
                try:
                    WebDriverWait(self._ensure_driver(), 3).until(
                        EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true" and @data-tab="10"]'))
                    )
                    logger.info(f"Found pinned channel: {channel_name}")
                    return True
                except:
                    logger.warning("Found element but might be in search results, trying channels tab")
                    pass
            except:
                # Channel not visible directly, try through the channels tab
                pass
                
            # Try to find and click the channels tab first
            try:
                logger.info("Looking for channels tab")
                channels_tab_xpath = '//span[@data-icon="newsletter-tab"] | //span[@data-testid="newsletter-tab"] | //span[@data-icon="newsletter-outline"] | //span[@data-testid="newsletter"]'
                channels_tab = WebDriverWait(self._ensure_driver(), 10).until(
                    EC.element_to_be_clickable((By.XPATH, channels_tab_xpath))
                )
                channels_tab.click()
                time.sleep(3)
                logger.info("Clicked on channels tab")
                
                # Now look for the channel in the channels list
                try:
                    # First try direct match
                    channel_in_tab_xpath = f'//span[@title="{channel_name}"]'
                    channel = WebDriverWait(self._ensure_driver(), 5).until(
                        EC.element_to_be_clickable((By.XPATH, channel_in_tab_xpath))
                    )
                    channel.click()
                    time.sleep(2)
                    logger.info(f"Found channel in tab list: {channel_name}")
                    return True
                except:
                    # Use search if direct match fails
                    search_box_xpath = '//div[@contenteditable="true"][@data-tab="3"] | //div[@contenteditable="true"][@role="textbox"]'
                    search_box = WebDriverWait(self._ensure_driver(), 10).until(
                        EC.presence_of_element_located((By.XPATH, search_box_xpath))
                    )
                    search_box.clear()
                    search_box.click()
                    time.sleep(1)
                    
                    # Enter the channel name
                    ActionChains(self._ensure_driver()).send_keys(channel_name).perform()
                    time.sleep(3)
                    
                    # Look for matching channel
                    try:
                        channel_xpath = f'//span[@title="{channel_name}"]'
                        channel = WebDriverWait(self._ensure_driver(), 10).until(
                            EC.element_to_be_clickable((By.XPATH, channel_xpath))
                        )
                        channel.click()
                        time.sleep(2)
                        
                        # Verify we entered the channel and not just selected in search
                        WebDriverWait(self._ensure_driver(), 5).until(
                            EC.presence_of_element_located((By.XPATH, '//div[@contenteditable="true" and @data-tab="10"]'))
                        )
                        logger.info(f"Found channel after search: {channel_name}")
                        return True
                    except:
                        logger.warning(f"Channel not found: {channel_name}")
                        return False
                        
            except Exception as e:
                logger.error(f"Error accessing channels tab: {e}")
                return False
                    
        except Exception as e:
            logger.error(f"Error finding channel: {e}")
            return False

    def wait_for_login(self):
        """Wait for WhatsApp Web login and handle popups."""
        if self.driver is None:
            logger.error("Cannot wait for login: WebDriver is not initialized")
            return False
            
        try:
            # Check if already on WhatsApp Web
            if "web.whatsapp.com" not in self.driver.current_url:
                self.driver.get("https://web.whatsapp.com")
                time.sleep(2)
            
            # Handle popups
            self._handle_popups()
            
            # Check if already logged in
            try:
                WebDriverWait(self._ensure_driver(), 10).until(
                    EC.presence_of_element_located((By.XPATH, '//div[@id="side"]'))
                )
                logger.info("Already logged in!")
                return True
            except:
                # Need to scan QR code
                logger.info("Waiting for QR code scan...")
                
                # Wait longer for user to scan QR code
                try:
                    WebDriverWait(self._ensure_driver(), 60).until(
                        EC.presence_of_element_located((By.XPATH, '//div[@id="side"]'))
                    )
                    logger.info("Login successful!")
                    
                    # Handle any post-login popups
                    self._handle_popups()
                    
                    # Save session data
                    self._save_cookies()
                    self._improve_session_persistence()
                    return True
                except:
                    logger.error("Login timeout")
                    return False
                
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False

    def _handle_popups(self):
        """Handle various WhatsApp Web popups."""
        if self.driver is None:
            logger.warning("Cannot handle popups: WebDriver is not initialized")
            return
            
        popup_xpaths = [
            '//div[@role="button" and contains(., "Continue")]',
            '//div[@role="button" and contains(., "Accept")]',
            '//div[@role="button" and contains(., "OK")]',
            '//div[contains(@class, "popup") or contains(@class, "modal")]//div[@role="button"]'
        ]
        
        for xpath in popup_xpaths:
            try:
                popup = WebDriverWait(self._ensure_driver(), 3).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                )
                if popup:
                    popup.click()
                    time.sleep(1)
                    logger.info(f"Clicked popup")
            except:
                pass

    def _save_cookies(self):
        """Save session cookies to file."""
        try:
            if self.driver and "web.whatsapp.com" in self.driver.current_url:
                cookies = self.driver.get_cookies()
                with open(self.cookies_file, 'wb') as f:
                    pickle.dump(cookies, f)
                logger.info("Cookies saved successfully")
                return True
        except Exception as e:
            logger.error(f"Failed to save cookies: {e}")
        return False

    def _improve_session_persistence(self):
        """Save additional session data like localStorage."""
        try:
            if not self.driver or "web.whatsapp.com" not in self.driver.current_url:
                return False
                
            # Save localStorage data
            local_storage = self.driver.execute_script(
                "var data = {}; "
                "for (var i = 0; i < localStorage.length; i++) {"
                "    var key = localStorage.key(i);"
                "    data[key] = localStorage.getItem(key);"
                "} "
                "return data;"
            )
            
            if local_storage:
                with open(self.storage_path, 'w') as f:
                    json.dump(local_storage, f)
                logger.info("localStorage data saved")
            
            return True
        except Exception as e:
            logger.error(f"Error saving session data: {e}")
            return False

    def _load_cookies(self):
        """Load saved cookies and session data."""
        try:
            # First check for localStorage data
            if os.path.exists(self.storage_path) and self.driver:
                try:
                    with open(self.storage_path, 'r') as f:
                        local_storage = json.load(f)
                    
                    for key, value in local_storage.items():
                        self.driver.execute_script(
                            f"window.localStorage.setItem('{key}', '{value}');"
                        )
                    logger.info("localStorage data loaded")
                except Exception as e:
                    logger.warning(f"Error loading localStorage: {e}")
            
            # Then load cookies
            if os.path.exists(self.cookies_file) and self.driver:
                with open(self.cookies_file, 'rb') as f:
                    cookies = pickle.load(f)
                
                for cookie in cookies:
                    try:
                        self.driver.add_cookie(cookie)
                    except Exception as e:
                        logger.debug(f"Could not add cookie: {e}")
                
                logger.info("Cookies loaded")
                self.driver.refresh()
                time.sleep(2)
                return True
                
        except Exception as e:
            logger.error(f"Error loading session data: {e}")
        
        return False

    def download_image(self, image_url, save_path):
        """Download image from URL to local file."""
        try:
            response = requests.get(image_url, stream=True)
            response.raise_for_status()
            
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    
            logger.info(f"Image downloaded to {save_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to download image: {e}")
            return False

    def _verify_driver_health(self):
        """Check if the WebDriver session is still valid."""
        if not self.driver:
            return False
            
        try:
            # Simple check that doesn't navigate
            current_url = self.driver.current_url
            self.driver.title  # This will throw exception if driver is dead
            return True
        except:
            return False

    def _save_pid(self):
        """Save the WebDriver process ID."""
        try:
            if self.driver and hasattr(self.driver, 'service') and hasattr(self.driver.service, 'process'):
                pid = self.driver.service.process.pid
                with open(self.pid_file, 'w') as f:
                    f.write(str(pid))
                logger.info(f"Saved driver PID: {pid}")
        except Exception as e:
            logger.error(f"Error saving PID: {e}")

    def _kill_driver_process(self, pid):
        """Kill a specific process by ID."""
        try:
            if psutil.pid_exists(pid):
                process = psutil.Process(pid)
                process.terminate()
                process.wait(timeout=3)
                logger.info(f"Terminated process {pid}")
        except Exception as e:
            logger.warning(f"Could not terminate process {pid}: {e}")
            try:
                if os.name == 'nt':  # Windows
                    subprocess.run(['taskkill', '/F', '/PID', str(pid)], check=False)
                else:  # Linux/macOS
                    os.kill(pid, signal.SIGKILL)
                logger.info(f"Forcefully killed process {pid}")
            except:
                pass

    def _kill_all_edge_drivers(self):
        """Kill all Edge WebDriver processes."""
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if 'msedgedriver' in proc.info['name'].lower():
                        proc.kill()
                        logger.info(f"Killed Edge WebDriver process: {proc.info['pid']}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            logger.error(f"Error killing Edge drivers: {e}")

    def _release_profile_locks(self, profile_dir):
        """Release locks that might prevent profile use."""
        if not os.path.exists(profile_dir):
            return
            
        lock_patterns = ['SingletonLock', 'SingletonCookie', '.lock', 'lockfile']
        for pattern in lock_patterns:
            for root, _, files in os.walk(profile_dir):
                for file in files:
                    if pattern in file.lower():
                        try:
                            lock_path = os.path.join(root, file)
                            os.remove(lock_path)
                            logger.info(f"Removed lock file: {lock_path}")
                        except:
                            pass

    def _cleanup_processes(self):
        """Clean up all resources and processes."""
        # Kill existing Edge driver processes
        self._kill_all_edge_drivers()
        
        # Remove lock files
        for filename in [self.pid_file, self.lock_file]:
            if os.path.exists(filename):
                try:
                    os.remove(filename)
                except:
                    pass
        
        # Release profile locks
        if os.path.exists(self._user_data_dir):
            self._release_profile_locks(self._user_data_dir)

    def _cleanup_all(self):
        """Full cleanup of all resources."""
        try:
            # Save session data if possible
            if self.driver:
                try:
                    self._save_cookies()
                    self._improve_session_persistence()
                except:
                    pass
                
                # Quit driver
                try:
                    self.driver.quit()
                except:
                    pass
                self.driver = None
            
            # Clean up processes and files
            self._cleanup_processes()
            
        except Exception as e:
            logger.error(f"Error during cleanup: {e}")

    def close(self):
        """Properly close the WhatsApp sender instance."""
        self._cleanup_all()
        WhatsappSender._initialized = False

    def __del__(self):
        """Ensure cleanup when object is garbage collected."""
        self.close()

    def reset_profile(self):
        """Reset the profile (requires new QR scan)."""
        self.close()
        
        # Remove profile directory
        if os.path.exists(self._user_data_dir):
            try:
                shutil.rmtree(self._user_data_dir, ignore_errors=True)
                os.makedirs(self._user_data_dir, exist_ok=True)
                logger.info("Profile directory reset")
            except Exception as e:
                logger.error(f"Failed to reset profile directory: {e}")
        
        # Remove cookie and storage files
        for file_path in [self.cookies_file, self.storage_path]:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except:
                    pass
                    
        logger.info("WhatsApp profile reset complete")
        return True

    def _ensure_driver(self) -> webdriver.Edge:
        """Ensures the driver is initialized and returns it."""
        if self.driver is None:
            raise RuntimeError("WebDriver is not initialized")
        return self.driver

    # Add this helper method to your class
    def _ensure_element_clickable(self, element, timeout=3):
        """
        Make sure an element is visible and clickable by scrolling it into view
        """
        try:
            # Make sure element is scrolled into view
            driver = self._ensure_driver()
            driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", element)
            time.sleep(0.5)
            
            # Now wait until it's clickable
            return WebDriverWait(driver, timeout).until(EC.element_to_be_clickable((By.XPATH, element.get_attribute("xpath"))))
        except:
            # If we can't get the xpath, just return the original element
            return element

    # Add this helper method to your class
    def _debug_capture_ui_state(self, prefix="debug"):
        """Capture screenshots and page source for debugging"""
        if not self.driver:
            return
        
        try:
            # Create debug folder if needed
            debug_dir = os.path.join(self._data_dir, "debug")
            os.makedirs(debug_dir, exist_ok=True)
            
            # Take screenshot
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            screenshot_path = os.path.join(debug_dir, f"{prefix}_screenshot_{timestamp}.png")
            self.driver.save_screenshot(screenshot_path)
            
            # Save page source
            source_path = os.path.join(debug_dir, f"{prefix}_source_{timestamp}.html")
            with open(source_path, 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)
                
            logger.info(f"Debug info captured to {debug_dir}")
        except Exception as e:
            logger.error(f"Failed to capture debug info: {e}")




