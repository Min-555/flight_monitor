from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import os
import time
import logging
from datetime import datetime
from dotenv import load_dotenv
import re
import pandas as pd
import random
import socket

# Load environment variables
load_dotenv()

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('flight_monitor.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

def check_internet():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except OSError:
        return False

if not check_internet():
    logger.error("No internet connection. Exiting.")
    exit()

class FlightMonitor:
    def __init__(self):
        self.price_threshold = 8000
        self.check_interval = 1800  # check every 30 minutes
        self.retry_interval = 60  # retry every 5 minutes
        self.max_retries = 3
        self.last_price = None
        self.lowest_price_list = None
        self.email_sent = False 
        self.destination = "GOT-BJS"
        self.dates_range = ["2025-12-21", "2026-01-11"]
        self.shortest_date = 16
        self.setup_urls()

    def setup_keys_names(self):
        """ Set up the keys and names for the flight search """
        title = self.destination
        first_date = datetime.strptime(self.dates_range[0], "%Y-%m-%d")
        last_date = datetime.strptime(self.dates_range[1], "%Y-%m-%d")

        keys = []
        dep_date = first_date
        return_date = last_date
        range_length = (return_date - dep_date).days + 1

        # Generate date combinations for the flight search
        while range_length >= self.shortest_date:
            # Check if the departure date and return date is within the range and not less than the shortest date
            while dep_date >= first_date and return_date <= last_date:
                keys.append(f"{title}_{dep_date.strftime('%Y%m%d')}_{return_date.strftime('%Y%m%d')}")
                dep_date += pd.Timedelta(days=1)
                return_date += pd.Timedelta(days=1)
            
            range_length -= 1
            dep_date = first_date
            return_date = dep_date + pd.Timedelta(days=range_length-1)
        return keys


    def setup_urls(self):
        """ Set up the URLs for the flight search """

        # Set up diffrerent conmbinations of dates and destinations
        # These URLs are for flights from Gothenburg (GOT) to Beijing (BJS) on specific dates
        # The dates are from December 21, 2025 to January 11, 2026

        dates_combinations = self.setup_keys_names()
        self.urls = {}

        for key in dates_combinations:
            destination = key.split("_")[0]
            dep_date = key.split("_")[1][:4] + "-" + key.split("_")[1][4:6] + "-" + key.split("_")[1][6:]
            return_date = key.split("_")[2][:4] + "-" + key.split("_")[2][4:6] + "-" + key.split("_")[2][6:]
            self.urls[key] = f"https://www.kayak.se/flights/{destination}/{dep_date}/{return_date}?ucs=1hk4vhy&sort=price_a&fs=cfc=1;takeoff=1012,2230__;layoverdur=-300;legdur=-1500;stops=1;bfc=1"
        logger.info(f"Set up URLs: {self.urls}")

    def setup_driver(self):
        try:
            chrome_options = Options()
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--disable-gpu")
            chrome_options.add_argument("--window-size=1920,1080")
            chrome_options.add_argument("--headless")

            chrome_options.add_argument("--disable-blink-features=AutomationControlled")
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)

            user_agents = [
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            ]
            chrome_options.add_argument(f'--user-agent={random.choice(user_agents)}')
            
            driver = webdriver.Chrome(options=chrome_options)

            driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            driver.execute_cdp_cmd('Network.setUserAgentOverride', {
                "userAgent": random.choice(user_agents)
            })

            driver.implicitly_wait(10)
            logger.info("Chrome driver started successfully")
            return driver
        except Exception as e:
            logger.error(f"Chrome driver started unsuccessfully: {e}")
            raise

    def check_element_exists(self, driver, xpath):
        """ Check if an element exists on the page """
        wait = WebDriverWait(driver, 5)
        try:
            wait.until(
                        EC.element_to_be_clickable((By.XPATH, xpath))
                    )
            return True
        except NoSuchElementException:
            return False
        except WebDriverException as e:
            # logger.error(f"WebDriverException: {e}")
            return False
        
    
    def fetch_flight_data(self, driver):
        """ Extract flight data from the Kayak page """
        flight_data = []

        for key, url in self.urls.items():
            try:
                for attempt in range(3): 
                    try:
                        driver.set_page_load_timeout(30)
                        driver.get(url)
                        break
                    except Exception as e:
                        logger.warning(f"Attempt {attempt+1} timeout for {url}. Retrying...")
                        time.sleep(5)
                logger.info(f"Accessing URL: {url}")

                cookie_check = self.check_element_exists(driver, "/html/body/div[3]/div/div[2]/div/div/div[3]/div/div[1]/button[1]/div")
                if not cookie_check:
                    logger.warning("Cookie consent button not found, skipping cookie consent")
                else:
                    logger.info("Cookie consent button found, attempting to click")
                    try:
                        cookie_button = driver.find_element(By.XPATH, "/html/body/div[3]/div/div[2]/div/div/div[3]/div/div[1]/button[1]/div")
                        cookie_button.click()
                        logger.info("Cookie consent accepted")
                        time.sleep(2)
                    except TimeoutException:
                        logger.warning("Cookie consent button not found or timed out")
    
                wait = WebDriverWait(driver, 20)
    
                price_selectors = [
                    '''//*[@id="flight-results-list-wrapper"]/div[2]/div[1]/div/div[2]/div/span[1]''',
                    '''//*[@id="flight-results-list-wrapper"]/div[6]/div[2]/div/div[1]/div[2]/div/div/div/div[2]/div/div[2]/div/div[1]/div[1]/a/div/div/div/div/div''',
                    '''//div[contains(@class, 'e2GB-price-text') and contains(text(), 'kr')]''',
                    '''//*[contains(text(), 'kr') and contains(@class, 'e2GB-price-text')]''',
                    '''//*[contains(text(), 'kr')]'''
                    ]# Wait for the page to load
                
                for selector in price_selectors:
                    try:
                        price_element = wait.until(
                            EC.presence_of_element_located((By.XPATH, selector))
                        )
                        raw_price = price_element.text

                        if raw_price and "kr" in raw_price:
                            logger.info(f"Raw price fetched with selector {selector}: {raw_price}")
                            break

                    except TimeoutException:
                        logger.debug(f"Selector {selector} not found")
                        continue

                if raw_price:
                    flight_data.append((key, raw_price))
                else:
                    logger.error(f"No price element found for {key}")
                    flight_data.append((key, None))

                    with open(f"debug_page_{key}.html", "w", encoding="utf-8") as f:
                        f.write(driver.page_source)
                    logger.info(f"Debug: Page source saved as debug_page_{key}.html")
            
            except Exception as e:
                logger.error(f"Error fetching flight data for {key}: {e}")
                flight_data.append((key, None))
                continue

        return flight_data if flight_data else None
   

    
    def parse_price(self, flight_raw_price):
        """ Parse the price from the raw string"""

        price_list = []
        for key, raw_price in flight_raw_price:
            if raw_price is None:
                logger.error(f"Price for {key} is None")
                continue
            try:
                price_text = raw_price.replace("kr", "").replace(" ", "").replace(",", "")
                price_clean = re.sub(r'[^\d]', '', price_text)
        
                if price_clean.isdigit():
                    price = int(price_clean)
                    logger.info(f"Price: {raw_price} -> {price}")
                    price_list.append((key, price))
                else:
                    logger.warning(f"Unable to get parse the price: {raw_price}")
                    price_list.append((key, None))
                
            except Exception as e:
                logger.error(f"Error parsing price for {key}: {e}")
                price_list.append((key, None))

        return price_list    

    def send_email(self, price):
        """ Send an email notification about the flight price"""
        try:
            msg = MIMEMultipart()
            body = f"""The flight price for {self.destination} has dropped below the threshold.\nThe current prices are:\n{price}"""
            msg['From'] = os.getenv('FROM')
            msg['To'] = os.getenv('TO')
            msg['Subject'] = f"Flight Price Alert: {self.destination}"

            msg.attach(MIMEText(body, 'plain'))

            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(msg['From'], os.getenv('PASSWORD'))
            server.send_message(msg)
            server.quit()

            logger.info("Email sent successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to send email: {e}")
            return False 

    def check_flight_price(self):
        """ Check the flight price and send an email if it meets the criteria"""
        driver = None
        statue = False

        try:
            driver = self.setup_driver()
            flight_raw_price = self.fetch_flight_data(driver)
            if flight_raw_price is None:
                logger.error("Failed to fetch flight data")
                return statue
            
            flight_prices = self.parse_price(flight_raw_price)
            logger.info(f"Flight prices: {flight_prices}")

            valid_prices = [price for price in flight_prices if price[1] is not None]

            if not valid_prices:
                logger.error("No valid flight prices found")
                return statue
            
            current_lowest_price = min(price[1] for price in valid_prices)
            logger.info(f"Current lowest price: {current_lowest_price}")
            logger.info(f"Price threshold: {self.price_threshold}")

            if self.lowest_price_list:
                logger.info(f"Lowest price so far: {self.lowest_price_list} kr")

            should_send_email = False
            if current_lowest_price < self.price_threshold:
                if self.lowest_price_list is None:
                    should_send_email = True
                    self.lowest_price_list = current_lowest_price
                elif current_lowest_price < self.lowest_price_list:
                    should_send_email = True
                    self.lowest_price_list = current_lowest_price
                else:
                    logger.info(f"Price {current_lowest_price} is below threshold but not lower than best seen price {self.lowest_price_list} kr")
            else:
                logger.info(f"Price {current_lowest_price} is above the threshold {self.price_threshold} kr") 
            
            if should_send_email:
                below_threshold_prices = [price for price in valid_prices if price[1] < self.price_threshold]

                if self.send_email(below_threshold_prices):
                    logger.info("Email notification sent successfully")
                    logger.info(f"New lowest price recorded: {self.lowest_price_list} kr")
                    statue = True
                else:
                    logger.error("Failed to send email notification")
            else:
                logger.info("No flight prices below the threshold or email already sent")
                statue = True

            self.last_price = current_lowest_price

        except Exception as e:
            logger.error(f"Error checking flight price: {e}")
            return statue
        finally:
            if driver:
                try:
                    driver.quit()
                    logger.info("Driver closed successfully")
                except:
                    pass

        return statue


    def run(self):
        """ Main loop to monitor the flight price"""
        logger.info("Starting flight monitor")
        logger.info(f"Monitoring flight prices for {self.destination} from {self.dates_range[0]} to {self.dates_range[1]}")
        while True:
            try:
                success = self.check_flight_price()

                if success:
                    logger.info("Flight price check completed successfully")
                    logger.info(f"Waiting for {self.check_interval} seconds before the next check")
                    time.sleep(self.check_interval)
                else:
                    logger.error("Flight price check failed")
                    logger.info(f"Retrying in {self.retry_interval} seconds")
                    time.sleep(self.retry_interval)

                

            except KeyboardInterrupt:
                logger.info("Flight monitor stopped by user")
                break
            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                time.sleep(self.check_interval)

if __name__ == "__main__":
    monitor = FlightMonitor()
    monitor.run()


