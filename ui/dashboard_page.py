import streamlit as st
import pandas as pd
import plotly.express as px
from db.db_manager import DataManager

def load_products_df() -> pd.DataFrame:
    """
    Load products from the database and return as a DataFrame.
    Ensures all required fields are present in the DataFrame.
    """
    db = DataManager()
    products = db.get_all_products()
    
    # Ensure each product has the essential fields
    for p in products:
        p["_id"] = str(p.get("_id", ""))
        # Ensure these fields exist in all products
        if "product_major_category" not in p or p["product_major_category"] is None:
            p["product_major_category"] = "Uncategorized"
        if "product_minor_category" not in p or p["product_minor_category"] is None:
            p["product_minor_category"] = "Uncategorized"
        if "Product_current_price" not in p or p["Product_current_price"] is None:
            p["Product_current_price"] = 0
        if "Product_Buy_box_price" not in p or p["Product_Buy_box_price"] is None:
            p["Product_Buy_box_price"] = 0
        if "Publish" not in p or p["Publish"] is None:
            p["Publish"] = False
        if "Publish_time" not in p:
            p["Publish_time"] = None
    
    # If products is empty, return an empty DataFrame with the required columns
    if not products:
        return pd.DataFrame({
            "product_major_category": [],
            "product_minor_category": [],
            "Product_current_price": [],
            "Product_Buy_box_price": [],
            "Publish": [],
            "Publish_time": []
        })
        
    return pd.DataFrame(products)

class DashboardPage:
    def render(self):
        st.header("📊 Product Dashboard")

        df = load_products_df()
        
        # Check if dataframe has required columns, if not provide defaults
        required_columns = ["product_major_category", "Publish", "Publish_time"]
        missing_columns = [col for col in required_columns if col not in df.columns]
        
        if missing_columns:
            st.warning(f"Warning: Missing required columns in data: {', '.join(missing_columns)}")
            for col in missing_columns:
                if col == "product_major_category":
                    df[col] = "Uncategorized"
                elif col == "Publish":
                    df[col] = False
                elif col == "Publish_time":
                    df[col] = None
        
        total = df.shape[0]
        published = df[df["Publish"] == True].shape[0] if "Publish" in df.columns else 0
        scheduled = (
            df[df["Publish_time"].notna() & (df["Publish"] == False)].shape[0]
            if "Publish_time" in df.columns
            else 0
        )
        categories = df["product_major_category"].nunique()

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Products", total)
        c2.metric("Published", published)
        c3.metric("Scheduled", scheduled)
        c4.metric("Categories", categories)

        st.markdown("---")
        if df.empty:
            st.warning("No products available to display.")
            return

        if "product_major_category" not in df.columns:
            st.warning("The 'product_major_category' column is missing from the data.")
            return

        category_counts = df["product_major_category"].value_counts().reset_index()
        category_counts.columns = ["product_major_category", "Count"]  
        fig = px.bar(
            category_counts,
            x="product_major_category",
            y="Count",
            title="Number of Products by Major Category",
            text="Count",
            labels={"product_major_category": "Category", "Count": "Number of Products"}
        )
        fig.update_traces(textposition="outside")
        fig.update_layout(showlegend=False, xaxis_title="Category", yaxis_title="Number of Products")
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")

        

        st.subheader("📥 Filter & Download Data")
        all_cats = df["product_major_category"].dropna().unique().tolist()
        selected_cats = st.multiselect(
            "Filter by Major Category",
            options=all_cats,
            default=all_cats
        )
        filtered_df = df[df["product_major_category"].isin(selected_cats)]

        all_cols = filtered_df.columns.tolist()
        default_cols = [
            "product_name",
            "Product_unique_ID",
            "product_major_category",
            "Product_current_price"
        ]
        selected_cols = st.multiselect(
            "Select columns to include",
            options=all_cols,
            default=[c for c in default_cols if c in all_cols]
        )

        preview_df = filtered_df[selected_cols] if selected_cols else filtered_df
        st.dataframe(preview_df, use_container_width=True)

        csv_bytes = preview_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download CSV",
            data=csv_bytes,
            file_name="products_export.csv",
            mime="text/csv"
        )