-------------------------------------------
-------------------------------------------
-------------------------------------------

WITH flight_times AS (
    SELECT
        flight_id,
        MIN(event_date + event_time) FILTER (WHERE type = 'entry-runway') AS start_ts,
        MAX(event_date + event_time) FILTER (WHERE type = 'exit-runway')  AS end_ts
    FROM fact_flight_event
    WHERE type IN ('entry-runway', 'exit-runway')
      AND EXTRACT(YEAR FROM event_date) = 2025
    GROUP BY flight_id
)
SELECT
    ff.id                                  AS flight_id,
    da.name                                AS airline,
    da.country                             AS airline_country,
    ff.adep                                AS origin,
    ff.ades                                AS destination,
    ff.dof,
    ft.start_ts,
    ft.end_ts,
    ft.end_ts - ft.start_ts                            AS flight_duration,
    EXTRACT(EPOCH FROM (ft.end_ts - ft.start_ts)) / 60 AS flight_duration_minutes
FROM flight_times ft
INNER JOIN fact_flight ff ON ff.id   = ft.flight_id
INNER JOIN dim_airline da ON da.icao = ff.icao_operator
WHERE EXTRACT(YEAR FROM ff.dof) = 2025
  AND ft.start_ts IS NOT NULL
  AND ft.end_ts   IS NOT NULL
  AND ft.end_ts > ft.start_ts
ORDER BY flight_duration DESC;


-------------------------------------------


WITH flight_times AS (
    SELECT
        flight_id,
        MIN(event_date + event_time) FILTER (WHERE type = 'entry-runway') AS start_ts,
        MAX(event_date + event_time) FILTER (WHERE type = 'exit-runway')  AS end_ts
    FROM fact_flight_event
    WHERE type IN ('entry-runway', 'exit-runway')
      AND EXTRACT(YEAR FROM event_date) = 2025
    GROUP BY flight_id
),
flight_durations AS (
    SELECT
        da.name   AS airline,
        ff.adep   AS origin,
        ff.ades   AS destination,
        EXTRACT(EPOCH FROM (ft.end_ts - ft.start_ts)) / 60 AS duration_minutes
    FROM flight_times ft
    INNER JOIN fact_flight ff ON ff.id   = ft.flight_id
    INNER JOIN dim_airline da ON da.icao = ff.icao_operator
    WHERE EXTRACT(YEAR FROM ff.dof) = 2025
      AND ft.start_ts IS NOT NULL
      AND ft.end_ts   IS NOT NULL
      AND ft.end_ts > ft.start_ts
)
SELECT
    airline,
    origin,
    destination,
    COUNT(*)                                                  AS num_flights,
    ROUND(AVG(duration_minutes)::numeric, 1)                  AS avg_minutes,
    ROUND(
        PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY duration_minutes)::numeric, 1
    )                                                         AS median_minutes,
    ROUND(MIN(duration_minutes)::numeric, 1)                  AS min_minutes,
    ROUND(MAX(duration_minutes)::numeric, 1)                  AS max_minutes
FROM flight_durations
GROUP BY airline, origin, destination
HAVING COUNT(*) >= 10
ORDER BY origin, destination, avg_minutes;
	