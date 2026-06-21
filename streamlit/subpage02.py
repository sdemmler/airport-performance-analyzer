import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import calplot

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
    df_apt = run_query("SELECT ident, name FROM dim_airport")
    df_apt["name"] = df_apt["name"].apply(fix_encoding)
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

st.title("Airport Dashboard")

# -----------------------------------------------------------------
# 0. Airport Selection
# -----------------------------------------------------------------

df_apt = load_airport_list()
name_map = dict(zip(df_apt["ident"], df_apt["name"]))

def apt_label(code):
    return name_map.get(code, code)

airports = sorted(df_apt["ident"].dropna().unique(), key=apt_label)

apt_icao = st.selectbox(
    "Which airport interests you the most?",
    airports,
    format_func=apt_label,
    index=None, #airports.index("EDDM") if "EDDM" in airports else 0,
    placeholder="Select an airport"
)

airport_name = apt_label(apt_icao)

# -----------------------------------------------------------------
# 1. Prepare Data
# -----------------------------------------------------------------

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


############ Heatmap ############ 

show__heatmap = st.toggle(f"Want to see a detailed heatmap of the delays per day for {apt_label(apt_icao)}")

if show__heatmap:
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