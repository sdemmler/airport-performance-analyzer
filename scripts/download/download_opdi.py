import os
import requests
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

def generate_urls(data_type: str, start_date: str, end_date: str) -> list:
    """
    Generate a list of URLs for flight lists, flight events, or measurements.

    Args:
        data_type (str): Type of data ("flight_list", "flight_events", "measurements").
        start_date (str): The start date in the format YYYYMM or YYYYMMDD.
        end_date (str): The end date in the format YYYYMM or YYYYMMDD.

    Returns:
        list: List of generated URLs.
    """
    base_url = f"https://www.eurocontrol.int/performance/data/download/OPDI/v002/{data_type}/{data_type}_"

    urls = []
    
    if data_type == "flight_list":  # Monthly intervals
        start_dt = datetime.strptime(start_date, "%Y%m")
        end_dt = datetime.strptime(end_date, "%Y%m")
        delta = relativedelta(months=1)
    else:  # Flight events & Measurements: 10-day intervals
        start_dt = datetime.strptime(start_date, "%Y%m%d")
        end_dt = datetime.strptime(end_date, "%Y%m%d")
        delta = timedelta(days=10)

    current_dt = start_dt
    while current_dt <= end_dt:
        if data_type == "flight_list":
            url = f"{base_url}{current_dt.strftime('%Y%m')}.parquet"
        else:
            next_dt = current_dt + delta
            url = f"{base_url}{current_dt.strftime('%Y%m%d')}_{next_dt.strftime('%Y%m%d')}.parquet"
        
        urls.append(url)
        current_dt += delta

    return urls

def download_files(urls: list, save_folder: str):
    """
    Download files from the generated URLs and save them in the specified folder.

    Args:
        urls (list): List of URLs to download.
        save_folder (str): Folder to save downloaded files.
    """
    os.makedirs(save_folder, exist_ok=True)

    for url in urls:
        file_name = url.split("/")[-1]
        save_path = os.path.join(save_folder, file_name)

        if os.path.exists(save_path):
            print(f"Skipping {file_name}, already exists.")
            continue

        print(f"Downloading {url}...")

        try:
            response = requests.get(url, stream=True)
            response.raise_for_status()

            with open(save_path, "wb") as file:
                for chunk in response.iter_content(chunk_size=1024):
                    file.write(chunk)

            print(f"Saved to {save_path}")

        except requests.exceptions.RequestException as e:
            print(f"Failed to download {url}: {e}")

if __name__ == "__main__":
    datasets = {
        "flight_list": ("`r format(cfg$coverage$start, "%Y%m")`", "`r format(cfg$coverage$end, "%Y%m")`"),
        "flight_events": ("`r format(start_date, "%Y%m%d")`", "`r format(end_date, "%Y%m%d")`")#,
        #"measurements": ("`r format(cfg$coverage$start, "%Y%m%d")`", "`r format(cfg$coverage$end, "%Y%m%d")`")
    }

    for data_type, (start_date, end_date) in datasets.items():
        urls = generate_urls(data_type, start_date, end_date)
        download_files(urls, f"../../data/raw/opdi/{data_type}")