import pandas as pd
import os
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
YEARS_LIST = list(range(2016, 2027))



# -------------- Import fact_weather -------------------------------------

# -- Extract raw data --

weather_url = "../../data/raw/weather/"
path = f"{weather_url}fact_weather.parquet"
df_weather = pd.read_parquet(path, engine="pyarrow")


# -- Transform --

df_weather["ts_hour"] = df_weather["ts_hour"].dt.tz_localize(None)

df_weather = df_weather.drop_duplicates(subset=["apt_icao", "ts_hour"], keep="first")

df_weather.columns = [col.lower() for col in df_weather.columns]


# -- Load --

def copy_to_sql(df, table, engine):
    
    # create in-memory-buffer
    buffer = StringIO()
    df.to_csv(buffer, index=False, header=False)
    
    # Reset buffer cursor to the beginning
    buffer.seek(0)
    
    # Extract raw psycopg2 connection from SQLAlchemy engine
    with engine.connect() as conn:
        dbapi_conn = conn.connection
        
        with dbapi_conn.cursor() as cursor:
            # Bulk load via PostgreSQL COPY
            # sep="," matches CSV format, null="" maps empty fields to NULL
            cursor.copy_from(buffer, table, sep=",", null="")
        
        dbapi_conn.commit()

copy_to_sql(df_weather, "fact_weather", engine)

print("-- fact_weather finished --")