from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import sqlite3, os, requests
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-before-public-deployment")
DB_PATH = os.environ.get("DATABASE_PATH", os.path.join(os.path.dirname(__file__), "climatewatch.db"))

# Approximate coordinates for commonly searched Indian cities. Add more as needed.
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

def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with connect_db() as conn:
        conn.execute("""CREATE TABLE IF NOT EXISTS searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL, temperature REAL, humidity REAL, rain REAL,
            searched_at TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS citizen_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            city TEXT NOT NULL, issue TEXT NOT NULL, details TEXT NOT NULL,
            created_at TEXT NOT NULL
        )""")

def weather_for(city):
    if city not in CITIES:
        raise ValueError("Please select a city from the list.")
    lat, lon, state = CITIES[city]
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat, "longitude": lon,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,rain,wind_speed_10m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max",
        "timezone": "auto", "forecast_days": 7
    }
    response = requests.get(url, params=params, timeout=12)
    response.raise_for_status()
    data = response.json()
    current = data.get("current", {})
    daily = data.get("daily", {})
    temp = current.get("temperature_2m")
    rain = current.get("rain", 0) or 0
    humidity = current.get("relative_humidity_2m")
    wind = current.get("wind_speed_10m")
    # Transparent heuristic indicators, not official warnings or a validated hazard model.
    heat = "High" if temp is not None and temp >= 35 else ("Moderate" if temp is not None and temp >= 30 else "Low")
    wet = "Elevated" if (rain or 0) >= 5 else "Low today"
    return {
        "city": city, "state": state, "latitude": lat, "longitude": lon,
        "current": current, "daily": daily, "heat_risk": heat, "rain_indicator": wet,
        "fetched_at": datetime.now().strftime("%d %b %Y, %I:%M %p")
    }

@app.route("/")
def index():
    return render_template("index.html", cities=sorted(CITIES.keys()))

@app.route("/weather")
def weather():
    city = request.args.get("city", "Virar")
    if city not in CITIES:
        city = "Virar"
    try:
        report = weather_for(city)
        c = report["current"]
        with connect_db() as conn:
            conn.execute("INSERT INTO searches(city, temperature, humidity, rain, searched_at) VALUES(?,?,?,?,?)",
                         (city, c.get("temperature_2m"), c.get("relative_humidity_2m"), c.get("rain", 0),
                          datetime.now().isoformat(timespec="seconds")))
        return render_template("weather.html", report=report, cities=sorted(CITIES.keys()))
    except (requests.RequestException, ValueError, KeyError) as exc:
        return render_template("weather.html", report=None, cities=sorted(CITIES.keys()),
                               selected_city=city, error="Live weather data could not be loaded. Check your internet connection and try again.")

@app.route("/api/cities")
def api_cities():
    return jsonify([{"city": name, "state": vals[2], "lat": vals[0], "lon": vals[1]} for name, vals in CITIES.items()])

@app.route("/api/weather/<city>")
def api_weather(city):
    try:
        return jsonify(weather_for(city))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except requests.RequestException:
        return jsonify({"error": "Weather provider is temporarily unavailable."}), 502

@app.route("/report", methods=["GET", "POST"])
def report_issue():
    if request.method == "POST":
        city = request.form.get("city", "").strip()
        issue = request.form.get("issue", "").strip()
        details = request.form.get("details", "").strip()
        if city not in CITIES or issue not in ["Waterlogging/flooding", "Extreme heat", "Water shortage", "Waste/plastic pollution", "Tree/green-space loss", "Other"] or len(details) < 5:
            flash("Please complete all fields. Details must be at least 5 characters.", "error")
        else:
            with connect_db() as conn:
                conn.execute("INSERT INTO citizen_reports(city, issue, details, created_at) VALUES(?,?,?,?)",
                             (city, issue, details[:1200], datetime.now().isoformat(timespec="seconds")))
            flash("Your sample citizen report has been saved.", "success")
            return redirect(url_for("report_issue"))
    return render_template("report.html", cities=sorted(CITIES.keys()))

@app.route("/dashboard")
def dashboard():
    with connect_db() as conn:
        total_searches = conn.execute("SELECT COUNT(*) FROM searches").fetchone()[0]
        total_reports = conn.execute("SELECT COUNT(*) FROM citizen_reports").fetchone()[0]
        recent_searches = conn.execute("SELECT * FROM searches ORDER BY id DESC LIMIT 10").fetchall()
        reports = conn.execute("SELECT * FROM citizen_reports ORDER BY id DESC LIMIT 20").fetchall()
        city_counts = conn.execute("SELECT city, COUNT(*) AS n FROM searches GROUP BY city ORDER BY n DESC LIMIT 8").fetchall()
    return render_template("dashboard.html", total_searches=total_searches, total_reports=total_reports,
                           recent_searches=recent_searches, reports=reports, city_counts=city_counts)

@app.route("/compare")
def compare():
    return render_template("compare.html", cities=sorted(CITIES.keys()))

@app.route("/health")
def health():
    return jsonify({"status": "ok", "database": "sqlite", "weather_provider": "Open-Meteo"})

init_db()

if __name__ == "__main__":
    app.run(debug=True, port=int(os.environ.get("PORT", 5000)))
