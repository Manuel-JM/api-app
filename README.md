# ITD112 Laboratory Exercise 1: Integrating Soil and Weather APIs

A one-file Streamlit app that combines soil properties from SoilGrids with daily weather from Open-Meteo for sites across Mindanao. The page walks through the integration one step at a time, from the inputs to the exported data, and shows what each step produced.

## What the app does

1. **Inputs:** choose sites (five defaults across Mindanao, plus an optional custom site) and a date range. The inputs are checked before any request is sent.
2. **Request:** builds one Open-Meteo request for all sites and one SoilGrids request per site, and shows the exact URLs.
3. **Send:** every call has a 60-second timeout and up to 3 retries with backoff on 429 and 5xx errors. Successful responses are saved to `cache/`, and the app pauses 12 seconds between uncached SoilGrids calls for fair use. A response log shows the status, time, and size of each call.
4. **Parse:** turns both JSON responses into tables. Each SoilGrids value is divided by its own `d_factor`, and an audit table shows the raw value, the divisor, and the result.
5. **Integrate:** joins soil onto the daily weather by site, calculates the daily water balance (rainfall minus reference ET0), and summarises each site. A join check confirms the row count is unchanged.
6. **Analyse:** answers six questions with six charts.
7. **Export:** downloads the site summary, the joined daily records, and a provenance file.

## The six questions

| | Question | Chart | Data |
|---|---|---|---|
| Q1 | How does temperature change over time? | Line, 7-day rolling mean | Open-Meteo |
| Q2 | Does rainfall meet evaporative demand? | Monthly rainfall bars with an ET0 line | Open-Meteo |
| Q3 | How variable is daily rainfall? | Box plot by month | Open-Meteo |
| Q4 | What is the topsoil texture at each site? | 100% stacked bar | SoilGrids |
| Q5 | Does soil moderate water stress? | Bubble scatter with trend line | Both |
| Q6 | Where are the sites, and how do they differ? | Map, colour = SOC, size = rainfall | Both |

The Q5 trend line appears only when five or more sites are selected. With five sites it is an exploratory sketch, not evidence of a relationship.

## Project structure

```
api-app/
├── .streamlit/
│   └── config.toml      # app theme
├── cache/               # saved API responses, one JSON file per request
├── .gitignore
├── requirements.txt
└── streamlit_app.py     # the whole app
```

## Setup

Requires Python 3.10 or newer.

```
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

The app opens at http://localhost:8501.

## Using the app

1. Select sites and a date range.
2. Click **Run the integration**.
3. Scroll through Steps 3 to 7 to see the responses, tables, charts, and downloads.

A first run with five sites takes about a minute because of the SoilGrids pause. Running the same inputs again is instant, since every response comes from `cache/`. The response log shows these as "saved copy".

The `cache/` folder is included in this repository, so the app can run with the default sites and dates without calling the APIs.

## Notes

- **Null soil values:** SoilGrids returns null for points over water or in gaps in its map. The app shows a warning and keeps going instead of filling in zeros. Moving the point slightly inland usually fixes it.
- **Archive delay:** Open-Meteo's historical archive runs about five days behind today, so the end date must be at least five days in the past.
- **SoilGrids availability:** the SoilGrids REST API is a beta service and is sometimes paused. If it is down, the cached responses still work.

## Data sources

- SoilGrids 2.0 by ISRIC, 0 to 5 cm mean, licensed CC BY 4.0
- Open-Meteo Historical Weather API, licensed CC BY 4.0

SoilGrids values are modelled estimates with quantified uncertainty, not measurements taken at these coordinates.