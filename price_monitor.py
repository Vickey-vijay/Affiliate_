import pymongo
from datetime import datetime
from monitors.amazon_monitor import AmazonIndiaMonitor

class PriceMonitor:
    """
    Class responsible for monitoring product prices, comparing them with new data,
    and determining whether to update the database.
    """
    def __init__(self, products_collection: pymongo.collection.Collection, amazon_config=None):
        """
        Initialize the PriceMonitor with a MongoDB collection for products.
        :param products_collection: MongoDB collection containing product details.
        :param amazon_config: Amazon configuration settings (optional).
        """
        self.products_collection = products_collection
        self.amazon_config = amazon_config
        self.amazon_monitor = AmazonIndiaMonitor()

    def check_price_update(self, product: dict, new_price: float) -> bool:
        """
        Check if price should be updated based on:
        - Lower than current price
        - Lower than buy box price
        - Lower than last published price (if exists)
        """
        try:
            current_price = float(product.get("Product_current_price", 0))
            buy_box_price = float(product.get("Product_Buy_box_price", 0))
            last_published_price = float(product.get("last_published_price", 0))
            
            if new_price < current_price and new_price < buy_box_price:
                # Also check against last published price if it exists
                if last_published_price and new_price < last_published_price:
                    return True
                elif not last_published_price:
                    return True
                    
            return False
            
        except (ValueError, TypeError):
            return False

    def update_price(self, product_id: str, new_price: float):
        """
        Update the product's current price in the database and log the change.
        
        :param product_id: Unique identifier of the product.
        :param new_price: New product price to update.
        """
        self.products_collection.update_one(
            {"Product_unique_ID": product_id},
            {"$set": {
                "Product_current_price": new_price,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }}
        )
        print(f"[INFO] Updated product {product_id} with new price: {new_price}")

    def monitor_all_products(self, fetch_price_callback):
        """
        Monitors all products in the collection, fetches new prices using the provided callback,
        and updates the database if the new price meets the update criteria.
        
        :param fetch_price_callback: A callback function that takes a product dict and returns the new price as a float.
        """
        products = list(self.products_collection.find({}))
        for product in products:
            new_price = fetch_price_callback(product)
            if new_price is None:
                continue
            if self.check_price_update(product, new_price):
                self.update_price(product.get("Product_unique_ID"), new_price)
            else:
                print(f"[INFO] No update required for product {product.get('Product_unique_ID')}")

    def fetch_new_price(self, product: dict) -> float:
        """
        Placeholder method to fetch a new price for the product.
        In production, integrate this with AmazonScraper or another service.
        For now, it simulates a 5% price drop.
        
        :param product: A dictionary representing the product record.
        :return: The new price as a float.
        """
        try:
            current_price = float(product.get("Product_current_price", 0))
            new_price = current_price * 0.95
            return round(new_price, 2)
        except (ValueError, TypeError):
            return None

    def monitor_products(self):
        """
        Monitor all products, fetch new data, and update the database.
        """
        products = self.products_collection.find({})
        product_ids = [product["Product_unique_ID"] for product in products if "Product_unique_ID" in product]

        self.amazon_monitor.run(product_ids)