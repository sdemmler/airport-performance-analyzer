"""
download_weather.py
====================
Downloads historical weather data from Open-Meteo for all relevant EU airports listed in `airports.csv` and saves it directly to PostgreSQL.

"""

import os
import time
import logging
import requests
import pandas as pd
import psycopg2
from io    import StringIO
from datetime import datetime, timedelta
from dotenv   import load_dotenv

# ── Configuration ─────────────────────────────────────────────

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

DB_SCHEMA = os.getenv("DB_SCHEMA", "public")

AIRPORTS_CSV = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "../../data/raw/opdi/airports.csv")

YEARS = list(range(2019, 2027))   # 2019 – 2026 incl.

VARIABLES = [
    "wind_speed_10m",   # km/h
    "precipitation",    # mm
    "temperature_2m",   # °C
    "snowfall",         # cm
    "cloud_cover",      # %
]

# API calculation:
MAX_CALLS_PER_DAY = 8000
CALLS_PER_YEAR    = 26
SLEEP_SECONDS     = 1.2   # Pause between requests

# ── Logging ───────────────────────────────────────────────────

os.makedirs("logs", exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.FileHandler("logs/download_weather.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)


# ── Database setup ───────────────────────────────────────────

def init_db(conn) -> None:

    cur = conn.cursor()

    cur.execute(f"CREATE SCHEMA IF NOT EXISTS {DB_SCHEMA};")

    cur.execute(f"SET search_path TO {DB_SCHEMA};")

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS {DB_SCHEMA}.fact_weather (
            apt_icao      CHAR(4)       NOT NULL,
            ts_hour       TIMESTAMPTZ   NOT NULL,
            wind_speed    NUMERIC(6,2),
            precipitation NUMERIC(6,2),
            visibility    NUMERIC(8,1),
            temperature   NUMERIC(5,2),
            snow_depth    NUMERIC(6,2),
            cloud_cover   NUMERIC(5,1),
            PRIMARY KEY (apt_icao, ts_hour)
        );
    """)
    cur.execute(f"""
        CREATE INDEX IF NOT EXISTS idx_weather_apt_hour
            ON {DB_SCHEMA}.fact_weather (apt_icao, ts_hour);
    """)
    conn.commit()
    cur.close()
    log.info(f"✓ Table {DB_SCHEMA}.fact_weather ready")


def get_already_loaded(conn) -> set:

    cur = conn.cursor()
    cur.execute(f"""
        SELECT DISTINCT
            TRIM(apt_icao),
            EXTRACT(year FROM ts_hour)::INTEGER
        FROM {DB_SCHEMA}.fact_weather
    """)
    result = {(row[0], row[1]) for row in cur.fetchall()}
    cur.close()
    return result


# ── Download airports ───────────────────────────────────────────

def load_airports(csv_path: str) -> pd.DataFrame:
    """
        Filters:
        - Continent: EU
        - Type: large / medium / small airport
        - scheduled_service = yes
        - IATA code present (= commercial operation)
        - Coordinates present
    """
    if not os.path.exists(csv_path):
        raise FileNotFoundError(
            f"\n File not found: {csv_path}\n"
        )

    log.info(f"Load airports from: {csv_path}")
    df = pd.read_csv(csv_path, low_memory=False)
    df.columns = df.columns.str.strip().str.lower()

    log.info(f"  Total in CSV        : {len(df):,}")

    mask = (
        (df["continent"] == "EU") &
        (df["type"].isin([
            "large_airport", "medium_airport", "small_airport"
        ])) &
        (df["scheduled_service"].astype(str).str.strip() == "yes") &
        (df["iata_code"].notna()) &
        (df["iata_code"].str.strip() != "") &
        (df["latitude_deg"].notna()) &
        (df["longitude_deg"].notna()) &
        (df["ident"].str.len() == 4) 
    )

    filtered = (
        df[mask][["ident", "name", "latitude_deg", "longitude_deg"]]
        .drop_duplicates(subset=["ident"])
        .sort_values("ident")
        .reset_index(drop=True)
    )

    log.info(f"  After filter (EU+IATA): {len(filtered):,}")
    return filtered


# ── API Call ───────────────────────────────────────────────

def fetch_weather(lat: float, lon: float, year: int) -> dict:

    yesterday  = (datetime.now() - timedelta(days=1)).date()
    start_date = f"{year}-01-01"
    end_date   = min(datetime(year, 12, 31).date(), yesterday)

    # Jahr liegt vollständig in der Zukunft → überspringen
    if end_date < datetime(year, 1, 1).date():
        raise ValueError(f"Year {year} lies in the future –> is skipped")

    r = requests.get(
        "https://archive-api.open-meteo.com/v1/archive",
        params={
            "latitude":   round(float(lat), 6),
            "longitude":  round(float(lon), 6),
            "start_date": start_date,
            "end_date":   str(end_date),
            "hourly":     ",".join(VARIABLES),
            "timezone":   "UTC",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


# ── Database import ──────────────────────────────────────────

def save_to_postgres(data: dict, icao: str, conn) -> int:

    h = data["hourly"]
    n = len(h["time"])

    df = pd.DataFrame({
        "apt_icao":     icao,
        "ts_hour":      h["time"],
        "wind_speed":   h.get("wind_speed_10m",  [None] * n),
        "precipitation":h.get("precipitation",   [None] * n),
        "visibility":   h.get("visibility",      [None] * n),
        "temperature":  h.get("temperature_2m",  [None] * n),
        "snow_depth":   h.get("snowfall",        [None] * n),
        "cloud_cover":  h.get("cloud_cover",     [None] * n),
    })

    cur = conn.cursor()

    cur.execute(f"""
        CREATE TEMP TABLE tmp_weather
        (LIKE {DB_SCHEMA}.fact_weather INCLUDING DEFAULTS)
        ON COMMIT DROP;
    """)

    buf = StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="")
    buf.seek(0)

    cur.copy_expert("""
        COPY tmp_weather
            (apt_icao, ts_hour, wind_speed, precipitation,
             visibility, temperature, snow_depth, cloud_cover)
        FROM STDIN
        WITH (FORMAT csv, NULL '')
    """, buf)

    cur.execute(f"""
        INSERT INTO {DB_SCHEMA}.fact_weather
            SELECT * FROM tmp_weather
        ON CONFLICT (apt_icao, ts_hour) DO NOTHING;
    """)

    conn.commit()
    cur.close()
    return n


# ── Pause logic ───────────────────────────────────────────────

def wait_until_tomorrow() -> None:

    now      = datetime.now()
    tomorrow = (
        datetime.combine(now.date() + timedelta(days=1),
                         datetime.min.time())
        + timedelta(minutes=5)
    )
    secs = int((tomorrow - now).total_seconds())
    h, m = secs // 3600, (secs % 3600) // 60
    log.info(f"Limit reached – pause until tomorrow ({h}h {m}min)")
    time.sleep(secs)


# ── main ───────────────────────────────────────────────────────────

def main():
    log.info("═══ download_weather.py started ══════════════")

    # 1. Load airports
    airports = load_airports(AIRPORTS_CSV)
    total    = len(airports) * len(YEARS)

    log.info(f"Years: {YEARS[0]}–{YEARS[-1]}")
    log.info(f"Requests  : {total:,} gesamt")
    log.info(f"Runtime: ca. {total // MAX_CALLS_PER_DAY + 1} Days")

    # 2. DB connection
    log.info("Connect with PostgreSQL...")
    conn = psycopg2.connect(DATABASE_URL)
    init_db(conn)

    # 3. Get already loaded airports
    already_done = get_already_loaded(conn)
    log.info(f"Already in DB: {len(already_done):,} (icao, year) pairs")

    # 4. Loop
    day_counter = 0
    day_start   = datetime.now().date()
    done        = 0
    skipped     = 0
    errors      = []

    for _, apt in airports.iterrows():
        icao = str(apt["ident"]).strip()

        for year in YEARS:

            # Already loaded → skip
            if (icao, year) in already_done:
                skipped += 1
                continue

            today = datetime.now().date()
            if today != day_start:
                day_counter = 0
                day_start   = today
                log.info("New Days – API-Counter reset")

            if day_counter + CALLS_PER_YEAR > MAX_CALLS_PER_DAY:
                wait_until_tomorrow()
                day_counter = 0
                day_start   = datetime.now().date()

            # Print progress
            progress = done + skipped + len(errors) + 1
            log.info(
                f"[{progress:>5}/{total}]  "
                f"{icao}  {year}  "
                f"– {str(apt['name'])[:35]:<35}  "
                f"(Day-Calls: {day_counter}/{MAX_CALLS_PER_DAY})"
            )

            max_retries = 3
            retry       = 0

            while retry < max_retries:
                try:
                    data = fetch_weather(
                        apt["latitude_deg"], apt["longitude_deg"], year
                    )
                    rows = save_to_postgres(data, icao, conn)

                    day_counter += CALLS_PER_YEAR
                    done        += 1
                    already_done.add((icao, year))
                    log.info(f"  {rows:,} hours saved")
                    break

                except ValueError as e:
                    # Year in the future → skip
                    log.info(f"  ↷ {e}")
                    skipped += 1
                    already_done.add((icao, year))
                    break

                except requests.exceptions.HTTPError as e:
                    if e.response.status_code == 429:
                        log.warning("  429 Rate-Limit – 1 hour pause")
                        time.sleep(3600)
                        day_counter = 0
                        continue
                    else:
                        log.error(f"  ✗ HTTP {e.response.status_code}: {e}")
                        errors.append(f"{icao} {year}: HTTP {e.response.status_code}")
                        break

                except requests.exceptions.Timeout:
                    retry += 1
                    wait   = 30 * retry   # 30s, 60s, 90s
                    log.warning(
                        f"  Timeout - retry {retry}/{max_retries} "
                        f"– wait {wait}s"
                    )
                    if retry < max_retries:
                        time.sleep(wait)
                    else:
                        log.error(f"  ✗ Timeout after {max_retries} tries")
                        errors.append(f"{icao} {year}: Timeout")

                except requests.exceptions.ConnectionError:
                    retry += 1
                    wait   = 60 * retry   # 60s, 120s, 180s
                    log.warning(
                        f"  Connection error – retry {retry}/{max_retries} "
                        f"– wait {wait}s"
                    )
                    if retry < max_retries:
                        time.sleep(wait)
                    else:
                        log.error(f"  Connection error after {max_retries} tries")
                        errors.append(f"{icao} {year}: Connection Error")

                except psycopg2.Error as e:
                    log.error(f"  ✗ DB-error: {e}")
                    errors.append(f"{icao} {year}: DB-error {e.pgcode}")

                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = psycopg2.connect(DATABASE_URL)
                    break

                except Exception as e:
                    log.error(f"  Error: {e}")
                    errors.append(f"{icao} {year}: {e}")
                    break

            time.sleep(SLEEP_SECONDS)

    # 5. Result
    conn.close()

    log.info("═══ Download finished ══════════════════════")
    log.info(f"  Successful: {done:,}")
    log.info(f"  Skipped: {skipped:,}")
    log.info(f"  Errors: {len(errors)}")

    if errors:
        log.warning("Failed requests (to be retried):")
        for e in errors:
            log.warning(f"  {e}")


if __name__ == "__main__":
    main()
