import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import calplot
import matplotlib.ticker as mticker

# no st.set_page_config() here – only on the main python file

# Show figures
def show(fig):
    if isinstance(fig, go.Figure):
        st.plotly_chart(fig, width='stretch')
    else:
        st.pyplot(fig)
        plt.close(fig)

def fix_encoding(x):
    if not isinstance(x, str):
        return x
    try:
        return x.encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return x  # already correct, leave as-is

# Run query from session state. run_query is defined in the main page
run_query = st.session_state.get("run_query")


# Cache airport list to improve performance
@st.cache_data(show_spinner="Loading airport list ...")
def load_airport_list():
    df_apt = run_query("""
        SELECT
            a.ident,
            a.name,
            a.iso_country,
            r.country_name
        FROM dim_airport a
        INNER JOIN (
            SELECT DISTINCT iso_country, country_name
            FROM dim_entity_region
        ) r ON a.iso_country = r.iso_country
    """)
    df_apt["name"] = df_apt["name"].apply(fix_encoding)
    df_apt["country_name"] = df_apt["country_name"].fillna(df_apt["iso_country"])
    return df_apt


# Cache data of chosen airport to improve performance
@st.cache_data(show_spinner="Loading data ...")
def load_airport_data(apt_icao):
    return run_query("""
    SELECT
        flt_date,
        ROUND(SUM(COALESCE(dly_apt_arr_1, 0)) / NULLIF(SUM(flt_arr_1), 0), 2) AS avg_delay_per_arrival
    FROM fact_airport_delay
    WHERE flt_date >= :date_start AND flt_date <= :date_end AND apt_icao = :apt_icao
    GROUP BY flt_date
    ORDER BY flt_date ASC;
    """,
    params={
        "date_start": dates_start,
        "date_end": dates_end,
        "apt_icao": apt_icao,
    },
    )


# Cache airline ranking for the chosen airports to improve performance
@st.cache_data(show_spinner="Loading data ...")
def load_top_airlines(airport_icao, direction, top_n):
    col = "adep" if direction == "dep" else "ades"
    return run_query(f"""
        SELECT da.name AS airline, COUNT(*) AS n_flights
        FROM fact_flight ff
        INNER JOIN dim_airline da ON da.icao = ff.icao_operator
        WHERE ff.{col} = '{airport_icao}'
        GROUP BY da.name
        ORDER BY n_flights DESC
        LIMIT {top_n}
        """
    )


# Cache airline ranking for the chosen airports to improve performance
@st.cache_data(show_spinner="Loading data ...")
def load_enroute(iso):
    return run_query("""
    SELECT
        e.year,
        ROUND(SUM(e.dly_ert_c_1), 0)  AS delay_atc_capacity,
        ROUND(SUM(e.dly_ert_s_1), 0)  AS delay_staffing,
        ROUND(SUM(e.dly_ert_w_1), 0)  AS delay_weather,
        ROUND(SUM(e.dly_ert_t_1), 0)  AS delay_equipment,
        ROUND(SUM(e.dly_ert_p_1), 0)  AS delay_special_event,
        ROUND(SUM(e.dly_ert_r_1), 0)  AS delay_routeing,
        ROUND(SUM(e.dly_ert_g_1), 0)  AS delay_aerodrome,
        ROUND(SUM(e.dly_ert_m_1), 0)  AS delay_military,
        ROUND(SUM(e.dly_ert_i_1), 0)  AS delay_industrial_action,
        ROUND(SUM(e.dly_ert_na_1), 0) AS delay_unclassified
    FROM fact_enroute_delay e
    JOIN dim_entity_region r ON e.entity_name = r.entity_name
    WHERE r.iso_country = :iso
    AND e.year BETWEEN 2016 AND 2025
    AND e.entity_type = 'ANSP (AUA)'
    GROUP BY e.year
    ORDER BY e.year
    """,
    params={"iso": iso},
    )


# Cache airport delay causes for the chosen airport to improve performance
@st.cache_data(show_spinner="Loading data ...")
def load_airport_delay_causes(apt_icao):
    return run_query("""
    SELECT
        year,
        ROUND(SUM(dly_apt_arr_a_1), 0)  AS delay_atc_capacity,
        ROUND(SUM(dly_apt_arr_c_1), 0)  AS delay_staffing,
        ROUND(SUM(dly_apt_arr_w_1), 0)  AS delay_weather,
        ROUND(SUM(dly_apt_arr_e_1), 0)  AS delay_equipment,
        ROUND(SUM(dly_apt_arr_s_1), 0)  AS delay_special_event,
        ROUND(SUM(dly_apt_arr_t_1), 0)  AS delay_routeing,
        ROUND(SUM(dly_apt_arr_g_1), 0)  AS delay_aerodrome,
        ROUND(SUM(dly_apt_arr_m_1), 0)  AS delay_met,
        ROUND(SUM(dly_apt_arr_i_1), 0)  AS delay_industrial_action,
        ROUND(SUM(dly_apt_arr_na_1), 0) AS delay_unclassified
    FROM fact_airport_delay
    WHERE apt_icao = :apt_icao
      AND year BETWEEN 2016 AND 2025
    GROUP BY year
    ORDER BY year
    """,
    params={"apt_icao": apt_icao},
    )


################### Website start ###################

st.title("Airport Dashboard")

# 0. Airport Selection

df_apt = load_airport_list()
name_map = dict(zip(df_apt["ident"], df_apt["name"]))

def apt_label(code):
    return name_map.get(code, code)

# 0a. Country selection 
countries = sorted(df_apt["country_name"].dropna().unique())

country = st.selectbox(
    "Which country interests you?",
    countries,
    index=None,
    placeholder="Select a country",
)

# 0b. Airport selection 
if country:
    airports = sorted(
        df_apt.loc[df_apt["country_name"] == country, "ident"].dropna().unique(),
        key=apt_label,
    )
else:
    airports = []

apt_icao = st.selectbox(
    "Which airport interests you the most?",
    airports,
    format_func=apt_label,
    index=None,
    placeholder="Select an airport" if country else "Select a country first",
    disabled=not country,
)

airport_name = apt_label(apt_icao)


# 1. Prepare Data

dates_start = "2016-01-01"
dates_end = "2025-12-31"

if apt_icao == None:
    st.stop()

ts_df = load_airport_data(apt_icao)


ts = ts_df.set_index("flt_date")["avg_delay_per_arrival"]

# Inform if no data for airport available
if ts.empty:
    st.warning(f"No data for {airport_name} ({apt_icao}) available for the given time period (2016 - 2025).")
    st.stop()

ts.index = pd.to_datetime(ts.index)


st.divider()


############ TOP X airlines for the chosen airports ############

top_n_list = list(range(1,6))

top_n = st.selectbox("Ranking amount", top_n_list, index=4, placeholder="How many airlines?")

    # --- departing airlines (airport = origin) ---
df_dep = load_top_airlines(apt_icao, "dep", top_n)


# --- arriving airlines (airport = destination) ---
df_arr = load_top_airlines(apt_icao, "arr", top_n)

fig1, ax1 = plt.subplots(figsize=(7, 5))
ax1.barh(df_dep["airline"], df_dep["n_flights"], color="steelblue")
ax1.invert_yaxis()
#ax1.set_title(f"🛫 Top {top_n} departing airlines — {apt_label(o)}")
ax1.set_xlabel("Number of flights")

fig2, ax2 = plt.subplots(figsize=(7, 5))
ax2.barh(df_arr["airline"], df_arr["n_flights"], color="indianred")
ax2.invert_yaxis()
#ax2.set_title(f"🛬 Top {top_n} arriving airlines — {apt_label(d)}")
ax2.set_xlabel("Number of flights")

cy, cz = st.columns(2)
with cy:
    st.subheader(f"🛫 Top {top_n} departing airlines\n{apt_label(apt_icao)}")
    show(fig1)
with cz:
    st.subheader(f"🛬 Top {top_n} arriving airlines\n{apt_label(apt_icao)}")
    if df_arr["airline"].tolist() == df_dep["airline"].tolist():
        st.warning("Ranking of departing and arriving airlines is identical!")
    else:
        show(fig2)


st.divider()

############ Heatmap ############ 

st.subheader("Total delays zoomed in to a day-to-day comparison")

# calculate figure height and title offset (dynamic)
n_years = ts.index.year.nunique()
fig_height = 2.2 * n_years
title_offset_inches = 0.45
title_y = 1 + (title_offset_inches / fig_height)

# vmax only over days with actual delay (excludes 0-values from scale calculation)
# to avoid skewing the colormap when most days have 0 ATFM delay (e.g. EDDM ~82%)
vmax = ts[ts > 0].quantile(0.85)

# Plot Heatmap
fig, axes = calplot.calplot(
    ts,
    how=None,                 # data is already aggregated daily, no resampling needed
    dropzero=False,           # prevent calplot from auto-converting 0→NaN when >50% zeros
    cmap="YlOrRd",
    colorbar=True,
    suptitle=f"Average delay per arrival per day (minutes)\n{airport_name}\n",
    suptitle_kws={"fontsize": 16, "fontweight": "bold", "y": title_y},
    figsize=(16, fig_height),
    edgecolor="white",
    linewidth=0.6,
    fillcolor="lightgrey",    # lightgrey = missing data (no row in fact_airport_delay)
    vmin=0,
    vmax=vmax,
    yearlabel_kws={"fontsize": 12, "fontweight": "bold", "color": "#333333"},
    monthlabels=["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
    daylabels=["Mon.", "Tue.", "Wed.", "Thu.", "Fri.", "Sat.", "Sun."],
)

show(fig)


st.divider()

############ Deep Dive: selected airport vs. its country ############

st.subheader("Comparison of delay types of selected airport and its country-based airspace")

# Stop here until an airport has been selected in the dropdowns above
if apt_icao is None:
    st.info("Select a country and an airport above to see the deep dive.")
    st.stop()

# ISO country code of the selected airport (country name comes from the country dropdown)
apt_country_iso = df_apt.loc[df_apt["ident"] == apt_icao, "iso_country"].iloc[0]

# Load En-Route (country of the selected airport)

df_enroute = load_enroute(apt_country_iso)

# Load selected Airport data 
df_airport = load_airport_delay_causes(apt_icao)

# Labels
delay_labels = {
    "delay_atc_capacity":      "ATC Capacity (C)",
    "delay_staffing":          "ATC Staffing (S)",
    "delay_weather":           "Weather (W)",
    "delay_equipment":         "Equipment (T)",
    "delay_special_event":     "Special Event (P)",
    "delay_routeing":          "Routeing (R)",
    "delay_aerodrome":         "Aerodrome (G)",
    "delay_met":               "MET (M)",
    "delay_military":          "Military (M)",
    "delay_industrial_action": "Industrial Action (I)",
    "delay_unclassified":      "Unclassified (NA)",
}

airport_cols = [c for c in delay_labels.keys() if c in df_airport.columns]
enroute_cols = [c for c in delay_labels.keys() if c in df_enroute.columns]

COLOR_MAP = {
    "delay_atc_capacity":      "#1f77b4",
    "delay_staffing":          "#ff7f0e",
    "delay_weather":           "#2ca02c",
    "delay_equipment":         "#d62728",
    "delay_special_event":     "#9467bd",
    "delay_routeing":          "#8c564b",
    "delay_aerodrome":         "#e377c2",
    "delay_met":               "#7f7f7f",
    "delay_military":          "#bcbd22",
    "delay_industrial_action": "#17becf",
    "delay_unclassified":      "#aec7e8",
}

# Plot
fig, axes = plt.subplots(1, 2, figsize=(22, 7))

for ax, df, cols, title in [
    (axes[0], df_airport, airport_cols, f"Airport ATFM Delays — {airport_name} (2016–2025)"),
    (axes[1], df_enroute, enroute_cols, f"En-Route ATFM Delays — {country} (2016–2025)"),
]:
    bottom = [0] * len(df)
    for col in cols:
        if col not in df.columns:
            continue
        ax.bar(df["year"], df[col].fillna(0),
               label=delay_labels[col],
               color=COLOR_MAP[col],          # fixed color per delay cause
               bottom=bottom, width=0.65)
        bottom = [b + v for b, v in zip(bottom, df[col].fillna(0))]

    ax.set_title(title, fontsize=12, fontweight='bold', pad=10)
    ax.set_xlabel("Year")
    ax.set_ylabel("ATFM Delay (Minutes)")
    ax.set_xticks(df["year"])
    ax.tick_params(axis='x', rotation=45)
    ax.legend(loc="upper left", fontsize=9)

# Scale the en-route axis to millions for readability
axes[1].yaxis.set_major_formatter(
    mticker.FuncFormatter(lambda x, _: f"{x/1e6:.1f}M")
)

plt.suptitle(f"Airport vs. En-Route ATFM Delay Causes — {airport_name} ({country})",
             fontsize=14, fontweight='bold', y=1.01)
plt.tight_layout()
show(fig)