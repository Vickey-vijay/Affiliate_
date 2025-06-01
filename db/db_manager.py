from pymongo import MongoClient
from config import MONGO_URI, DB_NAME
from datetime import datetime,time

class DataManager:
    def __init__(self):
        self.client = MongoClient(MONGO_URI)
        self.db = self.client[DB_NAME]
        self.products = self.db["products"]
        # self.published = self.db.published
        self.price_history = self.db.price_history
        self.published_products = self.db["published_products"]  # Add this new collection

    def get_all_products(self):
        return list(self.products.find())

    def insert_product(self, data):
        self.products.insert_one(data)

    def check_login(self, username, password):
        user = self.db["login_info"].find_one({
            "username": username,
            "password": password  
        })
        return user

    def get_total_products(self) -> int:
        return self.products.count_documents({})

    def get_published_product_count(self) -> int:
        return self.products.count_documents({"Publish": True})

    def get_scheduled_products(self) -> int:
        return self.products.count_documents({
            "Publish": False,
            "Publish_time": {"$ne": None}
        })

    def get_total_categories(self) -> int:
        return len(self.products.distinct("product_major_category"))

    def get_products_grouped_by_category(self) -> list[dict]:
        pipeline = [
            {"$group": {"_id": "$product_major_category", "count": {"$sum": 1}}},
            {"$sort": {"count": -1}}
        ]
        return list(self.products.aggregate(pipeline))

    def get_products_by_site(self, site: str) -> list[dict]:
        return list(self.products.find({"product_Affiliate_site": site}))

    def get_unique_values(self, field, query=None):
        if query is None:
            query = {}
        unique_values = self.products.distinct(field, query)
        return [str(val) for val in unique_values if val is not None]

    def get_next_serial_number(self):
        highest = self.products.find_one(sort=[("s_no", -1)])
        if highest and "s_no" in highest and highest["s_no"] is not None:
            try:
                return int(highest["s_no"]) + 1
            except (ValueError, TypeError):
                # Handle case where s_no exists but isn't a valid integer
                return 1
        else:
            return 1

    def product_exists(self, product_id):
        count = self.products.count_documents({"Product_unique_ID": product_id})
        return count > 0

    def get_product_by_id(self, product_id):
        """
        Get a product by its unique ID
        """
        return self.products.find_one({"Product_unique_ID": product_id})

    def get_products(self, query=None):
        if query is None:
            query = {}
        return list(self.products.find(query))

    def add_product(self, product_data):
        try:
            result = self.products.insert_one(product_data)
            return result.acknowledged
        except Exception as e:
            print(f"Error adding product: {str(e)}")
            return False

    def update_product(self, product_id, update_data):
        """
        Update a product in the database and add the updated_date field.
        :param product_id: Unique identifier of the product.
        :param update_data: Dictionary containing fields to update.
        """
        try:
            update_data["updated_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            result = self.products.update_one(
                {"Product_unique_ID": product_id},
                {"$set": update_data}
            )
            return result.modified_count > 0
        except Exception as e:
            print(f"Error updating product: {str(e)}")
            return False

    def delete_product(self, product_id):
        """
        Delete a product from the database.
        :param product_id: Unique identifier of the product.
        """
        try:
            result = self.products.delete_one({"Product_unique_ID": product_id})
            return result.deleted_count > 0
        except Exception as e:
            print(f"Error deleting product: {str(e)}")
            return False

    def save_email_schedule(self, schedule_config):
        """Save an email schedule to the database."""
        try:
            self.db.email_schedules.insert_one(schedule_config)
        except Exception as e:
            print(f"Error saving email schedule: {e}")

    def get_email_schedules(self):
        """Retrieve all email schedules from the database."""
        try:
            return list(self.db.email_schedules.find())
        except Exception as e:
            print(f"Error retrieving email schedules: {e}")
            return []

    def delete_email_schedule(self, schedule_id):
        """Delete an email schedule by its ID."""
        try:
            self.db.email_schedules.delete_one({"_id": schedule_id})
        except Exception as e:
            print(f"Error deleting email schedule: {e}")

    def create_published_product(self, product_data):
        """Create a record in the published products collection"""
        try:
            published_data = {
                "product_id": product_data.get("Product_unique_ID"),
                "product_name": product_data.get("product_name"),
                "publish_date": datetime.now(),
                "published_price": product_data.get("Product_current_price"),
                "product_data": product_data,  # Store full product data for reference
                "publish_channels": [],  # Track where it was published
                "publish_status": "success"
            }
            result = self.published_products.insert_one(published_data)
            return result.acknowledged
        except Exception as e:
            print(f"Error creating published product: {e}")
            return False

    def get_published_products(self, query=None):
        """Get published products with optional query"""
        if query is None:
            query = {}
        return list(self.published_products.find(query))

    def get_last_published_price(self, product_id):
        """Get the last published price for a product"""
        last_published = self.published_products.find_one(
            {"product_id": product_id},
            sort=[("publish_date", -1)]
        )
        return last_published.get("published_price") if last_published else None

    def reset_publish_status(self, product_id):
        """Reset publish status after successful publishing"""
        self.products.update_one(
            {"Product_unique_ID": product_id},
            {
                "$set": {
                    "Publish": False,
                    "Publish_time": None,
                    "last_published_price": "$Product_current_price",
                    "last_published_date": datetime.now()
                }
            }
        )

    def save_monitor_schedule(self, schedule_config):
        """Save monitor schedule configuration to database"""
        try:
            # Convert time objects to strings before saving
            daily_times = []
            for t in schedule_config.get("daily_times", []):
                if isinstance(t, time):
                    daily_times.append(t.strftime("%H:%M"))
                elif isinstance(t, str):
                    daily_times.append(t)
                
            self.db.monitor_schedules.update_one(
                {"_id": "current"},
                {"$set": {
                    "active": True,
                    "type": schedule_config["type"],
                    "hours": schedule_config.get("hours", 0),
                    "minutes": schedule_config.get("minutes", 0),
                    "daily_times": daily_times,
                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "sites": schedule_config.get("sites", [])
                }},
                upsert=True
            )
        except Exception as e:
            print(f"Error saving schedule: {e}")

    def get_monitor_schedule(self):
        """Retrieve saved monitor schedule"""
        try:
            schedule = self.db.monitor_schedules.find_one({"_id": "current"})
            if schedule:
                if schedule.get("daily_times"):
                    schedule["daily_times"] = [datetime.strptime(t, "%H:%M").time() for t in schedule["daily_times"]]
            return schedule
        except Exception as e:
            print(f"Error retrieving schedule: {e}")
            return None

    def save_notification_schedule(self, schedule_config):
        """Save notification schedule to database"""
        try:
            self.db.notification_schedules.update_one(
                {"_id": "current"},
                {"$set": schedule_config},
                upsert=True
            )
        except Exception as e:
            print(f"Error saving notification schedule: {e}")
            raise e

    def get_notification_schedule(self):
        """Retrieve current notification schedule"""
        try:
            return self.db.notification_schedules.find_one({"_id": "current"})
        except Exception as e:
            print(f"Error retrieving notification schedule: {e}")
            return None

    def get_auto_publish_config(self):
        """Get automatic publishing configuration"""
        config = self.db.auto_publish_config.find_one({}) or {}
        return config

    def save_auto_publish_config(self, config):
        """Save automatic publishing configuration"""
        if self.db.auto_publish_config.count_documents({}) > 0:
            self.db.auto_publish_config.update_one({}, {"$set": config})
        else:
            self.db.auto_publish_config.insert_one(config)
