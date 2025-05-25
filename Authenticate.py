# Authenticate.py
import hashlib
class LoginManager:
    """
    Handles user authentication by verifying credentials against the MongoDB collection.
    """
    def __init__(self, collection):
        """
        Initialize with a MongoDB collection that stores user login details.
        :param collection: MongoDB collection with user credentials.
        """
        self.collection = collection

    def hash_password(self, password: str) -> str:
        """Hash a password for storing."""
        return hashlib.sha256(password.encode()).hexdigest()

    def authenticate(self, username: str, password: str) -> bool:
        """
        Checks if a user exists with the provided username and hashed password.
        """
        hashed_password = self.hash_password(password)
        user = self.collection.find_one({"username": username, "password": hashed_password})
        return user is not None