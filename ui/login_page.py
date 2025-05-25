import streamlit as st
from pymongo import MongoClient
from config import MONGO_URI, DB_NAME
import json
import os

REMEMBER_ME_FILE = "remember_me.json"

def save_remember_me(username):
    """Save the username to a file for persistent login."""
    with open(REMEMBER_ME_FILE, "w") as f:
        json.dump({"username": username}, f)

def load_remember_me():
    """Load the username from the file if it exists."""
    if os.path.exists(REMEMBER_ME_FILE):
        with open(REMEMBER_ME_FILE, "r") as f:
            data = json.load(f)
            return data.get("username")
    return None

def clear_remember_me():
    """Clear the saved username."""
    if os.path.exists(REMEMBER_ME_FILE):
        os.remove(REMEMBER_ME_FILE)

@st.cache_data
def load_cookies_from_txt(file_path="utils/web.whatsapp.com_cookies.txt"):
    """
    Load cookies from a .txt file and return them as a dictionary.
    """
    cookies = {}
    try:
        with open(file_path, "r") as f:
            for line in f:
                if not line.startswith("#") and line.strip():
                    parts = line.strip().split("\t")
                    if len(parts) >= 7:
                        cookies[parts[5]] = parts[6]
        return cookies
    except Exception as e:
        st.error(f"Failed to load cookies: {e}")
        return {}

def show_login():
    st.title("Login")

    remembered_username = load_remember_me()
    if remembered_username:
        st.session_state["logged_in"] = True
        st.session_state["username"] = remembered_username
        st.success(f"Welcome back, {remembered_username}!")
        st.rerun()

    username = st.text_input("Username", value=remembered_username or "")
    password = st.text_input("Password", type="password")
    remember_me = st.checkbox("Remember Me", value=bool(remembered_username))

    if st.button("🔐 Login"):
        client = MongoClient(MONGO_URI)
        db = client[DB_NAME]
        user = db.login_info.find_one({"username": username, "password": password})

        if user:
            st.success("Login successful!")
            st.session_state["logged_in"] = True
            st.session_state["username"] = username

            if remember_me:
                save_remember_me(username)
            else:
                clear_remember_me()

            st.rerun()
        else:
            st.error("Invalid credentials")
