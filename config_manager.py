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
        """
        Retrieves the Telegram configuration settings.
        :return: A dictionary of Telegram settings.
        """
        return {
            "bot_token": self.config["Telegram"].get("bot_token"),
            "channel_name": self.config["Telegram"].get("channel_name")  
        }

    
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


