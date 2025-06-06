import streamlit as st
from datetime import datetime
import builtins
from db.db_manager import DataManager
from notification.notification_manager import NotificationManager
from urllib.parse import urlparse
from monitors.amazon_monitor import AmazonIndiaMonitor
from utils.monitor_utils import save_logs_to_file, get_products_for_notification
import os
import uuid
import traceback
import sys

# Initialize session state variables - use the dictionary style access to ensure it works
if "log_text" not in st.session_state:
    st.session_state["log_text"] = ""

os.makedirs("logs", exist_ok=True)

# Global log container for displaying logs
log_container = None
log_display = None

def update_log_display():
    """Update the log text area in the UI with the current log content"""
    global log_display
    if log_display is not None:
        # Use markdown instead of text_area to avoid creating interactive elements
        log_display.markdown(f"""
```
{st.session_state["log_text"]}
```
""", unsafe_allow_html=True)

def add_log(message):
    """Add a message to the log with timestamp"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    # Use dictionary-style access for session_state
    st.session_state["log_text"] += log_entry
    
    # Use sys.stdout.write instead of print to avoid recursion
    sys.stdout.write(f"{message}\n")
    sys.stdout.flush()

def run_monitor_once_for_sites(sites):
    """
    For each site, instantiate its monitor and run it on products from that site.
    Returns the number of price changes detected.
    """
    db = DataManager()
    notification_manager = NotificationManager()
    
    add_log("Starting price monitoring...")
    
    # Save the original print function
    original_print_func = builtins.print
    
    # Define a new print function that doesn't use the add_log function
    def ui_print(*args, **kwargs):
        message = " ".join(str(arg) for arg in args)
        timestamp = datetime.now().strftime("%H:%M:%S")
        log_entry = f"[{timestamp}] {message}\n"
        # Use dictionary-style access for session_state
        st.session_state["log_text"] += log_entry
        # Don't call print or add_log here to avoid recursion
        sys.stdout.write(f"{message}\n")
        sys.stdout.flush()
    
    # Replace the built-in print with our custom function
    builtins.print = ui_print
    
    total_products_checked = 0
    price_changes = []
    successful_products = 0
    failed_products = 0
    
    try:
        for site in sites:
            domain = urlparse(site).netloc if '://' in site else site
            add_log(f"Working with site: {domain}")
            
            if 'amazon.in' in domain.lower():
                try:
                    add_log("Querying products from database...")
                    
                    all_products = list(db.products.find({"product_Affiliate_site": site}))
                    if not all_products:
                        add_log(f"No products found for site {site}. Trying with all products...")
                        all_products = list(db.products.find({}))
                    
                    product_ids = [p.get("Product_unique_ID") for p in all_products if p.get("Product_unique_ID")]
                    
                    if not product_ids:
                        add_log("⚠️ No product ASINs found in database!")
                        continue
                        
                    add_log(f"Found {len(product_ids)} products to check")
                    add_log(f"Sample ASINs: {product_ids[:5]}")
                    total_products_checked += len(product_ids)
                    
                    add_log("Initializing Amazon monitor...")
                    monitor = AmazonIndiaMonitor()
                    
                    add_log(f"Using Amazon API credentials - Access key: {monitor.access_key[:4]}***, Tag: {monitor.partner_tag}")
                    
                    batch_size = 10
                    for i in range(0, len(product_ids), batch_size):
                        batch = product_ids[i:i+batch_size]
                        add_log(f"Processing batch {i//batch_size + 1}/{(len(product_ids) + batch_size - 1)//batch_size}")
                        add_log(f"Batch ASINs: {batch}")
                        
                        try:
                            product_data = monitor.fetch_product_data(batch)
                            
                            if not product_data:
                                add_log(f"⚠️ No data returned for batch {i//batch_size + 1}")
                                failed_products += len(batch)
                                continue
                            
                            add_log(f"✅ Received data for {len(product_data)} products in batch")
                            
                            # Make sure the MRP is being correctly calculated and stored during updates
                            for asin, data in product_data.items():
                                current_product = db.products.find_one({"Product_unique_ID": asin})
                                old_price = current_product.get("Product_current_price") if current_product else None
                                
                                price = data.get("price")
                                mrp = data.get("mrp")
                                
                                # If mrp is None but price is available, calculate a default markup
                                if mrp is None and price is not None:
                                    mrp = price * 1.2  # Default 20% markup
                                elif mrp is not None and price is not None and mrp <= price:
                                    # Ensure MRP is higher than price (at least 5% higher)
                                    mrp = price * 1.2
                                
                                # Round the MRP to 2 decimal places
                                if mrp is not None:
                                    mrp = round(mrp, 2)
                                
                                update_data = {
                                    "Product_current_price": price,
                                    "Product_Buy_box_price": data.get("buy_box_price"),
                                    "Product_MRP": mrp,  # Using the safely calculated mrp
                                    "Product_image_path": data.get("image_path", ""),
                                    "last_updated": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "updated_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                }

                                db.update_product(asin, update_data)
                                successful_products += 1
                                add_log(f"✅ Database updated for {asin}")
                                
                                if old_price and data.get("price") and float(old_price) != float(data.get("price")):
                                    add_log(f"💰 Price change detected for {asin}: {old_price} -> {data.get('price')}")
                                    if current_product:
                                        price_changes.append(current_product)
                                        notification_manager.notify_price_change(
                                            current_product,
                                            old_price,
                                            data.get("price")
                                        )
                        
                        except Exception as batch_error:
                            add_log(f"❌ Error processing batch: {str(batch_error)}")
                            failed_products += len(batch)
                            add_log(traceback.format_exc())
                    
                    add_log(f"✅ Amazon monitoring completed: {successful_products} successful, {failed_products} failed")
                except Exception as e:
                    add_log(f"❌ Error during Amazon monitoring: {str(e)}")
                    add_log(traceback.format_exc())
            else:
                add_log(f"⚠️ Site {domain} not fully implemented yet")
        
        add_log(f"🏁 Monitoring complete! Checked {total_products_checked} products, found {len(price_changes)} price changes.")
        
        try:
            publish_candidates = get_products_for_notification(db)
            add_log(f"Found {len(publish_candidates)} products that meet publishing criteria")
            st.session_state["filter_results"] = publish_candidates
        except Exception as e:
            add_log(f"❌ Error in filtering products: {str(e)}")
            st.session_state["filter_results"] = []
        
        # No need to call this anymore since we update in add_log
        # update_log_display()
                
    finally:
        # Restore the original print function
        builtins.print = original_print_func
        
    return len(price_changes)


class ProductMonitorPage:
    def render(self):
        global log_container, log_display
        
        st.header("🔄 Product Monitor")
        
        self.render_site_selection()
        self.render_simplified_monitor()

    def render_site_selection(self):
        db = DataManager()
        sites = db.products.distinct("product_Affiliate_site")
        
        # Initialize with Amazon as default if available
        if "sites" not in st.session_state:
            st.session_state["sites"] = [site for site in sites if isinstance(site, str) and 'amazon.in' in site.lower()] if sites else []
        
        # Filter the default values to ensure they exist in options
        valid_defaults = [site for site in st.session_state["sites"] if site in sites]
        
        col1, col2 = st.columns([3, 1])
        with col1:
            selected_sites = st.multiselect(
                "Select sites to monitor",
                options=sites,
                default=valid_defaults
            )
        st.session_state["sites"] = selected_sites

    def render_simplified_monitor(self):
        global log_container, log_display
        
        # Simple layout with just the Run Once button and logs
        st.markdown("### Monitor Controls")
        
        col1, col2 = st.columns([3, 1])
        
        # Only the Run Once button
        with col1:
            run_once_button = st.button("🔄 Run Once", type="primary", use_container_width=True)
        
        with col2:
            clear_logs = st.button("🗑️ Clear Logs", use_container_width=True)

        # Display log area
        st.markdown("### 📜 Monitor Logs")
        
        # Create a container for the log display
        log_container = st.container()
        
        # Create an empty placeholder for the log content
        with log_container:
            log_display = st.empty()
        
        # Verify log_text exists before trying to display it
        if "log_text" not in st.session_state:
            st.session_state["log_text"] = ""
            
        # Display the initial logs
        # update_log_display()

        # Handle Run Once button click
        if run_once_button:
            try:
                # Get selected sites
                sites = st.session_state.get("sites", [])
                if not sites:
                    st.error("Please select at least one site to monitor")
                    return
                
                # Run the monitor
                with st.spinner("Running monitor..."):
                    total_changes = run_monitor_once_for_sites(sites)
                
                # Show success message
                st.success(f"✅ Monitor run complete! Detected {total_changes} price changes.")
            except Exception as e:
                st.error(f"❌ Error running monitor: {str(e)}")
                st.error(traceback.format_exc())
        
        # Handle Clear Logs button
        if clear_logs:
            st.session_state["log_text"] = ""
            # update_log_display()
                
        # Add option to export logs
        # if st.session_state.get("log_text"):
            # if st.button("📥 Download Logs"):
            #     try:
            #         log_file = f"logs/monitor_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            #         with open(log_file, "w") as f:
            #             f.write(st.session_state["log_text"])
            #         st.success(f"✅ Logs exported: {log_file}")
            #     except Exception as e:
            #         st.error(f"❌ Error exporting logs: {str(e)}")
        
        # Add option to view logs
        if st.session_state.get("log_text"):
            if st.button("👁️ View Logs"):
                try:
                    # Generate a unique filename in the logs directory
                    log_file = f"logs/monitor_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                    
                    # Write logs with UTF-8 encoding to support emojis and special characters
                    with open(log_file, "w", encoding="utf-8") as f:
                        f.write(st.session_state["log_text"])
                        
                    # Display the log contents in a larger format
                    st.markdown("### Log Contents")
                    with st.expander("Expand to view full log", expanded=True):
                        st.code(st.session_state["log_text"], language="bash")
                        
                    st.info(f"✅ Logs saved to: {log_file}")
                except Exception as e:
                    st.error(f"❌ Error handling logs: {str(e)}")
                    st.error(traceback.format_exc())
        
        # Add cleanup button
        if st.button("🧹 Cleanup Affiliate Sites"):
            with st.spinner("Cleaning up site values..."):
                try:
                    cleanup_affiliate_sites()
                    st.success("✅ Cleanup complete!")
                except Exception as e:
                    st.error(f"❌ Error during cleanup: {str(e)}")
                    st.error(traceback.format_exc())

def cleanup_affiliate_sites():
    db = DataManager()
    products = db.products.find({"product_Affiliate_site": {"$exists": True}})
    
    for product in products:
        site = product.get("product_Affiliate_site")
        if site is not None and not isinstance(site, str):
            # Convert non-string values to strings
            db.update_product(
                product.get("Product_unique_ID"),
                {"product_Affiliate_site": str(site)}
            )
            print(f"Converted site value {site} to string for product {product.get('Product_unique_ID')}")
