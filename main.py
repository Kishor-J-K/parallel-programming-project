from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright
import asyncio
from bs4 import BeautifulSoup
import concurrent.futures
import json
import sys
from fastapi.responses import FileResponse
from openpyxl import Workbook
import os
import csv
from fastapi import BackgroundTasks
import zipfile
import uuid
from typing import Dict
import traceback
import re

def delete_file(path: str):
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print("File delete error:", e)

def cleanup_progress(task_id: str):
    try:
        if task_id in progress_store:
            progress_store.pop(task_id)
    except Exception as e:
        print("Progress cleanup error:", e)


if sys.platform == "win32":
    # Keep ProactorEventLoop for FastAPI compatibility
    # Playwright should work with it, but we'll handle any issues in the code
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

# Thread pool for running sync playwright operations
executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)


app = FastAPI()

# Load college links
try:
    with open("college_links.json", "r", encoding="utf-8") as f:
        COLLEGE_LINKS = json.load(f)
except:
    COLLEGE_LINKS = {}

# Progress tracking storage
progress_store: Dict[str, Dict] = {}

def clean_cell_text(text: str) -> str:
    """Remove 'check details' and similar phrases from cell text"""
    if not text:
        return text
    # Remove "check details" (case-insensitive) and variations
    # Remove "check details", "check detail", "view details", etc.
    text = re.sub(r'\s*check\s+details?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*view\s+details?\s*', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s*see\s+details?\s*', '', text, flags=re.IGNORECASE)
    # Clean up extra spaces
    text = ' '.join(text.split())
    return text.strip()

def sanitize_filename(name: str, max_length: int = 100) -> str:
    """Sanitize and shorten filename to avoid Windows path length issues"""
    if not name:
        return "file"
    # Remove invalid characters for filenames
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    # Replace spaces and special characters
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s_-]+', '_', name)
    # Truncate if too long
    if len(name) > max_length:
        name = name[:max_length]
    # Remove leading/trailing underscores
    name = name.strip('_')
    return name if name else "file"

@app.get("/", response_class=HTMLResponse)
def home():
    return open("templates/index.html", encoding="utf-8").read()

@app.get("/colleges")
def get_colleges():
    return list(COLLEGE_LINKS.keys())

@app.get("/progress/{task_id}")
def get_progress(task_id: str):
    if task_id in progress_store:
        return progress_store[task_id]
    return {"status": "not_found", "percentage": 0, "message": "Task not found"}

# -------- HELPER FUNCTION (NOT API ROUTE) --------
async def scrape_table(context, url, index, task_id: str = None, total: int = 0):
    page = await context.new_page()
    try:
        if task_id and task_id in progress_store:
            progress_store[task_id]["current"] = index + 1
            progress_store[task_id]["message"] = f"Scraping course {index + 1} of {total}..."
            progress_store[task_id]["percentage"] = int((index + 1) / total * 60)  # 60% for scraping
        
        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        data_list = []

        button = page.locator(
            "span[class='jsx-3955509628 icon icon-20 clg-sprite arrow-d-blue-20 mr-1 ']"
        ).nth(index)
        await button.scroll_into_view_if_needed()
        await button.click()

        await page.wait_for_timeout(3000)

        html = await page.content()
        soup = BeautifulSoup(html, 'html.parser')

        tables = soup.find_all('table', class_="jsx-2530098677 table-new table-responsive")

        block = page.locator(
            'div[class="jsx-3955509628 course-detail d-flex justify-content-between"]'
        ).nth(index)
        name = await block.locator('a').inner_text()

        for table in tables:
            header = [i.text.strip() for i in table.find('tr').find_all('th')]
            data = []
            for row in table.find_all('tr')[1:]:
                cells = row.find_all('td')
                if not cells:
                    continue
                row_data = [clean_cell_text(cell.text.strip()) for cell in cells]
                data.append(dict(zip(header, row_data)))

            data_list.append({name: data})

        return data_list
    except Exception as e:
        print(f"Error scraping table {index + 1}: {e}")
        return []
    finally:
        await page.close()

# -------- API ROUTE --------
@app.get("/scrape")
async def scrape(
    background_tasks: BackgroundTasks,
    college: str = Query(...),
    task_id: str = Query(None)
):
    try:
        if college not in COLLEGE_LINKS:
            error_msg = "College not found"
            if task_id:
                progress_store[task_id] = {
                    "status": "error",
                    "percentage": 0,
                    "message": error_msg
                }
            return JSONResponse({"error": error_msg}, status_code=404)

        # Initialize progress if task_id provided
        if task_id:
            progress_store[task_id] = {
                "status": "processing",
                "percentage": 0,
                "message": "Initializing...",
                "current": 0,
                "total": 0
            }

        relative_url = COLLEGE_LINKS[college]
        url = "https://collegedunia.com" + relative_url.strip() + "/courses-fees"

        if task_id and task_id in progress_store:
            progress_store[task_id]["percentage"] = 5
            progress_store[task_id]["message"] = "Opening browser..."

        # Helper function to scrape a single course (runs in parallel)
        def scrape_single_course(index, url, task_id):
            browser = None
            page = None
            try:
                playwright = sync_playwright().start()
                try:
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context()
                    page = context.new_page()
                    page.goto(url, timeout=60000)
                    page.wait_for_load_state("load")
                    
                    button = page.locator(
                        "span[class='jsx-3955509628 icon icon-20 clg-sprite arrow-d-blue-20 mr-1 ']"
                    ).nth(index)
                    button.scroll_into_view_if_needed()
                    button.click()
                    page.wait_for_timeout(3000)
                    
                    html = page.content()
                    soup = BeautifulSoup(html, 'html.parser')
                    tables = soup.find_all('table', class_="jsx-2530098677 table-new table-responsive")
                    
                    block = page.locator(
                        'div[class="jsx-3955509628 course-detail d-flex justify-content-between"]'
                    ).nth(index)
                    name = block.locator('a').inner_text()
                    
                    data_list = []
                    for table in tables:
                        header = [th.text.strip() for th in table.find('tr').find_all('th')]
                        data = []
                        for row in table.find_all('tr')[1:]:
                            cells = row.find_all('td')
                            if not cells:
                                continue
                            row_data = [clean_cell_text(cell.text.strip()) for cell in cells]
                            data.append(dict(zip(header, row_data)))
                        data_list.append({name: data})
                    
                    # Update progress
                    if task_id and task_id in progress_store:
                        progress_store[task_id]["current"] = index + 1
                        total = progress_store[task_id].get("total", 1)
                        progress_store[task_id]["message"] = f"Scraping course {index + 1} of {total}..."
                        progress_store[task_id]["percentage"] = 15 + int((index + 1) / total * 50)  # 15-65% for scraping
                    
                    return data_list
                finally:
                    # Clean up resources
                    if page:
                        try:
                            page.close()
                        except:
                            pass
                    if browser:
                        try:
                            browser.close()
                        except:
                            pass
                    try:
                        playwright.stop()
                    except:
                        pass
            except Exception as e:
                print(f"Error scraping table {index + 1}: {e}")
                import traceback
                traceback.print_exc()
                return []
        
        # Use sync playwright in a thread to get total count
        def get_total_courses():
            browser = None
            page = None
            try:
                playwright = sync_playwright().start()
                try:
                    browser = playwright.chromium.launch(headless=True)
                    context = browser.new_context()
                    page = context.new_page()
                    page.goto(url, timeout=60000)
                    page.wait_for_load_state("networkidle", timeout=30000)
                    # Wait a bit more for dynamic content
                    page.wait_for_timeout(3000)
                    
                    # Try multiple selectors to find course buttons
                    selectors = [
                        "span[class='jsx-3955509628 icon icon-20 clg-sprite arrow-d-blue-20 mr-1 ']",
                        "span.icon-20.clg-sprite.arrow-d-blue-20",
                        "span.arrow-d-blue-20",
                        "button[aria-expanded='false']",
                        ".course-detail"
                    ]
                    
                    total_buttons = 0
                    for selector in selectors:
                        try:
                            count = page.locator(selector).count()
                            if count > 0:
                                total_buttons = count
                                print(f"Found {total_buttons} courses using selector: {selector}")
                                break
                        except Exception as e:
                            print(f"Selector {selector} failed: {e}")
                            continue
                    
                    # If still 0, try to find course detail divs
                    if total_buttons == 0:
                        try:
                            course_divs = page.locator('div[class*="course-detail"]').count()
                            if course_divs > 0:
                                total_buttons = course_divs
                                print(f"Found {total_buttons} courses using course-detail divs")
                        except:
                            pass
                    
                    # Debug: Print page title and URL
                    print(f"Page URL: {page.url}")
                    print(f"Page title: {page.title()}")
                    
                    return total_buttons
                finally:
                    # Clean up resources
                    if page:
                        try:
                            page.close()
                        except:
                            pass
                    if browser:
                        try:
                            browser.close()
                        except:
                            pass
                    try:
                        playwright.stop()
                    except:
                        pass
            except Exception as e:
                print(f"Error getting total courses: {e}")
                import traceback
                traceback.print_exc()
                return 0
        
        try:
            if task_id and task_id in progress_store:
                progress_store[task_id]["percentage"] = 10
                progress_store[task_id]["message"] = "Counting courses..."
            
            # Get total number of courses
            total_buttons = await asyncio.to_thread(get_total_courses)
            
            if total_buttons == 0:
                error_msg = f"No courses found on the page. The page structure may have changed or the college may not have course information available. URL: {url}"
                print(f"DEBUG: No courses found for college: {college}")
                print(f"DEBUG: URL attempted: {url}")
                if task_id and task_id in progress_store:
                    progress_store[task_id]["status"] = "error"
                    progress_store[task_id]["message"] = "No courses found on the page. Please check the college URL or try another college."
                return JSONResponse({"error": "No courses found on the page. The page structure may have changed or this college may not have course information available."}, status_code=404)
            
            if task_id and task_id in progress_store:
                progress_store[task_id]["total"] = total_buttons
                progress_store[task_id]["percentage"] = 15
                progress_store[task_id]["message"] = f"Found {total_buttons} courses. Starting parallel scraping..."
            
            # Run parallel scraping with ThreadPoolExecutor
            # Use max 5 concurrent tabs to avoid overwhelming the system
            max_workers = min(5, total_buttons)
            
            def run_parallel_scrape():
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
                    # Submit all scraping tasks
                    futures = [
                        executor.submit(scrape_single_course, i, url, task_id) 
                        for i in range(total_buttons)
                    ]
                    
                    # Collect results as they complete
                    results = []
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            result = future.result()
                            results.extend(result)
                        except Exception as e:
                            print(f"Error in parallel scraping: {e}")
                    
                    return results
            
            # Run parallel scraping in a thread
            results = await asyncio.to_thread(run_parallel_scrape)
            
            if task_id and task_id in progress_store:
                progress_store[task_id]["percentage"] = 65
                progress_store[task_id]["message"] = "Processing scraped data..."
                
        except Exception as e:
            error_type = type(e).__name__
            error_details = str(e) if str(e) else "No error message available"
            error_msg = f"Scraping error ({error_type}): {error_details}"
            if task_id and task_id in progress_store:
                progress_store[task_id]["status"] = "error"
                progress_store[task_id]["message"] = error_msg
            print(f"Scraping error: {error_type} - {error_details}")
            traceback.print_exc()
            return JSONResponse({"error": error_msg}, status_code=500)

        # ✅ Flatten data (results is already a list of dicts from sync function)
        flat_data = results

        if not flat_data:
            error_msg = "No data found after scraping"
            if task_id and task_id in progress_store:
                progress_store[task_id]["status"] = "error"
                progress_store[task_id]["message"] = error_msg
            return JSONResponse({"error": error_msg}, status_code=404)

        if task_id and task_id in progress_store:
            progress_store[task_id]["percentage"] = 70
            progress_store[task_id]["message"] = "Creating CSV files..."

        # Sanitize college name (max 50 chars to leave room for course names)
        safe_name = sanitize_filename(college, max_length=50)
        zip_filename = f"{safe_name}_fees.zip"
        zip_path = os.path.join(os.getcwd(), zip_filename)

        csv_files = []
        total_files = len(results)
        files_created = 0

        for idx, table_data in enumerate(results):
            for course_name, rows in table_data.items():
                if not rows:
                    continue

                # Sanitize course name (max 60 chars) and ensure total path stays under limit
                safe_course = sanitize_filename(course_name, max_length=60)
                # Use shorter format: college_course_idx.csv (max total ~150 chars including path)
                csv_name = f"{safe_name}_{safe_course}_{idx+1}.csv"
                
                # Final safety check - truncate if still too long
                if len(csv_name) > 100:
                    # Keep college name, truncate course name more aggressively
                    remaining = 100 - len(safe_name) - len(str(idx+1)) - 7  # 7 for "_" and ".csv"
                    safe_course = sanitize_filename(course_name, max_length=max(10, remaining))
                    csv_name = f"{safe_name}_{safe_course}_{idx+1}.csv"
                
                csv_path = os.path.join(os.getcwd(), csv_name)

                headers = rows[0].keys()

                # Use UTF-8-sig encoding to add BOM so Excel recognizes UTF-8 and displays symbols correctly
                with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
                    writer = csv.writer(f)
                    writer.writerow(headers)
                    for row in rows:
                        writer.writerow(row.values())

                csv_files.append(csv_name)
                files_created += 1
                
                if task_id and task_id in progress_store:
                    progress = 70 + int((files_created / total_files) * 20) if total_files > 0 else 85
                    progress_store[task_id]["percentage"] = progress
                    progress_store[task_id]["message"] = f"Created {files_created} of {total_files} CSV files..."

        if task_id and task_id in progress_store:
            progress_store[task_id]["percentage"] = 90
            progress_store[task_id]["message"] = "Creating ZIP archive..."

        # ✅ Create ZIP
        with zipfile.ZipFile(zip_path, "w") as zipf:
            for file in csv_files:
                zipf.write(file)
                background_tasks.add_task(delete_file, os.path.join(os.getcwd(), file))

        # ✅ Auto delete ZIP
        background_tasks.add_task(delete_file, zip_path)

        if task_id and task_id in progress_store:
            progress_store[task_id]["percentage"] = 100
            progress_store[task_id]["status"] = "completed"
            progress_store[task_id]["message"] = "Download ready!"
            # Clean up progress after 5 minutes
            background_tasks.add_task(cleanup_progress, task_id)

        return FileResponse(
            path=zip_path,
            media_type="application/zip",
            filename=zip_filename
        )
    except Exception as e:
        # Get error information with fallbacks
        error_type = type(e).__name__ or "UnknownException"
        error_str = str(e)
        error_repr = repr(e)
        
        # Build error details with multiple fallbacks
        if error_str and error_str.strip():
            error_details = error_str
        elif error_repr and error_repr.strip():
            error_details = error_repr
        else:
            error_details = "No error message available"
        
        error_msg = f"Unexpected error ({error_type}): {error_details}"
        
        # Print full traceback for debugging
        print(f"\n{'='*60}")
        print(f"Unexpected error in scrape endpoint:")
        print(f"Error type: {error_type}")
        print(f"Error str: '{error_str}'")
        print(f"Error repr: '{error_repr}'")
        print(f"Error details: '{error_details}'")
        print(f"Final error_msg: '{error_msg}'")
        print(f"{'='*60}")
        traceback.print_exc()
        print(f"{'='*60}\n")
        
        if task_id and task_id in progress_store:
            progress_store[task_id]["status"] = "error"
            progress_store[task_id]["message"] = error_msg
        
        # Ensure we always return a valid error message
        if not error_msg or error_msg.strip() == "Unexpected error ():":
            error_msg = f"An unexpected error occurred. Check server logs for details. Error type: {error_type}"
        
        return JSONResponse({"error": error_msg}, status_code=500)




    # return {
    #     "college": college,
    #     "data": results
    # }
