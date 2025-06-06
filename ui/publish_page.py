import streamlit as st
import pandas as pd
from datetime import datetime, timedelta, time
import time as time_module
from threading import Thread
from db.db_manager import DataManager
from notification_publisher import NotificationPublisher
import uuid
import schedule
import traceback
from monitors.amazon_monitor import AmazonIndiaMonitor
import sys
import os

class PublishPage:
    def __init__(self, config_manager):
        self.db = DataManager()
        self.notification_publisher = NotificationPublisher(config_manager)
        self.config_manager = config_manager
        # Initialize scheduler properly
        self.scheduler = schedule
        self.scheduled_tasks = []
        # Add a flag to track running jobs
        if "auto_publish_running" not in st.session_state:
            st.session_state.auto_publish_running = False
 
    def __del__(self):
        """Cleanup resources when page is destroyed"""
        try:
            if hasattr(self, 'notification_publisher'):
                self.notification_publisher.close()
            # Also clean up any WebDriver instances
            self._cleanup_whatsapp_drivers()
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
        # Get unpublished products - improved query to catch ALL unpublished products
        products = self.db.get_products({
            # "$or": [
            #     {"published_status": {"$ne": True}},
            #     {"published_status": {"$exists": False}}
            # ]
        })
        
        if not products:
            st.info("No products available for publishing")
            return

        # Create product selection dataframe
        df = pd.DataFrame(products)
        
        # Add diagnostics
        st.write(f"Found {len(products)} unpublished products")
        
        # Use session state to track selection state but with better sync
        if "selected_products" not in st.session_state:
            st.session_state.selected_products = df.copy()
            st.session_state.selected_products["Select"] = False
        else:
            # Create a new DataFrame with all current products
            new_df = df.copy()
            new_df["Select"] = False
            
            # If we have existing selections, preserve them by product ID
            if "Product_unique_ID" in df.columns and "Product_unique_ID" in st.session_state.selected_products.columns:
                # Create a mapping of product IDs to their selection status
                selection_map = {
                    row["Product_unique_ID"]: row["Select"] 
                    for _, row in st.session_state.selected_products.iterrows()
                    if "Product_unique_ID" in row and "Select" in row
                }
                
                # Apply selections from the map to the new DataFrame
                for i, row in new_df.iterrows():
                    if "Product_unique_ID" in row and row["Product_unique_ID"] in selection_map:
                        new_df.at[i, "Select"] = selection_map[row["Product_unique_ID"]]
        
            # Update the session state with the new DataFrame
            st.session_state.selected_products = new_df
    
        # Continue with the rest of your existing code...
        col1, col2 = st.columns(2)
        with col1:
            if st.button("Select All"):
                st.session_state.selected_products["Select"] = True
        with col2:
            if st.button("Clear Selection"):
                st.session_state.selected_products["Select"] = False
        
        # Create a new DataFrame with the desired column order
        display_df = st.session_state.selected_products.copy()
        
        # Select the columns you want to display in the desired order
        columns_to_display = ["Select", "product_name", "Product_unique_ID", "product_major_category", 
                             "product_minor_category", "Product_current_price", "Product_Buy_box_price"]
        
        # Make sure all columns exist in the dataframe
        available_columns = [col for col in columns_to_display if col in display_df.columns]
        
        # Add any remaining columns at the end
        remaining_columns = [col for col in display_df.columns if col not in available_columns and col != "Select"]
        display_columns = available_columns + remaining_columns
        
        # Display the editor with rearranged columns
        edited_df = st.data_editor(
            display_df[display_columns],
            hide_index=True,
            column_config={
                "Select": st.column_config.CheckboxColumn("Select"),
                "product_name": st.column_config.TextColumn("Product Name"),
                "Product_current_price": st.column_config.NumberColumn("Current Price"),
                "Product_Buy_box_price": st.column_config.NumberColumn("Buy Box Price"),
                "product_mrp": st.column_config.NumberColumn("MRP"),
                "Product_unique_ID": st.column_config.TextColumn("ASIN"),
                "product_major_category": st.column_config.TextColumn("Category"),
                "product_minor_category": st.column_config.TextColumn("Sub-category")
            }
        )
        
        # Update the session state with edited values
        st.session_state.selected_products = edited_df

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
                selected_products = edited_df[edited_df["Select"] == True].to_dict('records')
                if not selected_products:
                    st.warning("Please select products to publish")
                    return

                # Convert time to 24hr format
                try:
                    publish_time = datetime.strptime(f"{hour}:{minute} {am_pm}", "%I:%M %p")
                    schedule_time = publish_time.strftime("%H:%M")

                    # Store in DB with scheduled time
                    for product in selected_products:
                        self.db.update_product(product['Product_unique_ID'], {
                            "Publish": True,
                            "Publish_time": schedule_time,
                            "published_status": False
                        })
                    
                    st.success(f"✅ Scheduled {len(selected_products)} products for {schedule_time}")
                except Exception as e:
                    st.error(f"Error scheduling products: {str(e)}")
        
        with col2:
            st.subheader("Publish Immediately")
            
            channels = st.multiselect(
                "Select Channels", 
                ["Telegram", "WhatsApp"], 
                default=["Telegram", "WhatsApp"],
                key="immediate_channels"
            )
            
            if st.button("Push Now", type="primary"):
                selected_products = edited_df[edited_df["Select"] == True].to_dict('records')
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
                    
                    time_module.sleep(1)
                
                # Show final result
                if success_count > 0:
                    st.success(f"✅ Successfully published {success_count} products!")
                if failed_count > 0:
                    st.warning(f"⚠️ Failed to publish {failed_count} products. See errors above.")

    def render_automatic_publish(self):
        """
        Render the Automatic Publish tab with improved filtering, scheduling and execution logic
        """
        st.subheader("Automatic Publish Configuration")
        
        # Load existing configuration
        auto_config = self.db.get_auto_publish_config()
        
        # RESET THE ACTIVE STATUS: Add this line to force inactive state on page load
        if not st.session_state.get("auto_publish_status_preserved", False):
            auto_config["active"] = False
            self.db.save_auto_publish_config(auto_config)
            st.session_state.auto_publish_status_preserved = True
            
        saved_filters = auto_config.get("filters", {})
        is_active = auto_config.get("active", False)
        
        # Filter criteria expander with checkboxes as requested
        with st.expander("📋 Publishing Criteria", expanded=True):
            price_change = st.checkbox(
                "Price change should be there", 
                value=bool(saved_filters.get("price_change", True)),
                help="Only publish products that have a recent price change"
            )
            
            # Add time window configuration if price change is enabled
            price_change_hours = 24
            price_change_strict = False
            include_price_logs = False
            
            if price_change:
                col1, col2 = st.columns(2)
                with col1:
                    price_change_hours = st.number_input(
                        "Price change time window (hours)",
                        min_value=1,
                        max_value=72,
                        value=int(saved_filters.get("price_change_hours", 24)),
                        step=1,
                        help="Only consider price changes that occurred within this many hours"
                    )
                with col2:
                    price_change_strict = st.checkbox(
                        "Strict mode",
                        value=bool(saved_filters.get("price_change_strict", False)),
                        help="If checked, stops if no price changes found. If unchecked, continues with all products."
                    )
            
                # New checkbox for including price change logs
                include_price_logs = st.checkbox(
                    "Include detailed price change logs",
                    value=bool(saved_filters.get("include_price_logs", False)),
                    help="Include detailed logs of price changes from Amazon monitor"
                )
            
            # Rest of the checkboxes remain the same
            never_published = st.checkbox(
                "Never published before", 
                value=bool(saved_filters.get("never_published", True)),
                help="Automatically publish products that have never been published"
            )
            price_dropped = st.checkbox(
                "Price dropped since last publish", 
                value=bool(saved_filters.get("price_dropped", True)),
                help="Only republish if price has dropped since last publication"
            )
            not_recent = st.checkbox(
                "Not published recently (4 days)", 
                value=bool(saved_filters.get("not_recent", True)),
                help="Publish products not published within 4 days"
            )

        # Deliverables selection
        st.header("📢 Deliverables")
        channels = st.multiselect(
            "Select channels to publish to",
            options=["Telegram", "WhatsApp"],
            default=auto_config.get("channels", ["Telegram"]),
            help="Choose where to publish products"
        )
        
        # Frequency setting
        frequency = st.number_input(
            "Check Frequency (minutes)",
            min_value=1,
            max_value=59,
            value=int(auto_config.get("frequency", 30)),
            step=1,
            help="How often to check for publishable products"
        )

        # Start/Stop buttons
        col1, col2 = st.columns(2)
        with col1:
            start_button = st.button(
                "▶️ Start Auto Publishing", 
                disabled=is_active,
                type="primary"
            )
        with col2:
            stop_button = st.button(
                "🛑 Stop Auto Publishing", 
                disabled=not is_active,
                type="secondary"
            )

        # Status display
        status_color = "green" if is_active else "red"
        status_text = "ACTIVE" if is_active else "INACTIVE"
        st.markdown(f"<h3>Current Status: <span style='color:{status_color};'>{status_text}</span></h3>", unsafe_allow_html=True)
        
        # Show next run time if active
        if is_active:
            next_run_time = auto_config.get("next_run", "Unknown")
            try:
                next_run_dt = datetime.strptime(next_run_time, "%Y-%m-%d %H:%M:%S")
                next_run_time = next_run_dt.strftime("%Y-%m-%d %I:%M %p")
            except:
                pass
        
            st.info(f"Next scheduled run: {next_run_time}")
            
            # Display upcoming schedule details
            with st.expander("⏱️ Upcoming Schedule Details", expanded=True):
                upcoming_schedules = {
                    "frequency_minutes": frequency,
                    "next_run": next_run_time,
                    "filters": {
                        "price_change": price_change,
                        "never_published": never_published,
                        "price_dropped": price_dropped,
                        "not_recent": not_recent
                    },
                    "channels": channels
                }
                st.json(upcoming_schedules)
            
            # Display last run logs
            if "last_run_log" in auto_config:
                with st.expander("📜 Last Run Logs"):
                    last_run = auto_config.get("last_run_log", {})
                    log_file = last_run.get("log_file")
                    summary_file = last_run.get("summary_file")
                    
                    # Add log file browser
                    st.subheader("Browse Log Files")
                    
                    # Find all log files in the logs directory
                    try:
                        all_log_files = []
                        if os.path.exists("logs"):
                            all_log_files = [f for f in os.listdir("logs") if f.startswith("auto_publish_") or f.startswith("summary_")]
                            # Sort by creation time (newest first)
                            all_log_files.sort(key=lambda f: os.path.getmtime(os.path.join("logs", f)), reverse=True)
                        
                        # Get the default file to display (current log or most recent)
                        default_log = None
                        if log_file and os.path.exists(log_file):
                            default_log = os.path.basename(log_file)
                        elif all_log_files:
                            default_log = all_log_files[0]
                            
                        if all_log_files:
                            selected_log = st.selectbox(
                                "Select Log File", 
                                all_log_files,
                                index=all_log_files.index(default_log) if default_log in all_log_files else 0,
                                format_func=lambda x: f"{x} - {datetime.fromtimestamp(os.path.getmtime(os.path.join('logs', x))).strftime('%Y-%m-%d %H:%M:%S')}"
                            )
                            
                            # Display the selected log file
                            if selected_log:
                                selected_path = os.path.join("logs", selected_log)
                                if os.path.exists(selected_path):
                                    with open(selected_path, 'r', encoding='utf-8') as f:
                                        log_content = f.read()
                                    if selected_log.startswith("summary_"):
                                        st.text_area("Summary", log_content, height=300, disabled=True)
                                    else:
                                        st.text_area("Log Content", log_content, height=300, disabled=True)
                        else:
                            st.info("No log files found in logs directory.")
                    except Exception as e:
                        st.error(f"Error loading log files: {str(e)}")
                    
                    # First show the summary if available (keep existing code as a fallback)
                    if summary_file and os.path.exists(summary_file):
                        st.subheader("Latest Run Summary")
                        with open(summary_file, 'r') as f:
                            summary_content = f.read()
                        st.text_area("Summary", summary_content, height=200, disabled=True)
                    
                    # Summary statistics 
                    st.subheader("Latest Run Statistics")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Run Time:** {last_run.get('time', 'Unknown')}")
                        st.write(f"**Duration:** {last_run.get('duration_seconds', 0):.2f} seconds")
                    with col2:
                        st.write(f"**Products Checked:** {last_run.get('products_checked', 0)}")
                        st.write(f"**Products Published:** {last_run.get('published', 0)}")

        # Handle start button
        if start_button:
            if not channels:
                st.error("Please select at least one channel for publishing")
                return
                
            # Prepare filters
            filters = {
                "price_change": price_change,
                "price_change_hours": price_change_hours,
                "price_change_strict": price_change_strict,  # Add this line
                "never_published": never_published,
                "price_dropped": price_dropped,
                "not_recent": not_recent,
                "days_threshold": 4
            }
            
            # Calculate next run time
            next_run = datetime.now() + timedelta(minutes=frequency)
            
            # Save configuration
            config = {
                "filters": filters,
                "channels": channels,
                "frequency": frequency,
                "active": True,
                "next_run": next_run.strftime("%Y-%m-%d %H:%M:%S"),
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            
            # Preserve last_run_log if it exists
            if "last_run_log" in auto_config:
                config["last_run_log"] = auto_config["last_run_log"]
                
            # Save the config
            self.db.save_auto_publish_config(config)
            
            # Show toast and run immediately if requested
            st.toast("Automatic publishing started", icon="🚀")
            
            # Run immediately first time
            if st.checkbox("Run immediately", value=True):
                st.info("Running initial check now...")
                try:
                    # Fix buy box prices before running
                    self.ensure_valid_buybox_prices()
                    self.auto_publish_job(filters, channels)
                    st.success("✅ Initial run completed successfully!")
                except Exception as e:
                    st.error(f"❌ Error during initial run: {str(e)}")
                    
            st.success("✅ Automatic publishing configured and started")
            st.rerun()
            
        # Handle stop button
        if stop_button:
            # Update config to inactive
            self.db.save_auto_publish_config({
                **auto_config,
                "active": False,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            st.toast("Automatic publishing stopped", icon="🛑")
            st.success("Automatic publishing stopped")
            st.rerun()

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
                        "enabled": filter_custom_date_range,
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
                    "time": schedule_time.strftime("%H:%M") if hasattr(schedule_time, "strftime") else "00:00",
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
                        self.db.delete_email_schedule(schedule.get("_id"))
                        st.success("✅ Schedule deleted successfully!")
                        st.rerun()

    def render_immediate_push(self):
        try:
            # Get all products
            products = self.db.get_products({})
            if not products:
                st.info("No products available")
                return

            # Product selection
            selected_product_tuple = st.selectbox(
                "Select Product",
                options=[(p.get("product_name", "Unknown"), p) for p in products],
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

    def publish_product(self, product):
        """
        Common function to publish a product to selected channels
        :param product: Dictionary containing product details
        :return: (success, message) tuple
        """
        try:
            # Initialize publisher if needed
            if not hasattr(self, 'notification_publisher'):
                self.notification_publisher = NotificationPublisher(self.config_manager)
            
            # Generate formatted message using the centralized format function
            message = self.notification_publisher.format_product_message(product)
            
            # Track successful channels and errors
            successful_channels = []
            errors = []
            
            # Get the selected channels from session state
            selected_channels = st.session_state.get("immediate_channels", ["Telegram"])
            
            # Send to Telegram ONLY IF selected
            if "Telegram" in selected_channels:
                telegram_success, telegram_error = self.notification_publisher.telegram_push(
                    message, 
                    product.get("Product_image_path")
                )
                if telegram_success:
                    successful_channels.append("Telegram")
                else:
                    errors.append(f"Telegram: {telegram_error}")
                    print(f"❌ Telegram push failed: {telegram_error}")
            
            # Send to WhatsApp ONLY IF selected
            if "WhatsApp" in selected_channels:
                whatsapp_config = self.config_manager.get_whatsapp_config()
                if not whatsapp_config:
                    errors.append("WhatsApp: Configuration not found")
                else:
                    # Get channel and group configurations
                    whatsapp_channels = whatsapp_config.get("channel_names", "").split(",") if whatsapp_config.get("channel_names") else []
                    whatsapp_groups = whatsapp_config.get("group_names", "").split(",") if whatsapp_config.get("group_names") else []
                    
                    # Process each channel and group
                    for channel_type, items in [("channel", whatsapp_channels), ("group", whatsapp_groups)]:
                        for item in items:
                            item = item.strip()
                            if not item:
                                continue

                            try:
                                # Initialize fresh WhatsApp sender for each send to avoid session issues
                                is_channel = (channel_type == "channel")
                                if self.notification_publisher.whatsapp_push(product, item, message, is_channel=is_channel):
                                    successful_channels.append(f"WhatsApp {channel_type}: {item}")
                                else:
                                    errors.append(f"WhatsApp: Failed to send to {channel_type} {item}")
                            except Exception as e:
                                errors.append(f"WhatsApp {channel_type} error: {str(e)}")
                                print(f"❌ WhatsApp {channel_type} error: {str(e)}")
            
            # Clean up WhatsApp driver after each operation
            self._cleanup_whatsapp_drivers()

            # Update product status in database
            product_id = product.get("Product_unique_ID")
            if product_id:
                # Update the product record
                self.db.update_product(product_id, {
                    "published_status": True,
                    "Publish": False,
                    "Publish_time": None,
                    "Last_published_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "last_published_price": product.get("Product_current_price"),
                    "published_channels": successful_channels
                })
                
                # Record in the publications collection
                self.db.db.published_products.insert_one({
                    "product_id": product_id,
                    "product_name": product.get("product_name"),
                    "product_price": product.get("Product_current_price"),
                    "published_date": datetime.now(),
                    "channels": successful_channels,
                    "message": message,
                    "errors": errors if errors else None
                })
                
                if successful_channels:
                    return True, f"Published to {', '.join(successful_channels)}"
                else:
                    return False, f"Failed to publish to any channels: {'; '.join(errors)}"
            else:
                return False, "Product ID is missing"
            
        except Exception as e:
            print(f"❌ Error in publish_product: {str(e)}")
            traceback.print_exc()
            return False, f"Error: {str(e)}"

    def _cleanup_whatsapp_drivers(self):
        """Clean up any WhatsApp web driver instances that might be in session"""
        try:
            # Clean up session state drivers if they exist
            if 'whatsapp_drivers' in st.session_state:
                for driver in st.session_state.whatsapp_drivers:
                    try:
                        if driver:
                            driver.quit()
                            print("WhatsApp driver instance closed from session state")
                    except Exception as e:
                        print(f"Error closing driver: {e}")
                st.session_state.whatsapp_drivers = []
        
            # Also make sure the notification_publisher's WhatsApp sender is cleaned up
            if hasattr(self, 'notification_publisher') and hasattr(self.notification_publisher, '_whatsapp_sender') and self.notification_publisher._whatsapp_sender:
                try:
                    # Save cookies before closing for session persistence
                    sender = self.notification_publisher._whatsapp_sender
                    if sender and hasattr(sender, 'driver') and sender.driver:
                        if hasattr(sender, '_save_cookies'):
                            sender._save_cookies()
                        sender.driver.quit()
                        sender.driver = None
                except Exception as e:
                    print(f"Error closing WhatsApp driver: {e}")
        except Exception as e:
            print(f"Error in cleanup: {e}")

    def ensure_valid_buybox_prices(self):
        """
        Ensures all products have valid Buy Box prices that are higher than their current prices.
        This function fixes the common issue where Buy Box prices are not properly set or 
        are lower than current prices, which prevents products from being published.
        """
        try:
            db = DataManager()
            all_products = list(db.products.find({}))
            
            print(f"🔍 Checking buy box prices for {len(all_products)} products...")
            updated_count = 0
            skipped_count = 0
            error_count = 0
            
            for product in all_products:
                product_id = product.get("Product_unique_ID")
                product_name = product.get("product_name", "Unknown")
                
                if not product_id:
                    print(f"⚠️ Skipping product without ID: {product_name}")
                    skipped_count += 1
                    continue
                    
                try:
                    current_price = product.get("Product_current_price")
                    buy_box_price = product.get("Product_Buy_box_price")
                    mrp = product.get("Product_MRP")
                    
                    # Skip if no current price available
                    if current_price is None:
                        print(f"⚠️ Skipping {product_name} (ID: {product_id}): No current price")
                        skipped_count += 1
                        continue
                        
                    # Convert prices to float for proper comparison
                    try:
                        current_price = float(current_price)
                    except (ValueError, TypeError):
                        print(f"⚠️ Invalid current price for {product_name}: {current_price}")
                        skipped_count += 1
                        continue
                    
                    # Check if buy box price exists and is properly set
                    needs_update = False
                    new_buy_box = None
                    
                    # Case 1: Buy box is missing or None
                    if buy_box_price is None:
                        needs_update = True
                        # Set buy box 10% higher than current price
                        new_buy_box = current_price * 1.1
                        print(f"📈 Setting buy box for {product_name}: No buy box price found")
                        
                    # Case 2: Buy box is not a proper number
                    elif not isinstance(buy_box_price, (int, float, str)) or (isinstance(buy_box_price, str) and not buy_box_price.strip()):
                        needs_update = True
                        new_buy_box = current_price * 1.1
                        print(f"🔄 Correcting invalid buy box price for {product_name}: {buy_box_price}")
                        
                    # Case 3: Buy box is a string that needs conversion
                    elif isinstance(buy_box_price, str):
                        try:
                            buy_box_float = float(buy_box_price)
                            # If buy box isn't higher than current price, update it
                            if buy_box_float <= current_price:
                                needs_update = True
                                new_buy_box = current_price * 1.1
                                print(f"📊 Adjusting buy box for {product_name}: {buy_box_float} → {new_buy_box:.2f} (current: {current_price})")
                        except (ValueError, TypeError):
                            needs_update = True
                            new_buy_box = current_price * 1.1
                            print(f"🔄 Converting invalid buy box value for {product_name}: {buy_box_price}")
                            
                    # Case 4: Buy box is numeric but not higher than current price
                    elif float(buy_box_price) <= current_price:
                        needs_update = True
                        new_buy_box = current_price * 1.1
                        print(f"📊 Adjusting buy box for {product_name}: {float(buy_box_price)} → {new_buy_box:.2f} (current: {current_price})")
                    
                    # If MRP is available, make sure buy box doesn't exceed it
                    if needs_update and mrp is not None and new_buy_box is not None:
                        try:
                            mrp_float = float(mrp)
                            if new_buy_box > mrp_float:
                                new_buy_box = mrp_float * 0.98  # Set just below MRP
                                # But still ensure it's higher than current price
                                if new_buy_box <= current_price:
                                    new_buy_box = current_price * 1.05  # Minimum 5% markup
                        except (ValueError, TypeError):
                            # Invalid MRP, ignore this constraint
                            pass
                    
                    # Update database if needed
                    if needs_update:
                        db.update_product(product_id, {
                            "Product_Buy_box_price": new_buy_box
                        })
                        updated_count += 1
                    
                except Exception as e:
                    print(f"❌ Error processing {product_name}: {str(e)}")
                    error_count += 1
            
            print(f"✅ Buy box price check complete:")
            print(f"   - {updated_count} products updated")
            print(f"   - {skipped_count} products skipped")
            print(f"   - {error_count} errors encountered")
            
            return updated_count > 0  # Return True if any products were updated
            
        except Exception as e:
            print(f"❌ Critical error in ensure_valid_buybox_prices: {str(e)}")
            return False

    def auto_publish_job(self, filters, channels):
        """Automatic publishing job that checks for eligible products and publishes them"""
        # Check if another job is already running
        if st.session_state.auto_publish_running:
            print("[AutoPublish] Previous job still running, skipping this execution")
            return
        
        try:
            # Set running flag
            st.session_state.auto_publish_running = True
            job_start_time = datetime.now()
            
            # Create log filename with timestamp for persistence
            log_filename = f"logs/auto_publish_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            os.makedirs("logs", exist_ok=True)
            
            run_log = {
                "time": job_start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "products_checked": 0,
                "published": 0,
                "skipped": 0,
                "failed": 0,
                "skipped_reasons": {},
                "published_products": [],
                "detailed_logs": [],
                "log_file": log_filename
            }
            
            # Log function to add to detailed logs and also write to file
            def add_log(message):
                timestamp = datetime.now().strftime("%H:%M:%S")
                log_entry = f"[{timestamp}] {message}"
                print(log_entry)
                run_log["detailed_logs"].append(log_entry)
                # Also write to log file for persistence
                with open(log_filename, 'a') as f:
                    f.write(log_entry + "\n")

            add_log(f"Starting automatic publishing job...")
            
            try:
                # Fix buy box prices at the beginning of each run
                add_log("Checking and fixing buy box prices before monitoring...")
                updated = self.ensure_valid_buybox_prices()
                if updated:
                    add_log("✅ Buy box prices were adjusted for some products to ensure proper filtering")
                
                db = DataManager()
                
                # First apply base filter: current price < buy box price
                add_log("Applying base filter: Current price < Buy box price")
                base_query = {"$expr": {"$lt": ["$Product_current_price", "$Product_Buy_box_price"]}}
                candidate_products = list(db.get_products(base_query))
                
                if not candidate_products:
                    add_log("⚠️ No products found where current price < buy box price. Checking will stop here.")
                    run_log["products_checked"] = 0
                    run_log["skipped"] = 0
                    return
                
                # Extract product IDs of candidates
                candidate_ids = [p.get("Product_unique_ID") for p in candidate_products if p.get("Product_unique_ID")]
                add_log(f"Found {len(candidate_ids)} products with current price < buy box price")
                
                # Track how many products we've checked
                run_log["products_checked"] = len(candidate_products)
                
                # Define batch size for processing
                batch_size = 10  # Process 10 products at a time to avoid overloading APIs
                
                # Initialize products_with_price_changes list
                products_with_price_changes = []
                
                # Only update prices if we need to check for price changes
                if filters.get("price_change", True):
                    add_log("'Price change should be there' filter is enabled - checking for price changes...")
                    
                    # Get the time window for price changes
                    price_change_hours = filters.get("price_change_hours", 24)
                    change_cutoff_time = datetime.now() - timedelta(hours=price_change_hours)
                    add_log(f"Price change time window: {price_change_hours} hours (since {change_cutoff_time.strftime('%Y-%m-%d %H:%M:%S')})")
                    
                    # Check products for price changes
                    for product in candidate_products:
                        product_id = product.get("Product_unique_ID")
                        product_name = product.get("product_name", "Unknown")
                        current_price = product.get("Product_current_price")
                        
                        # Check if this product has a price_changed_at timestamp within our window
                        last_change_time = product.get("price_changed_at")
                        try:
                            if last_change_time:
                                # Convert to datetime if it's a string
                                if isinstance(last_change_time, str):
                                    last_change_time = datetime.strptime(last_change_time, "%Y-%m-%d %H:%M:%S")
                                
                                # Check if it's recent enough
                                if last_change_time >= change_cutoff_time:
                                    old_price = product.get("previous_price", "Unknown")
                                    add_log(f"✅ Price change detected for {product_name}: Previous price: ₹{old_price}, Current price: ₹{current_price}")
                                    products_with_price_changes.append(product)
                        except Exception as e:
                            add_log(f"⚠️ Error checking price change time for {product_name}: {str(e)}")
                            
                    # Log how many products have price changes
                    add_log(f"Found {len(products_with_price_changes)} products with price changes in the last {price_change_hours} hours")
                    
                    # If strict mode is enabled and no price changes, stop
                    if filters.get("price_change_strict", False) and not products_with_price_changes:
                        add_log("⚠️ No price changes found and strict mode is enabled. Stopping the process.")
                        run_log["skipped"] = run_log["products_checked"]
                        return
                        
                    # In strict mode, only use products with price changes
                    if filters.get("price_change_strict", False) and products_with_price_changes:
                        add_log(f"Strict mode: Filtering to only {len(products_with_price_changes)} products with recent price changes")
                        all_products = products_with_price_changes
                    else:
                        # In non-strict mode, keep using all candidates
                        all_products = candidate_products
                else:
                    add_log("'Price change should be there' filter is disabled - using existing prices")
                    all_products = candidate_products
                
                # Continue with the existing filtering logic
                if len(all_products) == 0:
                    add_log("⚠️ No products found matching all filters.")
                    run_log["skipped"] = run_log["products_checked"]
                    return
                
                # Get all published products for reference
                published_records = list(db.db.published_products.find(
                    {}, {"product_id": 1, "product_price": 1, "published_date": 1}
                ))
                add_log(f"Found {len(published_records)} publishing history records")
                
                # Create lookup dictionaries for efficient filtering
                never_published_ids = set()
                published_product_prices = {}  # {product_id: [(price, date), ...]}
                
                # Process all products to find those never published
                for product in all_products:
                    product_id = product.get("Product_unique_ID")
                    
                    # Skip products without ID
                    if not product_id:
                        continue
                        
                    # Find publication history for this product
                    product_history = []
                    for record in published_records:
                        if record.get("product_id") == product_id:
                            pub_date = record.get("published_date")
                            price = record.get("product_price")
                            if pub_date and price:
                                product_history.append((price, pub_date))
                    
                    # Sort by date, newest first
                    product_history.sort(key=lambda x: x[1], reverse=True)
                    
                    # Store in lookup dict
                    if product_history:
                        published_product_prices[product_id] = product_history
                    else:
                        never_published_ids.add(product_id)
                
                add_log(f"Products never published before: {len(never_published_ids)}")
                add_log(f"Products with publication history: {len(published_product_prices)}")
                
                # Check which filters are active and apply accordingly
                eligible_products = []
                
                # If no filters are active, use all products
                if not filters.get("never_published", True) and not filters.get("price_dropped", True) and not filters.get("not_recent", True):
                    add_log("⚠️ No product filters are active - using all products that match base criteria")
                    eligible_products = all_products
                else:
                    # Apply filters to each product
                    for product in all_products:
                        product_id = product.get("Product_unique_ID")
                        product_name = product.get("product_name", "Unknown")
                        current_price = product.get("Product_current_price")
                        buy_box_price = product.get("Product_Buy_box_price")
                        mrp = product.get("Product_MRP")
                        
                        # Skip invalid products
                        if not product_id or not current_price:
                            add_log(f"Skipping product {product_id}: Missing ID or price data")
                            continue
                            
                        # Enhanced price information in logs
                        add_log(f"Checking product {product_id} ({product_name}): Current: ₹{current_price}, Buy Box: ₹{buy_box_price}, MRP: ₹{mrp}")
                        
                        # FILTER 1: Never published before
                        if product_id in never_published_ids and filters.get("never_published", True):
                            add_log(f"✅ Product {product_name} eligible - never published before")
                            price_diff = float(buy_box_price) - float(current_price)
                            pct_diff = (price_diff / float(buy_box_price)) * 100 if float(buy_box_price) > 0 else 0
                            add_log(f"   📊 Price stats: Current < Buy Box by ₹{price_diff:.2f} ({pct_diff:.1f}%)")
                            eligible_products.append(product)
                            continue
                        
                        # For previously published products
                        if product_id in published_product_prices:
                            history = published_product_prices[product_id]
                            last_price, last_date = history[0]  # Most recent publication
                            
                            # Calculate days since last publication
                            days_ago = (datetime.now() - last_date).days
                            threshold_days = filters.get("days_threshold", 4)
                            
                            add_log(f"Last published: {last_date.strftime('%Y-%m-%d')} ({days_ago} days ago), Last price: ₹{last_price}")
                            
                            try:
                                current_price_float = float(current_price)
                                last_price_float = float(last_price)
                                
                                price_dropped = current_price_float < last_price_float
                                not_recent = days_ago >= threshold_days
                                
                                add_log(f"Checking conditions: Price dropped: {price_dropped}, Not published recently: {not_recent}")
                                
                                # Check which filters are active and apply proper logic
                                price_dropped_filter = filters.get("price_dropped", True)
                                not_recent_filter = filters.get("not_recent", True)
                                
                                # Check if product passes the enabled filters
                                if (price_dropped_filter and price_dropped) or (not_recent_filter and not_recent):
                                    # If either condition is true, add to eligible products
                                    if price_dropped:
                                        price_drop = last_price_float - current_price_float
                                        price_drop_pct = (price_drop / last_price_float) * 100
                                        add_log(f"✅ Product {product_name} eligible - price dropped ₹{price_drop:.2f} ({price_drop_pct:.1f}%)")
                                    
                                    if not_recent:
                                        add_log(f"✅ Product {product_name} eligible - not published in {days_ago} days (threshold: {threshold_days})")
                                    
                                    price_diff = float(buy_box_price) - float(current_price)
                                    bb_pct_diff = (price_diff / float(buy_box_price)) * 100 if float(buy_box_price) > 0 else 0
                                    add_log(f"   📊 Price stats: Current < Buy Box by ₹{price_diff:.2f} ({bb_pct_diff:.1f}%)")
                                    eligible_products.append(product)
                                else:
                                    # Log why the product was skipped
                                    if price_dropped_filter and not price_dropped:
                                        reason = f"current price (₹{current_price_float}) not lower than last published price (₹{last_price_float})"
                                        add_log(f"❌ Product {product_name} skipped: {reason}")
                                        run_log["skipped_reasons"][reason] = run_log["skipped_reasons"].get(reason, 0) + 1
                                    
                                    if not_recent_filter and not not_recent:
                                        reason = f"published too recently ({days_ago} days ago, threshold: {threshold_days} days)"
                                        add_log(f"❌ Product {product_name} skipped: {reason}")
                                        run_log["skipped_reasons"][reason] = run_log["skipped_reasons"].get(reason, 0) + 1
                            except (ValueError, TypeError) as e:
                                add_log(f"❌ Error comparing prices for {product_name}: {str(e)}")

                add_log(f"Filter results: {len(eligible_products)} products eligible for publishing")
                
                # Update next run time in config
                now = datetime.now()

                # Get frequency from auto_config
                auto_config = db.get_auto_publish_config()
                frequency_minutes = auto_config.get("frequency", 30)

                # Calculate next run time using frequency
                next_run = now + timedelta(minutes=frequency_minutes)
                add_log(f"Next run scheduled for: {next_run.strftime('%Y-%m-%d %I:%M:%S %p')} (in {frequency_minutes} minutes)")

                # Update config with next run time
                auto_config["next_run"] = next_run.strftime("%Y-%m-%d %H:%M:%S")
                db.save_auto_publish_config(auto_config)
                
                # Now publish eligible products
                successful_count = 0
                failed_count = 0
                published_details = []
                
                add_log(f"Starting publication of {len(eligible_products)} eligible products")
                run_log["eligible"] = len(eligible_products)
                
                # Get the selected channels
                selected_channels = auto_config.get("channels", ["Telegram"])
                add_log(f"Publishing to channels: {', '.join(selected_channels)}")
                
                for product in eligible_products:
                    try:
                        product_name = product.get("product_name", "Unknown")
                        product_id = product.get("Product_unique_ID", "Unknown")
                        add_log(f"Attempting to publish: {product_name} (ID: {product_id})")
                        
                        # Call publish_product with selected channels
                        st.session_state.immediate_channels = selected_channels  # Set the channels in session state
                        success, message = self.publish_product(product)
                        product_info = {
                            "name": product.get("product_name"),
                            "id": product.get("Product_unique_ID"),
                            "price": product.get("Product_current_price"),
                            "buybox": product.get("Product_Buy_box_price"),
                            "mrp": product.get("Product_MRP"),
                            "channels": selected_channels
                        }
                        
                        if success:
                            add_log(f"✅ Published: {product.get('product_name', 'Unknown')} - {message}")
                            successful_count += 1
                            published_details.append(product_info)
                        else:
                            add_log(f"❌ Failed to publish {product.get('product_name', 'Unknown')}: {message}")
                            failed_count += 1
                        
                        # Delay between publishes to avoid rate limiting
                        time_module.sleep(5)
                        
                    except Exception as publish_error:
                        add_log(f"❌ Error publishing {product.get('product_name', 'Unknown')}: {str(publish_error)}")
                        failed_count += 1
                
                # These should be outside the product loop
                job_end_time = datetime.now()
                duration_seconds = (job_end_time - job_start_time).total_seconds()
                
                run_log["published"] = successful_count
                run_log["skipped"] = run_log["products_checked"] - len(eligible_products) 
                run_log["failed"] = failed_count
                run_log["duration_seconds"] = duration_seconds
                run_log["published_products"] = published_details
                
                # Final summary log
                add_log(f"Automatic publishing completed in {duration_seconds:.2f} seconds.")
                add_log(f"Products checked: {run_log['products_checked']}, Eligible: {len(eligible_products)}, Published: {successful_count}, Failed: {failed_count}")
                
                # Save run log and create summary file
                auto_config = db.get_auto_publish_config()
                auto_config["last_run_log"] = run_log
                db.save_auto_publish_config(auto_config)
                
                # Create a separate summary log file
                summary_filename = f"logs/summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                try:
                    with open(summary_filename, "w", encoding="utf-8") as f:
                        f.write(f"===== AUTO PUBLISH SUMMARY - {job_start_time.strftime('%Y-%m-%d %I:%M:%S %p')} =====\n\n")
                        f.write(f"Duration: {duration_seconds:.2f} seconds\n")
                        f.write(f"Products checked: {run_log['products_checked']}\n")
                        f.write(f"Products eligible: {len(eligible_products)}\n")
                        f.write(f"Products published: {successful_count}\n")
                        f.write(f"Products failed: {failed_count}\n\n")
                        
                        f.write("===== PUBLISHED PRODUCTS =====\n\n")
                        if published_details:
                            for i, product in enumerate(published_details):
                                f.write(f"{i+1}. {product['name']} (ID: {product['id']})\n")
                                f.write(f"   Price: ₹{product['price']} | Buy Box: ₹{product['buybox']} | MRP: ₹{product['mrp']}\n")
                                f.write(f"   Published to: {', '.join(product['channels'])}\n\n")
                        else:
                            f.write("No products were published in this run.\n\n")
                            
                        f.write("===== SKIPPED PRODUCTS REASONS =====\n\n")
                        if run_log["skipped_reasons"]:
                            for reason, count in run_log["skipped_reasons"].items():
                                f.write(f"- {reason}: {count} products\n")
                        else:
                            f.write("No products were skipped in this run.\n")
                            
                        f.write(f"\n===== NEXT RUN SCHEDULED FOR: {next_run.strftime('%Y-%m-%d %I:%M:%S %p')} =====\n")
                    
                    # Save the summary file path in run_log as well
                    run_log["summary_file"] = summary_filename
                    auto_config["last_run_log"] = run_log
                    db.save_auto_publish_config(auto_config)
                    
                    add_log(f"✅ Summary log saved to {summary_filename}")
                except Exception as log_error:
                    add_log(f"⚠️ Error creating summary log: {str(log_error)}")
                    
            except Exception as process_error:
                print(f"❌ Error during auto publish job processing: {str(process_error)}")
                traceback.print_exc()
                
        except Exception as outer_e:
            print(f"❌ Critical error in auto_publish_job: {str(outer_e)}")
            traceback.print_exc()
        finally:
            # Always clear the running flag
            st.session_state.auto_publish_running = False
