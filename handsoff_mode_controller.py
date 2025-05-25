from datetime import datetime, timedelta
from pymongo.collection import Collection


class HandsOffModeController:
    def __init__(self, products_collection: Collection, published_collection: Collection, notification_publisher):
        self.products_collection = products_collection
        self.published_collection = published_collection
        self.notification_publisher = notification_publisher

    def run_hands_off(self):
        """
        Executes the automated hands-off publishing logic.
        """
        print("🔁 Running Hands-Off Mode Check...")

        all_products = list(self.products_collection.find({}))
        now = datetime.now()

        for product in all_products:
            product_id = str(product.get("_id"))
            title = product.get("product_name", "Unnamed Product")
            current_price = product.get("Product_current_price")
            buy_box_price = product.get("Product_Buy_box_price")
            last_published_price = self._get_last_published_price(product_id)

            if not current_price or not buy_box_price:
                continue

            if current_price >= buy_box_price:
                print(f"❌ Skipping {title}: Current price is not lower than buy box price.")
                continue

            last_published = self.published_collection.find_one(
                {"product_id": product_id},
                sort=[("timestamp", -1)]
            )

            if not last_published:
                print(f"✅ Publishing {title}: Product has never been published.")
                self._publish_product(product)
                continue

            last_published_time = last_published["timestamp"]
            four_days_ago = now - timedelta(days=4)

            if last_published_time >= four_days_ago:
                if current_price < last_published["price"]:
                    print(f"✅ Publishing {title}: Current price is lower than last published price.")
                    self._publish_product(product)
                else:
                    print(f"❌ Skipping {title}: Current price is not lower than last published price.")
            else:
                print(f"✅ Publishing {title}: Last published more than 4 days ago.")
                self._publish_product(product)

    def _get_last_published_price(self, product_id):
        """
        Returns the most recent published price of a product.
        """
        record = self.published_collection.find_one(
            {"product_id": product_id},
            sort=[("timestamp", -1)]
        )
        return record["price"] if record else None

    def _publish_product(self, product):
        """
        Handles publishing a product via the notification system
        and logs the publication in published_collection.
        """
        self.notification_publisher.publish(product)

        self.published_collection.insert_one({
            "product_id": str(product["_id"]),
            "title": product.get("product_name"),
            "price": product.get("Product_current_price"),
            "timestamp": datetime.now()
        })

        print(f"✅ Published (Hands-Off): {product.get('product_name')} @ ₹{product.get('Product_current_price')}")

    def process_and_publish(self):
        """
        Process and publish products in hands-off mode.
        This is an alias for run_hands_off to match the function name used in scheduler.
        """
        self.run_hands_off()

