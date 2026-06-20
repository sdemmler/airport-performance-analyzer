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

# Run query from session state. run_query is defined in the main page
run_query = st.session_state.get("run_query")


# Cache data of chosen year to improve performance
@st.cache_data(show_spinner="Loading data ...")
def load_year_data(year_selection):
    return run_query(f"""
        WITH flight_times AS (
            SELECT
                flight_id,
                MIN(event_date + event_time) FILTER (WHERE type = 'exit-runway')  AS start_ts,
                MAX(event_date + event_time) FILTER (WHERE type = 'entry-runway') AS end_ts
            FROM fact_flight_event
            WHERE type IN ('entry-runway', 'exit-runway')
            AND event_date >= DATE '{year_selection}-01-01'
            AND event_date <  DATE '{year_selection + 1}-01-01'
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
        WHERE ff.dof >= DATE '{year_selection}-01-01'
        AND ff.dof <  DATE '{year_selection + 1}-01-01'
        AND ft.start_ts IS NOT NULL
        AND ft.end_ts   IS NOT NULL
        AND ft.end_ts   > ft.start_ts
        ORDER BY origin;
        """
    )


# Cache airline ranking for the chosen airports to improve performance
@st.cache_data(show_spinner=False)
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



st.title("Dashboard")

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

    # Airport names for display (ICAO stays the internal value)
    df_apt = run_query("SELECT ident, name FROM dim_airport")
    df_apt["name"] = df_apt["name"].apply(
        lambda x: x.encode("latin-1").decode("utf-8") if isinstance(x, str) else x
    )  # same encoding fix as on the main page; remove if names are already clean
    name_map = dict(zip(df_apt["ident"], df_apt["name"]))

    def apt_label(code):
        return name_map.get(code, code)        

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

        # Boxplot (airlines with >= 30 flights)
        sub = df_view[(df_view["origin"] == o) & (df_view["destination"] == d)]
        counts = sub["airline"].value_counts()
        sub = sub[sub["airline"].isin(counts[counts >= 30].index)]
        order = sub.groupby("airline")["flight_duration_minutes"].median().sort_values().index
        data  = [sub.loc[sub["airline"] == a, "flight_duration_minutes"] for a in order]

        # Show airline and number of flight counts used in the boxplot
        labels = [f"{a} (n={counts[a]})" for a in order]

        if len(data) == 0:
            st.info("No airline with ≥ 30 flights on this route - no boxplot.")
        else:
            fig, ax = plt.subplots(figsize=(10, 5))
            ax.boxplot(data, tick_labels=labels, showfliers=False)
            ax.set_title(f"Flight duration {apt_label(o)} → {apt_label(d)} by airline")
            ax.set_ylabel("Minutes (airborne)")
            # ax.set_xlabel("Airline")
            plt.xticks(rotation=45, ha="right")
            plt.tight_layout()
            show(fig)

            

### TOP X airlines for the chosen airports

    top_n_list = list(range(1,6))

    top_n = st.selectbox("Ranking amount", top_n_list, index=4, placeholder="How many airlines?")
    
        # --- departing airlines (airport = origin) ---
    df_dep = load_top_airlines(o, "dep", top_n)


    # --- arriving airlines (airport = destination) ---
    df_arr = load_top_airlines(d, "arr", top_n)
    
    fig1, ax1 = plt.subplots(figsize=(7, 5))
    ax1.barh(df_dep["airline"], df_dep["n_flights"], color="steelblue")
    ax1.invert_yaxis()
    ax1.set_title(f"Top {top_n} departing airlines — {apt_label(o)}")
    ax1.set_xlabel("Number of flights")

    fig2, ax2 = plt.subplots(figsize=(7, 5))
    ax2.barh(df_arr["airline"], df_arr["n_flights"], color="indianred")
    ax2.invert_yaxis()
    ax2.set_title(f"Top {top_n} arriving airlines — {apt_label(d)}")
    ax2.set_xlabel("Number of flights")

    cy, cz = st.columns(2)
    with cy:
        show(fig1)
    with cz:
        show(fig2)