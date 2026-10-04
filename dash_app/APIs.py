import pandas as pd
import requests
import re
import os
from dotenv import load_dotenv
import numpy as np
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

load_dotenv()
EIA_KEY = os.getenv("EIA_KEY")
base_url = "https://api.eia.gov/v2/natural-gas/"

def update_storage():
    start_date = "2010-01"
    today = datetime.today() + timedelta(days=15)
    end_date = datetime.strptime(today.strftime("%Y-%m-01"), "%Y-%m-%d")

    storage_df = pd.DataFrame()

    for start, end in generate_date_chunks(start_date, end_date, interval_years=5):
        temp_df = EIA_extractor(start, end, URL_link= "https://api.eia.gov/v2/natural-gas/stor/wkly/data/?frequency=weekly&data[0]=value&start=&end=&sort[0][column]=period&sort[0][direction]=desc&offset=0")
        
        storage_df = pd.concat([storage_df, temp_df], axis=0, ignore_index=True)
    
    storage_df = storage_df.sort_values(by='period', ascending=True, inplace=False)
    storage_df = storage_df.assign(
        period=pd.to_datetime(storage_df['period'], errors='coerce'), value=pd.to_numeric(storage_df['value'], errors='coerce'), **{'series-description': storage_df['series-description'].astype('string'), 'units': storage_df['units'].astype('string')} 
    )

    # Total storage for L48 states
    agg_storage = storage_df[storage_df['duoarea'] == 'R48'][['period', 'series-description', 'value','units']].copy().reset_index(drop=True)
    # Regional storage, note: South Central = Salt + Non-Salt
    regional_storage = storage_df[storage_df['duoarea'] != 'R48'][['period', 'series-description', 'value','units']].copy().reset_index(drop=True)
    regional_storage['Region'] = (regional_storage['series-description'].str.split(' ', expand=True)[1])
    regional_grp = regional_storage.groupby(['period','Region']).agg({'value': 'sum', 'units': 'first'}).reset_index()

    for region in regional_grp['Region'].unique():
        region_mask = regional_grp['Region'] == region
        
        regional_grp.loc[region_mask, 'WoW_Change'] = regional_grp.loc[region_mask, 'value'].diff(1)
        regional_grp.loc[region_mask, 'YoY_Change'] = regional_grp.loc[region_mask, 'value'].diff(52)
        regional_grp.loc[region_mask, 'WoW_pctChange'] = regional_grp.loc[region_mask, 'value'].pct_change(1, fill_method=None) * 100
        regional_grp.loc[region_mask, 'YoY_pctChange'] = regional_grp.loc[region_mask, 'value'].pct_change(52, fill_method=None) * 100
    
    # AUXILIARY ADJUSTMENTS
    # Rename South to South Central
    regional_grp['Region'] = regional_grp['Region'].replace({'South': 'South Central'})
    # Add additional column for display on data table
    regional_grp['Date_Display'] = regional_grp['period'].dt.strftime("%d %b %y")
    # Remove Salt and Nonsalt columns, salt+nonsalt = South Central
    regional_grp = regional_grp[~regional_grp['Region'].isin(['Salt','Nonsalt'])]
    return regional_grp, agg_storage

def EIA_extractor(start=str, end=str, URL_link=str):
    # Insert api key after the ? in pasted URL from EIA website
    edited_url = URL_link.replace("?", "?" + "api_key=" + EIA_KEY + "&")
    edited_url = edited_url.replace("start=&end=", f"start={start}&end={end}")
    print(f"Extracting data from {edited_url}...")
    
    response = requests.get(edited_url, timeout=60)
    response.raise_for_status()
    if response.status_code == 200:
        temp_data = response.json()
        rows = temp_data.get("response", {}).get("data", [])
        final_df = EIA_JSON_PARSER(rows)
    else:
        print("EIA Data Pull failed! Error Code: {}".format(response.status_code))
        
    return final_df

# function to generate the start and end dates
def generate_date_chunks(start, end, interval_years=5):
    """
    Generate start-end date chunks for a given range.
    
    Parameters:
        start (str): Start date in "YYYY-MM" format
        end (str): End date in "YYYY-MM" format
        interval_years (int): Number of years per chunk (default 5)
    
    Yields:
        tuple: (chunk_start, chunk_end) in "YYYY-MM" format
    """
    start_date = pd.to_datetime(start + "-01")
    end_date = pd.to_datetime(end)

    while start_date <= end_date:
        chunk_end = start_date + relativedelta(years=interval_years) - relativedelta(days=1)
        if chunk_end > end_date:
            chunk_end = end_date
        
        yield (start_date.strftime("%Y-%m-%d"), chunk_end.strftime("%Y-%m-%d"))
        
        # Move start_date to next month after the current chunk
        start_date = chunk_end + relativedelta(days=1)


### -- EIA STATE PARSER (if needed)

def normalize_US_state(x):
        x = x.replace('USA-', '').replace('.', '').strip().upper()
        return x

US_regions = {
# East
"CT": "East", "DE": "East", "DC": "East", "FL": "East", "GA": "East", "MA": "East",
"MD": "East","ME": "East","NH": "East","NJ": "East","NY": "East","NC": "East","OH": "East","PA": "East",
"RI": "East","SC": "East","VT": "East","VA": "East","WV": "East",

# Southcentral
"AL": "South Central","AR": "South Central","KS": "South Central","LA": "South Central",
"MS": "South Central","OK": "South Central","TX": "South Central",

# Midwest
"IL": "Midwest","IN": "Midwest","IA": "Midwest","KY": "Midwest","MI": "Midwest","MN": "Midwest",
"MO": "Midwest","TN": "Midwest","WI": "Midwest",

# Mountain
"AZ": "Mountain","CO": "Mountain","ID": "Mountain","MT": "Mountain","NE": "Mountain",
"NM": "Mountain","NV": "Mountain","ND": "Mountain","SD": "Mountain","UT": "Mountain","WY": "Mountain",

# Pacific
"CA": "Pacific","OR": "Pacific","WA": "Pacific", "AK": "Alaska", "HI": "Hawaii",

# Offshore Gulf of America (classify under Southeast)
"OFFSHORE GULF": "GULF",

# North America
"CAN":"North America", "USA":"North America", "MEX":"North America", "BHS":"North America", "TTO":"North America", "PAN":"North America", "JAM":"North America", "DOM":"North America", "BRB":"North America", "ATG":"North America",

# South America
"ARG":"South America", "BRA":"South America", "CHL":"South America", "COL":"South America", "PER":"South America", "NIC":"South America", "BHR":"Asia", 

# Europe
"FRA":"Europe","GBR":"Europe","PRT":"Europe","NLD":"Europe","ESP":"Europe","ITA":"Europe","LTU":"Europe","HRV":"Europe","BEL":"Europe","POL":"Europe","FIN":"Europe","GRC":"Europe","DEU":"Europe", "RUS":"Europe", "NOR": "Europe",

# Asia
"KOR":"Asia","BGD":"Asia","THA":"Asia","PAK":"Asia","TWN":"Asia","MYS":"Asia","IDN":"Asia","JPN":"Asia","ISR":"Asia","TUR":"Asia","IND":"Asia","JOR":"Asia","KWT":"Asia","OMN":"Asia","ARE":"Asia","QAT":"Asia","YEM":"Asia","BRN":"Asia","SGP":"Asia","PHL":"Asia","CHN":"Asia",

# Africa
"EGY":"Africa","DZA":"Africa","GNQ":"Africa","NGA":"Africa","MRT":"Africa","SEN":"Africa","HTI":"Africa","SLV":"Africa",  # HTI & SLV are Caribbean, but adjust if needed

# Oceania
"AUS":"Oceania",

# Special / unknown
"MIAMI":"East"
}

# --- Step 3: Handle full names ---
state_abbrev = {
"ALABAMA":"AL","ALASKA":"AK","ARIZONA":"AZ","ARKANSAS":"AR",
"CALIFORNIA":"CA", "COLUMBIA": "DC", "COLORADO":"CO","CONNECTICUT":"CT","DELAWARE":"DE",
"FLORIDA":"FL","GEORGIA":"GA","HAWAII":"HI","IDAHO":"ID","ILLINOIS":"IL",
"INDIANA":"IN","IOWA":"IA","KANSAS":"KS","KENTUCKY":"KY","LOUISIANA":"LA",
"MAINE":"ME","MARYLAND":"MD","MASSACHUSETTS":"MA","MICHIGAN":"MI",
"MINNESOTA":"MN","MISSISSIPPI":"MS","MISSOURI":"MO","MONTANA":"MT",
"NEBRASKA":"NE","NEVADA":"NV","NEW HAMPSHIRE":"NH","NEW JERSEY":"NJ",
"NEW MEXICO":"NM","NEW YORK":"NY","NORTH CAROLINA":"NC",
"NORTH DAKOTA":"ND","OHIO":"OH","OKLAHOMA":"OK","OREGON":"OR",
"PENNSYLVANIA":"PA","RHODE ISLAND":"RI","SOUTH CAROLINA":"SC",
"SOUTH DAKOTA":"SD","TENNESSEE":"TN","TEXAS":"TX","UTAH":"UT",
"VERMONT":"VT","VIRGINIA":"VA","WASHINGTON":"WA","WEST VIRGINIA":"WV",
"WISCONSIN":"WI","WYOMING":"WY", "MIAMI": "FL", "NA": "OFFSHORE GULF" # EIA labels state of gulf of america, as North America (NA)
, "Others" : "Others"
}

# Used for cleaning the dataset after NAN treatment.
state_abbrev_clean = {
"ALABAMA":"AL","ALASKA":"AK","ARIZONA":"AZ","ARKANSAS":"AR",
"CALIFORNIA":"CA", "COLUMBIA": "DC", "COLORADO":"CO","CONNECTICUT":"CT","DELAWARE":"DE",
"FLORIDA":"FL","GEORGIA":"GA", "GUAM": "GU", "HAWAII":"HI","IDAHO":"ID","ILLINOIS":"IL",
"INDIANA":"IN","IOWA":"IA","KANSAS":"KS","KENTUCKY":"KY","LOUISIANA":"LA",
"MAINE":"ME","MARYLAND":"MD","MASSACHUSETTS":"MA","MICHIGAN":"MI",
"MINNESOTA":"MN","MISSISSIPPI":"MS","MISSOURI":"MO","MONTANA":"MT",
"NEBRASKA":"NE","NEVADA":"NV","NEW HAMPSHIRE":"NH","NEW JERSEY":"NJ",
"NEW MEXICO":"NM","NEW YORK":"NY","NORTH CAROLINA":"NC",
"NORTH DAKOTA":"ND","OHIO":"OH","OKLAHOMA":"OK","OREGON":"OR",
"PENNSYLVANIA":"PA","RHODE ISLAND":"RI","SOUTH CAROLINA":"SC",
"SOUTH DAKOTA":"SD","TENNESSEE":"TN","TEXAS":"TX","UTAH":"UT",
"VERMONT":"VT","VIRGINIA":"VA","WASHINGTON":"WA","WEST VIRGINIA":"WV",
"WISCONSIN":"WI","WYOMING":"WY", "NA": "OFFSHORE GULF" # EIA labels state of gulf of america, as North America (NA)
,"Others": "Others"
}


def get_abbrev(y):
    if y in state_abbrev:
        return state_abbrev[y]
    return y

def extract_us_states(desc):
    # Special function for US Imports Destination and Exports Origin
    match = re.search(r",\s*([A-Z]{2})\s", desc.upper())
    if match:
        return match.group(1)
    return None

# general parser for EIA data
def EIA_JSON_PARSER(data_list):
    df_to_return = pd.DataFrame(data_list)
    
    # Drop unwanted columns and clean up data types and values
    df_to_return['value'] = df_to_return['value'].astype(float)
    df_to_return['period'] = df_to_return['period'].astype("datetime64[ns]")

    # Parse descriptions into State and Region classifications (for classification later on)
    df_to_return["State"] = df_to_return['area-name'].apply(normalize_US_state)
    df_to_return["State"] = df_to_return["State"].apply(get_abbrev)
    df_to_return["Region"] = df_to_return["State"].map(US_regions).fillna("Unknown")

    return df_to_return

def load_ng_data():
    eia_data = EIA_data_generator()
    
    pipeline_demand, lease_demand, production, consumption, US_imports, US_exports, prod_share, demand_share = eia_data
    
    return pipeline_demand, lease_demand, production, consumption, US_imports, US_exports, prod_share, demand_share

def EIA_data_generator():
    def EIA_SnD_extractor(start=str, end=str):
        US_data = {}

        # EIA format: base_url + dataset id + api_key
        PROD_URL = base_url + "prod/whv/data/?api_key={}&frequency=monthly&data[0]=value&facets[process][]=VGM&start={}&end={}&sort[0][column]=period&sort[0][direction]=desc&offset=0".format(EIA_KEY, start,end)  #Marketed production is the sum of gross withdrawals less gas used for repressuring, quantities vented and flared, and nonhydrocarbon gases removed.
        PIPELINEIMP_URL = base_url + "/move/poe1/data/?api_key={}&frequency=monthly&data[0]=value&facets[process][]=IML&facets[process][]=INC&facets[process][]=IRP&start={}&end={}&sort[0][column]=period&sort[0][direction]=desc&offset=0".format(EIA_KEY, start,end) #Pipeline imports by point of entry (inc. LNG, CNG)
        EXPORTS_URL = base_url + "/move/poe2/data/?api_key={}&frequency=monthly&data[0]=value&facets[process][]=ENC&facets[process][]=ENG&facets[process][]=ENP&start={}&end={}&sort[0][column]=period&sort[0][direction]=desc&offset=0".format(EIA_KEY, start,end) #Exports by points of exit (inc. CNG, LNG, pipeline exports)
        DEMAND_URL = base_url + "/cons/sum/data/?api_key={}&frequency=monthly&data[0]=value&facets[process][]=VGL&facets[process][]=VGP&facets[process][]=VGT&start={}&end={}&sort[0][column]=period&sort[0][direction]=desc&offset=0".format(EIA_KEY, start,end) #NG Demand by end use (includes all sectors)

        URLs= [PROD_URL, PIPELINEIMP_URL, EXPORTS_URL, DEMAND_URL]
        US_names = ["PROD","IMP","EXP","DEMAND","STOR"]
        for i, url in enumerate(URLs, start=1):
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            if response.status_code == 200:
                temp_data = response.json()
                rows = temp_data.get("response", {}).get("data", [])
                #print(US_names[i-1])
                US_data[f"df_{US_names[i-1]}"] = EIA_JSON_PARSER(rows)
                i += 1
            else:
                print("EIA Data Pull failed! Error Code: {}".format(response.status_code))

        US_PROD = US_data['df_PROD']
        US_IMP = US_data['df_IMP']
        US_EXP = US_data['df_EXP']
        US_DEMAND = US_data['df_DEMAND']

        US_IMP['Import Destined State'] = US_IMP["series-description"].apply(extract_us_states)
        US_EXP['Export Origin State'] = US_EXP["series-description"].apply(extract_us_states)

        # Map to region using full_region_map
        US_IMP["Import To"] = US_IMP["Import Destined State"].map(US_regions).fillna("Unknown")
        US_EXP["Export From"] = US_EXP["Export Origin State"].map(US_regions).fillna("Unknown")

        US_PROD = US_PROD.rename(columns={"value": "value_PROD", "units": "units_PROD"})
        US_DEMAND = US_DEMAND.rename(columns = {"value": "value_DEMAND", "units": "units_DEMAND"})
        US_IMP = US_IMP.rename(columns = {"value": "value_IMPORTS", "units": "units_IMPORTS", "State": "State Import Origin", "Region": "Imports From", "Import To": "Region"}) # value of imports must be added (+)
        US_EXP = US_EXP.rename(columns = {"value": "value_EXPORTS", "units": "units_EXPORTS", "State": "State Export Destined","Region": "Export To", "Export From": "Region"}) # value of exports must be minused (-)

        # Convert to billion cubic feet
        US_PROD.loc[:, 'value_PROD'] = US_PROD.loc[:, 'value_PROD'] / 1000
        US_DEMAND.loc[:, 'value_DEMAND'] = US_DEMAND.loc[:, 'value_DEMAND'] / 1000
        US_IMP.loc[:, 'value_IMPORTS'] = US_IMP.loc[:, 'value_IMPORTS'] / 1000
        US_EXP.loc[:, 'value_EXPORTS'] = US_EXP.loc[:, 'value_EXPORTS'] / 1000

        return [US_PROD, US_DEMAND, US_IMP, US_EXP]

    # Data Generating Process
    start_date = "2010-01"
    today = datetime.today()
    end_date = datetime.strptime(today.strftime("%Y-%m-01"), "%Y-%m-%d")

    US_demand = pd.DataFrame()
    US_prod = pd.DataFrame()
    US_imports = pd.DataFrame()
    US_exports = pd.DataFrame()

    for start_chunk, end_chunk in generate_date_chunks(start_date, end_date):
        print("Extracting Data from {} to {}".format(start_chunk, end_chunk))

        df_list = EIA_SnD_extractor(start=start_chunk, end=end_chunk)
        prod = df_list[0]
        demand = df_list[1]
        imports = df_list[2]
        exports = df_list[-1]

        US_prod = pd.concat([US_prod, prod], ignore_index=True, axis=0)
        US_demand = pd.concat([US_demand, demand], ignore_index=True, axis=0)
        US_imports = pd.concat([US_imports, imports], ignore_index=True, axis=0)
        US_exports = pd.concat([US_exports, exports], ignore_index=True, axis=0)

    US_prod = US_prod.sort_values(by='period', ascending=True)
    US_demand = US_demand.sort_values(by='period', ascending=True)
    US_imports = US_imports.sort_values(by='period', ascending=True)
    US_exports = US_exports.sort_values(by='period', ascending=True)
    
    # NAN Treatment for production and consumption part of demand
    prod_nan_states = list(US_prod[US_prod['value_PROD'].isna() == True]['State'].unique())
    temp_nona = US_prod[~US_prod['State'].isin(prod_nan_states)]
    prod_manip = temp_nona[['period', 'process-name', 'value_PROD','State','Region']]

    # Create boolean masks for aggregate and individual states
    US_prod_mask = prod_manip['Region'] == 'Unknown'
    states_prod_mask = prod_manip['Region'] != 'Unknown'

    # Calculate "others" states values (individuals for these are NAN values)
    grouped = prod_manip[states_prod_mask].reset_index(drop=True).groupby('period', as_index=False).agg({'value_PROD': 'sum', 'process-name': 'first','State':'first','Region':'first'})
    grouped['State'] = 'Others'
    grouped['Region'] = 'Assorted'
    grouped_others = grouped.copy()
    grouped_others.loc[:, 'value_PROD'] = prod_manip.loc[US_prod_mask, 'value_PROD'].values - grouped.loc[:, 'value_PROD'].values

    production_cleaned = pd.concat([prod_manip, grouped_others], axis=0, ignore_index=True).reset_index(drop=True)
    production_cleaned = production_cleaned.sort_values(by=['Region','period'], ascending=True)
    
    consumption = US_demand[US_demand['process'] == 'VGT'][['period','process-name','value_DEMAND','State','Region']] # Individual state NANs only from 2024 onwards
    pipeline = US_demand[US_demand['process'] == 'VGP'][['period','process-name','value_DEMAND','State','Region']] # no NAN values
    lease = US_demand[US_demand['process'] == 'VGL'][['period','process-name','value_DEMAND','State','Region']] # no NAN values
    
    consumption = consumption.sort_values(by=['Region','period'], ascending=True, inplace=False)
    updates = []
    targets = consumption.loc[(consumption['value_DEMAND'].isna()), ['State', 'period']].copy()
    
    for _, row in targets.iterrows():
        state = row['State']
        target_period = row['period']
        temp_df = consumption[consumption['State'] == state]
        
        # growth rate interpolation
        time_step = timedelta(days=365)
        years = 6
        start_date = target_period - years*time_step
        end_date = target_period - time_step
        dates_array = pd.date_range(start_date, end_date, freq='YS')
        
        growth_calc_df = temp_df.loc[temp_df['period'].isin(dates_array)].reset_index(drop=True)
        growth_calc_df['value_DEMAND_t-1'] = growth_calc_df['value_DEMAND'].shift(periods=1)
        growth_calc_df.loc[:, 'growth_rate_annual'] = (growth_calc_df.loc[:, 'value_DEMAND'] - growth_calc_df.loc[:, 'value_DEMAND_t-1'])/growth_calc_df['value_DEMAND']
        
        # interpolation logic: all data points from 5 years before empty value. Annual seasonality basis.
        # interpolated value = avg growth rate * avg value*0.5 + median growth rate * median value*0.5 + latest_t-1_value
        # equal importance to average growth and median growth, protect skewed values from just average. Assumed linear growth.
        interpolated_value = growth_calc_df.iloc[-2]['value_DEMAND'] + growth_calc_df['growth_rate_annual'].mean()*growth_calc_df['value_DEMAND'].mean()*0.5 + growth_calc_df['growth_rate_annual'].median() * growth_calc_df['value_DEMAND'].median() * 0.5
        
        if np.isfinite(interpolated_value) == False:
            print(growth_calc_df.head())
        
        updates.append((state, target_period, interpolated_value))

    updates_df = pd.DataFrame(updates, columns=['State','period','value_DEMAND'])
    consumption.set_index(['State','period'], inplace=True)
    updates_df.set_index(['State','period'], inplace=True)
    consumption.update(updates_df)
    consumption.reset_index(inplace=True)
    
    state_to_statename = {value: key for key, value in state_abbrev_clean.items()}
    production_cleaned['State Name'] = production_cleaned['State'].map(state_to_statename)
    consumption['State Name'] = consumption['State'].map(state_to_statename)
    # End of Treatment
    
    # Data Manipulation
    US_prod_states = production_cleaned[production_cleaned['Region'] != 'Unknown'][['period','process-name', 'value_PROD','State', 'State Name','Region']].copy()
    US_cons_states = consumption[consumption['Region'] != 'Unknown'][['period','process-name','value_DEMAND','State', 'State Name','Region']].copy()
    US_imports_grouped = US_imports.groupby(['period', 'Region'], as_index=False).agg({'value_IMPORTS': 'sum'})
    US_exports_grouped = US_exports.groupby(['period', 'Region'], as_index=False).agg({'value_EXPORTS': 'sum'})

    # Supply and Demand Share Calculations (Replaced with forecast dataframe, because it always contains the most recent month. EIA dataset lags by 3 months)
    US_prod_latest = US_prod_states[US_prod_states['period'] == US_prod_states['period'].max()][['period','Region','value_PROD']]
    prod_share = US_prod_latest.groupby(['period', 'Region'], as_index=False).agg({'value_PROD': 'sum'})
    prod_share['prod_pctshare'] = prod_share['value_PROD'] / prod_share['value_PROD'].sum() * 100

    US_cons_latest = US_cons_states[US_cons_states['period'] == US_cons_states['period'].max()][['period','Region','value_DEMAND']]
    cons_share = US_cons_latest.groupby(['period', 'Region'], as_index=False).agg({'value_DEMAND': 'sum'})
    cons_share['demand_pctshare'] = cons_share['value_DEMAND'] / cons_share['value_DEMAND'].sum() * 100

    # Return object is slightly messy but helps to compartmentalise cleaned data.
    return [pipeline, lease, US_prod_states, US_cons_states, US_imports_grouped, US_exports_grouped, prod_share, cons_share]