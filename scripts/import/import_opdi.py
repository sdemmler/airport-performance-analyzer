import pandas as pd
import os
import glob
from collections import defaultdict
from io import StringIO
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


# Years to import
YEARS_LIST = list(range(2022, 2027))
MONTHS_LIST = ["01", "02", "03", "04", "05", "06", "07", "08", "09", "10", "11", "12"]

# Columns that may arrive as a native timestamp OR as an ISO string,
# depending on the OPDI export version -> parse them to datetime after concat.
TIME_COLS = ["dof", "first_seen", "last_seen"]
# Integer columns. Their storage type changed across exports (uint64 vs int64),
# and unix_time is missing in newer files. Cast each month to nullable Int64
# BEFORE concat so a uint64/int64 mix can't force a lossy float64 upcast.
INT_COLS = ["id", "unix_time"]

# Function to copy data with in-memory-buffer 
def copy_to_sql(df, table, engine):
    
    # create in-memory-buffer
    buffer = StringIO()
    df.to_csv(buffer, index=False, header=False, sep="\t")
    
    # Reset buffer cursor to the beginning
    buffer.seek(0)
    
    # Extract raw psycopg2 connection from SQLAlchemy engine
    with engine.connect() as conn:
        dbapi_conn = conn.connection
        
        with dbapi_conn.cursor() as cursor:
            # Bulk load via PostgreSQL COPY
            # sep="," matches CSV format, null="" maps empty fields to NULL
            cursor.copy_from(buffer, table, sep="\t", null="")
        
        dbapi_conn.commit()


# -------------- Import fact_flight -------------------------------------

# -- Extract raw data --

input_dir = "../../data/raw/opdi/flight_list/"
output_dir = "../../data/processed/opdi/flight_list/"

# Create the output folder if it does not exist yet
os.makedirs(output_dir, exist_ok=True)

for y in YEARS_LIST:
    df_months = []
    for m in MONTHS_LIST:
        path = f"{input_dir}flight_list_{y}{m}.parquet"
        if not os.path.exists(path):
            print(f"WARNING: File not found - {path} skipped")
            continue

        df = pd.read_parquet(path, engine="pyarrow")

        # Cast integer columns per month before concat. The intermediate int64
        # cast handles uint64 sources (uint64 -> Int64 fails the 'safe' rule),
        # then Int64 keeps full precision and allows missing values after concat.
        for col in INT_COLS:
            if col in df.columns:
                df[col] = df[col].astype("int64").astype("Int64")

        df_months.append(df)

    if not df_months:
        print(f"INFO: No data for {y}")
        continue

    df_year = pd.concat(df_months, ignore_index=True)

    # Normalize time columns (timestamp OR string depending on the month)
    for col in TIME_COLS:
        if col in df_year.columns:
            df_year[col] = pd.to_datetime(df_year[col], errors="coerce")
    
    # dof: drop the time part, keep date only
    if "dof" in df_year.columns:
        df_year["dof"] = df_year["dof"].dt.normalize()

    
    # first_seen / last_seen: keep BOTH date and time, in separate columns
    #   *_date -> midnight-normalized datetime64 -> PostgreSQL DATE
    #   *_time -> "HH:MM:SS" string              -> PostgreSQL TIME WITHOUT TIME ZONE
    for col in ["first_seen", "last_seen"]:
        if col in df_year.columns:
            df_year[f"{col}_date"] = df_year[col].dt.normalize()
            df_year[f"{col}_time"] = df_year[col].dt.strftime("%H:%M:%S")
            df_year = df_year.drop(columns=[col])


    output_path = f"{output_dir}flight_list_{y}.parquet"
    df_year.to_parquet(output_path, engine="pyarrow", compression="snappy", index=False)
    print(f"Exported {output_path} ({len(df_year):,} rows)")



# drop columns in previously generated dfs for each year
# final concat into one df to be imported into database

df_years = []

for y in YEARS_LIST:
    
    path = f"{output_dir}flight_list_{y}.parquet"

    df_temp = pd.read_parquet(path, engine="pyarrow")
    
    df_temp = df_temp.drop(columns=["unix_time", "adep_p", "ades_p", "registration", "icao_aircraft_class"], errors="ignore")

    # if column does not exist, drop will be ignored and continued
    # first_seen / last_seen were already split + dropped in the loop above.
    df_temp = df_temp.drop(
        columns=["unix_time", "adep_p", "ades_p", "registration", "icao_aircraft_class", "version"],
        errors="ignore"
    )

    # same id dtype
    df_temp = df_temp.assign(id=df_temp["id"].astype("Int64"))

    df_years.append(df_temp)

df_total = pd.concat(df_years, ignore_index=True)

output_path_total = f"{output_dir}flight_list_total.parquet"

# Remove duplicates
df_total = df_total.drop_duplicates(subset=["id"], keep="first")

# Clean string columns (remove tabs and commas that break COPY)
str_cols = df_total.select_dtypes(include="object").columns
df_total[str_cols] = df_total[str_cols].apply(
    lambda col: col.str.replace("\t", " ", regex=False)
                   .str.replace(",", " ", regex=False)
)

df_total.to_parquet(output_path_total, engine="pyarrow", compression="snappy", index=False)
print(f"Exported {output_path_total} ({len(df_total):,} rows)")

# -- Load --

CHUNK_SIZE = 500000

for i in range(0, len(df_total), CHUNK_SIZE):
    chunk = df_total.iloc[i:i+CHUNK_SIZE]
    copy_to_sql(chunk, "fact_flight", engine)
    print(f"Loaded rows {i} to {i+len(chunk)} to fact_flight")

del df_total
print("-- fact_flight finished --")



# -------------- Import fact_flight_event -------------------------------------

# -- Extract raw data --

input_dir = "../../data/raw/opdi/flight_events/"
output_dir = "../../data/processed/opdi/flight_events/"

# Create the output folder if it does not exist yet
os.makedirs(output_dir, exist_ok=True)

# Define the types of column ["type"] which to keep in the final df
TYPES_TO_KEEP = [
    "take-off",
    "landing",
    "entry-runway",
    "exit-runway",
    "exit-parking_position",
    "entry-parking_position",
    "top-of-climb",
    "top-of-descent"
]

for y in YEARS_LIST:
    files = sorted(glob.glob(f"{input_dir}flight_events_{y}*.parquet"))
    
    if not files:
        print(f"WARNING: No files found for year {y} - skipped")
        continue
    
    # temporary df to modify and drop columns and rows before concat 
    dfs = []
    for file in files:
        df_temp = pd.read_parquet(file)
        df_temp = df_temp.drop(
        columns=["source", "version"],
        errors="ignore"
        )                          
        df_temp = df_temp[df_temp["type"].isin(TYPES_TO_KEEP)]  
        df_temp["event_time"] = pd.to_datetime(df_temp["event_time"])
        df_temp["event_date"] = df_temp["event_time"].dt.normalize()
        df_temp["event_time"] = df_temp["event_time"].dt.strftime("%H:%M:%S")
        dfs.append(df_temp)
    
    df_total2 = pd.concat(dfs, ignore_index=True)
    df_total2["id"] = df_total2["id"].astype(str)
    df_total2["flight_id"] = df_total2["flight_id"].astype(str)
    
    # Drop info column
    df_total2 = df_total2.drop(columns=["info"])

    # Reorder columns to match setup.sql
    df_total2 = df_total2[["id", "flight_id", "type", "event_date", "event_time", "longitude", "latitude", "altitude"]]
    
    output_path = os.path.join(output_dir, f"flight_events_{y}.parquet")
    df_total2.to_parquet(output_path, index=False)
    
    # -- Load --
    
    CHUNK_SIZE = 500000
    
    for i in range(0, len(df_total2), CHUNK_SIZE):
        chunk = df_total2.iloc[i:i+CHUNK_SIZE]
        copy_to_sql(chunk, "fact_flight_event", engine)
    
    del df_total2, dfs
    
    print(f"Loaded: {output_path}")

print("-- fact_flight_event finished --")    


"""
# NOTE: fact_measurement is not currently required (outside the project scope). 
# The import logic remains commented out/unchanged for the time being, 
# in case the scope needs to be redefined at a later date.

# -------------- Import fact_measurement -------------------------------------

# -- Extract raw data --

input_dir = "../../data/raw/opdi/measurements/"
output_dir = "../../data/processed/opdi/measurements/"

# Create the output folder if it does not exist yet
os.makedirs(output_dir, exist_ok=True)

for y in YEARS_LIST:
    files = sorted(glob.glob(f"{input_dir}measurements_{y}*.parquet"))
    
    if not files:
        print(f"WARNING: No files found for year {y} - skipped")
        continue
    

    # during scripting, corrupt files turned up, which could not be fixed by re-downloading.
    # Due to that, the try/except block was placed
    # due to the high file size, the files will be placed in the db one after the other.
    # RAM is freed
    for i, file in enumerate(files):
        try:
            df_temp = pd.read_parquet(file, engine="pyarrow")
            df_temp = df_temp.drop(columns=["version"], errors="ignore")
            
            print(f"Loading: {file} ({len(df_temp)} rows)...")
            copy_to_sql(df_temp, "fact_measurement", engine)           
            print(f"Loaded: {file}")
            
        except Exception as e:
            print(f"CORRUPT: {file} → {e}")
            continue
        
        finally:
            if 'df_temp' in dir():
                del df_temp

print("-- fact_measurement finished --") 

"""