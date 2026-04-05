# 📈 EconPulse: Hyper-Local Economic Forecaster

Traditional macroeconomic indicators (like federal CPI and GDP) lag by months and fail to capture the reality of individual neighborhoods. EconPulse bypasses federal data entirely, using automated scraping and machine learning to calculate real-time inflation and economic heat scores for a single city block.

## 🏗️ The Architecture
EconPulse is not a standard LLM chatbot. It is a full-stack, automated data pipeline built entirely using Codex:

* **The Scrapers (Playwright & Python):** Three independent scraping pipelines extract unstructured local data:
    * *Commercial Building Permits:* Tracks capital influx and real estate development.
    * *Restaurant Menu Prices:* Tracks consumer goods pricing and local inflation.
    * *Local Job Boards:* Tracks labor demand and baseline salary shifts across retail, construction, and hospitality.
* **The Economics Engine (Pandas & Scikit-Learn):** Cleans the messy scraped data and processes it through a localized scoring algorithm to generate a weighted `local_inflation_index` and `local_economic_heat_score`.
* **The API (FastAPI):** Serves the calculated economic data via RESTful JSON endpoints.
* **The Dashboard (Vanilla JS, Tailwind, Chart.js):** A dark-mode financial terminal that fetches the API data and visualizes the local economic shifts in real-time.

## 🚀 How to Run Locally

1. Clone the repository and navigate into the folder:
   `git clone https://github.com/Kevin-A101/local-econ-forecaster.git`
   `cd local-econ-forecaster`

2. Create and activate a virtual environment:
   `python3 -m venv .venv`
   `source .venv/bin/activate`

3. Install dependencies and browser binaries:
   `pip install -r requirements.txt`
   `python -m playwright install chromium`

4. Launch the FastAPI server:
   `uvicorn main:app --reload`

5. Open `http://127.0.0.1:8000` in your browser to view the live financial dashboard.

## 🔮 What's Next
Expanding the Playwright scraper fleet to ingest local municipal utility district minutes and specialized court dockets to find even earlier leading indicators of neighborhood economic shifts.
