from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

def test_webdriver():
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument("--headless")  # Optional: run in headless mode

    # Create a Service object
    service = Service(ChromeDriverManager().install())

    # Initialize the WebDriver with the service and options
    driver = webdriver.Chrome(service=service, options=chrome_options)

    try:
        driver.get("https://web.whatsapp.com")
        print(driver.title)  # Print the title of the page
    except Exception as e:
        print(f"Error: {e}")
    finally:
        driver.quit()

# Run the test
test_webdriver()
