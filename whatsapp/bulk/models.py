import os
import shutil
import time
import logging
import psutil
import subprocess
import tempfile
from selenium import webdriver
from webdriver_manager.chrome import ChromeDriverManager
from django.contrib.auth.models import User
from django.db import models
from django.conf import settings
from selenium.webdriver.chrome.service import Service
from selenium.common.exceptions import WebDriverException

logger = logging.getLogger(__name__)

class WhatsAppAccount(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    number = models.CharField(max_length=20, null=True, blank=True)
    country_code = models.CharField(max_length=5, null=True, blank=True)
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    notes = models.TextField(blank=True, null=True)
    session_path = models.CharField(max_length=1000, blank=True, null=True)

    class Meta:
        unique_together = ('user', 'number')

    def has_valid_session_files(self, session_path):
        """Check if the given session path contains valid WhatsApp session files"""
        if not session_path or not os.path.exists(session_path):
            return False

        session_indicators = [
            'Local Storage/leveldb',
            'Session Storage',
            'IndexedDB',
            'Default/Local Storage/leveldb',
            'Default/Session Storage',
            'Default/IndexedDB',
            'Local State',
            'Preferences'
        ]

        for indicator in session_indicators:
            indicator_path = os.path.join(session_path, indicator)
            if os.path.exists(indicator_path):
                return True

        try:
            for root, dirs, files in os.walk(session_path):
                if files:
                    return True
        except OSError:
            pass

        return False

    # ✅ directly include kill + clear methods here
    @staticmethod
    def kill_chrome_processes():
        """Kill all Chrome and ChromeDriver processes"""
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    if any(name in proc.info['name'].lower() for name in ['chrome', 'chromedriver']):
                        proc.terminate()
                        proc.wait(timeout=3)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except ImportError:
            pass

        try:
            subprocess.run(['taskkill', '/F', '/IM', 'chrome.exe', '/T'],
                           capture_output=True, timeout=5)
            subprocess.run(['taskkill', '/F', '/IM', 'chromedriver.exe', '/T'],
                           capture_output=True, timeout=5)
        except:
            pass

        time.sleep(2)

    @staticmethod
    def clear_chrome_temp_files():
        """Clear Chrome temporary files that cause crashes"""
        temp_paths = [
            os.path.expandvars(r'%TEMP%\scoped_dir*'),
            os.path.expandvars(r'%TEMP%\chrome_*'),
            os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data\Crashpad'),
            os.path.expandvars(r'%LOCALAPPDATA%\Google\Chrome\User Data\ShaderCache'),
        ]

        import glob
        for path_pattern in temp_paths:
            try:
                for path in glob.glob(path_pattern):
                    if os.path.exists(path):
                        if os.path.isdir(path):
                            shutil.rmtree(path, ignore_errors=True)
                        else:
                            os.remove(path)
            except:
                pass

    # ✅ Updated get_driver method (inside WhatsAppAccount)
    def get_driver(self, headless=False, timeout=30, retry_count=2):
        """Chrome WebDriver with crash prevention"""

        for attempt in range(retry_count):
            driver = None
            temp_session_dir = None

            try:
                logger.info(f"Attempt {attempt + 1}/{retry_count} for account {self.name}")

                # STEP 1: Kill existing Chrome processes
                self.kill_chrome_processes()

                # STEP 2: Clear Chrome temp files
                self.clear_chrome_temp_files()

                # STEP 3: Create fresh temporary session
                temp_session_dir = tempfile.mkdtemp(prefix='wa_chrome_', suffix='_clean')

                # STEP 4: Configure Chrome options
                chrome_options = webdriver.ChromeOptions()
                chrome_options.add_argument(f"--user-data-dir={temp_session_dir}")
                chrome_options.add_argument("--no-sandbox")
                chrome_options.add_argument("--disable-dev-shm-usage")
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--disable-software-rasterizer")
                chrome_options.add_argument("--disable-background-timer-throttling")
                chrome_options.add_argument("--disable-backgrounding-occluded-windows")
                chrome_options.add_argument("--disable-renderer-backgrounding")
                chrome_options.add_argument("--disable-field-trial-config")
                chrome_options.add_argument("--disable-ipc-flooding-protection")
                chrome_options.add_argument("--disable-hang-monitor")
                chrome_options.add_argument("--disable-client-side-phishing-detection")
                chrome_options.add_argument("--disable-component-update")
                chrome_options.add_argument("--disable-domain-reliability")
                chrome_options.add_argument("--disable-sync")
                chrome_options.add_argument("--disable-translate")
                chrome_options.add_argument("--max_old_space_size=2048")
                chrome_options.add_argument("--memory-pressure-off")
                chrome_options.add_argument("--no-zygote")
                chrome_options.add_argument("--window-size=1200,800")
                chrome_options.add_argument("--start-maximized")
                chrome_options.add_argument("--disable-notifications")
                chrome_options.add_argument("--disable-background-networking")
                chrome_options.add_argument("--disable-features=NetworkService,NetworkServiceInProcess")
                chrome_options.add_argument("--disable-gpu")
                chrome_options.add_argument("--disable-software-rasterizer")
                chrome_options.add_argument("--disable-features=VizDisplayCompositor")
                chrome_options.add_argument("--disable-background-networking")
                chrome_options.add_argument("--disable-notifications")
                chrome_options.add_argument("--disable-default-apps")
                chrome_options.add_argument("--disable-sync")
                chrome_options.add_argument("--disable-crash-reporter")
                chrome_options.add_argument("--no-first-run")
                chrome_options.add_argument("--disable-extensions")



                if headless:
                    chrome_options.add_argument("--headless=new")

                chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
                chrome_options.add_experimental_option('useAutomationExtension', False)
                chrome_options.add_argument("--disable-blink-features=AutomationControlled")

                service = Service(
                    executable_path=ChromeDriverManager().install(),
                    log_output=os.devnull
                )

                driver = webdriver.Chrome(service=service, options=chrome_options)
                driver.set_page_load_timeout(timeout)
                driver.implicitly_wait(10)

                # Anti-detection JS
                driver.execute_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
                    Object.defineProperty(navigator, 'languages', { get: () => ["en-US", "en"] });
                """)

                logger.info(f"Loading WhatsApp Web for {self.name}")
                driver.get("https://web.whatsapp.com")
                time.sleep(8)

                if "whatsapp" not in driver.current_url.lower():
                    raise WebDriverException(f"Failed to load WhatsApp Web: {driver.current_url}")

                logger.info(f"Successfully created driver for {self.name}")
                return driver

            except Exception as e:
                logger.error(f"Attempt {attempt + 1} failed: {str(e)}")

                if driver:
                    try:
                        driver.quit()
                    except:
                        pass
                    driver = None

                if temp_session_dir and os.path.exists(temp_session_dir):
                    try:
                        shutil.rmtree(temp_session_dir, ignore_errors=True)
                    except:
                        pass

                self.kill_chrome_processes()

                if attempt < retry_count - 1:
                    wait_time = 3 + (attempt * 2)
                    logger.info(f"Waiting {wait_time}s before retry...")
                    time.sleep(wait_time)

        # Final emergency mode
        logger.warning("All attempts failed, trying emergency mode...")
        try:
            self.kill_chrome_processes()
            time.sleep(3)

            emergency_dir = tempfile.mkdtemp(prefix='emergency_chrome_')
            emergency_options = webdriver.ChromeOptions()
            emergency_options.add_argument(f"--user-data-dir={emergency_dir}")
            emergency_options.add_argument("--no-sandbox")
            emergency_options.add_argument("--disable-dev-shm-usage")
            emergency_options.add_argument("--disable-gpu")
            emergency_options.add_argument("--single-process")
            emergency_options.add_argument("--no-zygote")
            emergency_options.add_argument("--disable-web-security")
            emergency_options.add_argument("--disable-features=VizDisplayCompositor")

            service = Service(ChromeDriverManager().install(), log_output=os.devnull)
            driver = webdriver.Chrome(service=service, options=emergency_options)

            driver.get("https://web.whatsapp.com")
            time.sleep(10)

            logger.info("Emergency mode successful")
            return driver

        except Exception as emergency_error:
            logger.error(f"Emergency mode failed: {emergency_error}")
            raise WebDriverException("All Chrome driver attempts failed. Consider using Firefox.")

    # ✅ Firefox fallback inside WhatsAppAccount
    def get_firefox_driver_fallback(self, headless=False, timeout=30):
        try:
            from selenium.webdriver.firefox.service import Service as FirefoxService
            from webdriver_manager.firefox import GeckoDriverManager

            logger.info(f"Using Firefox fallback for {self.name}")
            temp_profile = tempfile.mkdtemp(prefix='ff_profile_')

            firefox_options = webdriver.FirefoxOptions()
            firefox_options.add_argument(f"--profile={temp_profile}")
            if headless:
                firefox_options.add_argument("--headless")

            firefox_service = FirefoxService(GeckoDriverManager().install())
            driver = webdriver.Firefox(service=firefox_service, options=firefox_options)
            driver.set_page_load_timeout(timeout)
            driver.implicitly_wait(10)
            driver.get("https://web.whatsapp.com")
            time.sleep(8)

            logger.info(f"Firefox driver created successfully for {self.name}")
            return driver

        except Exception as e:
            logger.error(f"Firefox fallback failed: {e}")
            raise
        

    
class WhatsAppCampaign(models.Model):
    name = models.CharField(max_length=255)
    message1 = models.TextField(blank=True, null=True)
    message2 = models.TextField(blank=True, null=True)
    excel_file = models.FileField(upload_to='uploads/', blank=True, null=True)
    numbers = models.TextField(null=True)
    country_code = models.CharField(max_length=10)
    whatsapp_group = models.CharField(max_length=255, blank=True, null=True)
    deduplicate = models.BooleanField(default=False)
    attachment = models.FileField(upload_to='attachments/', blank=True, null=True) 
    safe_mode = models.BooleanField(default=False)
    unsafe_mode = models.BooleanField(default=False)
    whatsapp_account = models.ForeignKey(WhatsAppAccount, on_delete=models.CASCADE,null=True)
    swipe_after = models.IntegerField(default=2)
    delay = models.IntegerField(default=5)
    schedule_time = models.DateTimeField(blank=True, null=True)
    friendly_numbers = models.BooleanField(default=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    is_sent = models.BooleanField(default=False)

    def get_driver(self):
        """Start Chrome with this account's saved session"""
        # Use stored session_path if available, otherwise create fallback
        session_dir = self.session_path or os.path.join(
            "whatsapp", "whatsapp_sessions", f"acct_{self.id}_{self.number}"
        )

        os.makedirs(session_dir, exist_ok=True)

        chrome_options = webdriver.ChromeOptions()
        chrome_options.add_argument(f"--user-data-dir={session_dir}")

        # Prevent crashpad PermissionError
        chrome_options.add_argument("--disable-crashpad")

        service = Service("chromedriver.exe")  # update if not in PATH
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return driver
     
    def __str__(self):
        return self.name

   
   