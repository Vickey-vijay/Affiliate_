import os
import time
import requests
import shutil
from datetime import datetime
from db.db_manager import DataManager
from paapi5_python_sdk.api.default_api import DefaultApi
from paapi5_python_sdk.models.condition import Condition
from paapi5_python_sdk.models.get_items_request import GetItemsRequest
from paapi5_python_sdk.models.get_items_resource import GetItemsResource
from paapi5_python_sdk.models.partner_type import PartnerType
from paapi5_python_sdk.rest import ApiException
from colorama import Fore, Style, init
import streamlit as st
from config_manager import ConfigManager
import traceback



init(autoreset=True)

class AmazonIndiaMonitor:
    def __init__(self):
        self.db = DataManager()
        self.temp_image_folder = "temp"
        os.makedirs(self.temp_image_folder, exist_ok=True)

        # Load Amazon API credentials dynamically using ConfigManager
        config_manager = ConfigManager()
        amazon_config = config_manager.get_amazon_config()

        self.access_key = amazon_config.get("access_key", "")
        self.secret_key = amazon_config.get("secret_key", "")
        self.partner_tag = amazon_config.get("partner_tag", "")
        self.host = "webservices.amazon.in"  # Correct host for Amazon India
        self.region = "eu-west-1"  # Correct region for Amazon India

        # Validate credentials
        if not all([self.access_key, self.secret_key, self.partner_tag]):
            raise ValueError("Amazon API credentials are missing. Please configure them in the configuration file.")

    def fetch_product_data(self, product_ids):
        """
        Fetch product data from Amazon using the Product Advertising API in batches of 10.
        Download images for all products and include the local image path in the product data.
        :param product_ids: List of product ASINs to fetch data for.
        :return: Dictionary of product data keyed by ASIN.
        """
        # Initialize the DefaultApi directly with correct credentials
        api = DefaultApi(
            access_key=self.access_key,
            secret_key=self.secret_key,
            host=self.host,  # Correct host
            region=self.region  # Correct region
        )
        print(f"Using credentials - Access Key: {self.access_key[:5]}..., Secret Key: {self.secret_key[:5]}..., "
              f"Partner Tag: {self.partner_tag}, Region: {self.region}, Host: {self.host}")

        resources = [
            GetItemsResource.ITEMINFO_TITLE,
            GetItemsResource.OFFERS_LISTINGS_PRICE,
            GetItemsResource.IMAGES_PRIMARY_LARGE
        ]

        product_data = {}
        for i in range(0, len(product_ids), 10):  # Batch size of 10
            batch = product_ids[i:i + 10]
            try:
                # Create request
                request = GetItemsRequest(
                    partner_tag=self.partner_tag,
                    partner_type=PartnerType.ASSOCIATES,
                    marketplace="www.amazon.in",
                    condition=Condition.NEW,
                    item_ids=batch,
                    resources=resources
                )

                # Send request
                response = api.get_items(request)

                # Process successful response
                if response:
                    # Check if response is a dict (JSON response) or has items_result attribute (SDK response)
                    if isinstance(response, dict) and 'ItemsResult' in response:
                        items_result = response['ItemsResult']
                        items = items_result['Items'] if isinstance(items_result, dict) and 'Items' in items_result else []
                        for item in items:
                            asin = item.get('ASIN')
                            title = item.get('ItemInfo', {}).get('Title', {}).get('DisplayValue')
                            price = item.get('Offers', {}).get('Listings', [{}])[0].get('Price', {}).get('Amount')
                            buy_box_price = item.get('Offers', {}).get('Listings', [{}])[0].get('Price', {}).get('Amount')
                            image_url = item.get('Images', {}).get('Primary', {}).get('Large', {}).get('URL')
                            # Download the product image
                            image_path = self.download_image(image_url, asin) if image_url else None
                            
                            product_data[asin] = {
                                "title": title,
                                "price": price,
                                "buy_box_price": buy_box_price,
                                "image_url": image_url,
                                "image_path": image_path  # Include the local image path
                            }
                    # SDK response object - check correctly for the response type
                    elif hasattr(response, 'items_result'):
                        items_result = getattr(response, 'items_result', None)
                        if items_result is not None and hasattr(items_result, 'items') and items_result.items:
                            for item in items_result.items:
                                asin = getattr(item, 'asin', None)
                                title = getattr(getattr(getattr(item, 'item_info', None), 'title', None), 'display_value', None)
                                price = getattr(getattr(getattr(getattr(item, 'offers', None), 'listings', [None])[0], 'price', None), 'amount', None) if getattr(item, 'offers', None) and getattr(item.offers, 'listings', None) else None
                                buy_box_price = price
                                image_url = getattr(getattr(getattr(getattr(item, 'images', None), 'primary', None), 'large', None), 'url', None)
                                # Download the product image
                                image_path = self.download_image(image_url, asin) if image_url else None

                                product_data[asin] = {
                                    "title": title,
                                    "price": price,
                                    "buy_box_price": buy_box_price,
                                    "image_url": image_url,
                                    "image_path": image_path  # Include the local image path
                                }

                                if image_path:
                                    print(f"✅ Image downloaded and saved for ASIN: {asin}")
                                else:
                                    print(f"❌ Failed to download image for ASIN: {asin}")

                    print(f"[AmazonAPI] Successfully fetched data for batch: {batch}")
                else:
                    print(f"[AmazonAPI] No item results found in response for batch: {batch}")

            except ApiException as e:
                print(f"[AmazonAPI] API Exception for batch {batch}: {e}")
                print(f"Response body: {e.body if hasattr(e, 'body') else 'No response body'}")
            except Exception as e:
                print(f"[AmazonAPI] Error fetching data for batch {batch}: {e}")
                traceback.print_exc()

            # Respect Amazon's rate limits
            time.sleep(2)  # Enforce a 2-second delay between requests

        return product_data
    
    def fetch_product_data_boto(self, product_ids):
        """
        Alternative implementation using boto3 for request signing.
        :param product_ids: List of product ASINs to fetch data for.
        :return: Dictionary of product data keyed by ASIN.
        """
        import boto3
        from botocore.auth import SigV4Auth
        from botocore.awsrequest import AWSRequest
        import json
        
        print(f"Using boto3 method with credentials - Access Key: {self.access_key[:5]}..., Partner Tag: {self.partner_tag}")
        
        # Create a session with your credentials
        session = boto3.Session(
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region
        )
        
        product_data = {}
        for i in range(0, len(product_ids), 10):  # Batch size of 10
            batch = product_ids[i:i + 10]
            
            # Construct the request
            url = f"https://{self.host}/paapi5/getitems"
            headers = {
                'content-encoding': 'amz-1.0',
                'content-type': 'application/json; charset=utf-8',
                'host': self.host
            }
            
            payload = {
                "ItemIds": batch,
                "PartnerTag": self.partner_tag,
                "PartnerType": "Associates",
                "Marketplace": "www.amazon.in",
                "Resources": [
                    "ItemInfo.Title",
                    "Offers.Listings.Price",
                    "Images.Primary.Large"
                ]
            }
            
            try:
                # Create and sign the request
                request = AWSRequest(method='POST', url=url, data=json.dumps(payload), headers=headers)
                SigV4Auth(session.get_credentials(), 'paapi5', self.region).add_auth(request)
                
                # Send the signed request
                response = requests.post(
                    url,
                    headers=dict(request.headers),
                    data=request.data
                )
                
                print(f"Status code: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    items = data.get('ItemsResult', {}).get('Items', [])
                    for item in items:
                        asin = item.get('ASIN')
                        if asin:
                            product_data[asin] = {
                                "title": item.get('ItemInfo', {}).get('Title', {}).get('DisplayValue'),
                                "price": item.get('Offers', {}).get('Listings', [{}])[0].get('Price', {}).get('Amount'),
                                "buy_box_price": item.get('Offers', {}).get('Listings', [{}])[0].get('Price', {}).get('Amount'),
                                "image_url": item.get('Images', {}).get('Primary', {}).get('Large', {}).get('URL')
                            }
                    print(f"[AmazonAPI] Successfully fetched data for batch: {batch}")
                else:
                    print(f"[AmazonAPI] Error response: {response.status_code} - {response.text}")
                    
            except Exception as e:
                import traceback
                print(f"[AmazonAPI] Error fetching data for batch {batch}: {e}")
                traceback.print_exc()
                
            time.sleep(2)  # Respect Amazon's rate limits
            
        return product_data


    def download_image(self, url, asin):
        """
        Download the product image to the temp folder only if it doesn't already exist.
        :param url: Image URL.
        :param asin: Product ASIN.
        :return: Local path to the downloaded image.
        """
        if not url:
            print(f"[AmazonIN] No image URL provided for ASIN: {asin}")
            return None

        image_path = os.path.join(self.temp_image_folder, f"{asin}.jpg")
        
        # Check if image already exists
        if os.path.exists(image_path):
            print(f"[AmazonIN] Image already exists for ASIN: {asin}, skipping download")
            return image_path
            
        # Download only if image doesn't exist
        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()
            with open(image_path, "wb") as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(f"[AmazonIN] Image downloaded for ASIN: {asin}")
            return image_path
        except Exception as e:
            print(f"[AmazonIN] Error downloading image for ASIN {asin}: {e}")
            return None

    def clean_temp_folder(self):
        """
        Delete all files in the temp folder to free up storage.
        """
        try:
            shutil.rmtree(self.temp_image_folder)
            os.makedirs(self.temp_image_folder, exist_ok=True)
            print("[AmazonIN] Temp folder cleaned.")
        except Exception as e:
            print(f"[AmazonIN] Error cleaning temp folder: {e}")

    def update_product_data(self, product_data):
        """
        Update the product data in the database without storing image paths.
        :param product_data: Dictionary containing product details.
        """
        for asin, data in product_data.items():
            update_data = {
                "Product_current_price": data.get("price"),
                "Product_Buy_box_price": data.get("buy_box_price"),
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "updated_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            self.db.update_product(asin, update_data)
            print(f"[AmazonIN] Updated product {asin} in the database.")

    def run(self, product_ids):
        """
        Fetch product data, process it (download images, log progress), and update the database.
        :param product_ids: List of product ASINs to process.
        """
        print("[AmazonIN] Starting product data update...")
        product_data = self.fetch_product_data(product_ids)  # Fetch product data (unchanged)

        if not product_data:
            print("[AmazonIN] No product data fetched. Exiting.")
            return

        # Process the fetched product data
        self.process_product_data(product_data)

        print("[AmazonIN] Product data update completed.")

    def process_product_data(self, product_data):
        """
        Process the fetched product data by downloading images if needed, logging progress, and updating the database.
        :param product_data: Dictionary containing product details keyed by ASIN.
        """
        for asin, data in product_data.items():
            # Check if product already has an image path in the database
            existing_product = self.db.products.find_one({"Product_unique_ID": asin})
            existing_image_path = existing_product.get("Product_image_path") if existing_product else None
            
            # If there's already an image path and the file exists, use it
            if existing_image_path and os.path.exists(existing_image_path):
                print(f"✅ Using existing image for ASIN: {asin}")
                data["image_path"] = existing_image_path
            else:
                # Download the product image only if needed
                image_path = self.download_image(data.get("image_url"), asin)
                if image_path:
                    data["image_path"] = image_path
                    print(f"✅ Image fetched and saved for ASIN: {asin}")
                else:
                    print(f"❌ Failed to fetch image for ASIN: {asin}")

            # Update the product data in the database
            self.update_product_data_entry(asin, data)

    def update_product_data_entry(self, asin, data):
        """
        Update the product data in the database for a single product.
        :param asin: The ASIN of the product.
        :param data: The product data dictionary.
        """
        update_data = {
            "Product_current_price": data.get("price"),
            "Product_Buy_box_price": data.get("buy_box_price"),
            "Product_image_path": data.get("image_path"),
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        try:
            self.db.update_product(asin, update_data)
            print(f"[AmazonIN] Updated product {asin} in the database.")
        except Exception as e:
            print(f"[AmazonIN] Error updating product {asin} in the database: {e}")

    def log_request_response(self, request, response):
        """
        Log the request and response in a readable format with color coding.
        """
        print(f"\n{Style.BRIGHT}--- Request ---")
        print(f"{Fore.CYAN}Request Data: {request}")
        print(f"\n{Style.BRIGHT}--- Response ---")
        if response.get("title"):
            print(f"{Fore.GREEN}Response Data: {response}")
        else:
            print(f"{Fore.RED}Response Data: {response}")
        print("\n")




