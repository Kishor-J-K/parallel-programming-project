# Parallel Programming Project

A web application for scraping college course data using FastAPI, Playwright, and BeautifulSoup.

## Features

- Web interface for selecting colleges
- Asynchronous scraping of course information
- Export data to Excel and CSV formats
- Progress tracking for scraping tasks

## Setup

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/parallel-programming-project.git
   cd parallel-programming-project
   ```

2. Create a virtual environment:
   ```bash
   python -m venv .venv
   ```

3. Activate the virtual environment:
   - Windows: `.venv\Scripts\activate`
   - macOS/Linux: `source .venv/bin/activate`

4. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

5. Install Playwright browsers:
   ```bash
   playwright install
   ```

6. Run the application:
   ```bash
   uvicorn main:app --reload
   ```

7. Open your browser to `http://localhost:8000`

## Technologies Used

- FastAPI
- Playwright
- BeautifulSoup
- OpenPyXL
- Uvicorn

## License

MIT License