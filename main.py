from google.oauth2.service_account import Credentials
from gspread_dataframe import set_with_dataframe
from email.message import EmailMessage
from dotenv import load_dotenv
from datetime import datetime
import nodriver as uc
import pandas as pd
import traceback
import requests
import gspread
import asyncio
import smtplib
import random
import math
import uuid
import json
import time
import os
import re

error_email_sent = False
last_product = None

def send_error_email(error_text, last_product=None):
    load_dotenv("security.env")
    email = os.getenv("EMAIL")
    password = os.getenv("PASSWORD")
    global error_email_sent

    if error_email_sent:
        return  # prevents duplicates

    msg = EmailMessage()
    msg["Subject"] = "Champs Scraper Crashed"
    msg["From"] = email #Customize these for Hank's Email
    msg["To"] = email #Customize these for Hank's Email

    #The reason the scraper crashed
    body = error_text

    #The last item scraped before crashing
    if last_product:
        body += "\n\n--- LAST SCRAPED ITEM ---\n"
        body += json.dumps(last_product, indent=2)

    msg.set_content(body)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
        smtp.login(email, password)
        smtp.send_message(msg)

    #Sets a message that prevents email spam
    error_email_sent = True


async def main():
    shoe_data = []

    browser = await uc.start(
        browser_args=[
            "--window-size=1280,800",
            f"--user-data-dir=/tmp/chrome-test-{uuid.uuid4()}"
        ]
    )

    url = "https://www.champssports.com/category/sale/shoes.html"
    page = await browser.get(url)

    await asyncio.sleep(5)

    await page.wait_for("div.product-container.col.product-container-mobile-v3")

    items_el = await page.select("span.text-boulder")
    items = items_el.text

    match = re.search(r"\d+", items)
    if match:
        digits = int(match.group())

    pages = math.floor(digits / 48) + 1

    for i in range(pages):
        await page.wait_for(
            "div.product-container.col.product-container-mobile-v3"
        )

        # scroll to bottom (replaces JS + time.sleep loop)
        last_height = await page.evaluate("document.body.scrollHeight")

        while True:
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(2.5, 5.2))

            new_height = await page.evaluate("document.body.scrollHeight")

            if new_height == last_height:
                break

            last_height = new_height

        products = await page.select_all(
            "div.product-container.col.product-container-mobile-v3"
        )
        for product in products:
            try:
                name_el = await product.query_selector("span.ProductName-primary")
                name = name_el.text
            except:
                name = "N/A"
            try:
                sale_el = await product.query_selector("span.font-medium.text-speedcat_red")
                sale_price = sale_el.text

                match = re.search(r"\$([\d,.]+)", sale_price)
                if match:
                    sale_price = float(match.group(1))

            except:
                sale_price = "N/A"
            try:
                anchor = await product.query_selector("a")

                if anchor:
                    link = await anchor.apply("(el) => el.href")
            except:
                link = "N/A"
            try:
                og_el = await product.query_selector(
                    "span.font-normal.text-footlocker_black.line-through"
                )
                og_price = og_el.text

                match = re.search(r"\$([\d,.]+)", og_price)
                if match:
                    og_price = "$" + match.group(1)
            except:
                og_price = "N/A"
            try:
                salep_el = await product.query_selector("div[data-id='SalePercent']")
                sale = salep_el.text
                match = re.search(r"(\d+)%", sale)
                if match:
                    sale = match.group(1) + "%"
            except:
                sale = "N/A"

            shoe_data.append({
                "name": name,
                "sale_price": sale_price,
                "og_price": og_price,
                "percent_off": sale,
                "link": link
            })

        try:
            next_button = await page.select('a[aria-label="Go to next page"]')

            await next_button.scroll_into_view()
            await asyncio.sleep(random.uniform(0.3, 1.1))

            await next_button.click()

            await asyncio.sleep(3)

        except Exception as e:
            print(f"Error: {e}")
            break

    final_shoe = []
    mcallen_final_shoe = []

    print(shoe_data)

    start_time = time.time()

    # ----------------------------
    # SESSION (unchanged concept)
    # ----------------------------
    session = requests.Session()

    # cookies come from nodriver browser instead of selenium
    cookies = await browser.cookies.get_all()

    for cookie in cookies:
        session.cookies.set(cookie.name, cookie.value)

    # ----------------------------
    # HEADERS (nodriver replacement)
    # ----------------------------
    user_agent = await page.evaluate("navigator.userAgent")

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.champssports.com/",
    }

    # ----------------------------
    # dedupe (unchanged)
    # ----------------------------
    seen = set()
    unique_data = []

    for d in shoe_data:
        t = tuple(sorted(d.items()))
        if t not in seen:
            seen.add(t)
            unique_data.append(d)

    shoe_data = unique_data

    for shoe in shoe_data:
        last_product = shoe

        await asyncio.sleep(random.uniform(0.1, 0.6))

        response = session.get(shoe["link"], headers=headers)

        if response.status_code != 200:
            print(f"Request failed: {response.status_code} | {shoe['link']}")
            continue

        html = response.text

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
            print("Missing expected JSON structure:", shoe["link"])
            continue

        for s in sizes:
            if not (s.get("active") and s.get("upc")):
                continue

            item = {
                "UPC": s["upc"],
                "name": shoe["name"],
                "sale_price": shoe["sale_price"],
                "link": shoe["link"],
                "size": s["size"],
                "og_price": shoe["og_price"],
                "percent_off": shoe["percent_off"],
            }

            last_product = item
            final_shoe.append(item)

            if "1815150" in s.get("inventory", {}).get("inventoryAvailableLocations", []):
                mcallen_item = item.copy()
                mcallen_item["sale_price"] = round(mcallen_item["sale_price"] * 0.7, 2)
                mcallen_final_shoe.append(mcallen_item)

    end_time = time.time()
    elapsed_time = end_time - start_time
    print(f"Speed process took {elapsed_time} seconds")
    current_datetime = datetime.now()
    datetime_string = current_datetime.strftime("%m-%d-%Y %H:%M")
    # Make the spreadsheets and uploads them to drive
    final_shoe_df = pd.DataFrame(final_shoe)
    mcallen_final_shoe_df = pd.DataFrame(mcallen_final_shoe)
    champs_name = "Champs " + datetime_string
    mcallen_name = "McAllen Champs " + datetime_string
    final_shoe_df.to_csv(champs_name + ".csv", index=False)
    mcallen_final_shoe_df.to_csv(mcallen_name + ".csv", index=False)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
    client = gspread.authorize(creds)
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
    browser.stop()
    print("CSV saved!")
    send_error_email("Champs scraper finished successfully at " + datetime_string)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception:
        error_text = traceback.format_exc()
        print(error_text)
        send_error_email(error_text, last_product)
        raise



# from selenium.webdriver.support import expected_conditions as EC
# from selenium.webdriver.common.action_chains import ActionChains
# from selenium.webdriver.support.ui import WebDriverWait
# from selenium.common.exceptions import TimeoutException
# from google.oauth2.service_account import Credentials
# from gspread_dataframe import set_with_dataframe
# from selenium.webdriver.common.by import By
# from email.message import EmailMessage
# import undetected_chromedriver as uc
# from dotenv import load_dotenv
# from datetime import datetime
# import nodriver as uc
# import pandas as pd
# import traceback
# import requests
# import smtplib
# import asyncio
# import gspread
# import random
# import uuid
# import math
# import json
# import time
# import re
# import os
#
#
# error_email_sent = False
# last_product = None
#
# def send_error_email(error_text, last_product=None):
#     load_dotenv("security.env")
#     email = os.getenv("EMAIL")
#     password = os.getenv("PASSWORD")
#     global error_email_sent
#
#     if error_email_sent:
#         return  # prevents duplicates
#
#     msg = EmailMessage()
#     msg["Subject"] = "Champs Scraper Crashed"
#     msg["From"] = email #Customize these for Hank's Email
#     msg["To"] = email #Customize these for Hank's Email
#
#     #The reason the scraper crashed
#     body = error_text
#
#     #The last item scraped before crashing
#     if last_product:
#         body += "\n\n--- LAST SCRAPED ITEM ---\n"
#         body += json.dumps(last_product, indent=2)
#
#     msg.set_content(body)
#
#     with smtplib.SMTP_SSL("smtp.gmail.com", 465) as smtp:
#         smtp.login(email, password)
#         smtp.send_message(msg)
#
#     #Sets a message that prevents email spam
#     error_email_sent = True
#
#
# def main():
#     #Sets up the webpage to get information from
#     options = uc.ChromeOptions()
#     options.add_argument("--window-size=1280,800")
#     options.add_argument(f"--user-data-dir=/tmp/chrome-test-{uuid.uuid4()}")
#     # prefs = {"profile.managed_default_content_settings.images": 2}
#     # options.add_experimental_option("prefs", prefs)
#     driver = uc.Chrome(version_main=149, options=options)
#     url = "https://www.champssports.com/category/sale/shoes.html"
#     # sale_url = "https://www.champssports.com/category/sale/limited-time.html"
#     driver.get(url)
#     time.sleep(5)
#     # try:
#     #     page_link = driver.find_element(By.CSS_SELECTOR, 'a[href="/category/sale/shoes.html?currentPage=0"]')
#     #     driver.execute_script("arguments[0].scrollIntoView(true);", page_link)
#     #     driver.execute_script("arguments[0].click();", page_link)
#     # except:
#     #     print("No need for page 1")
#     shoe_data = []
#     #Loads page 1 and gets that info
#     wait = WebDriverWait(driver, 20)
#     wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.product-container.col.product-container-mobile-v3")))
#     items = driver.find_element(By.CSS_SELECTOR, "span.text-boulder").text
#     match = re.search(r"\d+", items)
#     if match:
#         digits = int(match.group())
#     pages = digits/48
#     pages = math.floor(pages) + 1
#     print(pages)
#     #McAllen = 1815150
#     for i in range(pages):
#         #Continues to load all of the other pages
#         wait = WebDriverWait(driver, 20)
#         wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.product-container.col.product-container-mobile-v3")))
#         last_height = driver.execute_script("return document.body.scrollHeight")
#         #Scrolls to the bottom of the page
#         while True:
#             driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
#             time.sleep(random.uniform(2.5, 5.2))  # random delay
#             new_height = driver.execute_script("return document.body.scrollHeight")
#             if new_height == last_height:
#                 break
#             last_height = new_height
#         #Get product info
#         try:
#             wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.product-container.col.product-container-mobile-v3")))
#             products = driver.find_elements(By.CSS_SELECTOR, "div.product-container.col.product-container-mobile-v3")
#             print(f"Found {len(products)} products.")
#             for product in products:
#                 try:
#                     name = product.find_element(By.CSS_SELECTOR, "span.ProductName-primary").text
#                 except:
#                     name = "N/A"
#                 try:
#                     sale_price = product.find_element(By.CSS_SELECTOR, "span.font-medium.text-sale_red").text
#                     sale_price = float(sale_price.replace("$", ""))
#                 except:
#                     sale_price = "N/A"
#                 try:
#                     og_price = product.find_element(By.CSS_SELECTOR, "span.font-normal.text-footlocker_black.line-through").text
#                     match = re.search(r"\$([\d,.]+)", og_price)
#                     if match:
#                         og_price = "$"+match.group(1)
#                 except:
#                     og_price = "N/A"
#                 try:
#                     sale = product.find_element(By.CSS_SELECTOR, "div[data-id='SalePercent']").text
#                     match = re.search(r"(\d+)%", sale)
#                     if match:
#                         sale = match.group(1)+"%"
#                 except:
#                     sale = "N/A"
#                 try:
#                     link = product.find_element(By.TAG_NAME, "a").get_attribute("href")
#                 except:
#                     link = "N/A"
#                 #Adds shoe to list
#                 shoe_data.append({
#                     "name": name,
#                     "sale_price": sale_price,
#                     "og_price": og_price,
#                     "percent_off": sale,
#                     "link": link
#                 })
#         except Exception as e:
#             print(f"Error: {e}")
#         #Goes to next page
#         try:
#             next_button = wait.until(
#                 EC.element_to_be_clickable((By.CSS_SELECTOR, 'a[aria-label="Go to next page"]'))
#             )
#             driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", next_button)
#             time.sleep(1)
#             ActionChains(driver) \
#                 .move_to_element(next_button) \
#                 .pause(random.uniform(0.3, 1.1)) \
#                 .click() \
#                 .perform()
#             input("Pause")
#             # time.sleep(2)
#             # driver.execute_script("arguments[0].click();", next_button)
#         except Exception as e:
#             print(f"Error: {e}")
#
#     #Creates lists of shoes on sale and if they are available in mcallen
#     final_shoe = []
#     mcallen_final_shoe = []
#     start_time = time.time()
#     session = requests.Session()
#     for cookie in driver.get_cookies():
#         session.cookies.set(cookie['name'], cookie['value'])
#     headers = {
#         "User-Agent": driver.execute_script("return navigator.userAgent;"),
#         "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
#         "Accept-Language": "en-US,en;q=0.9",
#         "Referer": "https://www.champssports.com/",
#     }
#     #Make sure we don't repeat shoes
#     seen = set()
#     unique_data = []
#     for d in shoe_data:
#         t = tuple(sorted(d.items()))
#         if t not in seen:
#             seen.add(t)
#             unique_data.append(d)
#     shoe_data = unique_data
#     for shoe in shoe_data:
#         #Go through each shoe to get more info
#         last_product = shoe
#         time.sleep(random.uniform(0.1,0.6))
#         response = session.get(shoe['link'], headers=headers)
#         if response.status_code == 200:
#             html = response.text
#         else:
#             print(f"Request failed: {response.status_code} | {shoe['link']}")
#             continue
#         start = html.find("STATE_FROM_SERVER:")
#         start = html.find("{", start)
#         brace_count = 0
#         end = start
#         for i in range(start, len(html)):
#             if html[i] == "{":
#                 brace_count += 1
#             elif html[i] == "}":
#                 brace_count -= 1
#
#             if brace_count == 0:
#                 end = i + 1
#                 break
#         json_str = html[start:end]
#         state = json.loads(json_str)
#         try:
#             sizes = state["api"]["productDetails"]["getDetails"]["data"]["sizes"]
#         except KeyError:
#             print("Missing expected JSON structure:", shoe['link'])
#             print(state.keys())
#             continue
#         #Look at each size of shoe available
#         for s in sizes:
#             if not (s.get("active") and s.get("upc")):
#                 continue
#             size = s["size"]
#             upc = s["upc"]
#             item = {
#                 "UPC": upc,
#                 "name": shoe["name"],
#                 "sale_price": shoe["sale_price"],
#                 "link": shoe["link"],
#                 "size": size,
#                 "og_price": shoe["og_price"],
#                 "percent_off": shoe["percent_off"],
#             }
#             last_product = item
#             final_shoe.append(item)
#             #Add to McAllen if it is there
#             if "1815150" in s.get("inventory", {}).get("inventoryAvailableLocations", []):
#                 mcallen_item = item.copy()
#                 mcallen_item["sale_price"] = round(mcallen_item["sale_price"] * 0.7, 2)  # example: extra 10% off
#                 mcallen_final_shoe.append(mcallen_item)
#     #Calculate how much time it took
#     end_time = time.time()
#     elapsed_time = end_time - start_time
#     print(f"Speed process took {elapsed_time} seconds")
#     current_datetime = datetime.now()
#     datetime_string = current_datetime.strftime("%m-%d-%Y %H:%M")
#     #Make the spreadsheets and uploads them to drive
#     final_shoe_df = pd.DataFrame(final_shoe)
#     mcallen_final_shoe_df = pd.DataFrame(mcallen_final_shoe)
#     champs_name = "Champs "+datetime_string
#     mcallen_name = "McAllen Champs "+datetime_string
#     final_shoe_df.to_csv(champs_name+".csv", index=False)
#     mcallen_final_shoe_df.to_csv(mcallen_name+".csv", index=False)
#     scopes = [
#         "https://www.googleapis.com/auth/spreadsheets",
#         "https://www.googleapis.com/auth/drive"
#     ]
#     creds = Credentials.from_service_account_file("credentials.json", scopes=scopes)
#     client = gspread.authorize(creds)
#     spreadsheet = client.open("Francis - Web Scraping")
#     def create_and_fill_sheet(spreadsheet, title, df):
#         rows, cols = df.shape
#
#         # +1 for header row, + a little buffer
#         worksheet = spreadsheet.add_worksheet(
#             title=title,
#             rows=str(rows + 1),
#             cols=str(cols)
#         )
#
#         set_with_dataframe(worksheet, df)
#         return worksheet
#
#     champs_sheet = create_and_fill_sheet(spreadsheet, champs_name, final_shoe_df)
#     mcallen_sheet = create_and_fill_sheet(spreadsheet, mcallen_name, mcallen_final_shoe_df)
#     driver.quit()
#     print("CSV saved!")
#     send_error_email("Champs scraper finished successfully at " + datetime_string)
#
# if __name__ == "__main__":
#     try:
#         asyncio.run(main())
#     except Exception:
#         error_text = traceback.format_exc()
#         print(error_text)
#         send_error_email(error_text, last_product)
#         raise