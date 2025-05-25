from db.db_manager import DBManager

class PriceTracker:
    def __init__(self):
        self.db = DBManager()

    def check_price_changes(self):
        products = self.db.get_products()
