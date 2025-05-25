import json
import streamlit as st

@st.cache_data
def load_secrets(path="secrets.json"):
    with open(path, "r") as f:
        return json.load(f)

SECRETS = load_secrets()
ACCESS_KEY = SECRETS["access_key"]
SECRET_KEY = SECRETS["secret_key"]
ASSOCIATE_TAG = SECRETS["associate_tag"]
REGION = SECRETS["region"]

MONGO_URI = SECRETS["mongo_uri"]  # Ensure this key exists in secrets.json
DB_NAME = SECRETS["db_name"]