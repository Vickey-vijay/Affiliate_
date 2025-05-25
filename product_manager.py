# product_manager.py

import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import pymongo
from notification_publisher import NotificationManager


class ProductManager:
    def __init__(self, db):
        """
        Initialize the ProductManager with a MongoDB database connection.
        :param db: The MongoDB database instance.
        """
        self.db = db
        self.products_collection = db["products"]

    def dashboard_page(self):
        st.header("📊 Product Dashboard")
        products = list(self.products_collection.find({}))
        if not products:
            st.info("No products found to display in dashboard.")
            return

        # Summary metrics
        col1, col2, col3, col4 = st.columns(4)
        total_products = len(products)
        published_products = sum(1 for p in products if p.get("published_status", False))
        scheduled_products = sum(1 for p in products if p.get("Publish", False) and not p.get("published_status", False))

        with col1:
            st.metric("Total Products", total_products)
        with col2:
            st.metric("Published", published_products)
        with col3:
            st.metric("Scheduled", scheduled_products)
        with col4:
            unique_categories = len(set(p.get("product_major_category", "") for p in products))
            st.metric("Categories", unique_categories)

        # Category distribution chart
        st.subheader("Product Categories")
        categories = {}
        for product in products:
            category = product.get("product_major_category", "Uncategorized")
            categories[category] = categories.get(category, 0) + 1
        category_df = pd.DataFrame({
            "Category": list(categories.keys()),
            "Count": list(categories.values())
        })
        st.bar_chart(category_df.set_index("Category"))

        # Price analysis table
        st.subheader("Price Analysis")
        price_data = []
        for product in products:
            try:
                current_price = float(product.get("Product_current_price", 0))
                buy_box_price = float(product.get("Product_Buy_box_price", 0))
                lowest_price = float(product.get("Product_lowest_price", 0))
                price_data.append({
                    "Product": product.get("product_name", "Unknown"),
                    "Current Price": current_price,
                    "Buy Box Price": buy_box_price,
                    "Lowest Price": lowest_price
                })
            except (ValueError, TypeError):
                continue

        if price_data:
            price_df = pd.DataFrame(price_data)
            st.dataframe(price_df.style.highlight_max(axis=0, subset=["Current Price", "Buy Box Price", "Lowest Price"]))
        else:
            st.warning("No valid price data to display")

        # Recently added products
        st.subheader("Recently Added Products")
        recent_products = sorted(products, key=lambda x: x.get("created_at", ""), reverse=True)[:5]
        for product in recent_products:
            with st.expander(f"{product.get('product_name', 'Unknown')}"):
                col1, col2 = st.columns(2)
                with col1:
                    st.write(f"**ID:** {product.get('Product_unique_ID', 'N/A')}")
                    st.write(f"**Category:** {product.get('product_major_category', 'N/A')} > {product.get('product_minor_category', 'N/A')}")
                    st.write(f"**Price:** {product.get('Product_current_price', 'N/A')}")
                with col2:
                    st.write(f"**Added:** {product.get('created_at', 'N/A')}")
                    st.write(f"**Published:** {'Yes' if product.get('published_status', False) else 'No'}")
                    st.write(f"**Affiliate:** {product.get('product_Affiliate_site', 'N/A')}")

    def extraction_page(self):
        st.header("📥 Extraction")
        st.write("Upload your Excel file for processing:")

        uploaded_file = st.file_uploader(
            "Drag and drop file here",
            type=["xlsx", "xls"],
            accept_multiple_files=False,
            help="Limit 200MB per file • XLSX, XLS"
        )

        REQUIRED_COLUMNS = [
            "s_no", "product_name", "Product_unique_ID",
            "product_Affiliate_site", "product_Affiliate_url",
            "product_major_category", "product_minor_category",
            "Product_Buy_box_price", "Product_lowest_price",
            "Product_current_price", "Product_image_path",
            "Publish", "Publish_time"
        ]

        if uploaded_file:
            try:
                uploaded_df = pd.read_excel(uploaded_file)
            except Exception as e:
                st.error(f"Failed to read Excel file: {e}")
                return

            df = uploaded_df.copy()
            df["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            if "Publish_time" in df.columns:
                df["Publish_time"] = pd.to_datetime(df["Publish_time"], errors='coerce')

            df["Product_Buy_box_price"] = pd.to_numeric(df["Product_Buy_box_price"], errors="coerce")
            df["Product_lowest_price"] = pd.to_numeric(df["Product_lowest_price"], errors="coerce")
            df["Product_current_price"] = pd.to_numeric(df["Product_current_price"], errors="coerce")

            REQUIRED_COLUMNS = [
                "s_no", "product_name", "Product_unique_ID", "product_Affiliate_site",
                "product_Affiliate_url", "product_major_category", "product_minor_category",
                "Product_Buy_box_price", "Product_lowest_price", "Product_current_price",
                "Product_image_path", "Publish", "Publish_time"
            ]

            # Ensure all required columns are present
            if not set(REQUIRED_COLUMNS).issubset(df.columns):
                st.error("❌ Uploaded file does not match required columns.")
                st.code("\n".join(REQUIRED_COLUMNS))
                return

            # Ensure numeric columns are properly converted
            numeric_columns = ["Product_Buy_box_price", "Product_lowest_price", "Product_current_price"]
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

            if not set(REQUIRED_COLUMNS).issubset(df.columns):
                st.error("❌ Uploaded file does not match required columns.")
                st.code("\n".join(REQUIRED_COLUMNS))
                return

            st.success(f"✅ File validated successfully! Found {len(df)} products.")
            if len(df) > 0:
                col_options = df.columns.tolist()
                selected_cols = st.multiselect(
                    "Select columns to preview",
                    options=col_options,
                    default=["product_name", "Product_unique_ID", "product_major_category", "Product_current_price"]
                )
                st.dataframe(df[selected_cols] if selected_cols else df)

            # Check for duplicates within the file
            if "Product_unique_ID" in df.columns:
                duplicate_ids = df[df.duplicated("Product_unique_ID", keep=False)]["Product_unique_ID"].unique()
                if duplicate_ids.size > 0:
                    st.warning(f"⚠️ Found {len(duplicate_ids)} duplicated product IDs within this file.")
                    with st.expander("View duplicate products"):
                        st.dataframe(df[df["Product_unique_ID"].isin(duplicate_ids)])

                # Check for duplicates in the database
                existing_products = []
                for product_id in df["Product_unique_ID"].unique():
                    if self.products_collection.find_one({"Product_unique_ID": product_id}):
                        existing_products.append(product_id)
                if existing_products:
                    st.warning(f"⚠️ Found {len(existing_products)} products that already exist in the database.")
                    st.info("These products will be updated with the new data upon confirmation.")

            # Upload options
            st.subheader("Upload Options")
            upload_mode = st.radio(
                "Select upload mode:",
                ["Replace duplicates (default)", "Skip duplicates", "Append all (may create duplicates)"]
            )

            with st.expander("Batch settings (apply to all products)"):
                batch_publish = st.checkbox("Set publish status for all products")
                publish_status = st.checkbox("Publish", value=False, disabled=not batch_publish)
                batch_publish_time = st.checkbox("Set publish time for all products")
                if batch_publish_time:
                    publish_date = st.date_input("Publish date")
                    publish_time = st.time_input("Publish time")
                    
                    # Safe handling of date input with improved type checking
                    use_date = datetime.now().date()  # Default fallback date

                    # Handle all possible return types from st.date_input
                    if isinstance(publish_date, tuple):
                        # It's a tuple in newer Streamlit versions
                        if len(publish_date) > 0 and hasattr(publish_date[0], 'year'):
                            use_date = publish_date[0]  # Extract the date from the tuple if it exists
                    elif isinstance(publish_date, datetime):
                        # It's a datetime object
                        use_date = publish_date.date()
                    elif hasattr(publish_date, 'year') and callable(getattr(publish_date, 'replace', None)):
                        # It's a date object
                        use_date = publish_date

                    # Check if use_date is valid before combining with publish_time
                    if use_date is not None:
                        publish_datetime = datetime.combine(use_date, publish_time)
                    else:
                        # Use current date as fallback if use_date is None
                        publish_datetime = datetime.combine(datetime.now().date(), publish_time)
                batch_category = st.checkbox("Set category for all products")
                if batch_category:
                    major_category = st.text_input("Major category")
                    minor_category = st.text_input("Minor category")

            if st.button("Confirm & Upload to DB"):
                if batch_publish:
                    df["Publish"] = publish_status
                if batch_publish_time:
                    df["Publish_time"] = publish_datetime
                if batch_category:
                    if major_category:
                        df["product_major_category"] = major_category
                    if minor_category:
                        df["product_minor_category"] = minor_category

                df["updated_date"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                for _, row in df.iterrows():
                    self.db.add_product(row.to_dict())

                if upload_mode == "Replace duplicates (default)":
                    for _, row in df.iterrows():
                        unique_id = row["Product_unique_ID"]
                        self.products_collection.delete_one({"Product_unique_ID": unique_id})
                        self.products_collection.insert_one(row.to_dict())
                elif upload_mode == "Skip duplicates":
                    skipped = 0
                    inserted = 0
                    for _, row in df.iterrows():
                        unique_id = row["Product_unique_ID"]
                        if not self.products_collection.find_one({"Product_unique_ID": unique_id}):
                            self.products_collection.insert_one(row.to_dict())
                            inserted += 1
                        else:
                            skipped += 1
                    st.info(f"Skipped {skipped} existing products, inserted {inserted} new products.")
                else:  # Append all
                    result = self.products_collection.insert_many([row.to_dict() for _, row in df.iterrows()])
                    st.info(f"Inserted {len(result.inserted_ids)} products.")

                st.success("🎉 Data uploaded to MongoDB successfully!")
                st.balloons()

    def manage_products_page(self):
        st.header("🛠️ Manage Products")
        products = list(self.products_collection.find({}))
        if not products:
            st.info("No products found.")
            return

        for product in products:
            with st.expander(f"📦 {product.get('product_name', 'Unnamed Product')}"):
                col1, col2 = st.columns(2)
                with col1:
                    product_name = st.text_input("Product Name", value=product.get("product_name", ""), key=f"name_{product['_id']}")
                    product_aff_url = st.text_input("Affiliate URL", value=product.get("product_Affiliate_url", ""), key=f"url_{product['_id']}")
                    buy_price = st.text_input("Buy Box Price", value=product.get("Product_Buy_box_price", ""), key=f"buy_{product['_id']}")
                    low_price = st.text_input("Lowest Price", value=product.get("Product_lowest_price", ""), key=f"low_{product['_id']}")
                    current_price = st.text_input("Current Price", value=product.get("Product_current_price", ""), key=f"current_{product['_id']}")
                with col2:
                    major_cat = st.text_input("Major Category", value=product.get("product_major_category", ""), key=f"major_{product['_id']}")
                    minor_cat = st.text_input("Minor Category", value=product.get("product_minor_category", ""), key=f"minor_{product['_id']}")
                    image_path = st.text_input("Image Path", value=product.get("Product_image_path", ""), key=f"img_{product['_id']}")
                    publish = st.checkbox("Publish", value=product.get("Publish", False), key=f"pub_{product['_id']}")
                    pub_time = st.text_input("Publish Time", value=product.get("Publish_time", ""), key=f"ptime_{product['_id']}")
                if st.button("Save Changes", key=f"save_{product['_id']}"):
                    updated_product = {
                        "product_name": product_name,
                        "product_Affiliate_url": product_aff_url,
                        "Product_Buy_box_price": buy_price,
                        "Product_lowest_price": low_price,
                        "Product_current_price": current_price,
                        "product_major_category": major_cat,
                        "product_minor_category": minor_cat,
                        "Product_image_path": image_path,
                        "Publish": publish,
                        "Publish_time": pub_time
                    }
                    self.products_collection.update_one(
                        {"Product_unique_ID": product["Product_unique_ID"]},
                        {"$set": updated_product}
                    )
                    st.success("✅ Product updated successfully!")
                    st.rerun()

    def product_search_page(self):
        st.header("🔍 Product Search")
        col1, col2 = st.columns(2)
        with col1:
            search_term = st.text_input("Search by product name or ID")
        with col2:
            categories = list(set(
                p.get("product_major_category", "")
                for p in self.products_collection.find({}, {"product_major_category": 1})
                if p.get("product_major_category")
            ))
            search_category = st.selectbox(
                "Filter by category",
                options=["All Categories"] + categories
            )
        col3, col4, col5 = st.columns(3)
        with col3:
            max_price = 10000.0
            sample = self.products_collection.find_one(sort=[("Product_current_price", -1)])
            try:
                if sample:
                    max_price = float(sample.get("Product_current_price", 10000))
            except (ValueError, TypeError):
                max_price = 10000.0
            price_range = st.slider(
                "Price range",
                min_value=0.0,
                max_value=max_price,
                value=(0.0, 5000.0),
                step=100.0
            )
        with col4:
            show_published = st.checkbox("Published products", value=True)
        with col5:
            show_unpublished = st.checkbox("Unpublished products", value=True)

        query = {}
        if search_term:
            query["$or"] = [
                {"product_name": {"$regex": search_term, "$options": "i"}},
                {"Product_unique_ID": {"$regex": search_term, "$options": "i"}}
            ]
        if search_category != "All Categories":
            query["product_major_category"] = search_category
        query["Product_current_price"] = {
            "$gte": str(price_range[0]),
            "$lte": str(price_range[1])
        }
        publish_conditions = []
        if show_published:
            publish_conditions.append({"published_status": True})
        if show_unpublished:
            publish_conditions.append({"published_status": False})
            publish_conditions.append({"published_status": {"$exists": False}})
        if publish_conditions:
            query["$or"] = query.get("$or", []) + publish_conditions

        if st.button("Search"):
            results = list(self.products_collection.find(query))
            if not results:
                st.info("No products match your search criteria.")
            else:
                st.success(f"Found {len(results)} products matching your criteria.")
                for product in results:
                    with st.expander(f"{product.get('product_name', 'Unknown')} ({product.get('Product_unique_ID', 'N/A')})"):
                        col1, col2, col3 = st.columns([2, 1, 1])
                        with col1:
                            st.subheader(product.get("product_name", "Unknown"))
                            st.write(f"**Category:** {product.get('product_major_category', 'N/A')} > {product.get('product_minor_category', 'N/A')}")
                            st.write(f"**Source:** {product.get('product_Affiliate_site', 'N/A')}")
                            if product.get("product_Affiliate_url"):
                                st.write(f"[Product Link]({product.get('product_Affiliate_url')})")
                        with col2:
                            st.metric("Current Price", product.get("Product_current_price", "N/A"))
                            st.metric("Buy Box Price", product.get("Product_Buy_box_price", "N/A"))
                            st.metric("Lowest Price", product.get("Product_lowest_price", "N/A"))
                        with col3:
                            published = product.get("published_status", False)
                            st.write(f"**Published:** {'Yes' if published else 'No'}")
                            if published and product.get("published_at"):
                                st.write(f"**Published At:** {product.get('published_at')}")
                            elif product.get("Publish") and product.get("Publish_time"):
                                st.write(f"**Scheduled For:** {product.get('Publish_time')}")
                            if not published:
                                if st.button("Publish Now", key=f"pub_{product['_id']}"):
                                    from publisher import Publisher
                                    publisher = Publisher()
                                    try:
                                        publisher.telegram_push(product)
                                        publisher.whatsapp_push(product)
                                        self.products_collection.update_one(
                                            {"_id": product["_id"]},
                                            {"$set": {
                                                "published_status": True,
                                                "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                            }}
                                        )
                                        publisher.published_collection.insert_one({**product, "published_at": datetime.now()})
                                        st.success("Product published successfully!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Failed to publish: {str(e)}")
                            if st.button("Edit", key=f"edit_{product['_id']}"):
                                st.session_state.page = "Manage Products"
                                st.session_state.edit_product_id = str(product["_id"])
                                st.rerun()

    def publisher_control_page(self):
        st.header("📢 Publisher Control")
        scheduled_products = list(self.products_collection.find({
            "Publish": True,
            "published_status": {"$ne": True}
        }))
        st.subheader("Scheduled Publications")
        if not scheduled_products:
            st.info("No products are currently scheduled for publication.")
        else:
            st.write(f"**{len(scheduled_products)}** products scheduled for publication")
            scheduled_df = pd.DataFrame([
                {
                    "Product": p.get("product_name", "Unknown"),
                    "Category": p.get("product_major_category", "N/A"),
                    "Scheduled Time": p.get("Publish_time", "N/A"),
                    "ID": p.get("Product_unique_ID", "N/A")
                } for p in scheduled_products
            ])
            st.dataframe(scheduled_df)

        st.subheader("Manual Publication")
        unpublished_products = list(self.products_collection.find({
            "$or": [
                {"published_status": {"$ne": True}},
                {"published_status": {"$exists": False}}
            ]
        }))
        if not unpublished_products:
            st.info("No unpublished products available.")
        else:
            product_options = {p.get("product_name", f"Unknown ({p.get('Product_unique_ID', 'N/A')})"):
                               p.get("Product_unique_ID", "") for p in unpublished_products}
            selected_products = st.multiselect(
                "Select products to publish",
                options=list(product_options.keys())
            )
            channels = st.multiselect(
                "Select channels",
                options=["Telegram", "WhatsApp"],
                default=["Telegram", "WhatsApp"]
            )
            if st.button("Publish Now", key="manual_publish"):
                if not selected_products:
                    st.warning("Please select at least one product to publish")
                elif not channels:
                    st.warning("Please select at least one channel")
                else:
                    from publisher import Publisher
                    publisher = Publisher()
                    success_count = 0
                    for product_name in selected_products:
                        product_id = product_options[product_name]
                        product = self.products_collection.find_one({"Product_unique_ID": product_id})
                        if not product:
                            st.error(f"Could not find product: {product_name}")
                            continue
                        try:
                            if "Telegram" in channels:
                                publisher.telegram_push(product)
                            if "WhatsApp" in channels:
                                notification_manager = NotificationManager()
                                group_name = "Your WhatsApp Group Name"  # Replace with your group name
                                message = (
                                    f"🛍️ *{product['product_name']}*\n"
                                    f"💰 *Current Price:* ₹{product['Product_current_price']}\n"
                                    f"💸 *MRP:* ₹{product['Product_Buy_box_price']}\n"
                                    f"🔗 [Buy Now]({product['product_Affiliate_url']})"
                                )
                                notification_manager.send_whatsapp_channel_message(group_name, message)
                            self.products_collection.update_one(
                                {"Product_unique_ID": product_id},
                                {"$set": {
                                    "published_status": True,
                                    "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                }}
                            )
                            publisher.published_collection.insert_one({**product, "published_at": datetime.now()})
                            success_count += 1
                        except Exception as e:
                            st.error(f"Failed to publish {product_name}: {str(e)}")
                    if success_count > 0:
                        st.success(f"Successfully published {success_count} products!")
                        st.balloons()

        st.subheader("Publisher Service Status")
        col1, col2 = st.columns(2)
        with col1:
            service_status = st.radio(
                "Publisher service:",
                ["Check status", "Start service", "Stop service"]
            )
            if service_status == "Check status":
                st.info("Publisher service status is simulated in this interface.")
            elif service_status == "Start service":
                st.success("Publisher service start command sent.")
                st.info("In a production environment, this would start the publisher.py script.")
            elif service_status == "Stop service":
                st.warning("Publisher service stop command sent.")
                st.info("In a production environment, this would stop the publisher.py script.")
        with col2:
            st.write("**Publisher Logs:**")
            st.code("""
[Publisher] Scheduler started.
[Publisher] Checking for scheduled publications...
[SUCCESS] Published Product ABC
[SUCCESS] Published Product XYZ
            """, language="text")

    def configuration_page(self):
        st.header("⚙️ Configuration")
        st.write("Configure your app here.")
    
    def summary_page(self):
        st.header("📊 Summary")
        st.write("Summary and reports will be displayed here.")
