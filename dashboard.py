import streamlit as st
import pandas as pd
import plotly.express as px # Added import
import os
import logging

import db_utils # Assuming db_utils.py is in the same directory

# Configure basic logging for the dashboard
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# DataFrame Column Name Constants
COL_TIMESTAMP = 'timestamp'
COL_MEMBER_COUNT = 'member_count'

@st.cache_data(ttl=60) # Cache data for 60 seconds
def load_data():
    """Loads member count data from the SQLite database."""
    conn = None
    try:
        db_path_from_config = None 
        conn = db_utils.get_db_connection(db_path=db_path_from_config)
        
        if conn:
            raw_data = db_utils.get_all_member_stats(conn)
            if raw_data:
                df = pd.DataFrame(raw_data, columns=[COL_TIMESTAMP, COL_MEMBER_COUNT])
                df[COL_TIMESTAMP] = pd.to_datetime(df[COL_TIMESTAMP])
                df = df.sort_values(by=COL_TIMESTAMP)
                logger.info(f"Successfully loaded {len(df)} records for the dashboard.")
                return df
            else:
                logger.info("No data found in the database.")
                return pd.DataFrame(columns=[COL_TIMESTAMP, COL_MEMBER_COUNT])
        else:
            st.error("Failed to connect to the database.")
            logger.error("Dashboard: Failed to connect to the database via db_utils.")
            return pd.DataFrame(columns=[COL_TIMESTAMP, COL_MEMBER_COUNT])
            
    except Exception as e:
        st.error("An error occurred while loading data. Please check application logs or try again later.")
        logger.error(f"Dashboard: Error loading data: {e}", exc_info=True)
        return pd.DataFrame(columns=[COL_TIMESTAMP, COL_MEMBER_COUNT])
    finally:
        if conn:
            conn.close()

st.set_page_config(page_title="Telegram Group Monitor", layout="wide")
st.title("Telegram Group Member Monitor")

data_df = load_data()

# Revised Interpolation logic starts
if not data_df.empty and COL_TIMESTAMP in data_df.columns and COL_MEMBER_COUNT in data_df.columns:
    logger.info(f"Original data points before revised interpolation: {len(data_df)}")
    
    df_original = data_df.copy() # Explicit copy
    df_original.loc[:, 'is_interpolated'] = False # Mark original data

    df_for_interpolation = df_original.copy()
    df_for_interpolation = df_for_interpolation.set_index(COL_TIMESTAMP)
    df_resampled = df_for_interpolation[COL_MEMBER_COUNT].resample('D').mean()
    df_interpolated_backbone_series = df_resampled.interpolate(method='linear')
    df_interpolated_backbone = df_interpolated_backbone_series.reset_index()
    df_interpolated_backbone.columns = [COL_TIMESTAMP, COL_MEMBER_COUNT]

    original_dates = pd.to_datetime(df_original[COL_TIMESTAMP].dt.date).unique()
    
    df_purely_interpolated_points = df_interpolated_backbone[
        ~pd.to_datetime(df_interpolated_backbone[COL_TIMESTAMP].dt.date).isin(original_dates)
    ].copy()
    df_purely_interpolated_points.loc[:, 'is_interpolated'] = True
    logger.info(f"Generated {len(df_purely_interpolated_points)} purely interpolated points for missing days.")

    df_combined = pd.concat([df_original, df_purely_interpolated_points], ignore_index=True)
    
    df_combined = df_combined.sort_values(by=COL_TIMESTAMP).reset_index(drop=True)
    df_combined[COL_MEMBER_COUNT] = pd.to_numeric(df_combined[COL_MEMBER_COUNT], errors='coerce')
    df_combined[COL_MEMBER_COUNT] = df_combined[COL_MEMBER_COUNT].round().astype(int)
    
    data_df = df_combined
    
    logger.info(f"Data points after revised interpolation (original + purely interpolated): {len(data_df)}")
else:
    if data_df.empty:
        logger.info("data_df is empty, skipping revised interpolation.")
    elif not (COL_TIMESTAMP in data_df.columns and COL_MEMBER_COUNT in data_df.columns):
        logger.info(f"data_df lacks '{COL_TIMESTAMP}' or '{COL_MEMBER_COUNT}' columns, skipping revised interpolation.")
# Revised Interpolation logic ends

if not data_df.empty:
    st.sidebar.header("Filters")
    if len(data_df[COL_TIMESTAMP].dt.date.unique()) > 1:
        min_date = data_df[COL_TIMESTAMP].min().date()
        max_date = data_df[COL_TIMESTAMP].max().date()
        
        start_date = st.sidebar.date_input("Start date", min_date, min_value=min_date, max_value=max_date)
        end_date = st.sidebar.date_input("End date", max_date, min_value=min_date, max_value=max_date)

        if start_date > end_date:
            st.sidebar.error("Error: End date must fall after start date.")
            filtered_df = pd.DataFrame() 
        else:
            start_datetime = pd.to_datetime(start_date)
            end_datetime = pd.to_datetime(end_date) + pd.Timedelta(days=1)
            filtered_df = data_df[(data_df[COL_TIMESTAMP] >= start_datetime) & (data_df[COL_TIMESTAMP] < end_datetime)].copy() # Explicit copy
    else:
        filtered_df = data_df.copy() # Explicit copy; No filter if only one day or no data
        st.sidebar.info("Date filter available when data spans multiple days.")

    st.sidebar.header("Chart Options")
    show_ma_7 = st.sidebar.checkbox("Show 7-day Moving Average", value=False)
    show_ma_30 = st.sidebar.checkbox("Show 30-day Moving Average", value=False)

    if not filtered_df.empty:
        # NEW DAILY CHANGE LOGIC
        # This logic calculates daily changes based on the full data_df and merges into filtered_df.
        processing_df_for_daily_change = data_df.copy() 
        processing_df_for_daily_change.loc[:, 'date'] = processing_df_for_daily_change[COL_TIMESTAMP].dt.date
        processing_df_for_daily_change = processing_df_for_daily_change.sort_values(by=COL_TIMESTAMP)
        
        daily_summary_agg = processing_df_for_daily_change.groupby('date').agg(
            last_member_count=(COL_MEMBER_COUNT, 'last'),
            is_last_interpolated=('is_interpolated', 'last')
        ).reset_index()
        
        daily_summary_agg['date'] = pd.to_datetime(daily_summary_agg['date'])
        daily_summary_agg = daily_summary_agg.sort_values(by='date')

        daily_summary_agg.loc[:, 'net_daily_change'] = daily_summary_agg['last_member_count'].diff().round().fillna(0).astype(int)
        
        # Ensure 'date' column in filtered_df is datetime64[ns] and normalized for merging
        filtered_df.loc[:, 'date'] = filtered_df[COL_TIMESTAMP].dt.normalize()

        summary_to_merge = daily_summary_agg[['date', 'net_daily_change', 'is_last_interpolated']]
        filtered_df = pd.merge(filtered_df, summary_to_merge, on='date', how='left')
        
        filtered_df.loc[:, 'net_daily_change'] = filtered_df['net_daily_change'].fillna(0).astype(int)
        filtered_df.loc[:, 'is_last_interpolated'] = filtered_df['is_last_interpolated'].fillna(False).astype(bool)
        # END OF NEW DAILY CHANGE LOGIC

        st.header("Current Status")
        latest_count = filtered_df[COL_MEMBER_COUNT].iloc[-1]
        latest_timestamp = filtered_df[COL_TIMESTAMP].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")
        st.metric(label=f"Latest Member Count (as of {latest_timestamp})", value=f"{int(latest_count):,}")

        st.header("Member Count Trend")
        fig = px.line(filtered_df, x=COL_TIMESTAMP, y=COL_MEMBER_COUNT, title="Member Count Trend", labels={COL_MEMBER_COUNT: 'Members'})
        
        if show_ma_7 and len(filtered_df) >= 7:
            filtered_df.loc[:, 'ma_7'] = filtered_df[COL_MEMBER_COUNT].rolling(window=7).mean() # Use .loc
            fig.add_scatter(x=filtered_df[COL_TIMESTAMP], y=filtered_df['ma_7'], mode='lines', name='7-day MA', line=dict(dash='dash'))
        elif show_ma_7:
            st.sidebar.warning("Not enough data for 7-day MA.")

        if show_ma_30 and len(filtered_df) >= 30:
            filtered_df.loc[:, 'ma_30'] = filtered_df[COL_MEMBER_COUNT].rolling(window=30).mean() # Use .loc
            fig.add_scatter(x=filtered_df[COL_TIMESTAMP], y=filtered_df['ma_30'], mode='lines', name='30-day MA', line=dict(dash='dot'))
        elif show_ma_30:
            st.sidebar.warning("Not enough data for 30-day MA.")
            
        st.plotly_chart(fig, use_container_width=True)

        st.header("Growth Analysis")
        initial_count = filtered_df[COL_MEMBER_COUNT].iloc[0]
        growth = latest_count - initial_count
        growth_percentage = ((growth / initial_count) * 100) if initial_count != 0 else 0
        
        col1, col2 = st.columns(2)
        col1.metric(label="Total Growth (in selected period)", value=f"{int(growth):,}")
        col2.metric(label="Total Growth % (in selected period)", value=f"{growth_percentage:.2f}%")

        if len(filtered_df) > 1:
            time_delta_days = (filtered_df[COL_TIMESTAMP].iloc[-1] - filtered_df[COL_TIMESTAMP].iloc[0]).days
            
            avg_daily_growth = (growth / time_delta_days) if time_delta_days > 0 else 0
            avg_weekly_growth = (growth / (time_delta_days / 7)) if time_delta_days >= 7 else 0

            col3, col4 = st.columns(2)
            col3.metric(label="Avg. Daily Growth", value=f"{avg_daily_growth:,.2f}")
            if time_delta_days >= 7:
                col4.metric(label="Avg. Weekly Growth", value=f"{avg_weekly_growth:,.2f}")
            else:
                col4.metric(label="Avg. Weekly Growth", value="N/A (less than 1 week of data)")
        
        # Old daily change logic (lines 194-227) is removed.

        st.subheader("Data Details (Filtered)")
        
        # Prepare data for download (Updated CSV Section)
        df_for_csv = filtered_df.copy()
        df_for_csv.loc[:, COL_MEMBER_COUNT] = df_for_csv[COL_MEMBER_COUNT].round().astype(int)
        
        cols_for_csv = [COL_TIMESTAMP, COL_MEMBER_COUNT, 'is_interpolated', 'net_daily_change', 'is_last_interpolated']
        actual_cols_for_csv = [col for col in cols_for_csv if col in df_for_csv.columns]

        if actual_cols_for_csv:
            csv_data_content = df_for_csv[actual_cols_for_csv].to_csv(index=False).encode('utf-8')
            st.download_button(
                label="Download Data as CSV",
                data=csv_data_content, # Renamed variable to avoid conflict
                file_name='filtered_member_data_with_change.csv',
                mime='text/csv',
            )
        else:
            st.warning("Could not prepare data for CSV download (missing expected columns).")

        # Updated Data Table Display Section
        filtered_df.loc[:, COL_MEMBER_COUNT] = filtered_df[COL_MEMBER_COUNT].round().astype(int)
        display_processing_df = filtered_df.sort_values(by=COL_TIMESTAMP, ascending=True).copy()
        
        if 'date' not in display_processing_df.columns: # Should exist
             display_processing_df.loc[:, 'date'] = display_processing_df[COL_TIMESTAMP].dt.date
        
        display_processing_df.loc[:, 'Formatted Daily Change'] = "--" 
        
        if not display_processing_df.empty:
            # Identify the last recorded row for each day
            display_processing_df.loc[:, 'is_last_for_day'] = ~display_processing_df['date'].duplicated(keep='last')

            def calculate_formatted_change_str(row):
                # Display change only on the last row of the day
                if row['is_last_for_day']:
                    change_val = int(row['net_daily_change'])
                    is_interp_last = bool(row['is_last_interpolated']) # This is 'is_last_interpolated' for the day
                    change_str_val = f"{change_val}"
                    if is_interp_last: # The interpolation mark applies to the day's closing value
                        change_str_val += " (interpolated)"
                    return change_str_val
                return "--"

            display_processing_df.loc[:, 'Formatted Daily Change'] = display_processing_df.apply(calculate_formatted_change_str, axis=1)
            
            # Clean up the helper column
            if 'is_last_for_day' in display_processing_df.columns: # Check before dropping
                display_processing_df = display_processing_df.drop(columns=['is_last_for_day'])
            
        final_display_columns_map = {
            COL_TIMESTAMP: 'Timestamp',
            COL_MEMBER_COUNT: 'Member Count',
            'Formatted Daily Change': 'Daily Change'
        }
        cols_to_display = [COL_TIMESTAMP, COL_MEMBER_COUNT, 'Formatted Daily Change']
        
        # Ensure all columns for display exist in display_processing_df
        # This check is more robust before selecting.
        missing_display_cols = [col for col in cols_to_display if col not in display_processing_df.columns]
        if not missing_display_cols:
            display_df_final = display_processing_df[cols_to_display].copy()
            display_df_final = display_df_final.rename(columns=final_display_columns_map)
            display_df_final = display_df_final.sort_values(by='Timestamp', ascending=False)
            st.dataframe(display_df_final, use_container_width=True)
        else:
            st.warning(f"Could not prepare all columns for the data table. Missing: {', '.join(missing_display_cols)}. Displaying available data from filtered_df.")
            # Fallback to displaying what's available in filtered_df if 'Formatted Daily Change' failed to create
            st.dataframe(filtered_df.sort_values(by=COL_TIMESTAMP, ascending=False), use_container_width=True)

    else: # filtered_df is empty
        st.info("No data available for the selected date range or filters.")

else: # data_df is empty
    st.info("No data collected yet. Run `main_monitor.py` to collect data.")

logger.info("Dashboard script finished execution.")
