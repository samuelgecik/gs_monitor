import streamlit as st
import pandas as pd
import plotly.express as px # Added import
import os
import logging

import db_utils # Assuming db_utils.py is in the same directory

# Configure basic logging for the dashboard
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@st.cache_data(ttl=60) # Cache data for 60 seconds
def load_data():
    """Loads member count data from the SQLite database."""
    conn = None
    try:
        # db_utils.get_db_connection will use its default path logic 
        # (data/telegram_group_stats.db relative to db_utils.py)
        # or the path from config if db_utils was modified to read it.
        # For simplicity here, we rely on db_utils default or pre-configuration.
        db_path_from_config = None # We'll let db_utils handle its default path
        
        # If you want to explicitly use the config.ini for the db_path in dashboard too:
        # import configparser
        # CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.ini')
        # if os.path.exists(CONFIG_FILE):
        #     config = configparser.ConfigParser()
        #     config.read(CONFIG_FILE)
        #     db_path_from_config = config.get('Database', 'db_path', fallback=None)
        #     if db_path_from_config and not os.path.isabs(db_path_from_config):
        #         db_path_from_config = os.path.join(os.path.dirname(__file__), db_path_from_config)
        
        conn = db_utils.get_db_connection(db_path=db_path_from_config) # Pass None to use default
        
        if conn:
            raw_data = db_utils.get_all_member_stats(conn)
            if raw_data:
                df = pd.DataFrame(raw_data, columns=['timestamp', 'member_count'])
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df = df.sort_values(by='timestamp')
                logger.info(f"Successfully loaded {len(df)} records for the dashboard.")
                return df
            else:
                logger.info("No data found in the database.")
                return pd.DataFrame(columns=['timestamp', 'member_count']) # Return empty DataFrame
        else:
            st.error("Failed to connect to the database.")
            logger.error("Dashboard: Failed to connect to the database via db_utils.")
            return pd.DataFrame(columns=['timestamp', 'member_count'])
            
    except Exception as e:
        st.error(f"Error loading data: {e}")
        logger.error(f"Dashboard: Error loading data: {e}", exc_info=True)
        return pd.DataFrame(columns=['timestamp', 'member_count']) # Return empty DataFrame on error
    finally:
        if conn:
            conn.close()

st.set_page_config(page_title="Telegram Group Monitor", layout="wide")
st.title("Telegram Group Member Monitor")

data_df = load_data()

# Revised Interpolation logic starts
if not data_df.empty and 'timestamp' in data_df.columns and 'member_count' in data_df.columns:
    logger.info(f"Original data points before revised interpolation: {len(data_df)}")
    
    df_original = data_df.copy()

    # 2. Generate Daily Interpolated Series (Backbone)
    df_for_interpolation = df_original.copy()
    df_for_interpolation = df_for_interpolation.set_index('timestamp')
    # Resample to daily, using mean to handle multiple original points on the same day for the backbone
    df_resampled = df_for_interpolation['member_count'].resample('D').mean()
    df_interpolated_backbone_series = df_resampled.interpolate(method='linear')
    df_interpolated_backbone = df_interpolated_backbone_series.reset_index()
    # Ensure column names are consistent
    df_interpolated_backbone.columns = ['timestamp', 'member_count']

    # 3. Isolate Purely Interpolated Points
    # Get unique dates from original data (ignoring time part for this comparison)
    original_dates = pd.to_datetime(df_original['timestamp'].dt.date).unique()
    
    # Filter backbone: keep only rows where its timestamp (date part) is NOT in original_dates
    # These are the points that truly fill gaps where no original data existed for that entire day.
    df_purely_interpolated_points = df_interpolated_backbone[
        ~pd.to_datetime(df_interpolated_backbone['timestamp'].dt.date).isin(original_dates)
    ]
    logger.info(f"Generated {len(df_purely_interpolated_points)} purely interpolated points for missing days.")

    # 4. Combine Original and Purely Interpolated Data
    df_combined = pd.concat([df_original, df_purely_interpolated_points], ignore_index=True)
    
    # 5. Sort and Prepare for Plotting
    df_combined = df_combined.sort_values(by='timestamp').reset_index(drop=True)
    df_combined['member_count'] = pd.to_numeric(df_combined['member_count'], errors='coerce')
    
    # Update data_df with the combined data
    data_df = df_combined
    
    logger.info(f"Data points after revised interpolation (original + purely interpolated): {len(data_df)}")
else:
    if data_df.empty: # Check specifically for empty
        logger.info("data_df is empty, skipping revised interpolation.")
    elif not ('timestamp' in data_df.columns and 'member_count' in data_df.columns): # Check for missing columns if not empty
        logger.info("data_df lacks 'timestamp' or 'member_count' columns, skipping revised interpolation.")
# Revised Interpolation logic ends

if not data_df.empty:
    st.sidebar.header("Filters")
    # Add date range selector if there's enough data
    if len(data_df['timestamp'].dt.date.unique()) > 1:
        min_date = data_df['timestamp'].min().date()
        max_date = data_df['timestamp'].max().date()
        
        start_date = st.sidebar.date_input("Start date", min_date, min_value=min_date, max_value=max_date)
        end_date = st.sidebar.date_input("End date", max_date, min_value=min_date, max_value=max_date)

        if start_date > end_date:
            st.sidebar.error("Error: End date must fall after start date.")
            filtered_df = pd.DataFrame() # Empty df if date range is invalid
        else:
            # Convert start_date and end_date to datetime for comparison
            start_datetime = pd.to_datetime(start_date)
            end_datetime = pd.to_datetime(end_date) + pd.Timedelta(days=1) # Include the whole end day
            filtered_df = data_df[(data_df['timestamp'] >= start_datetime) & (data_df['timestamp'] < end_datetime)]
    else:
        filtered_df = data_df # No filter if only one day or no data
        st.sidebar.info("Date filter available when data spans multiple days.")

    if not filtered_df.empty:
        st.header("Current Status")
        latest_count = filtered_df['member_count'].iloc[-1]
        latest_timestamp = filtered_df['timestamp'].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")
        st.metric(label=f"Latest Member Count (as of {latest_timestamp})", value=f"{latest_count:,}")

        st.header("Member Count Trend")
        # Create Plotly figure
        fig = px.line(filtered_df, x='timestamp', y='member_count', title="Member Count Trend")
    
        st.plotly_chart(fig, use_container_width=True)

        st.header("Growth Analysis")
        # Calculate overall growth in the filtered period
        initial_count = filtered_df['member_count'].iloc[0]
        growth = latest_count - initial_count
        growth_percentage = ((growth / initial_count) * 100) if initial_count else 0
        
        col1, col2 = st.columns(2)
        col1.metric(label="Total Growth (in selected period)", value=f"{growth:,}")
        col2.metric(label="Total Growth % (in selected period)", value=f"{growth_percentage:.2f}%")

        # Daily change (simple diff)
        if len(filtered_df) > 1:
            filtered_df['daily_change'] = filtered_df['member_count'].diff()
            st.subheader("Change Since Previous Record")
            st.line_chart(filtered_df.set_index('timestamp')['daily_change'])
        
        st.subheader("Raw Data (Filtered)")
        st.dataframe(filtered_df.sort_values(by='timestamp', ascending=False))
    else:
        st.info("No data available for the selected date range or filters.")

else:
    st.info("No data collected yet. Run `main_monitor.py` to collect data.")

logger.info("Dashboard script finished execution.")
