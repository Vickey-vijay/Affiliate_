import configparser
import os
import json

class ConfigManager:
    """
    ConfigManager handles the configuration settings for the application.
    It loads settings from a configuration file (config.ini) or creates one with default values.
    """
    def __init__(self, config_file: str = "config.ini"):
        """
        Initialize the ConfigManager with the specified config file.
        :param config_file: Path to the configuration file.
        """
        self.config_file = config_file
        self.config = configparser.ConfigParser()
        self.json_config = {}
        try:
            with open("config.json", "r") as f:
                self.json_config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        self.load_config()

    def load_config(self):
        """
        Loads the configuration from the config file.
        If the file does not exist, creates a default configuration.
        """
        if os.path.exists(self.config_file):
            self.config.read(self.config_file)
        else:
            self.create_default_config()

    def create_default_config(self):
        """
        Creates a default configuration file with sample settings.
        """
        self.config['Amazon'] = {
            'access_key': 'YOUR_ACCESS_KEY',
            'secret_key': 'YOUR_SECRET_KEY',
            'partner_tag': 'YOUR_PARTNER_TAG'
        }
        self.config['Telegram'] = {
            'bot_token': 'YOUR_TELEGRAM_BOT_TOKEN',
            'group_ids': 'GROUP_ID1, GROUP_ID2'
        }
        self.config['WhatsApp'] = {
            'cookies': 'YOUR_WHATSAPP_COOKIES'
        }
        self.config['Scheduler'] = {
            'scraping_frequency': '6',  
            'daily_report_time': '06:00',
            'weekly_report_day': 'Sunday',
            'monthly_report_day': '1'
        }
        self.config['General'] = {
            'hands_off_mode': 'False'
        }
        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)

    def get_amazon_config(self) -> dict:
        """
        Retrieves the Amazon configuration settings.
        :return: A dictionary of Amazon settings.
        """
        return dict(self.config['Amazon'])

    def get_telegram_config(self) -> dict:
        """Get Telegram configuration from either the flat structure or nested structure."""
        result = {}
        
        # Try to read from INI file first
        if "Telegram" in self.config:
            bot_token = self.config["Telegram"].get("bot_token", "")
            group_ids_str = self.config["Telegram"].get("group_ids", "")
            result = {
                "bot_token": bot_token,
                "channel_ids": {}
            }
            
            # Parse group IDs from comma-separated string
            if group_ids_str:
                for idx, group_id in enumerate(group_ids_str.split(",")):
                    channel_name = f"channel_{idx+1}"
                    result["channel_ids"][channel_name] = group_id.strip()
    
        # Fall back to JSON config or enhance from JSON config
        if self.json_config:
            # Check flat structure (as currently in your config.json)
            if "telegram_bot_token" in self.json_config:
                result["bot_token"] = self.json_config.get("telegram_bot_token", "")
                chat_id = self.json_config.get("telegram_chat_id", "")
                
                if chat_id and "channel_ids" not in result:
                    result["channel_ids"] = {}
                    
                if chat_id:
                    channel_name = chat_id if chat_id.startswith("@") else "default_channel"
                    result["channel_ids"][channel_name] = chat_id
                    
            # Also check nested structure for future compatibility
            elif "telegram" in self.json_config:
                telegram_config = self.json_config["telegram"]
                result["bot_token"] = telegram_config.get("bot_token", result.get("bot_token", ""))
                
                # Check if chat_id exists in nested config
                if "chat_id" in telegram_config:
                    chat_id = telegram_config["chat_id"]
                    if "channel_ids" not in result:
                        result["channel_ids"] = {}
                        
                    channel_name = chat_id if chat_id.startswith("@") else "default_channel"
                    result["channel_ids"][channel_name] = chat_id
                    
                # Check if channel_ids exists in nested config
                if "channel_ids" in telegram_config:
                    if "channel_ids" not in result:
                        result["channel_ids"] = {}
                    result["channel_ids"].update(telegram_config["channel_ids"])
    
        return result

    
    def get_whatsapp_config(self) -> dict:
        """Get WhatsApp configuration."""
        try:
            # First try to get WhatsApp config from JSON config
            if self.json_config and "whatsapp" in self.json_config:
                return self.json_config["whatsapp"]
            
            # For backward compatibility - check for whatsapp_channel_names in JSON
            if self.json_config and "whatsapp_channel_names" in self.json_config:
                return {
                    "channel_names": self.json_config["whatsapp_channel_names"],
                    "group_names": ""
                }
                
            # As a fallback, try the INI-style config
            if "WhatsApp" in self.config:
                whatsapp_section = self.config["WhatsApp"]
                return {
                    "channel_names": whatsapp_section.get("channel_names", ""),
                    "group_names": whatsapp_section.get("group_names", "")
                }
                
            # Return empty config if nothing found
            return {
                "channel_names": "",
                "group_names": ""
            }
        except Exception as e:
            print(f"Error getting WhatsApp config: {e}")
            return {
                "channel_names": "",
                "group_names": ""
            }

    def get_scheduler_config(self) -> dict:
        """
        Retrieves the Scheduler configuration settings.
        :return: A dictionary of Scheduler settings.
        """
        return dict(self.config['Scheduler'])

    def get_general_config(self) -> dict:
        """
        Retrieves the General configuration settings.
        :return: A dictionary of general settings.
        """
        return dict(self.config['General'])

    def update_config(self, section: str, key: str, value: str):
        """
        Updates a specific configuration setting and writes the changes to the config file.
        :param section: The section in the configuration file.
        :param key: The key within the section.
        :param value: The new value to set.
        """
        if section not in self.config:
            self.config[section] = {}
        self.config[section][key] = value

        with open(self.config_file, 'w') as configfile:
            self.config.write(configfile)

    def get_email_config(self) -> dict:
        """
        Retrieves the Email configuration settings.
        :return: A dictionary of Email settings.
        """
        if 'Email' in self.config:
            return dict(self.config['Email'])
        return {}


