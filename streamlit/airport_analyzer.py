import os
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st
from sqlalchemy import create_engine, text
from pathlib import Path
from dotenv import load_dotenv
import plotly.express as px
from theme import apply_theme
import plotly.graph_objects as go

# Page definition -- only for main page
st.set_page_config(
    page_title="Airport Performance Analyzer",
    page_icon=":airplane:",
    layout="wide",
)

# set global theme
apply_theme()

# Load .env from /streamlit/
load_dotenv(Path(__file__).parent / ".env")


# Connection to DB
@st.cache_resource
def get_engine():
    url = (
        f"postgresql+psycopg2://"
        f"{os.environ['DB_USER']}:{os.environ['DB_PASSWORD']}"
        f"@{os.environ['DB_HOST']}:{os.environ['DB_PORT']}"
        f"/{os.environ['DB_NAME']}"
    )
    return create_engine(url)

def run_query(query, params=None):
    with get_engine().connect() as conn:
        return pd.read_sql(text(query), conn, params=params or {})


# Show figures
def show(fig):
    if isinstance(fig, go.Figure):
        st.plotly_chart(fig, width='stretch')
    else:
        st.pyplot(fig)
        plt.close(fig)


# save run_query in session_state -> subpages can access it
st.session_state["run_query"] = run_query
st.session_state["get_engine"] = get_engine


# Main Page (set as funktion -> presented as its own page)
def home():
    st.title("✈️ Airport Performance Analyzer - Dashboard")
    st.markdown(
        """
        Welcome!
        """
    )
    st.divider()

    
    st.subheader("🇪🇺 Top 15 EU busiest countries.")
    
    with st.spinner("Loading data ..."):
        df_airports = run_query("""
            SELECT
                t.apt_icao,
                a.name            AS airport_name,
                a.iso_country     AS country,
                a.municipality,
                SUM(t.flt_tot_1)  AS total_movements,
                SUM(t.flt_dep_1)  AS departures,
                SUM(t.flt_arr_1)  AS arrivals,
                ROUND(AVG(t.flt_tot_1), 0) AS avg_daily
            FROM fact_airport_traffic t
            JOIN dim_airport a ON t.apt_icao = a.ident
            WHERE EXTRACT(year FROM t.flt_date) BETWEEN 2019 AND 2024
            AND t.flt_tot_1 > 0
            GROUP BY t.apt_icao, a.name, a.iso_country, a.municipality
            ORDER BY total_movements DESC
            LIMIT 20
            """
        )
    
    
    top15 = df_airports.head(15).copy()
    top15['label'] = top15['apt_icao'] + '\n' + top15['municipality'].str[:12]

    fig, ax = plt.subplots(figsize=(13, 5))
    bars = ax.bar(top15['label'], top15['total_movements'] / 1e6,
                alpha=0.85, edgecolor='white')
    ax.bar_label(bars, fmt=lambda x: f'{x:.1f}M', padding=3, fontsize=8)
    ax.set_ylabel('IFR flight movements (millions)')
    ax.set_title('Top 15 European airports by flight movements (2019–2024)',
                fontweight='bold', pad=12)
    ax.set_ylim(0, top15['total_movements'].max() / 1e6 * 1.15)
    plt.xticks(fontsize=8.5)

    plt.tight_layout()
    show(fig)
    

    st.divider()


    st.subheader("🇪🇺 Map of IFR flight movements within Europe.")

    with st.spinner("Loading data ..."):
        df_map = run_query("""
            SELECT
                t.apt_icao,
                a.name            AS airport_name,
                a.municipality,
                a.iso_country     AS country,
                a.latitude_deg    AS lat,
                a.longitude_deg   AS lon,
                SUM(t.flt_tot_1)  AS total_movements
            FROM fact_airport_traffic t
            JOIN dim_airport a ON t.apt_icao = a.ident
            WHERE EXTRACT(year FROM t.flt_date) = 2025
            AND t.flt_tot_1 > 0
            AND a.latitude_deg  BETWEEN 35 AND 72     -- Europe-Bounding-Box
            AND a.longitude_deg BETWEEN -25 AND 45
            AND a.type IN ('large_airport', 'medium_airport')
            GROUP BY t.apt_icao, a.name, a.municipality, a.iso_country, a.latitude_deg, a.longitude_deg
            HAVING SUM(t.flt_tot_1) > 500
            ORDER BY total_movements DESC
            """
            )

    fig = px.scatter_geo(
        df_map,
        lat='lat',
        lon='lon',
        size='total_movements',
        color='total_movements',
        color_continuous_scale='Blues',
        hover_name='airport_name',
        hover_data={
            'apt_icao':         True,
            'municipality':     True,
            'country':          True,
            'total_movements':  ':,.0f',
            'lat':              False,
            'lon':              False,
        },
        size_max=40,
        scope='europe',
        title='European airports by IFR flight movements (2025)',
        labels={'total_movements': 'Flight movements'},
    )
    fig.update_layout(
        coloraxis_colorbar=dict(title='Flight movements'),
        geo=dict(
            showland=True,        landcolor='#e8e8e8',
            showocean=True,       oceancolor='#dceefb',
            showcoastlines=True,  coastlinecolor='white',
            showcountries=True,   countrycolor='white',      
            projection_type='natural earth',
            center=dict(lat=52, lon=12),
            lataxis_range=[34, 72],
            lonaxis_range=[-25, 45],
        ),
        margin=dict(l=0, r=0, t=40, b=0),
        height=550,
    )
    show(fig)

    


# Definition off all pages
page_home     = st.Page(home,          title="Overview", icon="🏠", default=True)
page_subpage01 = st.Page("subpage01.py", title="Subpage01",  icon="✈️")
page_subpage02   = st.Page("subpage02.py",   title="Subpage02",     icon="✈️")

subpage = st.navigation([page_home, page_subpage01, page_subpage02])


# Sidebar
with st.sidebar:
    # st.image("") left blank to put an image later on
    st.markdown("---")


# Area, which is shown on ALL pages


subpage.run()