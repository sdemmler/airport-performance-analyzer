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
    
    st.divider()

    year = list(range(2016, 2027))

    year_selection = st.selectbox("", year, index=None, placeholder="Select a year")

    if not year_selection:
        st.write("Select a year in order to see interactive maps of the European Union regarding IFR flight movements and ATFM delay.")
    
    if year_selection:
    
        st.subheader(f"🇪🇺 Map of IFR flight movements within Europe ({year_selection}).")

        with st.spinner("Loading data ..."):
            df_map = run_query(f"""
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
                WHERE EXTRACT(year FROM t.flt_date) = {year_selection}
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

        
        st.subheader(f"🇪🇺 ATFM delay per arrival by airport ({year_selection}).")

        with st.spinner("Loading data ..."):
            df_map_delay = run_query(f"""
                SELECT
                    d.apt_icao,
                    a.name            AS airport_name,
                    a.municipality,
                    a.iso_country     AS country,
                    a.latitude_deg    AS lat,
                    a.longitude_deg   AS lon,
                    SUM(d.flt_arr_1)                                          AS total_arrivals,
                    SUM(d.dly_apt_arr_1)                                      AS total_delay_min,
                    ROUND(SUM(d.dly_apt_arr_1) / NULLIF(SUM(d.flt_arr_1), 0), 3) AS delay_per_arrival
                FROM fact_airport_delay d
                JOIN dim_airport a ON d.apt_icao = a.ident
                WHERE EXTRACT(year FROM d.flt_date) = {year_selection}
                AND d.dly_apt_arr_1 > 0
                AND a.latitude_deg  BETWEEN 35 AND 72
                AND a.longitude_deg BETWEEN -25 AND 45
                AND a.type IN ('large_airport', 'medium_airport')
                GROUP BY d.apt_icao, a.name, a.municipality, a.iso_country,
                        a.latitude_deg, a.longitude_deg
                HAVING SUM(d.flt_arr_1) > 365
                ORDER BY delay_per_arrival DESC
                """
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

    
        choro_toggle = st.toggle(f"Show ATFM delays per flight for {year_selection}")
        
        if choro_toggle:
            
            st.subheader(f"En-route ATFM delays per flight by country — ANSP/AUA level ({year_selection})")

            df_choro = run_query(f"""
                SELECT
                    r.iso_country AS iso_a2,
                    r.country_name,
                    SUM(e.dly_ert_1) AS total_delay_min,
                    SUM(e.flt_ert_1) AS total_flights,
                    ROUND(SUM(e.dly_ert_1) / NULLIF(SUM(e.flt_ert_1), 0), 4) AS delay_per_flight,
                    ROUND(SUM(e.flt_ert_1_dly_15)::NUMERIC
                        / NULLIF(SUM(e.flt_ert_1), 0) * 100, 2) AS pct_delayed_15min,
                    ROUND(SUM(e.dly_ert_c_1) / NULLIF(SUM(e.dly_ert_1), 0) * 100, 1) AS pct_atc_capacity,
                    ROUND(SUM(e.dly_ert_s_1) / NULLIF(SUM(e.dly_ert_1), 0) * 100, 1) AS pct_atc_staffing,
                    ROUND(SUM(e.dly_ert_w_1) / NULLIF(SUM(e.dly_ert_1), 0) * 100, 1) AS pct_weather,
                    ROUND(SUM(e.dly_ert_m_1) / NULLIF(SUM(e.dly_ert_1), 0) * 100, 1) AS pct_military,
                    ROUND(SUM(e.dly_ert_r_1) / NULLIF(SUM(e.dly_ert_1), 0) * 100, 1) AS pct_routeing
                FROM fact_enroute_delay e
                JOIN dim_entity_region r ON e.entity_name = r.entity_name
                WHERE EXTRACT(year FROM e.flt_date) = {year_selection}
                AND e.entity_type = 'ANSP (AUA)'
                AND e.dly_ert_1 IS NOT NULL
                GROUP BY r.iso_country, r.country_name
                ORDER BY delay_per_flight DESC
                """
            )
             
            # ISO-2 → ISO-3
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

            df_choro['iso_a3'] = df_choro['iso_a2'].map(ISO2_TO_ISO3)

            fig_choro = px.choropleth(
            df_choro.dropna(subset=['iso_a3']),
            locations='iso_a3',
            color='delay_per_flight',
            hover_name='country_name',
            hover_data={
                'iso_a3':            False,
                'iso_a2':            False,
                'delay_per_flight':  ':.4f',
                'total_delay_min':   ':,.0f',
                'total_flights':     ':,.0f',
                'pct_delayed_15min': ':.1f',
                'pct_atc_capacity':  ':.1f',
                'pct_atc_staffing':  ':.1f',
                'pct_weather':       ':.1f',
                'pct_military':      ':.1f',
                'pct_routeing':      ':.1f',
            },
            color_continuous_scale='Reds',
            scope='europe',
            #title='En-route ATFM delays per flight by country — ANSP/AUA level (2025)',
            labels={'delay_per_flight': 'min / flight'},
            )
            fig_choro.update_layout(
                coloraxis_colorbar=dict(title='min / flight'),
                geo=dict(
                    showland=True,       landcolor='#d0d0d0',
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

            show(fig_choro)

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

st.subheader("📊 EU-wide summary")

# Implement 4 rows
c1, c2, c3, c4 = st.columns(4)

top3_country_delay = run_query(
    """
    SELECT
        CASE 
            WHEN state_name IN ('Turkey', 'Turkiye', 'Türkiye') THEN 'Türkiye'
            ELSE state_name
        END AS state_name,
        SUM(flt_arr_1) AS total_arrivals,
        ROUND(SUM(dly_apt_arr_1) / NULLIF(SUM(flt_arr_1), 0), 2) AS avg_delay_per_arrival,
        ROUND(SUM(flt_arr_1_dly_15)::NUMERIC / NULLIF(SUM(flt_arr_1), 0) * 100, 2) AS pct_delayed_15
    FROM fact_airport_delay
    WHERE flt_date < '2026-01-01'
    GROUP BY 1
    HAVING SUM(dly_apt_arr_1) IS NOT NULL
    ORDER BY avg_delay_per_arrival DESC
    LIMIT 3;
    """
)

top3_country_delay = top3_country_delay.sort_values('avg_delay_per_arrival', ascending=True)

worst = top3_country_delay.iloc[-1]   # höchster Delay (nach dem Sortieren)
c1.metric("🌍 Worst country", worst['state_name'], f"{worst['avg_delay_per_arrival']} min")
c2.metric(" Worst airport", "—")
c3.metric("Worst ...", "—")
c4.metric(" Best ...", "—")


st.divider()

subpage.run()