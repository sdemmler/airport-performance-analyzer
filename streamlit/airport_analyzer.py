import os
import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns
import streamlit as st
from sqlalchemy import create_engine, text
from pathlib import Path
from dotenv import load_dotenv, find_dotenv
import plotly.express as px
from theme import apply_theme
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from sqlalchemy.engine import URL


# Page definition -- only for main page
st.set_page_config(
    page_title="Airport Performance Analyzer",
    page_icon=":airplane:",
    layout="wide",
)

# set global theme
#apply_theme()

# Load .env from /streamlit/
load_dotenv(find_dotenv())


# Connection to DB
@st.cache_resource
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
    st.title("Airport Performance Analyzer - Dashboard")
    st.markdown(
        """
        European aviation generates millions of delay minutes every year
        but the underlying data is scattered across sources and rarely analyzed together.

        This dashboard integrates **62.5 million individual flights**, **1 million ATFM delay records**
        and **38 million hourly weather observations** across 42 European countries into a single
        analytical platform built as a capstone project of a Data Science programme.

        **What you can explore:**
        - Which airports and countries are most and least reliable
        - What causes delays: weather, ATC capacity, airlines or strikes
        - When delays peak across seasons, weekdays and months
        - How strongly weather correlates with delay patterns

        > *Main Data sources: OPDI · Eurocontrol · Open-Meteo*
        """
    )
    st.divider()

    
    st.subheader("🇪🇺 Top 15 busiest airports within the European Union.")
    
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
        st.caption(
            "Ranked by total IFR flight movements (departures + arrivals) between 2019 and 2024. "
            "Movements are expressed in millions. Only airports with recorded traffic data are included."
        )
    
    st.divider()

    year = list(range(2016, 2027))

    year_selection = st.selectbox("", year, index=None, placeholder="Select a year")

    if not year_selection:
        st.write("Select a year in order to see interactive maps of the European Union regarding IFR flight movements and ATFM delay.")
    
    if year_selection:
    
        st.subheader(f"🇪🇺 Map of IFR flight movements within Europe ({year_selection}).")

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
                WHERE EXTRACT(year FROM t.flt_date) = :year_selection
                AND t.flt_tot_1 > 0
                AND a.latitude_deg  BETWEEN 35 AND 72
                AND a.longitude_deg BETWEEN -25 AND 45
                AND a.type IN ('large_airport', 'medium_airport')
                GROUP BY t.apt_icao, a.name, a.municipality, a.iso_country, a.latitude_deg, a.longitude_deg
                HAVING SUM(t.flt_tot_1) > 500
                ORDER BY total_movements DESC
                """,
                params={"year_selection": year_selection}
            )
        
        df_map['airport_name'] = df_map['airport_name'].apply(
        lambda x: x.encode('latin-1').decode('utf-8') if isinstance(x, str) else x
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
            #title=f'European airports by IFR flight movements ({year_selection})',
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
        st.caption(
            "Each bubble represents an airport. Bubble size and colour indicate total IFR flight movements "
            "for the selected year. Only large and medium airports with more than 500 annual movements are shown."
        )

        st.divider()


        st.subheader(f"🇪🇺 ATFM delay per arrival by airport ({year_selection}).")

        with st.spinner("Loading data ..."):
            df_map_delay = run_query("""
                SELECT
                    d.apt_icao,
                    a.name            AS airport_name,
                    a.municipality,
                    a.iso_country     AS country,
                    a.latitude_deg    AS lat,
                    a.longitude_deg   AS lon,
                    SUM(d.flt_arr_1)                                              AS total_arrivals,
                    SUM(d.dly_apt_arr_1)                                          AS total_delay_min,
                    ROUND(SUM(d.dly_apt_arr_1) / NULLIF(SUM(d.flt_arr_1), 0), 3) AS delay_per_arrival
                FROM fact_airport_delay d
                JOIN dim_airport a ON d.apt_icao = a.ident
                WHERE EXTRACT(year FROM d.flt_date) = :year_selection
                AND d.dly_apt_arr_1 > 0
                AND a.latitude_deg  BETWEEN 35 AND 72
                AND a.longitude_deg BETWEEN -25 AND 45
                AND a.type IN ('large_airport', 'medium_airport')
                GROUP BY d.apt_icao, a.name, a.municipality, a.iso_country,
                        a.latitude_deg, a.longitude_deg
                HAVING SUM(d.flt_arr_1) > 365
                ORDER BY delay_per_arrival DESC
                """,
                params={"year_selection": year_selection}
            )

        df_map_delay['airport_name'] = df_map_delay['airport_name'].apply(
        lambda x: x.encode('latin-1').decode('utf-8') if isinstance(x, str) else x
        )

        fig2 = px.scatter_geo(
            df_map_delay,
            lat='lat',
            lon='lon',
            size='delay_per_arrival',
            color='delay_per_arrival',
            color_continuous_scale='Reds',
            hover_name='airport_name',
            hover_data={
                'apt_icao':          True,
                'municipality':      True,
                'country':           True,
                'delay_per_arrival': ':.3f',
                'total_arrivals':    ':,.0f',
                'lat':               False,
                'lon':               False,
            },
            size_max=40,
            scope='europe',
            #title=f'ATFM delay per arrival by airport ({year_selection})',
            labels={'delay_per_arrival': 'min / arrival'},
        )
        fig2.update_layout(
            coloraxis_colorbar=dict(title='min / arrival'),
            geo=dict(
                showland=True,       landcolor='#e8e8e8',
                showocean=True,      oceancolor='#dceefb',
                showcoastlines=True, coastlinecolor='white',
                showcountries=True,  countrycolor='white',
                projection_type='natural earth',
                center=dict(lat=52, lon=12),
                lataxis_range=[34, 72],
                lonaxis_range=[-25, 45],
            ),
            margin=dict(l=0, r=0, t=40, b=0),
            height=550,
        )
        show(fig2)
        st.caption(
            "ATFM (Air Traffic Flow Management) arrival delay measures the average waiting time per arriving flight "
            "caused by capacity constraints at the destination airport. Values represent minutes of delay per arrival. "
            "Airports with fewer than 365 annual arrivals are excluded."
        )

        st.divider()
                    
        st.subheader(f"Airport vs. En-Route ATFM Delay by Country for {year_selection}")

        # ── Airport delay per arrival by country ─────────────
        df_apt_map = run_query("""
        SELECT
            d.state_name,
            a.iso_country AS iso_a2,
            SUM(d.flt_arr_1) AS total_arrivals,
            SUM(d.dly_apt_arr_1) AS total_delay_min,
            ROUND(SUM(d.dly_apt_arr_1) / NULLIF(SUM(d.flt_arr_1), 0), 4) AS delay_per_arrival
        FROM fact_airport_delay d
        JOIN dim_airport a ON d.apt_icao = a.ident
        WHERE d.year = 2025
        AND d.dly_apt_arr_1 IS NOT NULL
        GROUP BY d.state_name, a.iso_country
        ORDER BY delay_per_arrival DESC
        """
        )

        # ── En-route delay per flight by country ───────────────
        df_ert_map = run_query("""
        SELECT
            r.iso_country AS iso_a2,
            r.country_name,
            SUM(e.dly_ert_1) AS total_delay_min,
            SUM(e.flt_ert_1) AS total_flights,
            ROUND(SUM(e.dly_ert_1) / NULLIF(SUM(e.flt_ert_1), 0), 4) AS delay_per_flight
        FROM fact_enroute_delay e
        JOIN dim_entity_region r ON e.entity_name = r.entity_name
        WHERE e.year = 2025
        AND e.entity_type = 'ANSP (AUA)'
        AND e.dly_ert_1 IS NOT NULL
        GROUP BY r.iso_country, r.country_name
        ORDER BY delay_per_flight DESC
        """
        )
        
        # ── ISO-2 → ISO-3 Mapping ────────────────────────────────────
        ISO2_TO_ISO3 = {
            'AL':'ALB','AM':'ARM','AT':'AUT','AZ':'AZE','BA':'BIH','BE':'BEL',
            'BG':'BGR','BY':'BLR','CH':'CHE','CY':'CYP','CZ':'CZE','DE':'DEU',
            'DK':'DNK','EE':'EST','ES':'ESP','FI':'FIN','FR':'FRA','GB':'GBR',
            'GE':'GEO','GR':'GRC','HR':'HRV','HU':'HUN','IE':'IRL','IL':'ISR',
            'IS':'ISL','IT':'ITA','LT':'LTU','LU':'LUX','LV':'LVA','MD':'MDA',
            'ME':'MNE','MK':'MKD','MT':'MLT','NL':'NLD','NO':'NOR','PL':'POL',
            'PT':'PRT','RO':'ROU','RS':'SRB','SE':'SWE','SI':'SVN','SK':'SVK',
            'TR':'TUR','UA':'UKR',
        }
        df_apt_map['iso_a3'] = df_apt_map['iso_a2'].map(ISO2_TO_ISO3)
        df_ert_map['iso_a3'] = df_ert_map['iso_a2'].map(ISO2_TO_ISO3)

        # ── Plot ─────────────────────────────────────────────────────────────

        fig = make_subplots(
            rows=1, cols=2,
            specs=[[{"type": "choropleth"}, {"type": "choropleth"}]],
            subplot_titles=[
                "En-Route ATFM Delay per Flight (min)",
                "Airport ATFM Delay per Arrival (min)"
            ]
        )

        geo_layout = dict(
            showland=True,       landcolor='#d0d0d0',
            showocean=True,      oceancolor='#dceefb',
            showcoastlines=True, coastlinecolor='white',
            showcountries=True,  countrycolor='white',
            projection_type='natural earth',
            center=dict(lat=52, lon=12),
            lataxis_range=[34, 72],
            lonaxis_range=[-25, 45],
        )

        # geo (links): En-Route
        fig.add_trace(go.Choropleth(
            locations=df_ert_map['iso_a3'],
            z=df_ert_map['delay_per_flight'],
            text=df_ert_map['country_name'],
            colorscale='Blues',
            colorbar=dict(title="min / flight", x=0.46, len=0.8, thickness=15),
            zmin=0, zmax=df_ert_map['delay_per_flight'].quantile(0.95),
            hovertemplate="<b>%{text}</b><br>%{z:.4f} min / flight<extra></extra>",
            geo='geo'
        ))

        # geo2 (rechts): Airport
        fig.add_trace(go.Choropleth(
            locations=df_apt_map['iso_a3'],
            z=df_apt_map['delay_per_arrival'],
            text=df_apt_map['state_name'],
            colorscale='Reds',
            colorbar=dict(title="min / arrival", x=1.02, len=0.8, thickness=15),
            zmin=0, zmax=df_apt_map['delay_per_arrival'].quantile(0.95),
            hovertemplate="<b>%{text}</b><br>%{z:.4f} min / arrival<extra></extra>",
            geo='geo2'
        ))

        fig.update_layout(
            geo=dict(
                **geo_layout,
                domain=dict(x=[0.0, 0.44])
            ),
            geo2=dict(
                **geo_layout,
                domain=dict(x=[0.56, 1.0])
            ),
            height=500,
            margin=dict(l=0, r=80, t=60, b=0),
        )

        show(fig)
        st.caption(
            "Left map: average en-route ATFM delay per flight caused by airspace congestion along the route. "
            "Right map: average airport ATFM delay per arrival caused by capacity constraints at the destination. "
            "Both metrics are expressed in minutes and reflect the selected year."
        )

# Definition off all pages
page_home     = st.Page(home,          title="Overview", icon="🏠", default=True)
page_subpage01 = st.Page("subpage01.py", title="Routes & Airline Insights",  icon="🛣️")
page_subpage02   = st.Page("subpage02.py",   title="Airport Insights",     icon="🛬")

subpage = st.navigation([page_home, page_subpage01, page_subpage02])


# Sidebar
with st.sidebar:
    
    st.markdown(
        '<p style="font-size:1.0rem; color:#666; margin:0;">DSI Education · Capstone 2026</p>'
        '<p style="font-size:1.0rem; color:#666; margin:0;">Sebastian Demmler · André Janßen</p>',
        unsafe_allow_html=True
    )
    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown("Data sources:")
    st.link_button("OPDI", "https://ansperformance.eu/data/", type="secondary")
    st.link_button("Eurocontrol", "https://www.eurocontrol.int/our-data" , type="secondary")
    st.link_button("Openmeteo", "https://open-meteo.com/", type="secondary")
    st.link_button("OurAirports", "https://ourairports.com/data/", type="secondary")
    st.link_button("Nager", "https://date.nager.at/scalar/#api-version-3", type="secondary")
    st.link_button("Holidays", "https://openholidaysapi.org/de/", type="secondary")
    st.markdown("---")

# Area, which is shown on ALL pages

st.image("../docs/images/project_banner.svg", use_container_width=True)

st.divider()

subpage.run()