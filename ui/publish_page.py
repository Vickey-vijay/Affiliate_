import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import schedule
import time
from threading import Thread
from db.db_manager import DataManager
from notification_publisher import NotificationPublisher
import schedule

class PublishPage:
    def __init__(self, config_manager):
        self.db = DataManager()
        self.notification_publisher = NotificationPublisher(config_manager)
        self.config_manager = config_manager
        self.scheduler = schedule
        self.scheduled_tasks = []

    def __del__(self):
        """Cleanup resources when page is destroyed"""
        try:
            if hasattr(self, 'notification_publisher'):
                self.notification_publisher.close()
        except Exception as e:
            print(f"Warning: Error in PublishPage cleanup: {e}")

    def render(self):
        st.title("📤 Publish Products")

        tabs = st.tabs(["Manual Publish", "Automatic Publish", "Email Scheduling"])

        with tabs[0]:
            st.header("Manual Publish")
            self.render_manual_publish()

        with tabs[1]:
            st.header("Automatic Publish")
            self.render_automatic_publish()

        with tabs[2]:
            st.header("Email Scheduling")
            self.render_email_scheduling()

    def render_manual_publish(self):
        # Get unpublished products
        products = self.db.get_products({
            "published_status": {"$ne": False}
        })
        
        if not products:
            st.info("No products available for publishing")
            return

        # Create product selection dataframe
        df = pd.DataFrame(products)
        
        # Use session state to track selection state
        if "selected_products" not in st.session_state:
            st.session_state.selected_products = df.copy()
            st.session_state.selected_products["Select"] = False
        
        # Ensure our session state has the same products
        if len(st.session_state.selected_products) != len(df):
            st.session_state.selected_products = df.copy()
            st.session_state.selected_products["Select"] = False

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Select All"):
                st.session_state.selected_products["Select"] = True
        with col2:
            if st.button("Clear Selection"):
                st.session_state.selected_products["Select"] = False

        edited_df = st.data_editor(
            st.session_state.selected_products,
            hide_index=True,
            column_config={
                "Select": st.column_config.CheckboxColumn("Select")
            }
        )

        # Create two columns for the buttons
        col1, col2 = st.columns(2)
        
        # Time selection for scheduling (in first column)
        with col1:
            st.subheader("Schedule for Later")
            hour_col, minute_col, ampm_col = st.columns(3)
            hour = hour_col.selectbox("Hour", options=[f"{i:02d}" for i in range(1, 13)], key="schedule_hour")
            minute = minute_col.selectbox("Minute", options=[f"{i:02d}" for i in range(0, 60)], key="schedule_minute")
            am_pm = ampm_col.selectbox("AM/PM", options=["AM", "PM"], key="schedule_ampm")
            
            if st.button("Schedule Selected Products"):
                selected_products = edited_df[edited_df["Select"]].to_dict('records')
                if not selected_products:
                    st.warning("Please select products to publish")
                    return

                # Convert time to 24hr format
                publish_time = datetime.strptime(f"{hour}:{minute} {am_pm}", "%I:%M %p")
                schedule_time = publish_time.strftime("%H:%M")

                # Store in DB with scheduled time
                for product in selected_products:
                    self.db.update_product(product['Product_unique_ID'], {
                        "Publish": True,
                        "Publish_time": schedule_time,
                        "published_status": False
                    })
                    
                    self.scheduler.every().day.at(schedule_time).do(
                        self.publish_product, product
                    )
                
                st.success(f"✅ Scheduled {len(selected_products)} products for {schedule_time}")
        
        with col2:
            st.subheader("Publish Immediately")
            
            channels = st.multiselect(
                "Select Channels", 
                ["Telegram", "WhatsApp"], 
                default=["Telegram", "WhatsApp"],
                key="immediate_channels"
            )
            
            if st.button("Push Now", type="primary"):
                selected_products = edited_df[edited_df["Select"]].to_dict('records')
                if not selected_products:
                    st.warning("Please select products to publish")
                    return
                    
                if not channels:
                    st.warning("Please select at least one channel")
                    return
                    
                success_count = 0
                failed_count = 0
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for i, product in enumerate(selected_products):
                    status_text.text(f"Publishing {i+1}/{len(selected_products)}: {product['product_name']}")
                    
                    try:
                        success, message = self.publish_product(product)
                        if success:
                            success_count += 1
                        else:
                            failed_count += 1
                            st.error(f"Failed to publish {product['product_name']}: {message}")
                    except Exception as e:
                        failed_count += 1
                        st.error(f"Error publishing {product['product_name']}: {str(e)}")
                    
                    progress = (i + 1) / len(selected_products)
                    progress_bar.progress(progress)
                    
                    time.sleep(1)
                
                # Show final result
                if success_count > 0:
                    st.success(f"✅ Successfully published {success_count} products!")
                if failed_count > 0:
                    st.warning(f"⚠️ Failed to publish {failed_count} products. See errors above.")

    def render_automatic_publish(self):
        st.subheader("Automatic Publish Configuration")
        
        auto_config = self.db.get_auto_publish_config()
        saved_filters = auto_config.get("filters", {})
        saved_schedule_type = auto_config.get("schedule_type", "Frequency")
        saved_schedule = auto_config.get("schedule", "6 hours" if saved_schedule_type == "Frequency" else [])
        is_active = auto_config.get("active", False)
        
        st.info("Set up automatic publishing to monitor prices and publish products based on criteria.")
        
        with st.expander("Price Filters", expanded=True):
            filters = {
                "filter_lower_than_buybox": st.checkbox(
                    "Price lower than buybox", 
                    value=saved_filters.get("filter_lower_than_buybox", True),
                    help="Only publish products where current price is lower than buy box price"
                ),
                "filter_never_published": st.checkbox(
                    "Never published before", 
                    value=saved_filters.get("filter_never_published", False),
                    help="Only publish products that have never been published before"
                ),
                "filter_lower_than_last_published": st.checkbox(
                    "Price dropped since last publish", 
                    value=saved_filters.get("filter_lower_than_last_published", False),
                    help="Only publish products where price has dropped since last publication"
                ),
                "filter_published_over_days": st.checkbox(
                    "Not published recently", 
                    value=saved_filters.get("filter_published_over_days", False),
                    help="Only publish products not published in the specified number of days"
                )
            }
            
            if filters["filter_published_over_days"]:
                days_threshold = st.number_input(
                    "Days threshold", 
                    min_value=1, 
                    value=saved_filters.get("days_threshold", 4),
                    help="Publish products not published in this many days"
                )
                if days_threshold is not None:
                    if "numeric_values" not in saved_filters:
                        saved_filters["numeric_values"] = {}
                    saved_filters["numeric_values"]["days_threshold"] = int(days_threshold)

        st.subheader("Schedule")
        schedule_type = st.radio(
            "Schedule Type", 
            ["Frequency", "Fixed Times"],
            index=0 if saved_schedule_type == "Frequency" else 1
        )

        if schedule_type == "Frequency":
            frequency = st.selectbox(
                "Check Every",
                ["1 hour", "3 hours", "6 hours", "12 hours", "24 hours"],
                index=["1 hour", "3 hours", "6 hours", "12 hours", "24 hours"].index(saved_schedule) if isinstance(saved_schedule, str) and saved_schedule in ["1 hour", "3 hours", "6 hours", "12 hours", "24 hours"] else 2
            )
        else:
            default_times = saved_schedule if isinstance(saved_schedule, list) else []
            times = st.multiselect(
                "Select Times", 
                [f"{i:02d}:00" for i in range(24)],
                default=default_times
            )
            if not times and schedule_type == "Fixed Times":
                st.warning("Please select at least one time for fixed schedule.")

        col1, col2 = st.columns(2)
        with col1:
            start_button = st.button(
                "Start Automatic Publishing", 
                disabled=is_active,
                type="primary"
            )
        with col2:
            stop_button = st.button(
                "Stop Automatic Publishing", 
                disabled=not is_active,
                type="secondary"
            )

        status_color = "green" if is_active else "red"
        status_text = "ACTIVE" if is_active else "INACTIVE"
        st.markdown(f"<h3>Current Status: <span style='color:{status_color};'>{status_text}</span></h3>", unsafe_allow_html=True)
        
        if is_active:
            next_run_time = auto_config.get("next_run", "Unknown")
            st.info(f"Next scheduled run: {next_run_time}")

        if start_button:
            config = {
                "filters": filters,
                "schedule_type": schedule_type,
                "schedule": frequency if schedule_type == "Frequency" else times,
                "active": True,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "next_run": "Calculating..."
            }
            
            st.session_state.auto_filters = filters
            
            def monitor_and_publish():
                try:
                    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    print(f"[{current_time}] Starting automatic publishing job...")
                    
                    try:
                        from monitors.amazon_monitor import AmazonIndiaMonitor
                    except ImportError:
                        print("❌ Failed to import AmazonIndiaMonitor. Please check the module path.")
                        return
                    
                    try:
                        monitor = AmazonIndiaMonitor()
                        
                        products = self.db.get_products({})
                        if not products:
                            print("No products found in database.")
                            return
                            
                        product_ids = [p.get("Product_unique_ID") for p in products if p.get("Product_unique_ID")]
                        print(f"Found {len(product_ids)} products in database.")
                        
                        try:
                            monitor.run(product_ids)
                            print("✅ Completed price monitoring")
                        except Exception as monitor_error:
                            print(f"❌ Error during price monitoring: {monitor_error}")
                        
                        query = {}
                        
                        if st.session_state.auto_filters.get("filter_lower_than_buybox", False):
                            query["$expr"] = {"$lt": ["$Product_current_price", "$Product_Buy_box_price"]}
                        
                        if st.session_state.auto_filters.get("filter_never_published", False):
                            published_product_ids = []
                            published_data = list(self.db.db.published_products.find({}, {"product_id": 1, "_id": 0}))
                            for item in published_data:
                                if "product_id" in item:
                                    published_product_ids.append(item["product_id"])
                            
                            if published_product_ids:
                                if "$and" not in query:
                                    query["$and"] = []
                                query["$and"].append({"Product_unique_ID": {"$nin": published_product_ids}})
                        
                        if st.session_state.auto_filters.get("filter_lower_than_last_published", False):
                            published_prices = {}
                            published_data = list(self.db.db.published_products.find(
                                {}, 
                                {"product_id": 1, "product_price": 1, "_id": 0}
                            ).sort([("published_date", -1)]))
                            
                            for item in published_data:
                                product_id = item.get("product_id")
                                price = item.get("product_price")
                                if product_id and price and product_id not in published_prices:
                                    published_prices[product_id] = float(price)
                            
                            eligible_product_ids = []
                            for product in products:
                                product_id = product.get("Product_unique_ID")
                                current_price = float(product.get("Product_current_price", 0))
                                last_published_price = published_prices.get(product_id, float('inf'))
                                
                                if current_price < last_published_price:
                                    eligible_product_ids.append(product_id)
                            
                            if eligible_product_ids:
                                if "$and" not in query:
                                    query["$and"] = []
                                query["$and"].append({"Product_unique_ID": {"$in": eligible_product_ids}})
                            else:
                                if "$and" not in query:
                                    query["$and"] = []
                                query["$and"].append({"Product_unique_ID": None})  # This will match nothing
                        
                        if st.session_state.auto_filters.get("filter_published_over_days", False):
                            days = st.session_state.auto_filters.get("days_threshold", 4)
                            days_ago = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
                            
                            # Find products published before the threshold
                            recent_published_ids = []
                            published_data = list(self.db.db.published_products.find(
                                {"published_date": {"$gte": days_ago}}, 
                                {"product_id": 1, "_id": 0}
                            ))
                            
                            for item in published_data:
                                if "product_id" in item:
                                    recent_published_ids.append(item["product_id"])
                            
                            # Include products not recently published or never published
                            if recent_published_ids:
                                if "$and" not in query:
                                    query["$and"] = []
                                query["$and"].append({"Product_unique_ID": {"$nin": recent_published_ids}})
                        
                        # Get filtered products
                        filtered_products = self.db.get_products(query)
                        print(f"Found {len(filtered_products)} products matching filters")
                        
                        # Update next run time in config
                        hours = int(frequency.split()[0]) if schedule_type == "Frequency" and frequency else 24
                        next_run = datetime.now() + timedelta(hours=hours)
                        self.db.save_auto_publish_config({
                            **config,
                            "next_run": next_run.strftime("%Y-%m-%d %H:%M:%S")
                        })
                        
                        # Publish matching products
                        successful_count = 0
                        failed_count = 0
                        for product in filtered_products:
                            try:
                                success, message = self.publish_product(product)
                                if success:
                                    print(f"✅ Published: {product.get('product_name', 'Unknown')}")
                                    successful_count += 1
                                else:
                                    print(f"❌ Failed to publish {product.get('product_name', 'Unknown')}: {message}")
                                    failed_count += 1
                                time.sleep(5)  # Delay between publishes to avoid rate limiting
                            except Exception as publish_error:
                                print(f"❌ Error publishing {product.get('product_name', 'Unknown')}: {str(publish_error)}")
                                failed_count += 1
                        
                        print(f"Automatic publishing completed. Success: {successful_count}, Failed: {failed_count}")
                    except Exception as e:
                        print(f"❌ Error in monitor and publish job: {e}")
                        import traceback
                        print(traceback.format_exc())
                except Exception as outer_e:
                    print(f"❌ Critical error in monitor_and_publish: {outer_e}")
            
            # Save config to DB
            self.db.save_auto_publish_config(config)
            
            # Clear existing jobs for this task
            jobs = self.scheduler.get_jobs()
            for job in jobs:
                if job.tags and "auto_publish" in job.tags:
                    self.scheduler.cancel_job(job)
                    print(f"Cancelled job: {job}")
            
            # Setup new scheduler
            if schedule_type == "Frequency":
                freq_str = frequency if frequency else "6 hours"
                hours = int(freq_str.split()[0])
                job = self.scheduler.every(hours).hours.do(monitor_and_publish)
                job.tag("auto_publish")
                print(f"✅ Scheduled to run every {hours} hours")
            else:
                for time_str in times:
                    job = self.scheduler.every().day.at(time_str).do(monitor_and_publish)
                    job.tag("auto_publish")
                    print(f"✅ Scheduled to run at {time_str}")
            
            # Calculate and update next run time
            if schedule_type == "Frequency":
                freq_str = frequency if frequency else "6 hours"
                hours = int(freq_str.split()[0])
                next_run = datetime.now() + timedelta(hours=hours)
            else:
                # Find the next scheduled time
                now = datetime.now()
                today = now.date()
                next_run_datetime = None
                
                for time_str in times:
                    hours, minutes = map(int, time_str.split(":"))
                    time_today = datetime.combine(today, datetime.strptime(time_str, "%H:%M").time())
                    
                    if time_today > now:
                        if not next_run_datetime or time_today < next_run_datetime:
                            next_run_datetime = time_today
                
                # If no times today are in the future, use the first time tomorrow
                if not next_run_datetime and times:
                    tomorrow = today + timedelta(days=1)
                    hours, minutes = map(int, times[0].split(":"))
                    next_run_datetime = datetime.combine(tomorrow, datetime.strptime(times[0], "%H:%M").time())
                
                next_run = next_run_datetime if next_run_datetime else now + timedelta(days=1)
                
            # Update config with next run time
            self.db.save_auto_publish_config({
                **config,
                "next_run": next_run.strftime("%Y-%m-%d %H:%M:%S")
            })
            
            # Run immediately first time if requested
            if st.checkbox("Run immediately", value=True):
                try:
                    st.info("Running initial check now...")
                    monitor_and_publish()
                    st.success("✅ Initial check completed!")
                except Exception as e:
                    st.error(f"❌ Error during initial run: {str(e)}")
                    
            st.success("✅ Automatic publishing configured and started")
            st.rerun()  # Refresh to show updated status
        
        if stop_button:
            # Clear existing jobs for this task
            jobs = self.scheduler.get_jobs()
            for job in jobs:
                if job.tags and "auto_publish" in job.tags:
                    self.scheduler.cancel_job(job)
                    print(f"Cancelled job: {job}")
            
            # Update config status
            self.db.save_auto_publish_config({
                **auto_config,
                "active": False,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            st.success("Automatic publishing stopped")
            st.rerun()  # Refresh to show updated status

    def schedule_automatic_publish(self, frequency, start_time):
        """
        Schedule automatic publishing at the specified frequency and start time.
        """
        def automatic_publish_task():
            query = {}
            now = datetime.now()

            filters = st.session_state.get("auto_filters", {})
            if filters.get("filter_lower_than_buy_box"):
                query["$expr"] = {"$lt": ["$Product_current_price", "$Product_Buy_box_price"]}
            if filters.get("filter_never_published"):
                query["_id"] = {"$nin": [pub["product_id"] for pub in self.db.db.published_products.find({}, {"product_id": 1})]}
            if filters.get("filter_lower_than_last_published"):
                four_days_ago = now - timedelta(days=4)
                query["$and"] = [
                    {"_id": {"$in": [pub["product_id"] for pub in self.db.db.published_products.find(
                        {"timestamp": {"$gte": four_days_ago}}, {"product_id": 1})]}},
                    {"$expr": {"$lt": ["$Product_current_price", "$last_published_price"]}}
                ]
            if filters.get("filter_published_last_4_days"):
                four_days_ago = now - timedelta(days=4)
                query["_id"] = {"$in": [pub["product_id"] for pub in self.db.db.published_products.find(
                    {"timestamp": {"$gte": four_days_ago}}, {"product_id": 1})]}

            products = self.db.get_products(query)

            for product in products:
                message = (
                    f"🛍️ *{product['product_name']}*\n"
                    f"💰 *Current Price:* ₹{product['Product_current_price']}\n"
                    f"💸 *MRP:* ₹{product['Product_Buy_box_price']}\n"
                    f"🔗 [Buy Now]({product['product_Affiliate_url']})"
                )
                success, error_message = self.notification_publisher.telegram_push(message)
                if success:
                    self.db.update_product(product["Product_unique_ID"], {
                        "published_status": True,
                        "published_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    })
                    print(f"✅ Automatically Published: {product['product_name']}")
                else:
                    print(f"❌ Failed to publish {product['product_name']}: {error_message}")

        schedule.every().day.at(start_time).do(automatic_publish_task)
        schedule.every(frequency).minutes.do(automatic_publish_task)
        self.scheduled_tasks.append(automatic_publish_task)

    def render_immediate_push(self):
        try:
            # st.header("Immediate Push")

            # Get all products
            products = self.db.get_products({})
            if not products:
                st.info("No products available")
                return

            # Product selection
            selected_product_tuple = st.selectbox(
                "Select Product",
                options=[(p["product_name"], p) for p in products],
                format_func=lambda x: x[0]
            )
            selected_product = selected_product_tuple[1] if selected_product_tuple else None

            # Channel selection
            channels = st.multiselect(
                "Select Channels",
                ["Telegram", "WhatsApp"],
                default=["Telegram", "WhatsApp"]
            )

            if st.button("Push Now"):
                try:
                    if not channels:
                        st.warning("Please select at least one channel")
                        return

                    success, message = self.publish_product(selected_product)
                    if success:
                        st.success("✅ Product pushed successfully!")
                    else:
                        st.error(f"❌ Failed to push: {message}")
                finally:
                    if hasattr(self, 'notification_publisher'):
                        self.notification_publisher.close()
        except Exception as e:
            st.error(f"Error in immediate push: {e}")
            if hasattr(self, 'notification_publisher'):
                self.notification_publisher.close()

    def render_email_scheduling(self):
        st.subheader("Configure Email Schedules")

        st.markdown("### Filters")
        filter_published_last_week = st.checkbox("Published in the Last Week")
        filter_published_last_day = st.checkbox("Published in the Last Day")
        filter_custom_date_range = st.checkbox("Custom Date Range")

        start_date, end_date = None, None
        if filter_custom_date_range:
            start_date = st.date_input("Start Date")
            end_date = st.date_input("End Date")
            
            # Convert to single date objects if tuples are returned
            if isinstance(start_date, tuple) and start_date:
                start_date = start_date[0]
            if isinstance(end_date, tuple) and end_date:
                end_date = end_date[0]

        st.markdown("### Email Configuration")
        recipient_emails = st.text_input("Recipient Emails (comma-separated)")
        email_subject = st.text_input("Email Subject", "Scheduled Product Report")
        email_body = st.text_area("Email Body", "Please find the attached product report.")

        st.markdown("### Schedule Configuration")
        schedule_frequency = st.selectbox("Frequency", ["Daily", "Weekly", "Monthly"])
        schedule_time = st.time_input("Time")

        if st.button("Save Email Schedule"):
            if not recipient_emails:
                st.error("Recipient emails are required.")
                return
                
            # Parse recipient emails
            recipients = [email.strip() for email in recipient_emails.split(",") if email.strip()]
            
            # Create schedule config
            schedule_config = {
                "filters": {
                    "published_last_week": filter_published_last_week,
                    "published_last_day": filter_published_last_day,
                    "custom_date_range": {
                        "start_date": start_date.strftime("%Y-%m-%d") if start_date and hasattr(start_date, "strftime") else None,
                        "end_date": end_date.strftime("%Y-%m-%d") if end_date and hasattr(end_date, "strftime") else None,
                    }
                },
                "email": {
                    "recipients": recipients,
                    "subject": email_subject,
                    "body": email_body,
                },
                "schedule": {
                    "frequency": schedule_frequency,
                    "time": schedule_time.strftime("%H:%M"),
                }
            }

            self.db.save_email_schedule(schedule_config)
            st.success("✅ Email schedule saved successfully!")

        st.markdown("### Existing Schedules")
        schedules = self.db.get_email_schedules()
        if not schedules:
            st.info("No email schedules configured.")
        else:
            for i, schedule in enumerate(schedules):
                with st.expander(f"Schedule {i + 1}"):
                    st.json(schedule)
                    if st.button(f"Delete Schedule {i + 1}", key=f"delete_schedule_{i}"):
                        self.db.delete_email_schedule(schedule["_id"])
                        st.success("✅ Schedule deleted successfully!")

    def publish_product(self, product):
        """Common function to publish a product"""
        try:
            # Prepare product message
            message = (
                f"🛍️ {product.get('product_name', 'Product')}\n"
                f"💰 Deal Price: ₹{product.get('Product_current_price', 'N/A')}\n"
                f"💸 MRP: ₹{product.get('Product_Buy_box_price', 'N/A')}\n"
                f"🔗 [Buy Now]({product.get('product_Affiliate_url', '#')})"
            )
            
            # List to track successful channels
            channels = []
            errors = []
            
            # Initialize publisher if needed
            if not hasattr(self, 'notification_publisher'):
                self.notification_publisher = NotificationPublisher(self.config_manager)
            
            # Send to Telegram
            telegram_success, telegram_error = self.notification_publisher.telegram_push(message, product.get("Product_image_path"))
            if telegram_success:
                channels.append("telegram")
            else:
                errors.append(f"Telegram: {telegram_error}")
                print(f"❌ Telegram push failed: {telegram_error}")  # Print to console
            
            # Send to WhatsApp channels
            whatsapp_channel_names = self.config_manager.get_whatsapp_config().get("channel_names", "")
            if whatsapp_channel_names:
                # Initialize WhatsApp sender for fresh session
                try:
                    from utils.whatsapp_sender import WhatsappSender
                    whatsapp = WhatsappSender()
                except Exception as e:
                    errors.append(f"WhatsApp initialization failed: {str(e)}")
                    print(f"❌ Failed to initialize WhatsApp: {str(e)}")
                
                # Send to each configured channel
                for channel in whatsapp_channel_names.split(","):
                    channel = channel.strip()
                    if channel:
                        try:
                            # Process each channel with a fresh session
                            if self.notification_publisher.whatsapp_push(product, channel, message, is_channel=True):
                                channels.append(f"whatsapp_channel_{channel}")
                            else:
                                errors.append(f"WhatsApp: Failed to send to channel {channel}")
                                print(f"❌ Failed to send to WhatsApp channel: {channel}")
                        except Exception as e:
                            errors.append(f"WhatsApp channel error: {str(e)}")
                            print(f"❌ WhatsApp channel error: {str(e)}")
                            
                        # Close the driver after each channel to ensure clean state
                        try:
                            if hasattr(self.notification_publisher, 'whatsapp_sender'):
                                self.notification_publisher.whatsapp_sender._save_cookies()
                                if self.notification_publisher.whatsapp_sender.driver:
                                    self.notification_publisher.whatsapp_sender.driver.quit()
                                    self.notification_publisher.whatsapp_sender.driver = None
                        except:
                            pass
            
            # Send to WhatsApp groups
            whatsapp_group_names = self.config_manager.get_whatsapp_config().get("group_names", "")
            if whatsapp_group_names:
                # Initialize a fresh WhatsApp sender for groups
                try:
                    from utils.whatsapp_sender import WhatsappSender
                    whatsapp = WhatsappSender()
                except Exception as e:
                    errors.append(f"WhatsApp initialization failed: {str(e)}")
                    print(f"❌ Failed to initialize WhatsApp: {str(e)}")
                
                # Send to each configured group
                for group in whatsapp_group_names.split(","):
                    group = group.strip()
                    if group:
                        try:
                            # Process each group with a fresh session
                            if self.notification_publisher.whatsapp_push(product, group, message, is_channel=False):
                                channels.append(f"whatsapp_group_{group}")
                            else:
                                errors.append(f"WhatsApp: Failed to send to group {group}")
                                print(f"❌ Failed to send to WhatsApp group: {group}")
                        except Exception as e:
                            errors.append(f"WhatsApp group error: {str(e)}")
                            print(f"❌ WhatsApp group error: {str(e)}")
                        
                        # Close the driver after each group to ensure clean state
                        try:
                            if hasattr(self.notification_publisher, 'whatsapp_sender'):
                                self.notification_publisher.whatsapp_sender._save_cookies()
                                if self.notification_publisher.whatsapp_sender.driver:
                                    self.notification_publisher.whatsapp_sender.driver.quit()
                                    self.notification_publisher.whatsapp_sender.driver = None
                        except:
                            pass
            
            # Update product status
            products_data_update = {
                "published_status": True,
                "Publish": False,
                "Publish_time": None,
                "Last_published_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "last_published_price": product.get("Product_current_price"),  # Store current price for future comparisons
                "published_channels": channels
            }
            
            # Update database
            self.db.update_product(product.get("Product_unique_ID"), products_data_update)
            
            # Record in published_products collection
            published_data = {
                "product_id": product.get("Product_unique_ID"),
                "product_name": product.get("product_name"),
                "published_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "channels": channels,
                "message": message,
                "product_price": product.get("Product_current_price"),
                "errors": errors if errors else None
            }
            self.db.db.published_products.insert_one(published_data)
            
            if errors:
                return True, "Published with some errors: " + ", ".join(errors)
            self._cleanup_whatsapp_drivers()  # Clean up all driver instances after publishing
            return True, "Published successfully to " + ", ".join(channels)
            
        except Exception as e:
            print(f"❌ Publishing error: {str(e)}")
            return False, str(e)

    def process_scheduled_publishing(self):
        """Process products scheduled for publishing."""
        now = datetime.now()
        
        # Get all products scheduled for current time
        scheduled_products = self.db.get_products({
            "Publish": True,
            "published_status": {"$ne": True},
            "Publish_time": {"$lte": now.strftime("%Y-%m-%d %H:%M:%S")}
        })

        if not scheduled_products:
            print("No products scheduled for publishing.")
            return

        print(f"Found {len(scheduled_products)} products to publish")
        
        try:
            # Process each product with delay to avoid rate limits
            for product in scheduled_products:
                success, message = self.publish_product(product)
                if success:
                    print(f"✅ Published: {product['product_name']}")
                else:
                    print(f"❌ Failed to publish {product['product_name']}: {message}")
                
                # Add delay between products to avoid rate limits
                time.sleep(5)  # 5 second delay between products
                
        except Exception as e:
            print(f"Error in scheduled publishing: {e}")

    def _cleanup_whatsapp_drivers(self):
        """Kill all active WhatsApp driver instances stored in session state"""
        # First clean up session state drivers
        if 'whatsapp_drivers' in st.session_state:
            for driver in st.session_state.whatsapp_drivers:
                try:
                    if driver:
                        driver.quit()
                        print("WhatsApp driver instance closed from session state")
                except Exception as e:
                    print(f"Error closing session state driver: {e}")
            st.session_state.whatsapp_drivers = []
        
        # Then clean up notification publisher driver if it exists
        if hasattr(self, 'notification_publisher') and hasattr(self.notification_publisher, 'whatsapp_sender'):
            try:
                if self.notification_publisher.whatsapp_sender and hasattr(self.notification_publisher.whatsapp_sender, 'driver'):
                    if self.notification_publisher.whatsapp_sender.driver:
                        self.notification_publisher.whatsapp_sender.driver.quit()
                        self.notification_publisher.whatsapp_sender.driver = None
                        print("WhatsApp sender driver closed")
            except Exception as e:
                print(f"Error closing notification publisher driver: {e}")

def run_scheduler():
    while True:
        schedule.run_pending()
        time.sleep(1)

scheduler_thread = Thread(target=run_scheduler, daemon=True)
scheduler_thread.start()