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

        # Fixed resources list - removed invalid resource OFFERSV2_LISTINGS_SAVINGBASIS
        resources = [
            GetItemsResource.ITEMINFO_TITLE,
            GetItemsResource.ITEMINFO_BYLINEINFO,
            GetItemsResource.ITEMINFO_CONTENTINFO,
            GetItemsResource.OFFERS_LISTINGS_PRICE,
            GetItemsResource.OFFERS_LISTINGS_SAVINGBASIS,  # Critical for MRP
            GetItemsResource.OFFERS_SUMMARIES_LOWESTPRICE,
            GetItemsResource.OFFERS_SUMMARIES_HIGHESTPRICE,
            GetItemsResource.OFFERSV2_LISTINGS_PRICE,      # Better MRP source
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
                        # Safe access to items with default empty list
                        items = items_result.get('Items', []) if isinstance(items_result, dict) else []
                        
                        for item in items:
                            asin = item.get('ASIN')
                            # Safe access to nested dictionaries
                            item_info = item.get('ItemInfo', {})
                            title = item_info.get('Title', {}).get('DisplayValue') if isinstance(item_info, dict) else None
                            
                            # Extract all the price related data
                            offers = item.get('Offers', {})
                            listings = offers.get('Listings', []) if isinstance(offers, dict) else []
                            price = None
                            buy_box_price = None
                            mrp = None
                            
                            if listings and len(listings) > 0:
                                # Get the first listing (usually the buy box winner)
                                listing = listings[0]
                                price_info = listing.get('Price', {})
                                price = price_info.get('Amount') if isinstance(price_info, dict) else None
                                buy_box_price = price
                                
                                # Proper extraction of MRP from SavingBasis
                                saving_basis = listing.get('SavingBasis', {})
                                if isinstance(saving_basis, dict):
                                    if saving_basis.get('PriceType') == 'LIST_PRICE':
                                        mrp = saving_basis.get('Amount')
                                        print(f"[AmazonAPI] Found MRP in Offers.Listings.SavingBasis: {mrp} for ASIN {asin}")
                                
                                # Try to find MRP in Savings data
                                if mrp is None and isinstance(price_info, dict) and 'Savings' in price_info:
                                    savings = price_info['Savings']
                                    if isinstance(savings, dict):
                                        if 'Amount' in savings and 'Percentage' in savings and savings['Percentage'] > 0:
                                            # Calculate MRP from savings
                                            savings_amount = savings['Amount']
                                            savings_percentage = savings['Percentage']
                                            if price is not None and savings_percentage > 0 and savings_percentage < 100:
                                                calculated_mrp = price + savings_amount
                                                mrp = calculated_mrp
                                                print(f"[AmazonAPI] Calculated MRP from Savings: {mrp} for ASIN {asin}")
                            
                            # If MRP still not found, try OffersV2 (better structured data)
                            if mrp is None:
                                offers_v2 = item.get('OffersV2', {})
                                if isinstance(offers_v2, dict):
                                    listings_v2 = offers_v2.get('Listings', [])
                                    
                                    if listings_v2 and len(listings_v2) > 0:
                                        listing_v2 = listings_v2[0]
                                        price_info = listing_v2.get('Price', {})
                                        
                                        # Extract from SavingBasis in OffersV2
                                        if isinstance(price_info, dict):
                                            saving_basis = price_info.get('SavingBasis', {})
                                            if isinstance(saving_basis, dict):
                                                if saving_basis.get('SavingBasisType') == 'LIST_PRICE':
                                                    money = saving_basis.get('Money', {})
                                                    if isinstance(money, dict):
                                                        mrp = money.get('Amount')
                                                        print(f"[AmazonAPI] Found MRP in OffersV2.Listings.Price.SavingBasis: {mrp} for ASIN {asin}")
                            
                            # Get image URL
                            images = item.get('Images', {})
                            primary = images.get('Primary', {}) if isinstance(images, dict) else {}
                            large = primary.get('Large', {}) if isinstance(primary, dict) else {}
                            image_url = large.get('URL') if isinstance(large, dict) else None
                            
                            # Download the product image
                            image_path = self.download_image(image_url, asin) if image_url else None
                            
                            # Create the product data without any fake MRP calculations
                            product_data[asin] = {
                                "title": title,
                                "price": price,
                                "buy_box_price": buy_box_price,
                                "mrp": mrp,  # Store the actual MRP without any fallback calculations
                                "image_url": image_url,
                                "image_path": image_path  # Include the local image path
                            }
                            
                            # Log the extracted MRP for verification
                            print(f"[AmazonAPI] Product: {asin}, Title: {title}, Price: {price}, MRP: {mrp}")
                    
                    # SDK response object handling
                    elif hasattr(response, 'items_result'):
                        items_result = getattr(response, 'items_result', None)
                        if items_result is not None and hasattr(items_result, 'items'):
                            for item in items_result.items:
                                asin = getattr(item, 'asin', None)
                                title = None
                                if hasattr(item, 'item_info') and hasattr(item.item_info, 'title'):
                                    title = getattr(item.item_info.title, 'display_value', None)
                                
                                # Extract price-related data using proper SDK object navigation
                                price = None
                                buy_box_price = None
                                mrp = None
                                
                                # Get listings from Offers
                                if hasattr(item, 'offers') and hasattr(item.offers, 'listings') and item.offers.listings:
                                    listing = item.offers.listings[0]
                                    
                                    # Extract price
                                    if hasattr(listing, 'price') and hasattr(listing.price, 'amount'):
                                        price = listing.price.amount
                                        buy_box_price = price
                                
                                    # Extract MRP from SavingBasis in Offers
                                    if hasattr(listing, 'saving_basis'):
                                        saving_basis = listing.saving_basis
                                        if hasattr(saving_basis, 'price_type') and saving_basis.price_type == 'LIST_PRICE':
                                            if hasattr(saving_basis, 'amount'):
                                                mrp = saving_basis.amount
                                                print(f"[AmazonAPI] Found MRP in SDK Offers.Listings.SavingBasis: {mrp} for ASIN {asin}")
                                
                                    # Try to extract MRP from Savings data
                                    if mrp is None and hasattr(listing, 'price') and hasattr(listing.price, 'savings'):
                                        savings = listing.price.savings
                                        if hasattr(savings, 'amount') and hasattr(savings, 'percentage'):
                                            if price is not None and savings.percentage > 0 and savings.percentage < 100:
                                                calculated_mrp = price + savings.amount
                                                mrp = calculated_mrp
                                                print(f"[AmazonAPI] Calculated MRP from SDK Savings: {mrp} for ASIN {asin}")
                                
                                # Try OffersV2 if MRP still not found
                                if mrp is None and hasattr(item, 'offers_v2') and hasattr(item.offers_v2, 'listings') and item.offers_v2.listings:
                                    listing = item.offers_v2.listings[0]
                                    if hasattr(listing, 'price') and hasattr(listing.price, 'saving_basis'):
                                        saving_basis = listing.price.saving_basis
                                        if hasattr(saving_basis, 'saving_basis_type') and saving_basis.saving_basis_type == 'LIST_PRICE':
                                            if hasattr(saving_basis, 'money') and hasattr(saving_basis.money, 'amount'):
                                                mrp = saving_basis.money.amount
                                                print(f"[AmazonAPI] Found MRP in SDK OffersV2.Listings.Price.SavingBasis: {mrp} for ASIN {asin}")
                                
                                # Get image URL
                                image_url = None
                                if hasattr(item, 'images') and hasattr(item.images, 'primary') and hasattr(item.images.primary, 'large'):
                                    image_url = getattr(item.images.primary.large, 'url', None)
                                
                                # Download image
                                image_path = self.download_image(image_url, asin) if image_url else None
                                
                                # Create product data without fake MRP calculations
                                product_data[asin] = {
                                    "title": title,
                                    "price": price,
                                    "buy_box_price": buy_box_price,
                                    "mrp": mrp,  # Store only the actual MRP from Amazon
                                    "image_url": image_url,
                                    "image_path": image_path
                                }
                                
                                # Log the extracted MRP for verification
                                print(f"[AmazonAPI] SDK Product: {asin}, Title: {title}, Price: {price}, MRP: {mrp}")
                    
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
                "Product_MRP": data.get("mrp", data.get("price") * 1.2),  # Added MRP with fallback
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
        mrp = data.get("mrp")
        price = data.get("price")
        
        # Only if MRP is completely missing, we might need a fallback
        # But let's log this situation so you can investigate further
        if mrp is None and price is not None:
            print(f"[AmazonAPI] ⚠️ WARNING: No MRP found for {asin}. Using current product database MRP if available.")
            # Check if product exists in database and has an MRP
            existing_product = self.db.products.find_one({"Product_unique_ID": asin})
            if existing_product and existing_product.get("Product_MRP") is not None:
                mrp = existing_product.get("Product_MRP")
                print(f"[AmazonAPI] Using existing MRP from database: {mrp}")
            else:
                # Only use calculation as last resort, but log it clearly
                mrp = price * 1.2
                print(f"[AmazonAPI] ⚠️ CAUTION: Using calculated MRP ({mrp}) as no real MRP available for {asin}")
        
        update_data = {
            "Product_current_price": price,
            "Product_Buy_box_price": data.get("buy_box_price"),
            "Product_image_path": data.get("image_path"),
            "Product_MRP": mrp,
            "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

        try:
            self.db.update_product(asin, update_data)
            print(f"[AmazonIN] Updated product {asin} in the database with MRP: {mrp}")
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
 



