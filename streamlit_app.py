"""ITD112 Laboratory Exercise 1: Integrating Soil and Weather APIs.

One-file Streamlit app. The numbered sections below match the lab:
1 Configuration, 2 Build the request, 3 Send the request, 4 Parse the JSON,
5 Integrate, 6 Charts (Q1-Q6), 7 Page styling, 8 Pipeline and page.
"""
import hashlib
import json
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

st.set_page_config(page_title="ITD112 Laboratory Exercise 1: API Integration", layout="wide")


# =============================================================================
# 1  Configuration: sites, endpoints, properties, colours
# =============================================================================
SITES = pd.DataFrame(
    [
        ("Iligan City", 8.200, 124.300),
        ("Malaybalay", 8.150, 125.130),
        ("Valencia", 7.900, 125.090),
        ("Davao (Calinan)", 7.190, 125.460),
        ("General Santos", 6.150, 125.150),
    ],
    columns=["site", "lat", "lon"],
)

SOIL_URL = "https://rest.isric.org/soilgrids/v2.0/properties/query"
WEATHER_URL = "https://archive-api.open-meteo.com/v1/archive"

SOIL_PROPERTIES = ["clay", "sand", "silt", "phh2o", "soc"]
SOIL_DEPTH = "0-5cm"
DAILY_VARS = ["temperature_2m_mean", "precipitation_sum", "et0_fao_evapotranspiration"]
TIMEZONE = "Asia/Manila"

CACHE_DIR = Path(__file__).parent / "cache"   # one JSON file per request
SOILGRIDS_PAUSE_S = 12                        # fair use: about 5 calls per minute
TIMEOUT_S = 60

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

COLORS = {
    "teal": "#0F6E7A",
    "sky": "#2F7FC1",
    "sky_pale": "#B8D4EC",
    "sun": "#E39B2D",
    "sand": "#E2C385",
    "silt": "#B48A5E",
    "clay": "#7B4A2A",
    "grey": "#8A9396",
}
SITE_COLORS = ["#0F6E7A", "#E39B2D", "#2F7FC1", "#9C4F96", "#5B8C3A", "#C8553D", "#4B5563"]

SOURCE_NOTE = (f"Sources: SoilGrids 2.0 (ISRIC, CC BY 4.0), {SOIL_DEPTH} mean; "
               "Open-Meteo Historical Weather API (CC BY 4.0).")
CAVEAT = ("SoilGrids is a beta service that may be paused, and its values are modelled "
          "estimates with quantified uncertainty, not measurements taken at these coordinates.")


# =============================================================================
# 2  Build the request  (lab Step 3)
# =============================================================================
def full_url(url, params):
    """The exact URL that will be sent, with the query string encoded."""
    return requests.Request("GET", url, params=params).prepare().url


def build_weather_request(sites, start, end):
    """Open-Meteo accepts comma-separated coordinates, so one request covers every site."""
    params = {
        "latitude": ",".join(str(float(v)) for v in sites["lat"]),
        "longitude": ",".join(str(float(v)) for v in sites["lon"]),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": ",".join(DAILY_VARS),
        "timezone": TIMEZONE,
    }
    return {"api": "Open-Meteo", "label": "All sites", "url": WEATHER_URL,
            "params": params, "full_url": full_url(WEATHER_URL, params)}


def build_soil_request(site, lat, lon):
    """SoilGrids takes one point per request. 'property' repeats once per soil property,
    so params is a list of tuples: a dict would keep only the last 'property'."""
    params = [("lat", float(lat)), ("lon", float(lon)), ("depth", SOIL_DEPTH), ("value", "mean")]
    params += [("property", p) for p in SOIL_PROPERTIES]  # repeated keys
    return {"api": "SoilGrids", "label": site, "url": SOIL_URL,
            "params": params, "full_url": full_url(SOIL_URL, params)}


# =============================================================================
# 3  Send the request, defensively  (lab Step 4)
# =============================================================================
@st.cache_resource
def http_session():
    """Session that retries on rate limiting (429) and server errors (5xx).
    Waits 2 s, 4 s, 8 s between attempts. A 400 is deliberately not retried."""
    retry = Retry(total=3, backoff_factor=2,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=("GET",))
    s = requests.Session()
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.headers["User-Agent"] = "itd112-lab1/1.0"
    return s


def cache_key(req):
    """Hash of URL plus sorted parameters: change one coordinate or date, get a new file."""
    raw = req["url"] + json.dumps(req["params"], sort_keys=True, default=str)
    return hashlib.sha1(raw.encode()).hexdigest()


def send(req):
    """GET the request and return a response record. A response saved on disk is
    reused instead of calling the API again."""
    path = CACHE_DIR / f"{cache_key(req)}.json"
    if path.exists():  # cache hit: no network at all
        text = path.read_text(encoding="utf-8")
        return {"status": None, "from_cache": True, "ms": None,
                "bytes": len(text.encode("utf-8")), "data": json.loads(text)}

    t0 = time.perf_counter()
    r = http_session().get(req["url"], params=req["params"], timeout=TIMEOUT_S)
    ms = (time.perf_counter() - t0) * 1000
    if not r.ok:  # 4xx / 5xx: include the API's own reason when it gives one
        reason = ""
        try:
            body = r.json()
            if isinstance(body, dict):
                reason = str(body.get("reason") or body.get("detail") or "")
        except ValueError:
            pass
        raise requests.HTTPError(f"{r.status_code} {r.reason}. {reason}".strip(), response=r)

    data = r.json()
    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return {"status": r.status_code, "from_cache": False, "ms": ms,
            "bytes": len(r.content), "data": data}


def log_row(req, res):
    return {
        "api": req["api"],
        "request": req["label"],
        "status": "saved copy" if res["from_cache"] else str(res["status"]),
        "time_ms": None if res["ms"] is None else round(res["ms"]),
        "size_kb": round(res["bytes"] / 1024, 1),
    }


def fetch_all(weather_req, soil_reqs, status):
    """One batched Open-Meteo call, then a paced loop of SoilGrids calls."""
    log = []

    status.write("Open-Meteo: one request for all sites")
    try:
        weather_res = send(weather_req)
    except requests.RequestException as exc:
        raise RuntimeError(f"Open-Meteo failed: {exc}. Check the dates and coordinates, "
                           "then try again.") from exc
    log.append(log_row(weather_req, weather_res))

    soil_res = []
    for i, req in enumerate(soil_reqs):
        status.write(f"SoilGrids: {req['label']} ({i + 1} of {len(soil_reqs)})")
        try:
            res = send(req)
        except requests.RequestException as exc:
            raise RuntimeError(
                f"SoilGrids failed for {req['label']}: {exc}. The SoilGrids REST API is a "
                "beta service and is sometimes paused. Try again later; sites already "
                "fetched are saved in cache/ and will not be requested again.") from exc
        soil_res.append(res)
        log.append(log_row(req, res))
        if not res["from_cache"] and i < len(soil_reqs) - 1:
            status.write(f"Pausing {SOILGRIDS_PAUSE_S} s before the next SoilGrids call (fair use)")
            time.sleep(SOILGRIDS_PAUSE_S)

    return weather_res, soil_res, pd.DataFrame(log)


def preview(obj, n=3):
    """Shorten long arrays so a raw JSON response fits on screen."""
    if isinstance(obj, dict):
        return {k: preview(v, n) for k, v in obj.items()}
    if isinstance(obj, list):
        if len(obj) > n and all(not isinstance(x, (dict, list)) for x in obj):
            return obj[:n] + [f"... {len(obj) - n} more"]
        return [preview(x, n) for x in obj]
    return obj


# =============================================================================
# 4  Parse the JSON into tables  (lab Step 5)
# =============================================================================
def parse_weather(data, sites):
    """Each site's 'daily' block holds parallel arrays; each array becomes a column."""
    results = data if isinstance(data, list) else [data]  # one site returns an object
    if len(results) != len(sites):
        raise ValueError(f"Open-Meteo returned {len(results)} locations for {len(sites)} sites.")
    frames = []
    for site, res in zip(sites["site"], results):
        df = pd.DataFrame(res["daily"])
        df.insert(0, "site", site)  # the response identifies sites only by position
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def parse_soil(data, site):
    """One row per soil property. SoilGrids stores integers; dividing by d_factor gives
    conventional units (g/kg -> %, pH x10 -> pH, dg/kg -> g/kg)."""
    rows = []
    for layer in data["properties"]["layers"]:
        raw = layer["depths"][0]["values"]["mean"]
        unit = layer["unit_measure"]
        rows.append({
            "site": site,
            "property": layer["name"],
            "raw_mean": raw,
            "mapped_units": unit.get("mapped_units"),
            "d_factor": unit["d_factor"],
            "value": np.nan if raw is None else raw / unit["d_factor"],
            "target_units": unit.get("target_units"),
        })
    return pd.DataFrame(rows)


def soil_table(soil_long, sites):
    """Pivot to one row per site, one column per property, and attach coordinates."""
    wide = (soil_long.pivot(index="site", columns="property", values="value")
            .reindex(columns=SOIL_PROPERTIES).reset_index())
    wide.columns.name = None
    return sites.merge(wide, on="site", how="left")


# =============================================================================
# 5  Integrate  (lab Step 6)
# =============================================================================
def integrate(weather, soil):
    daily = weather.merge(soil, on="site", how="left")  # the join: soil broadcast to every day
    daily["time"] = pd.to_datetime(daily["time"])
    daily["month"] = daily["time"].dt.month
    daily["water_balance_mm"] = daily["precipitation_sum"] - daily["et0_fao_evapotranspiration"]

    summary = (daily.groupby("site", sort=False)
               .agg(rain_mm=("precipitation_sum", "sum"),
                    et0_mm=("et0_fao_evapotranspiration", "sum"),
                    water_balance_mm=("water_balance_mm", "sum"),
                    temp_mean_c=("temperature_2m_mean", "mean"))
               .reset_index().merge(soil, on="site"))
    return daily, summary


# =============================================================================
# 6  Charts (Q1-Q6)  (lab Step 7)
# =============================================================================
def style(fig, height=420):
    fig.update_layout(height=height, template="plotly_white",
                      margin=dict(l=10, r=10, t=40, b=10),
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None))
    return fig


def site_colors(sites):
    return {s: SITE_COLORS[i % len(SITE_COLORS)] for i, s in enumerate(sites)}


def chart_q1(daily, colors):
    """Q1: temperature over time, 7-day rolling mean per site."""
    d = daily.sort_values(["site", "time"]).copy()
    d["temp_7d"] = (d.groupby("site")["temperature_2m_mean"]
                    .transform(lambda s: s.rolling(7, min_periods=1).mean()))
    fig = px.line(d, x="time", y="temp_7d", color="site", color_discrete_map=colors,
                  labels={"time": "", "temp_7d": "Mean temperature, 7-day rolling (°C)"})
    return style(fig)


def chart_q2(daily, site):
    """Q2: monthly rainfall bars vs reference ET0 line, on the same mm axis."""
    m = (daily[daily["site"] == site].groupby("month")
         [["precipitation_sum", "et0_fao_evapotranspiration"]].sum())
    deficit = m["precipitation_sum"] < m["et0_fao_evapotranspiration"]
    x = [MONTHS[i - 1] for i in m.index]
    fig = go.Figure()
    fig.add_bar(x=x, y=m["precipitation_sum"], name="Rainfall (paler bar = deficit month)",
                marker_color=np.where(deficit, COLORS["sky_pale"], COLORS["sky"]).tolist())
    fig.add_scatter(x=x, y=m["et0_fao_evapotranspiration"], name="Reference ET0",
                    mode="lines+markers", line=dict(color=COLORS["sun"], width=2.5))
    fig.update_yaxes(title="mm per month", rangemode="tozero")
    return style(fig), [MONTHS[i - 1] for i in m.index[deficit]]


def chart_q3(daily, colors):
    """Q3: spread of daily rainfall, box plot by month."""
    d = daily.copy()
    d["month_name"] = d["month"].map(lambda i: MONTHS[i - 1])
    fig = px.box(d, x="month_name", y="precipitation_sum", color="site",
                 color_discrete_map=colors, category_orders={"month_name": MONTHS},
                 labels={"month_name": "", "precipitation_sum": "Daily rainfall (mm)"})
    fig.update_yaxes(rangemode="tozero")
    return style(fig)


def chart_q4(summary):
    """Q4: topsoil texture, 100% stacked bar. Rows are normalised to 100 first, because
    SoilGrids fractions are independent model outputs and rarely sum to exactly 100."""
    tex = summary.set_index("site")[["sand", "silt", "clay"]].dropna()
    if tex.empty:
        return None, None
    raw_total = tex.sum(axis=1)
    tex = tex.div(raw_total, axis=0).mul(100).sort_values("clay")
    fig = go.Figure()
    for comp in ["clay", "silt", "sand"]:
        fig.add_bar(y=tex.index, x=tex[comp], name=comp.capitalize(), orientation="h",
                    marker_color=COLORS[comp], text=tex[comp].map("{:.0f}%".format),
                    textposition="inside", insidetextanchor="middle",
                    hovertemplate="%{y}: %{x:.1f}%<extra>" + comp + "</extra>")
    fig.update_layout(barmode="stack")
    fig.update_xaxes(title="Share of fine earth (%), normalised to 100", range=[0, 100])
    return style(fig, height=140 + 60 * len(tex)), raw_total


def chart_q5(summary):
    """Q5: clay (SoilGrids) vs water balance (Open-Meteo), bubble size = SOC."""
    s = summary.dropna(subset=["clay", "soc"])
    if s.empty:
        return None, None, 0
    soc_max = s["soc"].max() or 1
    fig = go.Figure()
    fig.add_scatter(
        x=s["clay"], y=s["water_balance_mm"], mode="markers+text", text=s["site"],
        textposition="top center", name="Site (bubble size = SOC)", customdata=s["soc"],
        marker=dict(size=14 + 26 * s["soc"] / soc_max, color=COLORS["teal"], opacity=0.75,
                    line=dict(width=1, color="white")),
        hovertemplate="%{text}<br>Clay %{x:.1f}%<br>Water balance %{y:,.0f} mm"
                      "<br>SOC %{customdata:.1f} g/kg<extra></extra>",
    )
    r = None
    if len(s) >= 5:  # least-squares trend line only with five or more points
        slope, intercept = np.polyfit(s["clay"], s["water_balance_mm"], 1)
        r = float(np.corrcoef(s["clay"], s["water_balance_mm"])[0, 1])
        xs = np.linspace(s["clay"].min(), s["clay"].max(), 50)
        fig.add_scatter(x=xs, y=slope * xs + intercept, mode="lines",
                        name=f"Linear fit (r = {r:.2f}, n = {len(s)})",
                        line=dict(color=COLORS["sun"], dash="dash"))
    fig.add_hline(y=0, line_dash="dot", line_color=COLORS["grey"],
                  annotation_text="rainfall = ET0", annotation_position="bottom right")
    fig.update_xaxes(title="Topsoil clay (%)")
    fig.update_yaxes(title="Water balance over the period (mm)")
    return style(fig, height=460), r, len(s)


def chart_q6(summary):
    """Q6: map of the sites, colour = SOC, size = rainfall."""
    s = summary.dropna(subset=["soc"])
    if s.empty:
        return None
    kwargs = dict(
        lat="lat", lon="lon", color="soc", size="rain_mm", hover_name="site",
        hover_data={"lat": ":.3f", "lon": ":.3f", "soc": ":.1f", "rain_mm": ":,.0f",
                    "clay": ":.1f", "water_balance_mm": ":,.0f"},
        labels={"soc": "SOC (g/kg)", "rain_mm": "Rainfall (mm)", "clay": "Clay (%)",
                "water_balance_mm": "Water balance (mm)"},
        color_continuous_scale="YlOrBr", size_max=32, zoom=6,
        center={"lat": float(s["lat"].mean()), "lon": float(s["lon"].mean())},
    )
    if hasattr(px, "scatter_map"):  # Plotly 5.24+: MapLibre-based map
        fig = px.scatter_map(s, map_style="carto-positron", **kwargs)
    else:  # older Plotly
        fig = px.scatter_mapbox(s, mapbox_style="carto-positron", **kwargs)
    fig.update_layout(height=520, margin=dict(l=0, r=0, t=0, b=0))
    return fig


# =============================================================================
# 7  Page styling: CSS and the process diagram
# =============================================================================
CSS = """
<style>
.step-tag {display:inline-block; background:#0F6E7A; color:#FFFFFF; border-radius:999px;
           padding:2px 12px; font-size:0.8rem; font-weight:600; margin-top:1.2rem;}
.flow {display:flex; flex-wrap:wrap; align-items:center; gap:6px; margin:0.4rem 0 1.2rem 0;}
.flow .node {border:1px solid #CFDCDC; background:#F3F6F6; border-radius:8px;
             padding:6px 12px; font-size:0.9rem;}
.flow .node b {color:#0F6E7A; margin-right:4px;}
.flow .arrow {color:#8A9396;}
</style>
"""

FLOW = ["Inputs", "Request", "Send", "Parse", "Integrate", "Analyse", "Export"]


def process_diagram():
    parts = []
    for i, label in enumerate(FLOW, start=1):
        parts.append(f'<span class="node"><b>{i}</b>{label}</span>')
        if i < len(FLOW):
            parts.append('<span class="arrow">&rarr;</span>')
    st.markdown('<div class="flow">' + "".join(parts) + "</div>", unsafe_allow_html=True)


def step_header(n, title, caption):
    st.markdown(f'<span class="step-tag">Step {n}</span>', unsafe_allow_html=True)
    st.subheader(title)
    st.caption(caption)


# =============================================================================
# 8  Pipeline and page: Steps 1-7 rendered in order
# =============================================================================
st.markdown(CSS, unsafe_allow_html=True)
st.title("Integrating APIs: Soil and Weather Data")
st.write("Inputs, request, response, parsing, joining, analysis: one step at a time.")
process_diagram()

# ---- Step 1: Inputs ----------------------------------------------------------
step_header(1, "Define the inputs",
            "Where and when. These two answers become the query parameters for both APIs.")

c1, c2, c3 = st.columns([2, 1, 1])
chosen = c1.multiselect("Sites", SITES["site"].tolist(), default=SITES["site"].tolist()[:3])
start = c2.date_input("Start date", date(2025, 1, 1))
end = c3.date_input("End date", date(2025, 12, 31))

with st.expander("Add a custom site (optional)"):
    st.caption("Keep the point on land. SoilGrids returns null over water.")
    a1, a2, a3, a4 = st.columns([2, 1, 1, 1])
    custom_name = a1.text_input("Site name", "", placeholder="e.g. Maramag")
    custom_lat = a2.number_input("Latitude", value=7.763, min_value=-90.0, max_value=90.0,
                                 step=0.01, format="%.3f")
    custom_lon = a3.number_input("Longitude", value=125.005, min_value=-180.0, max_value=180.0,
                                 step=0.01, format="%.3f")
    a4.write("")
    use_custom = a4.checkbox("Include this site")

sites = SITES[SITES["site"].isin(chosen)].reset_index(drop=True)
problems = []
if use_custom:
    name = custom_name.strip()
    if not name:
        problems.append("Give the custom site a name, or untick Include this site.")
    elif name in sites["site"].values:
        problems.append(f"A site called {name} is already selected; choose another name.")
    else:
        extra = pd.DataFrame([{"site": name, "lat": round(custom_lat, 3), "lon": round(custom_lon, 3)}])
        sites = pd.concat([sites, extra], ignore_index=True)

# Validate before calling: an empty site list makes Open-Meteo answer with a 400.
latest = date.today() - timedelta(days=5)
if sites.empty:
    problems.append("Select at least one site.")
if start > end:
    problems.append("The start date must be on or before the end date.")
if end > latest:
    problems.append(f"The archive runs about five days behind today. "
                    f"Choose an end date on or before {latest}.")

for p in problems:
    st.error(p)
if not sites.empty:
    st.dataframe(sites, hide_index=True, width="stretch")

fetch = st.button("Run the integration", type="primary", disabled=bool(problems))

# ---- Step 2: Build the request ----------------------------------------------
step_header(2, "Build the request",
            "Endpoint plus query parameters, shaped differently for each API. "
            "These are the exact URLs that go over the wire.")

if sites.empty:
    st.info("Select at least one site to see the requests.")
    st.stop()

weather_req = build_weather_request(sites, start, end)
soil_reqs = [build_soil_request(r.site, r.lat, r.lon) for r in sites.itertuples()]
run_key = (tuple(map(tuple, sites[["site", "lat", "lon"]].values.tolist())), start, end)

st.markdown("**Open-Meteo:** one request covers every site (comma-separated coordinates)")
st.code(weather_req["full_url"], language="text", wrap_lines=True)
st.markdown(f"**SoilGrids:** {len(soil_reqs)} requests, one per site, with the "
            "`property` key repeated once per soil property")
for req in soil_reqs:
    st.code(req["full_url"], language="text", wrap_lines=True)

# ---- Run the pipeline (only when the button is pressed) ----------------------
if fetch:
    try:
        with st.status("Calling the APIs", expanded=True) as status:
            weather_res, soil_res, log = fetch_all(weather_req, soil_reqs, status)
            status.update(label="All responses received", state="complete", expanded=False)
    except RuntimeError as exc:
        st.error(str(exc))
        st.stop()

    try:
        weather = parse_weather(weather_res["data"], sites)
        soil_long = pd.concat([parse_soil(res["data"], s)
                               for res, s in zip(soil_res, sites["site"])], ignore_index=True)
        soil = soil_table(soil_long, sites)
        daily, summary = integrate(weather, soil)
    except (KeyError, ValueError, TypeError) as exc:
        st.error(f"Could not parse the responses: {exc}. Open the raw JSON in Step 3 to see what came back.")
        st.stop()

    # Kept in session_state so later widgets (like the Q2 site picker) don't refetch.
    st.session_state.run = {
        "key": run_key, "sites": sites, "log": log,
        "weather_raw": weather_res["data"], "soil_raw": soil_res[0]["data"],
        "weather": weather, "soil_long": soil_long, "soil": soil,
        "daily": daily, "summary": summary, "accessed": date.today().isoformat(),
    }

run = st.session_state.get("run")
if run is None:
    st.info("Press **Run the integration** to send these requests.")
    st.stop()
if run["key"] != run_key:
    st.warning("The inputs have changed since the last run. Everything below is from the "
               "previous run; press Run the integration to refresh it.")

weather, soil_long, soil = run["weather"], run["soil_long"], run["soil"]
daily, summary = run["daily"], run["summary"]
colors = site_colors(run["sites"]["site"])

# ---- Step 3: Send the request -------------------------------------------------
step_header(3, "Send the request, defensively",
            f"Timeout of {TIMEOUT_S} s on every call, 3 retries with backoff on 429 and 5xx, "
            f"a disk cache, and a {SOILGRIDS_PAUSE_S} s pause between SoilGrids calls.")

st.dataframe(run["log"], hide_index=True, width="stretch")
n_cached = int((run["log"]["status"] == "saved copy").sum())
st.caption(f"{n_cached} of {len(run['log'])} responses came from the disk cache. A saved copy "
           "never touches the network, so a second run with the same inputs is instant.")

j1, j2 = st.columns(2)
with j1.expander("Raw JSON: Open-Meteo (long arrays shortened)"):
    st.json(preview(run["weather_raw"]))
with j2.expander(f"Raw JSON: SoilGrids, {run['sites']['site'].iloc[0]}"):
    st.json(run["soil_raw"])

# ---- Step 4: Parse the JSON ---------------------------------------------------
step_header(4, "Parse the JSON into tables",
            "Open-Meteo's parallel arrays become columns. Every SoilGrids value is divided "
            "by its own d_factor, read from the response.")

missing = soil.loc[soil["clay"].isna(), "site"].tolist()
if missing:
    st.warning(f"SoilGrids returned null for: {', '.join(missing)}. The map has no value at "
               "that exact point (water, a built-up area, or a gap in the map). The request "
               "still succeeded; try moving the point slightly inland.")

p1, p2 = st.columns([3, 2])
p1.markdown("**SoilGrids audit table:** value = raw_mean ÷ d_factor")
p1.dataframe(soil_long, hide_index=True, width="stretch")
p2.markdown("**Soil, one row per site**")
p2.dataframe(soil.round(2), hide_index=True, width="stretch")

st.markdown(f"**Open-Meteo daily table:** {len(weather):,} rows (first 10 shown)")
st.dataframe(weather.head(10), hide_index=True, width="stretch")

# ---- Step 5: Integrate --------------------------------------------------------
step_header(5, "Integrate the two sources",
            "A left join on site copies each site's soil values onto every one of its daily "
            "rows, then the daily water balance is rainfall minus ET0.")

clay_rows = int(daily["clay"].notna().sum())
m1, m2, m3, m4 = st.columns(4)
m1.metric("Weather rows", f"{len(weather):,}")
m2.metric("Joined daily rows", f"{len(daily):,}")
m3.metric("Sites in summary", len(summary))
m4.metric("Daily rows with clay", f"{clay_rows:,}")

if len(daily) != len(weather):
    st.error("The join changed the row count. Check for duplicate site names in the soil table.")
elif clay_rows == 0:
    st.error("The join matched nothing: every soil column is empty. Check that site names "
             "match exactly between the two tables.")
elif clay_rows < len(daily):
    st.warning("Join check: row count unchanged, but some sites have no soil values (see Step 4).")
else:
    st.success("Join check passed: row count unchanged and clay populated on every row.")

st.markdown("**Summary: one row per site** (weather totals beside soil properties)")
st.dataframe(summary.round(2), hide_index=True, width="stretch")
with st.expander("Joined daily records (first 20 rows)"):
    st.dataframe(daily.head(20), hide_index=True, width="stretch")

# ---- Step 6: Analyse ----------------------------------------------------------
step_header(6, "Analyse: six questions, six charts",
            "Q1 to Q3 use Open-Meteo alone, Q4 uses SoilGrids alone, and Q5 and Q6 need both.")

st.markdown("#### Q1. How does temperature change over time?")
st.plotly_chart(chart_q1(daily, colors), width="stretch")

st.markdown("#### Q2. Does rainfall meet evaporative demand?")
q2_site = st.selectbox("Site", run["sites"]["site"].tolist(), key="q2_site")
fig2, deficit_months = chart_q2(daily, q2_site)
st.plotly_chart(fig2, width="stretch")
st.caption(f"Deficit months at {q2_site} (rainfall below ET0): "
           f"{', '.join(deficit_months) if deficit_months else 'none'}.")

st.markdown("#### Q3. How variable is daily rainfall?")
st.plotly_chart(chart_q3(daily, colors), width="stretch")

st.markdown("#### Q4. What is the topsoil texture at each site?")
fig4, raw_total = chart_q4(summary)
if fig4 is None:
    st.info("No soil texture values to plot.")
else:
    st.plotly_chart(fig4, width="stretch")
    st.caption("Raw sand + silt + clay before normalising: "
               + ", ".join(f"{s} {v:.1f}%" for s, v in raw_total.items()) + ".")

st.markdown("#### Q5. Does soil moderate water stress?")
fig5, r, n = chart_q5(summary)
if fig5 is None:
    st.info("No sites with both clay and SOC values to plot.")
else:
    st.plotly_chart(fig5, width="stretch")
    if r is None:
        st.caption(f"n = {n}. The trend line appears only with five or more sites.")
    else:
        st.caption(f"r = {r:.2f}, n = {n}. Five sites is an exploratory sketch, not evidence "
                   "of a relationship.")

st.markdown("#### Q6. Where are the sites, and how do they differ?")
fig6 = chart_q6(summary)
if fig6 is None:
    st.info("No sites with soil values to map.")
else:
    st.plotly_chart(fig6, width="stretch")
st.caption(SOURCE_NOTE)

# ---- Step 7: Export -----------------------------------------------------------
step_header(7, "Export, with its provenance",
            "The summary goes into a report; the joined daily records are what someone "
            "continues the analysis from.")

provenance = (f"{SOURCE_NOTE}\nAccessed: {run['accessed']}\n"
              f"Sites: {', '.join(run['sites']['site'])}\n"
              f"Period: {run['key'][1]} to {run['key'][2]}\n"
              f"Caveat: {CAVEAT}\n")

b1, b2, b3, _ = st.columns([1, 1, 1, 1])
b1.download_button("Download site summary (CSV)", summary.to_csv(index=False),
                   "site_summary.csv", "text/csv", width="stretch")
b2.download_button("Download daily records (CSV)", daily.drop(columns="month").to_csv(index=False),
                   "integrated_daily.csv", "text/csv", width="stretch")
b3.download_button("Download provenance (TXT)", provenance,
                   "provenance.txt", "text/plain", width="stretch")

st.info(f"{SOURCE_NOTE} Accessed {run['accessed']}. {CAVEAT}")