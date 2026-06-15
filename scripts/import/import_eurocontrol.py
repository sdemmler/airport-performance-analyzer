import pandas as pd
import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

# Set the working directory to the folder containing import_eurocontrol.py
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# Load .env file
load_dotenv()
DB_URL = os.getenv('DATABASE_URL')
engine = create_engine(DB_URL)

# Empty fact tables
with engine.connect() as conn:
    conn.execute(text("TRUNCATE TABLE fact_airport_delay RESTART IDENTITY CASCADE;"))
    conn.execute(text("TRUNCATE TABLE fact_airport_traffic RESTART IDENTITY CASCADE;"))
    conn.execute(text("TRUNCATE TABLE fact_enroute_delay RESTART IDENTITY CASCADE;"))
    conn.commit()

# Years to import
YEARS_LIST = list(range(2016, 2027))



# -------------- Import fact_airport_delay -------------------------------------

# -- Extract raw data --

apt_dly_url = "../../data/raw/eurocontrol/apt_dly/"
df_apt_dly = pd.DataFrame()

for y in YEARS_LIST:
    path = f"{apt_dly_url}apt_dly_{y}.csv"
    if not os.path.exists(path):
        print(f"WARNING: File not found - {path} skipped")
        continue

    df_temp = pd.read_csv(path, encoding='latin-1')
    df_apt_dly = pd.concat([df_apt_dly, df_temp])


# -- Transform --

df_apt_dly["FLT_DATE"] = pd.to_datetime(df_apt_dly["FLT_DATE"], errors="coerce")
df_apt_dly["FLT_DATE"] = df_apt_dly["FLT_DATE"].dt.tz_localize(None)

df_apt_dly["STATE_NAME"] = df_apt_dly["STATE_NAME"].replace({
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye"
})

df_apt_dly = df_apt_dly.drop(columns="ATFM_VERSION")

df_apt_dly.columns = [col.lower() for col in df_apt_dly.columns]


# -- Load --

df_apt_dly.to_sql("fact_airport_delay", engine, if_exists='append', index=False)
print("-- fact_airport_delay finished --")



# -------------- Import fact_enroute_delay -------------------------------------

# -- Extract raw data --

ert_dly_url = "../../data/raw/eurocontrol/enroute_ansp/"
df_ert_dly = pd.DataFrame()

for y in YEARS_LIST:
    path = f"{ert_dly_url}ert_dly_ansp_{y}.csv"
    if not os.path.exists(path):
        print(f"WARNING: File not found - {path} skipped")
        continue
    
    df_temp = pd.read_csv(path, encoding='latin-1')
    df_ert_dly = pd.concat([df_ert_dly, df_temp])


# -- Transform --

df_ert_dly["FLT_DATE"] = pd.to_datetime(df_ert_dly["FLT_DATE"], errors="coerce")
df_ert_dly["FLT_DATE"] = df_ert_dly["FLT_DATE"].dt.tz_localize(None)

df_ert_dly.columns = [col.lower() for col in df_ert_dly.columns]


# -- Load --

df_ert_dly.to_sql("fact_enroute_delay", engine, if_exists='append', index=False)
print("-- fact_enroute_delay finished --")



# -------------- Import fact_airport_traffic -----------------------------------

# -- Extract raw data --

apt_tfc_url = "../../data/raw/eurocontrol/airport_traffic/"
df_apt_tfc = pd.DataFrame()

for y in YEARS_LIST:
    path = f"{apt_tfc_url}airport_traffic_{y}.csv"
    if not os.path.exists(path):
        print(f"WARNING: File not found - {path} skipped")
        continue
    
    df_temp = pd.read_csv(path, encoding='latin-1')
    df_apt_tfc = pd.concat([df_apt_tfc, df_temp])


# -- Transform --

df_apt_tfc["FLT_DATE"] = pd.to_datetime(df_apt_tfc["FLT_DATE"], errors="coerce")
df_apt_tfc["FLT_DATE"] = df_apt_tfc["FLT_DATE"].dt.tz_localize(None)

df_apt_tfc["STATE_NAME"] = df_apt_tfc["STATE_NAME"].replace({
    "Turkey": "Türkiye",
    "Turkiye": "Türkiye"
})

df_apt_tfc = df_apt_tfc.drop(columns=["FLT_DEP_IFR_2", "FLT_ARR_IFR_2", "FLT_TOT_IFR_2"])

df_apt_tfc = df_apt_tfc.drop_duplicates(subset=["APT_ICAO", "FLT_DATE"], keep="first")

df_apt_tfc.columns = [col.lower() for col in df_apt_tfc.columns]


# -- Load --

df_apt_tfc.to_sql("fact_airport_traffic", engine, if_exists='append', index=False)
print("-- fact_airport_traffic finished --")



print("-- import_eurocontrol.py finished --")