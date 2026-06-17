from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from selenium.common.exceptions import TimeoutException
from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe
from selenium.webdriver.common.by import By
import undetected_chromedriver as uc
from datetime import datetime
import pandas as pd
import requests
import gspread
import random
import math
import json
import time
import re


# --- Setup undetected Chrome ---
options = uc.ChromeOptions()
options.add_argument("--window-size=1280,800")
options.add_argument("--incognito")
prefs = {"profile.managed_default_content_settings.images": 2}
options.add_experimental_option("prefs", prefs)

driver = uc.Chrome(version_main=147, options=options)

url = "https://www.champssports.com/category/sale/shoes.html"
# sale_url = "https://www.champssports.com/category/sale/limited-time.html"
driver.get(url)

# driver.find_element(By.CSS_SELECTOR, "a.Link[href*='currentPage=0']").click()

time.sleep(5)

page_link = driver.find_element(By.CSS_SELECTOR, 'a[href="/category/sale/shoes.html?currentPage=0"]')
driver.execute_script("arguments[0].scrollIntoView(true);", page_link)
driver.execute_script("arguments[0].click();", page_link)

shoe_data = []

# Wait for products to appear
wait = WebDriverWait(driver, 20)
wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.product-container.col.product-container-mobile-v3")))

items = driver.find_element(By.CSS_SELECTOR, "span.text-boulder").text
match = re.search(r"\d+", items)
if match:
    digits = int(match.group())

pages = digits/48
pages = math.floor(pages) + 1
print(pages)

#McAllen = 1815150

for i in range(pages):

    # Wait for products to appear
    wait = WebDriverWait(driver, 20)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.product-container.col.product-container-mobile-v3")))

    # ------------------- Scroll to Load All Shoes -------------------
    last_height = driver.execute_script("return document.body.scrollHeight")

    while True:
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(random.uniform(1.0, 2.0))  # random delay

        new_height = driver.execute_script("return document.body.scrollHeight")
        if new_height == last_height:
            break
        last_height = new_height

    # ------------------- Scrape Products -------------------
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.product-container.col.product-container-mobile-v3")))

        products = driver.find_elements(By.CSS_SELECTOR, "div.product-container.col.product-container-mobile-v3")

        print(f"Found {len(products)} products.")

        for product in products:
            try:
                name = product.find_element(By.CSS_SELECTOR, "span.ProductName-primary").text
            except:
                name = "N/A"

            try:
                sale_price = product.find_element(By.CSS_SELECTOR, "span.font-medium.text-sale_red").text
                sale_price = float(sale_price.replace("$", ""))
            except:
                sale_price = "N/A"

            try:
                og_price = product.find_element(By.CSS_SELECTOR, "span.font-normal.text-footlocker_black.line-through").text
                match = re.search(r"\$([\d,.]+)", og_price)
                if match:
                    og_price = "$"+match.group(1)
            except:
                og_price = "N/A"

            try:
                sale = product.find_element(By.CSS_SELECTOR, "div[data-id='SalePercent']").text
                match = re.search(r"(\d+)%", sale)
                if match:
                    sale = match.group(1)+"%"
            except:
                sale = "N/A"

            try:
                link = product.find_element(By.TAG_NAME, "a").get_attribute("href")
            except:
                link = "N/A"

            shoe_data.append({
                "name": name,
                "sale_price": sale_price,
                "og_price": og_price,
                "percent_off": sale,
                "link": link
            })
    except Exception as e:
        print(f"Error: {e}")

    try:
        next_button = wait.until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, 'a[aria-label="Go to next page"]'))
        )
        driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
        driver.execute_script("arguments[0].click();", next_button)
    except Exception as e:
        print(f"Error: {e}")

# ------------------- Output -------------------
final_shoe = []
mcallen_final_shoe = []

start_time = time.time()

session = requests.Session()

# copy cookies from selenium
for cookie in driver.get_cookies():
    session.cookies.set(cookie['name'], cookie['value'])

headers = {
    "User-Agent": driver.execute_script("return navigator.userAgent;"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.champssports.com/",
}

seen = set()
unique_data = []

for d in shoe_data:
    t = tuple(sorted(d.items()))  # make dict hashable
    if t not in seen:
        seen.add(t)
        unique_data.append(d)

shoe_data = unique_data

print(shoe_data)
print(len(shoe_data))

for shoe in shoe_data:

    time.sleep(random.uniform(0.1,0.6))
    response = session.get(shoe['link'], headers=headers)

    if response.status_code == 200:
        html = response.text
    else:
        print(f"Request failed: {response.status_code} | {shoe['link']}")
        continue

    start = html.find("STATE_FROM_SERVER:")
    start = html.find("{", start)

    brace_count = 0
    end = start

    for i in range(start, len(html)):
        if html[i] == "{":
            brace_count += 1
        elif html[i] == "}":
            brace_count -= 1

        if brace_count == 0:
            end = i + 1
            break

    json_str = html[start:end]

    state = json.loads(json_str)

    try:
        sizes = state["api"]["productDetails"]["getDetails"]["data"]["sizes"]
    except KeyError:
        print("Missing expected JSON structure:", shoe['link'])
        print(state.keys())
        continue

    for s in sizes:
        if not (s.get("active") and s.get("upc")):
            continue

        size = s["size"]
        upc = s["upc"]

        item = {
            "UPC": upc,
            "name": shoe["name"],
            "sale_price": shoe["sale_price"],
            "link": shoe["link"],
            "size": size,
            "og_price": shoe["og_price"],
            "percent_off": shoe["percent_off"],
        }
        final_shoe.append(item)

        # Append to McAllen list if second condition passes
        if "1815150" in s.get("inventory", {}).get("inventoryAvailableLocations", []):
            mcallen_item = item.copy()
            mcallen_item["sale_price"] = round(mcallen_item["sale_price"] * 0.7, 2)  # example: extra 10% off
            mcallen_final_shoe.append(mcallen_item)


end_time = time.time()

# Calculate elapsed time
elapsed_time = end_time - start_time
print(f"Speed process took {elapsed_time} seconds")

current_datetime = datetime.now()

# Convert it to a string (default format)
datetime_string = current_datetime.strftime("%m-%d-%Y %H:%M")

final_shoe_df = pd.DataFrame(final_shoe)
mcallen_final_shoe_df = pd.DataFrame(mcallen_final_shoe)

champs_name = "Champs "+datetime_string
mcallen_name = "McAllen Champs "+datetime_string

# Save to CSV
final_shoe_df.to_csv(champs_name+".csv", index=False)
mcallen_final_shoe_df.to_csv(mcallen_name+".csv", index=False)

scopes = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive"
]
creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
client = gspread.authorize(creds)

# Open spreadsheet
spreadsheet = client.open("Francis - Web Scraping")

def create_and_fill_sheet(spreadsheet, title, df):
    rows, cols = df.shape

    # +1 for header row, + a little buffer
    worksheet = spreadsheet.add_worksheet(
        title=title,
        rows=str(rows + 1),
        cols=str(cols)
    )

    set_with_dataframe(worksheet, df)
    return worksheet

champs_sheet = create_and_fill_sheet(spreadsheet, champs_name, final_shoe_df)
mcallen_sheet = create_and_fill_sheet(spreadsheet, mcallen_name, mcallen_final_shoe_df)

driver.quit()

print("CSV saved!")
