
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import json
import logging
import os
import sqlite3
import time
from datetime import datetime

import requests

app = Flask(__name__)
app.secret_key = os.environ.get(
    "SECRET_KEY", "change-this-secret-before-public-deployment"
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get(
    "DATABASE_PATH",
    os.path.join(BASE_DIR, "climatewatch.db")
)

logging.basicConfig(level=logging.INFO)

WEATHER_URL = "https://api.open-meteo.com/v1/forecast"

# Reuse successful weather data for 30 minutes.
WEATHER_CACHE_TTL = 30 * 60

# Stop repeated requests after a rate-limit error.
DEFAULT_RATE_LIMIT_COOLDOWN = 10 * 60

CITIES = {
    "Mumbai": (19.0760, 72.8777, "Maharashtra"),
    "Virar": (19.4559, 72.8114, "Maharashtra"),
    "Vasai": (19.3919, 72.8397, "Maharashtra"),
    "Nagpur": (21.1458, 79.0882, "Maharashtra"),
    "Pune": (18.5204, 73.8567, "Maharashtra"),
    "Nashik": (19.9975, 73.7898, "Maharashtra"),
    "Delhi": (28.6139, 77.2090, "Delhi"),
    "Bengaluru": (12.9716, 77.5946, "Karnataka"),
    "Chennai": (13.0827, 80.2707, "Tamil Nadu"),
    "Kolkata": (22.5726, 88.3639, "West Bengal"),
    "Hyderabad": (17.3850, 78.4867, "Telangana"),
    "Ahmedabad": (23.0225, 72.5714, "Gujarat"),
    "Jaipur": (26.9124, 75.7873, "Rajasthan"),
    "Lucknow": (26.8467, 80.9462, "Uttar Pradesh"),
    "Bhopal": (23.2599, 77.4126, "Madhya Pradesh"),
    "Indore": (22.7196, 75.8577, "Madhya Pradesh"),
    "Patna": (25.5941, 85.1376, "Bihar"),
    "Bhubaneswar": (20.2961, 85.8245, "Odisha"),
    "Guwahati": (26.1445, 91.7362, "Assam"),
    "Kochi": (9.9312, 76.2673, "Kerala"),
    "Thiruvananthapuram": (8.5241, 76.9366, "Kerala"),
    "Chandigarh": (30.7333, 76.7794, "Chandigarh"),
    "Srinagar": (34.0837, 74.7973, "Jammu and Kashmir"),
    "Dehradun": (30.3165, 78.0322, "Uttarakhand"),
    "Shimla": (31.1048, 77.1734, "Himachal Pradesh"),
    "Panaji": (15.4909, 73.8278, "Goa"),
    "Raipur": (21.2514, 81.6296, "Chhattisgarh"),
    "Ranchi": (23.3441, 85.3096, "Jharkhand"),
    "Amritsar": (31.6340, 74.8723, "Punjab"),
    "Surat": (21.1702, 72.8311, "Gujarat"),
    "Vadodara": (22.3072, 73.1812, "Gujarat"),
    "Visakhapatnam": (17.6868, 83.2185, "Andhra Pradesh"),
    "Vijayawada": (16.5062, 80.6480, "Andhra Pradesh"),
    "Coimbatore": (11.0168, 76.9558, "Tamil Nadu"),
    "Mysuru": (12.2958, 76.6394, "Karnataka"),
    "Jodhpur": (26.2389, 73.0243, "Rajasthan"),
    "Varanasi": (25.3176, 82.9739, "Uttar Pradesh"),
    "Agra": (27.1767, 78.0081, "Uttar Pradesh"),
    "Kanpur": (26.4499, 80.3319, "Uttar Pradesh"),
}


class WeatherProviderUnavailable(Exception):
    def __init__(self, message, status_code=502):
        super().__init__(message)
        self.status_code = status_code


def connect_db():
    folder = os.path.dirname(DB_PATH)

    if folder:
        os.makedirs(folder, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS searches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT NOT NULL,
                temperature REAL,
                humidity REAL,
                rain REAL,
                searched_at TEXT NOT NULL
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS citizen_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                city TEXT NOT NULL,
                issue TEXT NOT NULL,
                details TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Persistent weather cache.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS weather_cache (
                city TEXT PRIMARY KEY,
                fetched_epoch REAL NOT NULL,
                report_json TEXT NOT NULL
            )
        """)

        # Shared API cooldown.
        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_state (
                state_key TEXT PRIMARY KEY,
                state_value TEXT NOT NULL
            )
        """)


def resolve_city(city):
    if not city:
        return None

    cleaned = city.strip().casefold()

    for name in CITIES:
        if name.casefold() == cleaned:
            return name

    return None


def get_cached_weather(city):
    try:
        with connect_db() as conn:
            row = conn.execute(
                """
                SELECT fetched_epoch, report_json
                FROM weather_cache
                WHERE city = ?
                """,
                (city,),
            ).fetchone()

        if row is None:
            return None, None

        report = json.loads(row["report_json"])

        return float(row["fetched_epoch"]), report

    except (sqlite3.Error, ValueError, TypeError, json.JSONDecodeError):
        app.logger.exception("Could not read cache for %s", city)
        return None, None


def save_cached_weather(city, report):
    try:
        with connect_db() as conn:
            conn.execute(
                """
                INSERT INTO weather_cache
                    (city, fetched_epoch, report_json)
                VALUES (?, ?, ?)
                ON CONFLICT(city) DO UPDATE SET
                    fetched_epoch = excluded.fetched_epoch,
                    report_json = excluded.report_json
                """,
                (city, time.time(), json.dumps(report)),
            )

    except sqlite3.Error:
        app.logger.exception("Could not save cache for %s", city)


def get_cooldown_until():
    try:
        with connect_db() as conn:
            row = conn.execute(
                """
                SELECT state_value
                FROM app_state
                WHERE state_key = 'weather_cooldown_until'
                """
            ).fetchone()

        return float(row[0]) if row else 0.0

    except (sqlite3.Error, ValueError, TypeError):
        app.logger.exception("Could not read API cooldown")
        return 0.0


def set_cooldown(seconds):
    cooldown_until = time.time() + max(1, seconds)

    try:
        with connect_db() as conn:
            conn.execute(
                """
                INSERT INTO app_state (state_key, state_value)
                VALUES ('weather_cooldown_until', ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    state_value = excluded.state_value
                """,
                (str(cooldown_until),),
            )

    except sqlite3.Error:
        app.logger.exception("Could not save API cooldown")

    return cooldown_until


def stale_report(report, fetched_epoch):
    # Never pretend saved data is live.
    result = dict(report)
    result["is_stale"] = True
    result["cache_notice"] = (
        "Live weather is temporarily unavailable. "
        "Showing the last saved weather data."
    )
    result["fetched_at"] = datetime.fromtimestamp(
        fetched_epoch
    ).strftime("%d %b %Y, %I:%M %p")

    return result


def weather_for(city):
    city = resolve_city(city)

    if city is None:
        raise ValueError("Please select a supported city.")

    cached_epoch, cached_report = get_cached_weather(city)
    now = time.time()

    # Use recent cached data without calling the provider.
    if (
        cached_report
        and cached_epoch
        and now - cached_epoch < WEATHER_CACHE_TTL
    ):
        report = dict(cached_report)
        report["is_stale"] = False
        report["cache_notice"] = None

        app.logger.info("Using cached weather for %s", city)
        return report

    # Avoid repeated API requests during the cooldown.
    cooldown_until = get_cooldown_until()

    if cooldown_until > now:
        if cached_report and cached_epoch:
            return stale_report(cached_report, cached_epoch)

        wait_minutes = max(
            1, int((cooldown_until - now + 59) // 60)
        )

        raise WeatherProviderUnavailable(
            "Weather provider is rate-limited. "
            f"Please try again in about {wait_minutes} minute(s).",
            status_code=429,
        )

    lat, lon, state = CITIES[city]

    params = {
        "latitude": lat,
        "longitude": lon,
        "current": (
            "temperature_2m,relative_humidity_2m,"
            "apparent_temperature,is_day,precipitation,rain,"
            "wind_speed_10m,weather_code"
        ),
        "daily": (
            "temperature_2m_max,temperature_2m_min,"
            "precipitation_probability_max,uv_index_max"
        ),
        "timezone": "auto",
        "forecast_days": 7,
    }

    try:
        response = requests.get(
            WEATHER_URL,
            params=params,
            timeout=(5, 20),
            headers={"User-Agent": "ClimateWatchLocal/1.0"},
        )

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")

            try:
                cooldown_seconds = (
                    max(
                        DEFAULT_RATE_LIMIT_COOLDOWN,
                        int(retry_after),
                    )
                    if retry_after
                    else DEFAULT_RATE_LIMIT_COOLDOWN
                )
            except (TypeError, ValueError):
                cooldown_seconds = DEFAULT_RATE_LIMIT_COOLDOWN

            cooldown_until = set_cooldown(cooldown_seconds)

            if cached_report and cached_epoch:
                app.logger.warning(
                    "Rate limited; using saved weather for %s", city
                )
                return stale_report(cached_report, cached_epoch)

            wait_minutes = max(
                1, int((cooldown_until - time.time() + 59) // 60)
            )

            raise WeatherProviderUnavailable(
                "Weather provider rate limit reached. "
                f"Please wait about {wait_minutes} minute(s) "
                "before trying again.",
                status_code=429,
            )

        response.raise_for_status()
        data = response.json()

    except WeatherProviderUnavailable:
        raise

    except requests.RequestException as exc:
        app.logger.warning(
            "Open-Meteo request failed for %s: %s", city, exc
        )

        if cached_report and cached_epoch:
            return stale_report(cached_report, cached_epoch)

        raise WeatherProviderUnavailable(
            "Weather provider is temporarily unavailable. "
            "Please try again later.",
            status_code=502,
        ) from exc

    if data.get("error"):
        raise ValueError(
            data.get("reason", "Weather provider returned an error.")
        )

    current = data.get("current")
    daily = data.get("daily")

    if not isinstance(current, dict) or not current:
        raise ValueError("Current weather data is missing.")

    if not isinstance(daily, dict) or not daily.get("time"):
        raise ValueError("Forecast data is missing.")

    temp = current.get("temperature_2m")
    rain = current.get("rain") or 0

    if temp is None:
        raise ValueError("Current temperature is unavailable.")

    report = {
        "city": city,
        "state": state,
        "latitude": lat,
        "longitude": lon,
        "current": current,
        "daily": daily,
        "heat_risk": (
            "High" if temp >= 35
            else "Moderate" if temp >= 30
            else "Low"
        ),
        "rain_indicator": "Elevated" if rain >= 5 else "Low today",
        "fetched_at": datetime.now().strftime("%d %b %Y, %I:%M %p"),
        "is_stale": False,
        "cache_notice": None,
    }

    save_cached_weather(city, report)
    return report


@app.route("/")
def index():
    return render_template(
        "index.html",
        cities=sorted(CITIES.keys()),
    )


@app.route("/weather")
def weather():
    requested_city = request.args.get("city", "Virar")
    city = resolve_city(requested_city)

    if city is None:
        return render_template(
            "weather.html",
            report=None,
            cities=sorted(CITIES.keys()),
            selected_city=requested_city,
            error="Please select a valid city from the list.",
        )

    try:
        report = weather_for(city)
        current = report["current"]

        with connect_db() as conn:
            conn.execute(
                """
                INSERT INTO searches
                    (city, temperature, humidity, rain, searched_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    city,
                    current.get("temperature_2m"),
                    current.get("relative_humidity_2m"),
                    current.get("rain") or 0,
                    datetime.now().isoformat(timespec="seconds"),
                ),
            )

        return render_template(
            "weather.html",
            report=report,
            cities=sorted(CITIES.keys()),
            selected_city=city,
            error=None,
        )

    except WeatherProviderUnavailable as exc:
        return render_template(
            "weather.html",
            report=None,
            cities=sorted(CITIES.keys()),
            selected_city=city,
            error=str(exc),
        )

    except (ValueError, KeyError) as exc:
        app.logger.exception("Weather response error for %s", city)
        message = f"Weather data could not be processed: {str(exc)[:200]}"

    except sqlite3.Error:
        app.logger.exception("Database error while saving search")
        message = (
            "Weather data was received, but search history "
            "could not be saved."
        )

    except Exception:
        app.logger.exception("Unexpected weather page error")
        message = "An unexpected error occurred. Please try again later."

    return render_template(
        "weather.html",
        report=None,
        cities=sorted(CITIES.keys()),
        selected_city=city,
        error=message,
    )


@app.route("/api/cities")
def api_cities():
    return jsonify([
        {
            "city": name,
            "state": values[2],
            "lat": values[0],
            "lon": values[1],
        }
        for name, values in CITIES.items()
    ])


@app.route("/api/weather/<city>")
def api_weather(city):
    try:
        return jsonify(weather_for(city))

    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    except WeatherProviderUnavailable as exc:
        return jsonify({"error": str(exc)}), exc.status_code

    except Exception:
        app.logger.exception("Unexpected weather API error for %s", city)
        return jsonify({"error": "Unexpected server error."}), 500


@app.route("/report", methods=["GET", "POST"])
def report_issue():
    if request.method == "POST":
        city = resolve_city(request.form.get("city", ""))
        issue = request.form.get("issue", "").strip()
        details = request.form.get("details", "").strip()

        allowed_issues = [
            "Waterlogging/flooding",
            "Extreme heat",
            "Water shortage",
            "Waste/plastic pollution",
            "Tree/green-space loss",
            "Other",
        ]

        if city is None or issue not in allowed_issues or len(details) < 5:
            flash(
                "Please complete all fields. "
                "Details must contain at least 5 characters.",
                "error",
            )
        else:
            try:
                with connect_db() as conn:
                    conn.execute(
                        """
                        INSERT INTO citizen_reports
                            (city, issue, details, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (
                            city,
                            issue,
                            details[:1200],
                            datetime.now().isoformat(timespec="seconds"),
                        ),
                    )

                flash("Your citizen report has been saved.", "success")
                return redirect(url_for("report_issue"))

            except sqlite3.Error:
                app.logger.exception("Could not save citizen report")
                flash(
                    "The report could not be saved. Please try again.",
                    "error",
                )

    return render_template(
        "report.html",
        cities=sorted(CITIES.keys()),
    )


@app.route("/dashboard")
def dashboard():
    try:
        with connect_db() as conn:
            total_searches = conn.execute(
                "SELECT COUNT(*) FROM searches"
            ).fetchone()[0]

            total_reports = conn.execute(
                "SELECT COUNT(*) FROM citizen_reports"
            ).fetchone()[0]

            recent_searches = conn.execute(
                "SELECT * FROM searches ORDER BY id DESC LIMIT 10"
            ).fetchall()

            reports = conn.execute(
                "SELECT * FROM citizen_reports ORDER BY id DESC LIMIT 20"
            ).fetchall()

            city_counts = conn.execute(
                """
                SELECT city, COUNT(*) AS n
                FROM searches
                GROUP BY city
                ORDER BY n DESC
                LIMIT 8
                """
            ).fetchall()

        return render_template(
            "dashboard.html",
            total_searches=total_searches,
            total_reports=total_reports,
            recent_searches=recent_searches,
            reports=reports,
            city_counts=city_counts,
        )

    except sqlite3.Error:
        app.logger.exception("Dashboard database error")
        return "Dashboard database error. Check application logs.", 500


@app.route("/compare")
def compare():
    return render_template(
        "compare.html",
        cities=sorted(CITIES.keys()),
    )


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "database": "sqlite",
        "weather_provider": "Open-Meteo",
    })


init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
