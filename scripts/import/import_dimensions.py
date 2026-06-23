import pandas as pd
import os
from dotenv import load_dotenv, find_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL

load_dotenv(find_dotenv())

def get_engine():
    url = URL.create(
        "postgresql+psycopg2",
        username=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        host=os.environ["DB_HOST"],
        port=os.environ["DB_PORT"],
        database=os.environ["DB_NAME"],
    )
    return create_engine(url, pool_pre_ping=True, pool_recycle=1800)

engine = get_engine()

# Empty fact tables that reference dimensions
with engine.connect() as conn:
    conn.execute(text("TRUNCATE TABLE fact_enroute_delay RESTART IDENTITY CASCADE;"))
    conn.execute(text("TRUNCATE TABLE fact_airport_delay RESTART IDENTITY CASCADE;"))
    conn.execute(text("TRUNCATE TABLE fact_airport_traffic RESTART IDENTITY CASCADE;"))
    conn.execute(text("TRUNCATE TABLE fact_weather RESTART IDENTITY CASCADE;"))
    conn.commit()

# Years to import
YEARS_LIST = list(range(2016, 2027))



# -------------- Import dim_airport -------------------------------------

# -- Extract raw data --

airports_url = "../../data/raw/opdi/"
path = f"{airports_url}airports.csv"
df_airport = pd.read_csv(path, encoding='latin-1', na_values=[''], keep_default_na=False)


# -- Transform --

# scheduled_service in boolean
df_airport["scheduled_service"] = df_airport["scheduled_service"].apply(lambda x: True if x == "yes" else False)

# Drop columns
df_airport = df_airport.drop(columns=["elevation_ft", "home_link", "wikipedia_link", "keywords"])

df_airport.columns = [col.lower() for col in df_airport.columns]


# -- Load --

# Clear the table before importing
with engine.connect() as conn:
    conn.execute(text("TRUNCATE TABLE dim_airport RESTART IDENTITY CASCADE;"))
    conn.commit()

df_airport.to_sql("dim_airport", engine, if_exists='append', index=False)
print("-- dim_airport finished --")



# -------------- Import dim_runway -------------------------------------

# -- Extract raw data --

runway_url = "../../data/raw/opdi/"
path = f"{runway_url}runways.csv"
df_runway = pd.read_csv(path, encoding='latin-1')


# -- Transform --

# Drop columns
df_runway = df_runway.iloc[:, :8]

df_runway["lighted"] = df_runway["lighted"].astype(bool)
df_runway["closed"] = df_runway["closed"].astype(bool)

df_runway.columns = [col.lower() for col in df_runway.columns]


# -- Load --

with engine.connect() as conn:
    conn.execute(text("TRUNCATE TABLE dim_runway RESTART IDENTITY CASCADE;"))
    conn.commit()

df_runway.to_sql("dim_runway", engine, if_exists='append', index=False)
print("-- dim_runway finished --")



# -------------- Import dim_airline -------------------------------------

# -- Extract raw data --

airline_url = "../../data/raw/openflights/"
path = f"{airline_url}airlines.dat"
df_airline = pd.read_csv(
    path,
    header=None,
    names=["id", "name", "alias", "iata", "icao", "callsign", "country", "active"],
    encoding="utf-8",
    na_values=["\\N"]
    )


# -- Transform --

# Drop columns
df_airline = df_airline[["icao", "name", "country"]]

# Remove rows with missing icao values
df_airline = df_airline[df_airline["icao"].notnull()]

df_airline = df_airline.drop_duplicates(subset=["icao"], keep="first")

df_airline.columns = [col.lower() for col in df_airline.columns]


# -- Load --

with engine.connect() as conn:
    conn.execute(text("TRUNCATE TABLE dim_airline RESTART IDENTITY CASCADE;"))
    conn.commit()

df_airline.to_sql("dim_airline", engine, if_exists='append', index=False)
print("-- dim_airline finished --")



# -------------- Import dim_entity_region -------------------------------------

# -- Extract raw data --

region_url = "../../data/raw/eurocontrol/"
path = f"{region_url}dim_entity_region.csv"
df_entity_region = pd.read_csv(path, encoding='latin-1')


# -- Transform --

df_entity_region.columns = [col.lower() for col in df_entity_region.columns]


# -- Load --

with engine.connect() as conn:
    conn.execute(text("TRUNCATE TABLE dim_entity_region RESTART IDENTITY CASCADE;"))
    conn.commit()

df_entity_region.to_sql("dim_entity_region", engine, if_exists='append', index=False)
print("-- dim_entity_region finished --")



# -------------- Import dim_public_holidays -------------------------------------

# -- Extract raw data --

public_hol_url = "../../data/raw/holidays/"
path = f"{public_hol_url}public_holidays.csv"
df_public_hol = pd.read_csv(path, encoding='latin-1', keep_default_na=False)


# -- Transform --

df_public_hol["date"] = pd.to_datetime(df_public_hol["date"], errors="coerce")
df_public_hol["date"] = df_public_hol["date"].dt.tz_localize(None)

df_public_hol = df_public_hol.drop_duplicates(
    subset=["country_code", "date", "name"],
    keep="first"
)

df_public_hol["launch_year"] = pd.to_numeric(df_public_hol["launch_year"], errors="coerce")

# -- Load --

with engine.connect() as conn:
    conn.execute(text("TRUNCATE TABLE dim_public_holidays RESTART IDENTITY CASCADE;"))
    conn.commit()

df_public_hol.to_sql("dim_public_holidays", engine, if_exists='append', index=False)
print("-- dim_public_holidays finished --")



# -------------- Import dim_school_holidays -------------------------------------

# -- Extract raw data --

school_hol_url = "../../data/raw/holidays/"
path = f"{school_hol_url}school_holidays.csv"
df_school_hol = pd.read_csv(path, encoding='latin-1', keep_default_na=False)


# -- Transform --

df_school_hol["start_date"] = pd.to_datetime(df_school_hol["start_date"], errors="coerce")
df_school_hol["start_date"] = df_school_hol["start_date"].dt.tz_localize(None)

df_school_hol["end_date"] = pd.to_datetime(df_school_hol["end_date"], errors="coerce")
df_school_hol["end_date"] = df_school_hol["end_date"].dt.tz_localize(None)

df_school_hol = df_school_hol.drop(columns=["holiday_id"])

df_school_hol = df_school_hol.drop_duplicates(
    subset=["country_code", "start_date", "name"],
    keep="first"
)


# -- Load --

with engine.connect() as conn:
    conn.execute(text("TRUNCATE TABLE dim_school_holidays RESTART IDENTITY CASCADE;"))
    conn.commit()

df_school_hol.to_sql("dim_school_holidays", engine, if_exists='append', index=False)
print("-- dim_school_holidays finished --")



print("-- import_dimensions.py finished --")