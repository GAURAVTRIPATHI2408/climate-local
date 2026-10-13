CLIMATEWATCH LOCAL — SETUP GUIDE (HINGLISH)
===========================================

Is ZIP mein kya hai?
- Responsive landing page
- Live weather: Open-Meteo API (API key ki zaroorat nahi)
- 39 supported Indian cities
- City map (Leaflet + OpenStreetMap)
- City comparison
- Simple heat/rain indicators (educational heuristic only)
- Citizen issue report form
- SQLite database
- Dashboard with search/report history

IMPORTANT:
Yeh college-project starter application hai. Heat/rain indicators official alerts nahi hain.
Yeh ward-level scientific climate-risk prediction model nahi hai. Map markers city-centre
coordinates use karte hain. Public deployment se pehle dashboard/report data ko protect
karne ke liye admin login, production SECRET_KEY, HTTPS, and persistent database storage
configure karein. SQLite file serverless hosting par persistent na rahe; production mein
managed PostgreSQL use karein.

WINDOWS LAPTOP PAR RUN:
1. ZIP ko extract karein.
2. Extracted ClimateWatch_Local folder ko VS Code mein open karein.
3. VS Code Terminal > New Terminal kholein.
4. Commands ek-ek karke chalayein:

   py -m venv venv
   venv\Scripts\activate
   py -m pip install -r requirements.txt
   py app.py

5. Browser mein yeh address kholein:
   http://127.0.0.1:5000

Agar 'py' command na chale, to 'python' use karein:
   python -m venv venv
   venv\Scripts\activate
   python -m pip install -r requirements.txt
   python app.py

LIVE WEATHER:
Weather load karne ke liye internet connection chahiye. Data Open-Meteo se aata hai.
Agar provider temporarily unavailable ho, thodi der baad dobara try karein.

ONLINE PUBLISH KARNA:
Option A — Render (Flask app ke liye asaan):
1. GitHub par account/login karein.
2. Is folder ki files ko new GitHub repository mein upload/push karein.
3. Render par New > Web Service choose karke repository connect karein.
4. Build command: pip install -r requirements.txt
5. Start command: gunicorn app:app
6. Environment variable add karein: SECRET_KEY = long random secret value.
7. Deploy karein. Render free instances par local SQLite data restart/redeploy ke baad
   persist na kare; reliable production database ke liye managed PostgreSQL connect karein.

Option B — Vercel:
Vercel primarily serverless hosting hai; is Flask + SQLite starter ko Vercel par directly
deploy karna beginner-friendly nahi hai. SQLite writes serverless deployment par reliable
persistence nahi dete. Agar Vercel use karna hai, app ko suitable serverless adapter aur
managed database (e.g. PostgreSQL) ke saath configure karna hoga. Render is starter ke
liye simpler path hai.

PUBLIC WEBSITE SE PEHLE:
- Dashboard ko admin login se protect karein.
- Citizen reports mein personal data collect na karein.
- SECRET_KEY ko source code mein real secret ke roop mein na rakhein.
- Official weather/disaster alerts ke liye IMD/local authority sources check karein.
- Risk indicators ko validated hazard forecasts ke roop mein present na karein.

Useful pages:
Home: /
Live weather: /weather
Compare cities: /compare
Submit local issue: /report
Dashboard: /dashboard
Health check: /health
