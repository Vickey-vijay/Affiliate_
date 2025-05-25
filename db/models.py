class Product:
    def __init__(self, asin, title, price, image_url, added_on):
        self.asin = asin
        self.title = title
        self.price = price
        self.image_url = image_url
        self.added_on = added_on

class User:
    def __init__(self, username, password, role="user"):
        self.username = username
        self.password = password
        self.role = role
