import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import plotly.graph_objects as go
import calendar

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


# Cache data of chosen year to improve performance
@st.cache_data(show_spinner="Loading data ...")
def load_year_data(year_selection):
    return run_query("""
        WITH flight_times AS (
            SELECT
                flight_id,
                MIN(event_date + event_time) FILTER (WHERE type = 'exit-runway')  AS start_ts,
                MAX(event_date + event_time) FILTER (WHERE type = 'entry-runway') AS end_ts
            FROM fact_flight_event
            WHERE type IN ('entry-runway', 'exit-runway')
            AND event_date >= make_date(:year_selection, 1, 1)
            AND event_date <  make_date(:year_selection + 1, 1, 1)
            GROUP BY flight_id
        )
        SELECT
            ff.id        AS flight_id,
            da.name      AS airline,
            da.country   AS airline_country,
            ff.adep      AS origin,
            ff.ades      AS destination,
            ff.dof,
            ft.start_ts,
            ft.end_ts,
            ft.end_ts - ft.start_ts                            AS flight_duration,
            EXTRACT(EPOCH FROM (ft.end_ts - ft.start_ts)) / 60 AS flight_duration_minutes
        FROM flight_times ft
        INNER JOIN fact_flight ff ON ff.id   = ft.flight_id
        INNER JOIN dim_airline da ON da.icao = ff.icao_operator
        WHERE ff.dof >= make_date(:year_selection, 1, 1)
        AND ff.dof <  make_date(:year_selection + 1, 1, 1)
        AND ft.start_ts IS NOT NULL
        AND ft.end_ts   IS NOT NULL
        AND ft.end_ts   > ft.start_ts
        ORDER BY origin;
        """,
        params={"year_selection": year_selection}
    )


# Cache airport list to improve performance
@st.cache_data(show_spinner="Loading airport list ...")
def load_airport_list():
    df_apt = run_query("SELECT ident, name FROM dim_airport")
    df_apt["name"] = df_apt["name"].apply(fix_encoding)
    return df_apt


# Cache airline list to improve performance
@st.cache_data(show_spinner="Loading airline list ...")
def load_airline_list():
    df_airline = run_query("SELECT icao, name FROM dim_airline")
    df_airline["name"] = df_airline["name"].apply(fix_encoding) # same encoding fix as on the main page; remove if names are already clean
    return df_airline


# Cache top routes to improve performance
@st.cache_data(show_spinner="Loading routes ...")
def load_top_routes(icao_operator, top_n=5):
    return run_query("""
        SELECT
            ff.adep,
            ff.ades,
            COUNT(*) AS n_flights
        FROM fact_flight ff
        WHERE ff.icao_operator = :icao_operator
          AND ff.adep IS NOT NULL
          AND ff.ades IS NOT NULL
        GROUP BY ff.adep, ff.ades
        ORDER BY n_flights DESC
        LIMIT :top_n
        """,
        params={"icao_operator": icao_operator, "top_n": top_n},
    )

# Cache airlines to improve performance
@st.cache_data(show_spinner="Loading fleet ...")
def load_fleet(icao_operator):
    return run_query("""
        SELECT
            ff.model,
            COUNT(*) AS n_flights
        FROM fact_flight ff
        WHERE ff.icao_operator = :icao_operator
          AND ff.model IS NOT NULL
        GROUP BY ff.model
        ORDER BY n_flights DESC
        """,
        params={"icao_operator": icao_operator},
    )

# Airport names for display (ICAO stays the internal value)
df_apt = load_airport_list()
apt_name_map = dict(zip(df_apt["ident"], df_apt["name"]))

def apt_label(code):
    return apt_name_map.get(code, code)




################### Website start ###################

st.title("Routes & Airline Dashboard")

st.header("Route Insights")

years = list(range(2022, 2027))

year_selection = st.selectbox("", years, index=None, placeholder="Select a year")

if year_selection:
    
    df_year = load_year_data(year_selection)
              

    # keep only rows where both origin and destination are present
    both_not_null = df_year[
        df_year["origin"].notna() & df_year["destination"].notna()
    ]

    # flight duration > 10 min to drop miscalculated durations
    df_clean = both_not_null[
        (both_not_null["flight_duration_minutes"] >= 10) &
        (both_not_null["origin"] != both_not_null["destination"])
    ].copy() 

    # Derive month & day columns
    dts = pd.to_datetime(df_clean["dof"])
    df_clean["month"] = dts.dt.month
    df_clean["day"]   = dts.dt.day

    # Route: destination dropdown depends on the selected origin
    origins = sorted(df_clean["origin"].dropna().unique(), key=apt_label)

    cA, cB = st.columns(2)
    o = cA.selectbox("Departure airport", origins, format_func=apt_label,
                    index=origins.index("EGLL") if "EGLL" in origins else 0)

    destinations = sorted(df_clean.loc[df_clean["origin"] == o, "destination"].dropna().unique(),
                        key=apt_label)
    d = cB.selectbox("Destination airport", destinations, format_func=apt_label,
                    index=destinations.index("EHAM") if "EHAM" in destinations else 0)

    
    # Month & Day (Day only selectable once a month is chosen)
    c1, c2 = st.columns(2)
    month_sel = c1.selectbox("Month", ["All months"] + list(range(1, 13)))

    if month_sel != "All months":
        days_in_month = calendar.monthrange(year_selection, month_sel)[1]
        day_sel = c2.selectbox("Day", ["All days"] + list(range(1, days_in_month + 1)))
    else:
        day_sel = c2.selectbox("Day", ["All days"], disabled=True)

    # Apply filters (not selected = all)
    df_view = df_clean
    if month_sel != "All months": df_view = df_view[df_view["month"] == month_sel]
    if day_sel   != "All days":   df_view = df_view[df_view["day"]   == day_sel]

    # Table: all airlines on the route + total row
    sub_all = df_view[(df_view["origin"] == o) & (df_view["destination"] == d)]

    st.divider()

    st.subheader(f"Airlines on the route {apt_label(o)} → {apt_label(d)}")

    if sub_all.empty:
        st.info("No flights on this route for the selected period.")
    else:
        table = (sub_all["airline"].value_counts()
                .rename_axis("Airline")
                .reset_index(name="Flights"))
        total_row = pd.DataFrame({
            "Airline": [f"Total ({len(table)} airlines)"],
            "Flights": [int(table["Flights"].sum())],
        })
        table = pd.concat([table, total_row], ignore_index=True)
        st.dataframe(table, hide_index=True)

        
        # define month and day string for st.write()
        month_str = f"{month_sel}/" if month_sel != "All months" else ""
        day_str = f"{day_sel}/" if day_sel != "All days" else ""

        st.write(f"The table above shows every airline that operated between the chosen airports ({apt_label(o)} → {apt_label(d)}) during the selected period ({day_str}{month_str}{year_selection}). The boxplot below, however, only includes airlines with at least 30 flights on this route, to ensure the results are statistically meaningful.")

        st.divider()
        
        # Boxplot (airlines with >= 30 flights)
        sub = df_view[(df_view["origin"] == o) & (df_view["destination"] == d)]
        counts = sub["airline"].value_counts()
        sub = sub[sub["airline"].isin(counts[counts >= 30].index)]
        order = sub.groupby("airline")["flight_duration_minutes"].median().sort_values().index
        data  = [sub.loc[sub["airline"] == a, "flight_duration_minutes"] for a in order]

        # Only airline names on the x-axis (n is overlaid in the plot)
        labels = list(order)

        if len(data) == 0:
            st.info("No airline with ≥ 30 flights on this route - no boxplot.")
        else:
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.boxplot(
                data,
                tick_labels=labels,
                showfliers=False,
                patch_artist=True,
                boxprops=dict(facecolor="steelblue", alpha=0.9),
                medianprops=dict(color="crimson", linewidth=2),
            )

            # Overlay sample size per airline
            y_min, y_max = ax.get_ylim()
            y_pos = y_max - (y_max - y_min) * 0.02
            for i, a in enumerate(order, start=1):
                ax.text(i, y_pos, f"n={counts[a]:,}", ha="center", fontsize=8, color="gray")

            ax.set_title(f"Flight duration {apt_label(o)} → {apt_label(d)} by airline\n", fontsize=12)
            ax.set_ylabel("Minutes (airborne)", fontsize=8)
            ax.tick_params(axis="both", labelsize=8)
            plt.xticks(rotation=45, ha="right")
            plt.tight_layout()
            show(fig)


st.divider()

########### Deep Dive Airlines ###########

st.header("Deep dive Airlines")

st.write("Below are the **top 5 routes** of the selected airline along with the **aircraft models** in use, covering the period **2016–2026**.")

# Airline Selection

df_airline = load_airline_list()
airline_name_map = dict(zip(df_airline["icao"], df_airline["name"]))

def airline_label(code):
    return airline_name_map.get(code, code)

airlines = sorted(df_airline["icao"].dropna().unique(), key=airline_label)

airline_icao = st.selectbox(
    "Select an Airline",
    airlines,
    index=4530,
    format_func=airline_label,
)

airline_name = airline_label(airline_icao)


# Top 5 routes for the chosen airline

# Load airlines
df_routes = load_top_routes(airline_icao, top_n=5)

# Rename table columns
df_routes_display = df_routes.rename(columns={
    "adep": "Departure",
    "ades": "Destination",
    "n_flights": "Flights",
})

# display airport names instead of icao
df_routes_display["Departure"]   = df_routes_display["Departure"].apply(apt_label)
df_routes_display["Destination"] = df_routes_display["Destination"].apply(apt_label)

# load fleets
df_fleet = load_fleet(airline_icao)

# Rename table columns
df_fleet_display = df_fleet.rename(columns={
    "model": "Airplane model",
    "n_flights": "Flights",
})

# Display
c1, c2 = st.columns(2)

with c1:
    st.subheader(f"🛫 Top 5 Routes - {airline_name}")
    if df_routes.empty:
        st.warning(f"No route data available for {airline_name} ({airline_icao}).")
        st.stop()
    st.dataframe(df_routes_display, hide_index=True)

with c2:
    st.subheader(f"✈️ Airplane types - {airline_name}")
    if df_fleet.empty:
        st.warning(f"No data available for the airplane model types for {airline_name} ({airline_icao}).")
        st.stop()
    st.dataframe(df_fleet_display, hide_index=True)