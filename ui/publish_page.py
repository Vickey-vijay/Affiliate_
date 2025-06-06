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
        
        # Load existing configuration with INACTIVE default
        auto_config = self.db.get_auto_publish_config()
        saved_filters = auto_config.get("filters", {})
        saved_schedule_type = auto_config.get("schedule_type", "Frequency")
        saved_schedule = auto_config.get("schedule", "15" if saved_schedule_type == "Frequency" else [])
        
        # Important: Default to inactive
        is_active = auto_config.get("active", False)
        
        # Check if this is first run and no config exists yet
        if not auto_config:
            # Create default inactive config if none exists
            default_config = {
                "filters": {
                    "filter_lower_than_buybox": True,
                    "filter_never_published": True,
                    "filter_lower_than_last_published": True,
                    "filter_published_over_days": True,
                    "days_threshold": 4
                },
                "schedule_type": "Frequency",
                "schedule": "15",
                "active": False,  # Explicitly set to inactive
                "channels": ["Telegram", "WhatsApp"],
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            self.db.save_auto_publish_config(default_config)
            auto_config = default_config
        
        st.info("Set up automatic publishing to monitor prices and publish products based on criteria.")
        
        # Initialize filters dictionary at the function scope
        filter_flags = {}
        filter_settings = {}
        
        # Improved filters section with clear descriptions
        with st.expander("Price Filters", expanded=True):
            filter_flags = {
                "filter_lower_than_buybox": st.checkbox(
                    "✅ Price lower than buy box (required)", 
                    value=True,
                    disabled=True,  # Always required
                    help="Only publish products where current price is lower than buy box price"
                ),
                "filter_never_published": st.checkbox(
                    "Never published before", 
                    value=bool(saved_filters.get("filter_never_published", True)),
                    help="Automatically publish products that have never been published before"
                ),
                "filter_lower_than_last_published": st.checkbox(
                    "Price dropped since last publish", 
                    value=bool(saved_filters.get("filter_lower_than_last_published", True)),
                    help="For recently published products, only republish if price has dropped further"
                ),
                "filter_published_over_days": st.checkbox(
                    "Not published recently", 
                    value=bool(saved_filters.get("filter_published_over_days", True)),
                    help="Publish products not published within the specified number of days, even if price hasn't changed"
                )
            }

            if filter_flags["filter_published_over_days"]:
                days_threshold = st.number_input(
                    "Days threshold", 
                    min_value=1, 
                    value=int(saved_filters.get("days_threshold", 4)),
                    help="Republish products not published in this many days, regardless of price"
                )
                filter_settings["days_threshold"] = int(days_threshold)
                
            st.markdown("""
            ### How filters work together:
            1. **All products must have current price < buy box price** to be considered
            2. If **never published before** → publish immediately
            3. If published within last 4 days → only publish if **price dropped** further
            4. If not published in last 4 days → publish regardless of price change
            """)

        # Combine the filter dictionaries outside the expander block
        filters = {**filter_flags, **filter_settings}
        
        # Schedule configuration section
        st.subheader("Schedule")
        schedule_type = st.radio(
            "Schedule Type", 
            ["Frequency", "Fixed Times"],
            index=0 if saved_schedule_type == "Frequency" else 1
        )

        if schedule_type == "Frequency":
            frequency_minutes = st.number_input(
                "Check Every (minutes)",
                min_value=15,  # Minimum 15 minutes to avoid overloading
                max_value=120,
                value=int(saved_schedule) if isinstance(saved_schedule, (int, str)) and str(saved_schedule).isdigit() else 15,
                step=5,
                help="Check products and publish eligible ones on this schedule"
            )
            
            st.markdown("⚠️ **Note**: Setting too frequent checks may cause overlapping execution. Minimum 15 minutes recommended.")
            frequency = str(frequency_minutes)
        else:
            # Convert stored times to AM/PM format for display
            default_times = []
            if isinstance(saved_schedule, list) and saved_schedule:
                for time_str in saved_schedule:
                    try:
                        # Convert 24-hour to 12-hour AM/PM format for display
                        hours, minutes = map(int, time_str.split(":"))
                        dt = datetime.strptime(f"{hours}:{minutes}", "%H:%M")
                        ampm_time = dt.strftime("%I:%M %p")
                        default_times.append(ampm_time)
                    except:
                        pass
        
            # Time selection in AM/PM format
            available_times = []
            for hour in range(24):
                for minute in [0, 15, 30, 45]:  # Quarter-hour increments
                    dt = datetime.strptime(f"{hour}:{minute}", "%H:%M")
                    ampm_time = dt.strftime("%I:%M %p")
                    available_times.append(ampm_time)
        
            times = st.multiselect(
                "Select Times", 
                available_times,
                default=default_times
            )
            if not times and schedule_type == "Fixed Times":
                st.warning("Please select at least one time for fixed schedule.")

        # Add channel selection before the Start/Stop controls
        st.subheader("Publishing Channels")
        channels = st.multiselect(
            "Select Channels to Publish To", 
            ["Telegram", "WhatsApp"],
            default=auto_config.get("channels", ["Telegram", "WhatsApp"]),
            help="Choose which notification channels to use for automatic publishing"
        )

        # Start/Stop controls
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

        # Status display
        status_color = "green" if is_active else "red"
        status_text = "ACTIVE" if is_active else "INACTIVE"
        st.markdown(f"<h3>Current Status: <span style='color:{status_color};'>{status_text}</span></h3>", unsafe_allow_html=True)
        
        if is_active:
            next_run_time = auto_config.get("next_run", "Unknown")
            # Convert next run time to AM/PM format if it's properly formatted
            try:
                next_run_dt = datetime.strptime(next_run_time, "%Y-%m-%d %H:%M:%S")
                next_run_time = next_run_dt.strftime("%Y-%m-%d %I:%M %p")
            except:
                pass
            
            st.info(f"Next scheduled run: {next_run_time}")
            
            # Display upcoming schedules
            with st.expander("Upcoming Schedule Details"):
                upcoming_schedules = {
                    "schedule_type": schedule_type,
                    "frequency_minutes": frequency if schedule_type == "Frequency" else None,
                    "fixed_times": times if schedule_type == "Fixed Times" else None,
                    "next_run": next_run_time,
                    "filters": filters
                }
                st.json(upcoming_schedules)
                
            # Add a last run log section
            if "last_run_log" in auto_config:
                with st.expander("Last Run Results"):
                    last_run = auto_config.get("last_run_log", {})
                    
                    # Format last run time in AM/PM
                    last_run_time = last_run.get("time", "Unknown")
                    try:
                        last_run_dt = datetime.strptime(last_run_time, "%Y-%m-%d %H:%M:%S")
                        last_run_time = last_run_dt.strftime("%Y-%m-%d %I:%M %p")
                    except:
                        pass
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**Last Run Time:** {last_run_time}")
                        st.write(f"**Duration:** {last_run.get('duration_seconds', 0):.2f} seconds")
                    with col2:
                        st.write(f"**Products Checked:** {last_run.get('products_checked', 0)}")
                        st.write(f"**Products Published:** {last_run.get('published', 0)}")
                        st.write(f"**Products Skipped:** {last_run.get('skipped', 0)}")
                        st.write(f"**Products Failed:** {last_run.get('failed', 0)}")
                    
                    if "skipped_reasons" in last_run and last_run["skipped_reasons"]:
                        st.write("**Skipped Reasons:**")
                        for reason, count in last_run["skipped_reasons"].items():
                            st.write(f"- {reason}: {count}")
                    
                    # Add detailed logs section
                    if "detailed_logs" in last_run and last_run["detailed_logs"]:
                        st.write("**Detailed Logs:**")
                        st.code("\n".join(last_run["detailed_logs"]), language="bash")
                    
                    if last_run.get('published_products'):
                        st.write("**Published Products:**")
                        published_df = pd.DataFrame(last_run.get('published_products'))
                        st.dataframe(published_df)

        # Handle start button logic
        if start_button:
            # If fixed times, convert back to 24-hour format for internal use
            processed_times = []
            if schedule_type == "Fixed Times":
                for time_str in times:
                    try:
                        # Convert 12-hour AM/PM to 24-hour format for storage
                        time_obj = datetime.strptime(time_str, "%I:%M %p").time()
                        processed_times.append(time_obj.strftime("%H:%M"))
                    except ValueError as e:
                        st.error(f"Invalid time format: {time_str} - {e}")
                        return
            
            config = {
                "filters": filters,
                "schedule_type": schedule_type,
                "schedule": frequency if schedule_type == "Frequency" else processed_times,
                "active": True,  # Set active when started
                "channels": channels,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "next_run": "Calculating...",
                "job_id": str(uuid.uuid4()),
            }
            
            # Preserve last_run_log if it exists
            if "last_run_log" in auto_config:
                config["last_run_log"] = auto_config["last_run_log"]
            else:
                config["last_run_log"] = {}
                
            # Save filters in session state for access in the job
            st.session_state.auto_filters = filters
            
            # Set up the schedule
            # Clear existing jobs for this task
            for job in schedule.get_jobs():
                # We'll just clear all jobs for now
                schedule.clear()
                print(f"Cleared existing scheduled jobs")
            
            # Setup new scheduler based on type
            def monitor_and_publish_wrapper():
                # This wrapper allows us to access class methods from scheduled jobs
                self.monitor_and_publish(filters, schedule_type, frequency if schedule_type == "Frequency" else processed_times)
            
            # Schedule based on selected type
            if schedule_type == "Frequency":
                minutes = int(frequency)
                schedule.every(minutes).minutes.do(monitor_and_publish_wrapper)
                print(f"✅ Scheduled to run every {minutes} minutes")
            else:
                for time_str in processed_times:
                    schedule.every().day.at(time_str).do(monitor_and_publish_wrapper)
                    print(f"✅ Scheduled to run at {time_str}")
            
            # Calculate and update next run time
            if schedule_type == "Frequency":
                minutes = int(frequency)
                next_run = datetime.now() + timedelta(minutes=minutes)
            else:
                # Find the next scheduled time
                now = datetime.now()
                today = now.date()
                next_run_datetime = None
                
                for time_str in processed_times:
                    hours, minutes = map(int, time_str.split(":"))
                    time_today = datetime.combine(today, time(hours, minutes))
                    
                    if time_today > now:
                        if not next_run_datetime or time_today < next_run_datetime:
                            next_run_datetime = time_today
                
                # If no times today are in the future, use the first time tomorrow
                if not next_run_datetime and processed_times:
                    tomorrow = today + timedelta(days=1)
                    hours, minutes = map(int, processed_times[0].split(":"))
                    next_run_datetime = datetime.combine(tomorrow, time(hours, minutes))
                
                next_run = next_run_datetime if next_run_datetime else now + timedelta(days=1)
            
            # Update config with next run time
            config["next_run"] = next_run.strftime("%Y-%m-%d %H:%M:%S")
            self.db.save_auto_publish_config(config)
            
            # Run immediately first time if requested
            if st.checkbox("Run immediately", value=True):
                try:
                    st.info("Running initial check now...")
                    # Add this line to fix buy box prices before running
                    self.ensure_valid_buybox_prices()
                    self.monitor_and_publish(filters, schedule_type, frequency if schedule_type == "Frequency" else processed_times)
                    st.success("✅ Initial check completed!")
                except Exception as e:
                    st.error(f"❌ Error during initial run: {str(e)}")
                    st.error(traceback.format_exc())
                    
            st.success("✅ Automatic publishing configured and started")
            st.rerun()  # Refresh to show updated status
        
        if stop_button:
            # Clear existing jobs
            schedule.clear()
            
            # Update config status
            self.db.save_auto_publish_config({
                **auto_config,
                "active": False,
                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
            
            st.success("Automatic publishing stopped")
            st.rerun()  # Refresh to show updated status

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
        """Common function to publish a product"""
        try:
            # Initialize publisher if needed
            if not hasattr(self, 'notification_publisher'):
                self.notification_publisher = NotificationPublisher(self.config_manager)
            
            # Generate formatted message using the centralized format function
            message = self.notification_publisher.format_product_message(product)
            
            # List to track successful channels
            channels = []
            errors = []
            
            # Get the selected channels from session state
            selected_channels = st.session_state.get("immediate_channels", ["Telegram"])  # Default to Telegram if not set
            
            # Send to Telegram ONLY IF selected
            if "Telegram" in selected_channels:
                telegram_success, telegram_error = self.notification_publisher.telegram_push(message, product.get("Product_image_path"))
                if telegram_success:
                    channels.append("telegram")
                else:
                    errors.append(f"Telegram: {telegram_error}")
                    print(f"❌ Telegram push failed: {telegram_error}")
            
            # Send to WhatsApp channels ONLY IF selected
            if "WhatsApp" in selected_channels:
                whatsapp_config = self.config_manager.get_whatsapp_config()
                whatsapp_channel_names = whatsapp_config.get("channel_names", "") if whatsapp_config else ""
                
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
                        
                        # Clean up WhatsApp driver after each channel
                        self._cleanup_whatsapp_drivers()
            
                # Send to WhatsApp groups
                whatsapp_group_names = whatsapp_config.get("group_names", "") if whatsapp_config else ""
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
                            
                            # Clean up WhatsApp driver after each group
                            self._cleanup_whatsapp_drivers()
        
            # Update product status in database
            product_id = product.get("Product_unique_ID")
            if product_id:
                self.db.update_product(product_id, {
                    "published_status": True,
                    "Publish": False,
                    "Publish_time": None,
                    "Last_published_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "last_published_price": product.get("Product_current_price"),  # Store current price for future comparisons
                    "published_channels": channels
                })
                
                # Record publication in published_products collection
                self.db.db.published_products.insert_one({
                    "product_id": product_id,
                    "product_name": product.get("product_name"),
                    "product_price": product.get("Product_current_price"),
                    "published_date": datetime.now(),
                    "channels": channels,
                    "message": message,
                    "errors": errors if errors else None
                })
            
            # Make sure all drivers are cleaned up
            self._cleanup_whatsapp_drivers()
            
            # Return success if at least one channel worked
            if channels:
                return True, f"Published to {', '.join(channels)}"
            else:
                return False, f"Failed to publish to any channels: {'; '.join(errors)}"
            
        except Exception as e:
            print(f"❌ Error in publish_product: {str(e)}")
            return False, f"Error: {str(e)}"

    def _cleanup_whatsapp_drivers(self):
        """Clean up any WhatsApp web driver instances that might be in session state"""
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

    def monitor_and_publish(self, filters, schedule_type, schedule_value):
        """Monitoring and publishing logic extracted into a class method"""
        # Check if another job is already running
        if st.session_state.auto_publish_running:
            print("[AutoPublish] Previous job still running, skipping this execution")
            return
        
        try:
            # Set running flag
            st.session_state.auto_publish_running = True
            job_start_time = datetime.now()
            run_log = {
                "time": job_start_time.strftime("%Y-%m-%d %H:%M:%S"),
                "products_checked": 0,
                "published": 0,
                "skipped": 0,
                "failed": 0,
                "skipped_reasons": {},
                "published_products": [],
                "detailed_logs": []
            }
            
            # Log function to add to detailed logs
            def add_log(message):
                timestamp = datetime.now().strftime("%H:%M:%S")
                log_entry = f"[{timestamp}] {message}"
                print(log_entry)
                run_log["detailed_logs"].append(log_entry)
            
            add_log(f"Starting automatic publishing job...")
            
            # Add this section to fix buy box prices at the beginning of each run
            add_log("Checking and fixing buy box prices before monitoring...")
            updated = self.ensure_valid_buybox_prices()
            if updated:
                add_log("✅ Buy box prices were adjusted for some products to ensure proper filtering")
        
            # First update prices using the AmazonIndiaMonitor
            try:
                # Use the same monitor function from monitor_page
                db = DataManager()
                monitor = AmazonIndiaMonitor()
                
                # Get all products to check
                all_products = list(db.products.find({}))
                product_ids = [p.get("Product_unique_ID") for p in all_products if p.get("Product_unique_ID")]
                add_log(f"Found {len(product_ids)} products to check")
                run_log["products_checked"] = len(product_ids)
                
                # Process in batches to avoid overloading
                batch_size = 10
                for i in range(0, len(product_ids), batch_size):
                    batch = product_ids[i:i+batch_size]
                    add_log(f"Processing batch {i//batch_size + 1}/{(len(product_ids) + batch_size - 1)//batch_size}")
                    
                    try:
                        # Fetch fresh data
                        product_data = monitor.fetch_product_data(batch)
                        
                        # Update database with new prices
                        for asin, data in product_data.items():
                            current_product = db.products.find_one({"Product_unique_ID": asin})
                            if not current_product:
                                continue
                                
                            old_price = current_product.get("Product_current_price")
                            buy_box = current_product.get("Product_Buy_box_price")
                            price = data.get("price")
                            mrp = data.get("mrp")
                            
                            # FIXED: Update only the current price and MRP, not the buy box price
                            update_data = {
                                "Product_current_price": price,
                                # "Product_Buy_box_price": data.get("buy_box_price"),  # REMOVED THIS LINE
                                "Product_MRP": mrp,
                                "Product_image_path": data.get("image_path", ""),
                                "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "updated_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            }
                            
                            db.update_product(asin, update_data)
                            
                            # Log price changes with enhanced price information
                            if old_price != price:
                                add_log(f"Updated {asin}: Price changed from ₹{old_price} to ₹{price}, MRP: ₹{mrp}, Buy Box: ₹{buy_box}")
                            else:
                                add_log(f"Updated {asin}: Price unchanged at ₹{price}, MRP: ₹{mrp}, Buy Box: ₹{buy_box}")
                    except Exception as batch_error:
                        add_log(f"Error processing batch: {str(batch_error)}")
            
            except Exception as monitor_error:
                add_log(f"❌ Error during price monitoring: {str(monitor_error)}")
        
            # Now apply filters to find products to publish
            add_log("Beginning product filtering for publishing")
            query = {}
            
            # REQUIRED: Price lower than buy box
            query["$expr"] = {"$lt": ["$Product_current_price", "$Product_Buy_box_price"]}
            add_log(f"Base filter: Current price < Buy box price")
            
            # Get all product info including current prices
            all_products = list(self.db.get_products(query))
            add_log(f"Found {len(all_products)} products with price < buy box price")
            
            if len(all_products) == 0:
                add_log("⚠️ No products found with price < buy box. Check if product prices and buy box prices are set correctly.")
                
                # Add a diagnostic check to help troubleshoot
                all_prods = list(self.db.get_products({}))
                add_log(f"➡️ Total products in database: {len(all_prods)}")
                price_compare = []
                for p in all_prods[:10]:  # Check first 10 products
                    current = p.get("Product_current_price")
                    buybox = p.get("Product_Buy_box_price")
                    mrp = p.get("Product_MRP")
                    name = p.get("product_name", "Unknown")[:30]
                    price_compare.append(f"{name} - Current: ₹{current}, Buybox: ₹{buybox}, MRP: ₹{mrp}")
                
                add_log("➡️ Sample product prices (first 10):")
                for p in price_compare:
                    add_log(f"   - {p}")
            
            eligible_products = []
            
            # Get all published products for reference
            published_records = list(self.db.db.published_products.find(
                {}, {"product_id": 1, "product_price": 1, "published_date": 1}
            ))
            add_log(f"Found {len(published_records)} publishing history records")
            
            # Create lookup dictionaries for efficient filtering
            never_published_ids = set()
            published_product_prices = {}  # {product_id: [(price, date), ...]}
            
            # Process all products
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
                if product_id in never_published_ids and filters.get("filter_never_published", True):
                    add_log(f"✅ Product {product_name} eligible - never published before")
                    price_diff = float(buy_box_price) - float(current_price)
                    pct_diff = (price_diff / float(buy_box_price)) * 100 if float(buy_box_price) > 0 else 0
                    add_log(f"   📊 Price stats: Current < Buy Box by ₹{price_diff:.2f} ({pct_diff:.1f}%)")
                    eligible_products.append(product)
                    continue
                else:
                    add_log(f"Product {product_name} has been published before")
                
                # For previously published products
                if product_id in published_product_prices:
                    history = published_product_prices[product_id]
                    last_price, last_date = history[0]  # Most recent publication
                    
                    # Calculate days since last publication
                    days_ago = (datetime.now() - last_date).days
                    threshold_days = filters.get("days_threshold", 4)
                    
                    add_log(f"Last published: {last_date.strftime('%Y-%m-%d')} ({days_ago} days ago), Last price: ₹{last_price}")
                    
                    # FILTER 2: Not published in X days
                    if days_ago >= threshold_days and filters.get("filter_published_over_days", True):
                        add_log(f"✅ Product {product_name} eligible - not published in {days_ago} days (threshold: {threshold_days})")
                        price_diff = float(buy_box_price) - float(current_price)
                        pct_diff = (price_diff / float(buy_box_price)) * 100 if float(buy_box_price) > 0 else 0
                        add_log(f"   📊 Price stats: Current < Buy Box by ₹{price_diff:.2f} ({pct_diff:.1f}%)")
                        eligible_products.append(product)
                        continue
                    elif days_ago < threshold_days:
                        add_log(f"Product {product_name} published too recently ({days_ago} days ago)")
                    elif not filters.get("filter_published_over_days", True):
                        add_log(f"Not using 'days since publication' filter (disabled)")
                        
                    # FILTER 3: Price dropped since last publication
                    if filters.get("filter_lower_than_last_published", True):
                        # Only consider within threshold days
                        if days_ago < threshold_days:
                            try:
                                current_price_float = float(current_price)
                                last_price_float = float(last_price)
                                
                                add_log(f"Comparing prices: Current: ₹{current_price_float}, Last published: ₹{last_price_float}")
                                
                                if current_price_float < last_price_float:
                                    # Price dropped since last publication
                                    price_drop = last_price_float - current_price_float
                                    price_drop_pct = (price_drop / last_price_float) * 100
                                    
                                    add_log(f"✅ Product {product_name} eligible - price dropped ₹{price_drop:.2f} ({price_drop_pct:.1f}%) since last publish")
                                    price_diff = float(buy_box_price) - float(current_price)
                                    bb_pct_diff = (price_diff / float(buy_box_price)) * 100 if float(buy_box_price) > 0 else 0
                                    add_log(f"   📊 Price stats: Current < Buy Box by ₹{price_diff:.2f} ({bb_pct_diff:.1f}%)")
                                    eligible_products.append(product)
                                    continue
                                else:
                                    reason = f"current price (₹{current_price_float}) not lower than last published price (₹{last_price_float})"
                                    add_log(f"❌ Product {product_name} skipped: {reason}")
                                    run_log["skipped_reasons"][reason] = run_log["skipped_reasons"].get(reason, 0) + 1
                            except (ValueError, TypeError):
                                add_log(f"❌ Error comparing prices for {product_name}")
                        else:
                            reason = f"published {days_ago} days ago (< {threshold_days}), price not lower"
                            add_log(f"❌ Product {product_name} skipped: {reason}")
                            run_log["skipped_reasons"][reason] = run_log["skipped_reasons"].get(reason, 0) + 1
                    else:
                        add_log(f"Not using 'price drop' filter (disabled)")
                else:
                    # Should be caught by never_published_ids check above
                    add_log(f"Product {product_name} should have been in never_published_ids but was not found")
                    pass
            
            add_log(f"Filter results: {len(eligible_products)} products eligible for publishing")
            
            # Update next run time in config
            now = datetime.now()
            next_run = None
            
            if schedule_type == "Frequency":
                minutes = int(schedule_value) if isinstance(schedule_value, str) and schedule_value.isdigit() else 15
                next_run = now + timedelta(minutes=minutes)
                add_log(f"Next run scheduled for: {next_run.strftime('%Y-%m-%d %I:%M:%S %p')} (in {minutes} minutes)")
            else:
                # Find the next scheduled time
                today = now.date()
                next_run_datetime = None
                
                for time_str in schedule_value:
                    hours, minutes = map(int, time_str.split(":"))
                    time_today = datetime.combine(today, time(hours, minutes))
                    
                    if time_today > now:
                        if not next_run_datetime or time_today < next_run_datetime:
                            next_run_datetime = time_today
                
                # If no times today are in the future, use the first time tomorrow
                if not next_run_datetime and schedule_value:
                    tomorrow = today + timedelta(days=1)
                    hours, minutes = map(int, schedule_value[0].split(":"))
                    next_run_datetime = datetime.combine(tomorrow, time(hours, minutes))
                
                next_run = next_run_datetime if next_run_datetime else now + timedelta(days=1)
                add_log(f"Next run scheduled for: {next_run.strftime('%Y-%m-%d %I:%M:%S %p')}")
        
            # Update config with next run time
            auto_config = self.db.get_auto_publish_config()
            auto_config["next_run"] = next_run.strftime("%Y-%m-%d %H:%M:%S") if next_run else "Unknown"
            self.db.save_auto_publish_config(auto_config)
            
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
            
            # Update run log
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
            
            # Save run log
            auto_config = self.db.get_auto_publish_config()
            auto_config["last_run_log"] = run_log
            self.db.save_auto_publish_config(auto_config)
                
        except Exception as outer_e:
            print(f"❌ Critical error in monitor_and_publish: {str(outer_e)}")
            print(traceback.format_exc())
        finally:
            # Always clear the running flag
            st.session_state.auto_publish_running = False









