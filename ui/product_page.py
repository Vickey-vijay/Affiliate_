import os
import streamlit as st
import pandas as pd
from db.db_manager import DataManager
from datetime import datetime, timedelta
import logging
from notification_publisher import NotificationPublisher  # Add this import

class ProductPage:
    def __init__(self, config):
        self.config = config
        self.config_manager = config  # Add this line to make config_manager available
        self.db = DataManager()
        self.notification_publisher = NotificationPublisher(config)  # This stays the same
    
    def render(self):
        st.title("Manage Products")
        
        tabs = st.tabs([
            "View Products", "Add Product", "Bulk Add Products", 
            "Edit Product", "Delete Products", "Manage Publishing",
            "Published Products"  # New tab
        ])
        
    
        with tabs[0]:
            self.render_view_products()
        with tabs[1]:
            self.render_add_product()
        with tabs[2]:
            self.render_bulk_add_products()
        with tabs[3]:
            self.render_edit_product()
        with tabs[4]:
            self.render_delete_products()
        with tabs[5]:
            self.render_manage_publishing()
        with tabs[6]:  # New tab content
            self.render_published_products()

    def parse_datetime(self, x):
        """Helper function to parse datetime strings"""
        if pd.isna(x) or not isinstance(x, str):
            return None
        try:
            # Try different datetime formats
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(x, fmt)
                except ValueError:
                    continue
            return None
        except (ValueError, TypeError):
            return None

    def render_view_products(self):
        st.header("View Products")

        products = self.db.get_all_products()
        if not products:
            st.warning("No products available.")
            return

        df = pd.DataFrame(products)

        with st.expander("Filters", expanded=True):
            st.info("Use the filters below to refine the product list.")

            search_term = st.text_input("Search by Product Name", key="view_search")

            filter_by_category = st.checkbox("Filter by Category", key="view_filter_category")
            if filter_by_category:
                major_categories = self.db.get_unique_values("product_major_category")
                selected_major = st.multiselect("Major Category", 
                                              options=major_categories,
                                              key="view_major_cat")
                if selected_major:
                    df = df[df["product_major_category"].isin(selected_major)]

                    if not df.empty:
                        minor_categories = self.db.get_unique_values(
                            "product_minor_category", 
                            {"product_major_category": {"$in": selected_major}}
                        )
                        selected_minor = st.multiselect("Minor Category", 
                                                      options=minor_categories,
                                                      key="view_minor_cat")
                        if selected_minor:
                            df = df[df["product_minor_category"].isin(selected_minor)]

            filter_recent_price_changes = st.checkbox("Recent Changes in Price", 
                                                    key="view_recent_changes")
            if filter_recent_price_changes:
                col1, col2 = st.columns(2)
                with col1:
                    start_date = st.date_input("Start Date", 
                                              key="view_price_change_start_date")
                with col2:
                    end_date = st.date_input("End Date", 
                                            key="view_price_change_end_date")
                
                # Safe handling of date values from st.date_input()
                start_date_value = start_date[0] if isinstance(start_date, tuple) and len(start_date) > 0 else start_date
                end_date_value = end_date[0] if isinstance(end_date, tuple) and len(end_date) > 0 else end_date
                
                if start_date_value and end_date_value:
                    if start_date_value <= end_date_value:
                        df = df[df["updated_date"].apply(lambda x: (
                            (dt := self.parse_datetime(x)) is not None and start_date_value <= dt.date() <= end_date_value
                        ))]
                    else:
                        st.error("End date must be after start date")

            filter_published_last_4_days = st.checkbox("Published in the Last 4 Days",
                                                     key="view_published_4_days")
            if filter_published_last_4_days:
                four_days_ago = datetime.now() - timedelta(days=4)
                df = df[df["Publish_time"].apply(lambda x: (
                    (dt := self.parse_datetime(x)) is not None and dt >= four_days_ago
                ))]

            filter_never_published = st.checkbox("Never Published",
                                              key="view_never_published")
            if filter_never_published:
                df = df[df["Publish"] == False]

            filter_price_less_than_buy_box = st.checkbox("Current Price < Buy Box Price",
                                                       key="view_price_less_buybox")
            if filter_price_less_than_buy_box:
                df = df[df["Product_current_price"] < df["Product_Buy_box_price"]]

            filter_price_less_than_last_published = st.checkbox("Current Price < Last Published Price",
                                                              key="view_price_less_published")
            if filter_price_less_than_last_published:
                df = df[df["Product_current_price"] < df["Product_lowest_price"]]

            if search_term:
                df = df[df["product_name"].str.contains(search_term, case=False, na=False)]

            # Price filters with unique keys
            if st.checkbox("Price Lower Than Buy Box", key="view_lower_than_buybox"):
                df = df[df["Product_current_price"] < df["Product_Buy_box_price"]]
                
            if st.checkbox("Price Lower Than Last Published", key="view_lower_than_published"):
                # Get products from published collection
                published_products = list(self.db.published_products.find(
                    {},
                    {"product_id": 1, "published_price": 1, "_id": 0}
                ).sort([("publish_date", -1)])
                )
                
                # Create a dictionary of latest published prices
                published_prices = {}
                for pub in published_products:
                    product_id = pub.get("product_id")
                    if product_id and product_id not in published_prices:
                        published_prices[product_id] = pub.get("published_price")
                
                # Filter products where current price is lower than last published price
                filtered_indices = []
                for idx, row in df.iterrows():
                    product_id = row.get("Product_unique_ID")
                    current_price = float(row.get("Product_current_price", 0))
                    last_pub_price = published_prices.get(product_id)
                    
                    if last_pub_price and current_price < float(last_pub_price):
                        filtered_indices.append(idx)
                
                if filtered_indices:
                    df = df.loc[filtered_indices]
                else:
                    df = df.head(0)  # Empty DataFrame with same columns
                
            if st.checkbox("Price Changes in Last 24 Hours", key="view_changes_24h"):
                yesterday = datetime.now() - timedelta(days=1)
                df = df[df["updated_date"].apply(lambda x: (
                    (dt := self.parse_datetime(x)) is not None and dt >= yesterday
                ))]

            # Category filters
            col1, col2 = st.columns(2)
            with col1:
                major_cats = df["product_major_category"].unique()
                selected_major = st.multiselect("Filter Major Category", 
                                              major_cats,
                                              key="view_filter_major")
                if selected_major:
                    df = df[df["product_major_category"].isin(selected_major)]
                    
            with col2:
                if selected_major:
                    minor_cats = df[
                        df["product_major_category"].isin(selected_major)
                    ]["product_minor_category"].unique()
                    selected_minor = st.multiselect("Filter Minor Category", 
                                                  minor_cats,
                                                  key="view_filter_minor")
                    if selected_minor:
                        df = df[df["product_minor_category"].isin(selected_minor)]

        st.subheader("Actions")
        col1, col2 = st.columns(2)
        with col1:
            csv_data = df.to_csv(index=False).encode("utf-8")
            st.download_button(
                label="Download Filtered Data",
                data=csv_data,
                file_name="filtered_products.csv",
                mime="text/csv"
            )
        with col2:
            recipient_email = self.config.get("email", {}).get("recipients", [""])[0]
            # st.text_input("Recipient Email", recipient_email, disabled=True)
            if st.button("Send Filtered Data to Email"):
                if recipient_email:
                    try:
                        self.notification_publisher.send_email_report(
                            recipients=[recipient_email],
                            subject="Filtered Products Data",
                            body="Please find the attached filtered products data.",
                            csv_file="filtered_products.csv"
                        )
                        st.success(f"Filtered data sent to {recipient_email}")
                    except Exception as e:
                        st.error(f"Failed to send email: {e}")
                else:
                    st.warning("Recipient email is not configured.")

        st.subheader("Filtered Products")
        if df.empty:
            st.warning("No products match the selected filters.")
        else:
            for _, product in df.iterrows():
                with st.expander(f"📦 {product['product_name']}"):
                    col1, col2 = st.columns([1, 3])
                    with col1:
                        image_path = product.get("Product_image_path", None)
                        if image_path and isinstance(image_path, str) and os.path.exists(image_path):
                            st.image(image_path, width=150)
                        else:
                            st.warning("No image available for this product.")
                    with col2:
                        st.write(f"**Price:** ₹{product.get('Product_current_price', 'N/A')}")
                        st.write(f"**Category:** {product.get('product_major_category', 'N/A')} > {product.get('product_minor_category', 'N/A')}")
                        st.write(f"**Affiliate URL:** [Buy Now]({product.get('product_Affiliate_url', '#')})")
     
    def render_add_product(self):
        st.header("Add New Product")
        
        with st.form("add_product_form"):
            next_sno = self.db.get_next_serial_number()
            
            # Mandatory fields with asterisk (*)
            st.markdown("### Required Fields")
            col1, col2 = st.columns(2)
            with col1:
                product_name = st.text_input("Product Name*", key="add_name")
            with col2:
                product_id = st.text_input("Product Unique ID*", key="add_id")
            
            col3, col4 = st.columns(2)
            with col3:
                major_categories = self.db.get_unique_values("product_major_category")
                major_cat = st.selectbox(
                    "Major Category*", 
                    options=[""] + list(major_categories) + ["Add New Category"],
                    key="add_major_cat"
                )
                
                if major_cat == "Add New Category":
                    major_cat = st.text_input("Enter New Major Category")
            
            with col4:
                minor_categories = self.db.get_unique_values(
                    "product_minor_category", 
                    {"product_major_category": major_cat} if major_cat and major_cat != "Add New Category" else None
                )
                minor_cat = st.selectbox(
                    "Minor Category*", 
                    options=[""] + list(minor_categories) + ["Add New Category"],
                    key="add_minor_cat"
                )
                
                if minor_cat == "Add New Category":
                    minor_cat = st.text_input("Enter New Minor Category")
            
            col5, col6 = st.columns(2)
            with col5:
                affiliate_sites = self.db.get_unique_values("product_Affiliate_site")
                affiliate_site = st.selectbox(
                    "Affiliate Site*", 
                    options=[""] + list(affiliate_sites) + ["Add New Site"],
                    key="add_aff_site"
                )
                
                if affiliate_site == "Add New Site":
                    affiliate_site = st.text_input("Enter New Affiliate Site")
            
            with col6:
                affiliate_url = st.text_input("Affiliate URL*", key="add_aff_url")
            
            col7, col8 = st.columns(2)
            with col7:
                buy_box_price = st.text_input("Buy Box Price*", key="add_buybox")
            with col8:
                current_price = st.number_input("Current Price*", min_value=0.0, key="add_current")

            # Optional fields
            st.markdown("### Optional Fields")
            col9, col10 = st.columns(2)
            with col9:
                lowest_price = st.number_input("Lowest Price", min_value=0.0, key="add_lowest", value=0.0)
            with col10:
                publish = st.checkbox("Publish", key="add_publish", value=False)

            if publish:
                publish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                st.text(f"Publish Time: {publish_time}")
            
            submitted = st.form_submit_button("Add Product")
            
            if submitted:
                if not product_name or not product_id or not major_cat or not minor_cat or not affiliate_site or not affiliate_url or not buy_box_price or not current_price:
                    st.error("Please fill all required fields marked with *")
                    return
                
                new_product = {
                    "s_no": next_sno,
                    "product_name": product_name,
                    "Product_unique_ID": product_id,
                    "product_Affiliate_site": affiliate_site,
                    "product_Affiliate_url": affiliate_url,
                    "product_major_category": major_cat,
                    "product_minor_category": minor_cat,
                    "Product_Buy_box_price": buy_box_price,
                    "Product_current_price": current_price,
                    "Product_lowest_price": lowest_price if lowest_price > 0 else None,
                    "Product_image_path": None,
                    "Publish": publish,
                    "Publish_time": publish_time if publish else None,
                    "updated_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                }
                
                if self.db.product_exists(product_id):
                    st.error(f"Product with ID '{product_id}' already exists!")
                    return
                
                result = self.db.add_product(new_product)
                
                if result:
                    st.success(f"Product '{product_name}' added successfully!")
                else:
                    st.error("Failed to add product. Please try again.")

    def render_edit_product(self):
        st.header("Edit Product")
        
        # Get all products and create a name to ID mapping
        products = self.db.get_products({})
        if not products:
            st.warning("No products available.")
            return
        
        # Create product name to ID mapping
        product_names = {p.get("product_name", "Unnamed"): p.get("Product_unique_ID") 
                        for p in products}
        
        # Select by product name instead of ID
        selected_name = st.selectbox(
            "Select Product to Edit", 
            options=[""] + list(product_names.keys())
        )
        
        if not selected_name:
            st.info("Please select a product to edit")
            return
        
        # Get the product using the ID mapped to selected name
        selected_id = product_names[selected_name]
        product = self.db.get_product_by_id(selected_id)
        
        if not product:
            st.error(f"Product '{selected_name}' not found!")
            return

        # Rest of your existing edit form code
        with st.form("edit_product_form"):
            col1, col2 = st.columns(2)
            with col1:
                product_name = st.text_input("Product Name*", value=product.get("product_name", ""))
            with col2:
                product_id = st.text_input("Product Unique ID*", value=product.get("Product_unique_ID", ""), disabled=True)
            
            col3, col4 = st.columns(2)
            with col3:
                major_categories = self.db.get_unique_values("product_major_category")
                major_cat = st.selectbox(
                    "Major Category*", 
                    options=list(major_categories) + ["Add New Category"],
                    index=list(major_categories).index(product.get("product_major_category", "")) if product.get("product_major_category", "") in major_categories else 0
                )
                
                if major_cat == "Add New Category":
                    major_cat = st.text_input("Enter New Major Category")
            
            with col4:
                minor_categories = self.db.get_unique_values(
                    "product_minor_category", 
                    {"product_major_category": major_cat} if major_cat and major_cat != "Add New Category" else None
                )
                
                current_minor = product.get("product_minor_category", "")
                if current_minor not in minor_categories:
                    minor_categories = list(minor_categories) + [current_minor]
                
                minor_cat = st.selectbox(
                    "Minor Category*", 
                    options=list(minor_categories) + ["Add New Category"],
                    index=list(minor_categories).index(current_minor) if current_minor in minor_categories else 0
                )
                
                if minor_cat == "Add New Category":
                    minor_cat = st.text_input("Enter New Minor Category")
            
            col5, col6 = st.columns(2)
            with col5:
                affiliate_sites = self.db.get_unique_values("product_Affiliate_site")
                current_site = product.get("product_Affiliate_site", "")
                
                if current_site not in affiliate_sites:
                    affiliate_sites = list(affiliate_sites) + [current_site]
                
                affiliate_site = st.selectbox(
                    "Affiliate Site*", 
                    options=list(affiliate_sites) + ["Add New Site"],
                    index=list(affiliate_sites).index(current_site) if current_site in affiliate_sites else 0
                )
                
                if affiliate_site == "Add New Site":
                    affiliate_site = st.text_input("Enter New Affiliate Site")
            
            with col6:
                affiliate_url = st.text_input("Affiliate URL*", value=product.get("product_Affiliate_url", ""))
            
            col7, col8, col9 = st.columns(3)
            with col7:
                buy_box_price = st.text_input("Buy Box Price", value=product.get("Product_Buy_box_price", ""))
            with col8:
                try:
                    lowest_price_val = float(product.get("Product_lowest_price", 0))
                except (ValueError, TypeError):
                    lowest_price_val = 0
                    
                lowest_price = st.number_input("Lowest Price", min_value=0.0, value=lowest_price_val)
            with col9:
                try:
                    current_price_val = float(product.get("Product_current_price", 0))
                except (ValueError, TypeError):
                    current_price_val = 0
                    
                current_price = st.number_input("Current Price", min_value=0.0, value=current_price_val)
            
            col10, col11 = st.columns(2)
            with col10:
                publish = st.checkbox("Publish", value=bool(product.get("Publish", False)))
            with col11:
                current_publish_time = product.get("Publish_time", "nan")
                if publish and (current_publish_time == "nan" or not product.get("Publish", False)):
                    publish_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                else:
                    publish_time = current_publish_time
                    
                st.text(f"Publish Time: {publish_time}")
            
            submitted = st.form_submit_button("Update Product")
            
            if submitted:
                if not product_name or not major_cat or not minor_cat or not affiliate_site or not affiliate_url:
                    st.error("Please fill all required fields marked with *")
                    return
                
                updated_product = {
                    "product_name": product_name,
                    "product_Affiliate_site": affiliate_site,
                    "product_Affiliate_url": affiliate_url,
                    "product_major_category": major_cat,
                    "product_minor_category": minor_cat,
                    "Product_Buy_box_price": buy_box_price,
                    "Product_lowest_price": lowest_price,
                    "Product_current_price": current_price,
                    "Publish": publish,
                    "Publish_time": publish_time
                }
                
                result = self.db.update_product(product_id, updated_product)
                
                if result:
                    st.success(f"Product '{product_name}' updated successfully!")
                else:
                    st.error("Failed to update product. Please try again.")
    
    def render_delete_products(self):
        st.header("Delete Products")
        
        all_products = self.db.get_products({})
        
        if not all_products:
            st.warning("No products available.")
            return
        
        df = pd.DataFrame(all_products)
        
        # Add 's_no' if missing
        if 's_no' not in df.columns:
            df['s_no'] = range(1, len(df) + 1)
        
        display_columns = ['s_no', 'product_name', 'Product_unique_ID', 'product_major_category', 
                          'product_minor_category', 'Product_current_price', 'Publish']
        
        # Check if all required columns exist
        if all(col in df.columns for col in display_columns):
            display_df = df[display_columns]
        else:
            # Create a reduced set of columns that do exist
            available_columns = [col for col in display_columns if col in df.columns]
            display_df = df[available_columns]
            st.info(f"Some display columns are not available in the data. Showing available columns.")
        
        st.subheader("Bulk Delete")
        
        with st.expander("Filter Products", expanded=False):
            col1, col2 = st.columns(2)
            
            with col1:
                major_categories = self.db.get_unique_values("product_major_category")
                filter_major_cat = st.multiselect(
                    "Major Category", 
                    options=major_categories,
                    default=None,
                    key="delete_major_category"  
                )
            
            with col2:
                minor_categories = self.db.get_unique_values(
                    "product_minor_category", 
                    {"product_major_category": {"$in": filter_major_cat}} if filter_major_cat else None
                )
                filter_minor_cat = st.multiselect(
                    "Minor Category", 
                    options=minor_categories,
                    default=None,
                    key="delete_minor_category" 
                )
            
            filtered_df = display_df.copy()
            
            if filter_major_cat:
                filtered_df = filtered_df[filtered_df['product_major_category'].isin(filter_major_cat)]
            
            if filter_minor_cat:
                filtered_df = filtered_df[filtered_df['product_minor_category'].isin(filter_minor_cat)]
            
            st.write(f"Filtered to {len(filtered_df)} products")
        
        st.dataframe(filtered_df, use_container_width=True)
        
        select_all = st.checkbox("Select All Products", key="delete_select_all")
        selected_ids = st.multiselect(
            "Select Products to Delete",
            options=filtered_df['Product_unique_ID'].tolist(),
            default=filtered_df['Product_unique_ID'].tolist() if select_all else [],
            key="delete_selected_products"  
        )
        
        if selected_ids:
            st.warning(f"You are about to delete {len(selected_ids)} products. This action cannot be undone!")
            
            if st.button("Delete Selected Products", type="primary", key="delete_button"):
                deleted_count = 0
                for product_id in selected_ids:
                    result = self.db.delete_product(product_id)
                    if result:
                        deleted_count += 1
                
                if deleted_count > 0:
                    st.success(f"Successfully deleted {deleted_count} products!")
                    st.button("Refresh Page", key="refresh_button")
                else:
                    st.error("Failed to delete products. Please try again.")

    def render_bulk_add_products(self):
        st.header("Bulk Add Products")
        st.write("Upload a CSV or Excel file to add multiple products at once.")

        required_columns = [
            "product_name",
            "Product_unique_ID", 
            "product_Affiliate_site",
            "product_Affiliate_url",
            "product_major_category",
            "product_minor_category",
            "Product_Buy_box_price",
            "Product_current_price"
        ]
        template_data = {
        "product_name": ["Example Product"],
        "Product_unique_ID": ["ABC123"],
        "product_Affiliate_site": ["amazon.in"],
        "product_Affiliate_url": ["https://affiliate.link"],
        "product_major_category": ["Electronics"],
        "product_minor_category": ["Mobile Phones"],
        "Product_Buy_box_price": ["999.99"],
        "Product_current_price": ["899.99"],
        "Product_lowest_price": [None],
        "Product_image_path": [None]
        }

        template_df = pd.DataFrame(template_data)
        csv_template = template_df.to_csv(index=False).encode("utf-8")
        col1, col2 = st.columns(2)
        with col1:
            st.write("Download the template CSV file to get started.")
            st.download_button(
                label="📥 Download Template",
                data=csv_template,
                file_name="bulk_add_template.csv",
                mime="text/csv"
            )
        with col2:
            st.info("Required fields: product_name, Product_unique_ID, product_Affiliate_site, product_Affiliate_url, product_major_category, product_minor_category, Product_Buy_box_price, Product_current_price")

        uploaded_file = st.file_uploader("Choose a file", type=["csv", "xlsx", "xls"])

        if uploaded_file is not None:
            try:
                if uploaded_file.name.endswith(".csv"):
                    df = pd.read_csv(uploaded_file)
                else:
                    df = pd.read_excel(uploaded_file)

                missing_columns = [col for col in required_columns if col not in df.columns]
                if missing_columns:
                    st.error(f"Missing required columns: {', '.join(missing_columns)}")
                    return

                optional_fields = ["Product_lowest_price", "Product_image_path", "Publish", "Publish_time", "s_no"]
                for field in optional_fields:
                    if field not in df.columns:
                        df[field] = None



                st.write("Preview of uploaded data:")
                st.dataframe(df.head())

                if "Product_unique_ID" in df.columns:
                    duplicate_ids = df[df.duplicated("Product_unique_ID", keep=False)]["Product_unique_ID"].unique()
                    if duplicate_ids.size > 0:
                        st.warning(f"⚠️ Found {len(duplicate_ids)} duplicate `Product_unique_ID` values within the uploaded file.")
                        with st.expander("View duplicate entries in the file"):
                            st.dataframe(df[df["Product_unique_ID"].isin(duplicate_ids)])

                existing_ids = []
                for product_id in df["Product_unique_ID"].unique():
                    if self.db.product_exists(product_id):
                        existing_ids.append(product_id)

                if existing_ids:
                    st.warning(f"⚠️ Found {len(existing_ids)} products in the database with duplicate `Product_unique_ID` values.")
                    with st.expander("View existing products in the database"):
                        existing_products = self.db.get_products({"Product_unique_ID": {"$in": existing_ids}})
                        st.dataframe(pd.DataFrame(existing_products))

                st.subheader("Duplicate Handling Options")
                duplicate_handling = st.radio(
                    "How do you want to handle duplicates?",
                    options=["Skip duplicates", "Update existing records", "Replace duplicates"],
                    index=0
                )

                if st.button("Import Products"):
                    inserted_count = 0
                    updated_count = 0
                    skipped_count = 0

                    for _, row in df.iterrows():
                        product_data = row.to_dict()
                        product_data["updated_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        if self.db.product_exists(product_id):
                            if duplicate_handling == "Skip duplicates":
                                skipped_count += 1
                                continue
                            elif duplicate_handling == "Update existing records":
                                self.db.update_product(product_id, product_data)
                                updated_count += 1
                            elif duplicate_handling == "Replace duplicates":
                                self.db.delete_product(product_id)
                                self.db.add_product(product_data)
                                updated_count += 1
                        else:
                            self.db.add_product(product_data)
                            inserted_count += 1

                    st.success(f"✅ Import completed: {inserted_count} inserted, {updated_count} updated, {skipped_count} skipped.")
            except Exception as e:
                st.error(f"Error processing file: {e}")

    def process_scheduled_publishing(self):
        """
        Process products scheduled for publishing.
        """
        # Get current time
        now = datetime.now()
        
        # Initialize notification publisher if needed
        if not hasattr(self, 'notification_publisher'):
            self.notification_publisher = NotificationPublisher(self.config_manager)
        
        # Find products scheduled for publishing
        scheduled_products = list(self.db.get_products({"Publish": True}))
        
        if not scheduled_products:
            return
            
        for product in scheduled_products:
            product_id = product.get("Product_unique_ID")
            product_name = product.get("product_name")
            publish_time = product.get("Publish_time")
            
            try:
                if publish_time:
                    publish_dt = datetime.strptime(publish_time, "%Y-%m-%d %H:%M:%S")
                    if publish_dt > now:
                        continue  # Skip if scheduled for future
                
                # Generate formatted message using our centralized format function
                message = self.notification_publisher.format_product_message(product)
                
                telegram_success, telegram_error = self.notification_publisher.telegram_push(message)
                if not telegram_success:
                    raise Exception(f"Telegram Error: {telegram_error}")

                whatsapp_group = self.notification_publisher.email_config.get("whatsapp_group_name", "Default Group")
                self.notification_publisher.whatsapp_push(product, whatsapp_group, message)

                self.db.update_product(product_id, {
                    "Publish": False,
                    "Publish_time": None,
                    "Last_published_date": now.strftime("%Y-%m-%d %H:%M:%S")
                })

                st.success(f"✅ Successfully published '{product_name}'.")

            except Exception as e:
                st.error(f"❌ Failed to publish '{product_name}': {str(e)}")

    def render_manage_publishing(self):
        """
        Render the Manage Publishing page to handle scheduled publishing.
        """
        st.header("🕒 Scheduled Products")

        # Get scheduled products
        scheduled_products = self.db.get_products({
            "Publish": True,
            "published_status": False
        })

        if scheduled_products:
            df = pd.DataFrame(scheduled_products)
            # Format the display columns
            display_df = df[['product_name', 'Product_unique_ID', 'Product_current_price', 
                            'Publish_time', 'product_major_category']].copy()
            display_df.columns = ['Product Name', 'ID', 'Price', 'Scheduled Time', 'Category']
            
            st.dataframe(display_df, use_container_width=True)
            

        else:
            st.info("No products currently scheduled for publishing.")

    def render_published_products(self):
        """
        Render the Published Products page showing all published products sorted by the last published product first.
        """
        st.header("📢 Published Products")

        try:
            # Fetch all published products sorted by the last published date in descending order
            published_products = self.db.get_published_products(
                
                  # Sort by publish_date in descending order
            )
        except Exception as e:
            st.error(f"Error retrieving published products: {e}")
            return

        if not published_products:
            st.info("No published products found.")
            return

        # Convert to DataFrame for display
        df = pd.DataFrame(published_products)

        # Define columns to display
        display_columns = {
            "product_name": "Product Name",
            "Product_unique_ID": "Product ID",
            "product_major_category": "Category",
            "Product_current_price": "Price",
            "publish_date": "Publish Date",
            "publish_status": "Publish Status"
        }

        # Filter and rename columns for display
        newdf = df[[col for col in display_columns if col in df.columns]].rename(columns=display_columns)

        # Display the DataFrame
        st.dataframe(newdf, use_container_width=True)

        # Export options
        csv_data = df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Download as CSV",
            data=csv_data,
            file_name="published_products.csv",
            mime="text/csv"
        )


