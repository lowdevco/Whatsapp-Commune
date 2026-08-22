import os
import time
import phonenumbers
import random
import psutil
import shutil 
import logging
import re
import csv
import threading
import tempfile
from django.shortcuts import render, redirect
from django.conf import settings
from django.http import JsonResponse,HttpResponse
from django.views.decorators.csrf import csrf_exempt
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from django.contrib.auth import logout
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from django.contrib.auth.decorators import login_required
from .forms import WhatsAppAccountForm
from django.shortcuts import get_object_or_404
from .models import WhatsAppCampaign, WhatsAppAccount, FriendlyNumber
from django.contrib import messages
import mimetypes
from selenium import webdriver
from django.contrib.auth import authenticate, login
from django.contrib.auth.forms import UserCreationForm
from datetime import datetime
import base64
from selenium.common.exceptions import TimeoutException
from django.urls import reverse
from webdriver_manager.chrome import ChromeDriverManager
logger = logging.getLogger(__name__)
from django.http import JsonResponse
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from .models import WhatsAppCampaign
import pandas as pd
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time
import os
import urllib.parse
import logging
from pathlib import Path
from PIL import Image
from google import genai
from google.genai import errors as genai_errors
from playwright_stealth import Stealth

def human_click(page, selector):
    """Simulates a human moving the mouse with jitter and clicking an element."""
    try:
        element = page.locator(selector).first
        if element.is_visible(timeout=3000):
            box = element.bounding_box()
            if box and box['width'] > 0 and box['height'] > 0:
                target_x = box['x'] + box['width'] * random.uniform(0.2, 0.8)
                target_y = box['y'] + box['height'] * random.uniform(0.2, 0.8)
                page.mouse.move(target_x, target_y, steps=random.randint(5, 15))
                time.sleep(random.uniform(0.1, 0.3))
                page.mouse.click(target_x, target_y)
                return True
            else:
                element.click()
                return True
    except Exception as e:
        logger.debug(f"human_click failed for selector '{selector}': {str(e)}")
        # Direct fallback click
        try:
            page.locator(selector).first.click()
            return True
        except Exception as fallback_e:
            logger.debug(f"Direct click fallback failed for '{selector}': {str(fallback_e)}")
            raise fallback_e

def execute_human_idle_action(page):
    """
    Safe idle action: Moves mouse cursor across blank chat wallpaper ONLY.
    NEVER clicks anything, NEVER touches the sidebar, keeping New Chat button 100% untouched.
    """
    try:
        viewport = page.viewport_size or {'width': 1280, 'height': 800}
        # Right 50% of screen is chat wallpaper (completely safe neutral area)
        safe_min_x = int(viewport['width'] * 0.5)
        safe_max_x = int(viewport['width'] * 0.9)
        safe_min_y = int(viewport['height'] * 0.2)
        safe_max_y = int(viewport['height'] * 0.8)
        
        target_x = random.randint(safe_min_x, safe_max_x)
        target_y = random.randint(safe_min_y, safe_max_y)
        
        # Drift cursor smoothly with micro-steps (no clicking!)
        page.mouse.move(target_x, target_y, steps=random.randint(8, 18))
    except Exception:
        pass

def get_gaussian_delay(mean=12.0, stddev=3.0, min_delay=6.0, max_delay=20.0):
    """Generates a natural Gaussian (bell-curve) delay bounded by min/max limits."""
    delay = random.gauss(mean, stddev)
    return max(min_delay, min(max_delay, delay))


def generate_ai_spintax_template(original_message):
    """
    Dynamically rewrites the message into a Spintax template to bypass spam filters,
    while protecting links. Scales efficiently by generating the template once.
    """
    if not original_message or not original_message.strip():
        return original_message
        
    from bulk.models import AppSetting
    import os
    from dotenv import load_dotenv
    
    try:
        api_key_setting = AppSetting.objects.get(key='GEMINI_API_KEY')
        api_key = api_key_setting.value
    except AppSetting.DoesNotExist:
        api_key = None
        
    # Fallback to .env file if no key in database
    if not api_key:
        load_dotenv()
        api_key = os.environ.get("GEMINI_API_KEY")
        
    if not api_key:
        return original_message # Safety fallback if key is missing

    client = genai.Client(api_key=api_key)

    # 1. Token Shield: Mask URLs so the AI cannot break them
    urls = re.findall(r' (https?://[^\s]+)', original_message)
    masked_message = original_message
    for i, url in enumerate(urls):
        masked_message = masked_message.replace(url, f"[LINK_{i}]")
        
    prompt = f"""
    You are a strict copy-editor and WhatsApp marketing expert. 
    Your goal is to take the provided message and rewrite it into a single, highly varied Spintax template.
    
    Spintax uses curly braces and pipe characters to provide random variations. 
    For example: "{{Hi|Hello|Hey there}}, I wanted to share our {{new|latest|amazing}} product."
    
    STRICT RULES:
    1. Create variations for greetings, transition phrases, adjectives, and sign-offs ONLY.
    2. NEVER change the core meaning, facts, prices, or numbers.
    3. Ensure ALL variations sound 100% natural, conversational, and native to a human speaker. DO NOT use awkward, robotic, or clunky phrasing.
    4. Output EXACTLY the raw Spintax string and nothing else (no conversational filler, no markdown fences like ```spintax).
    5. You must KEEP any [LINK_X] tags exactly as they are.
    
    Message to rewrite into Spintax:
    {masked_message}
    """
    
    # 2. Fallback Loop: Iterate through configured models
    models_to_try = getattr(settings, 'GEMINI_MODELS', ["gemini-3.5-flash-lite", "gemini-3.7-flash", "gemini-3.6-flash", "gemini-3.1-flash-lite"])
    
    for model_name in models_to_try:
        try:
            logger.info(f"[AI] Generating campaign spintax using model: {model_name}...")
            response = client.models.generate_content(model=model_name, contents=prompt)
            
            if response and response.text:
                rewritten = response.text.strip()
                
                # Clean Markdown fences if the AI mistakenly added them
                rewritten = re.sub(r'^```(?:spintax|json|txt|markdown|md)?\s*(.*?)\s*```$', r'\1', rewritten, flags=re.IGNORECASE | re.DOTALL).strip()
                
                # 3. Token Unshield: Put the real URLs back in
                for i, url in enumerate(urls):
                    rewritten = rewritten.replace(f"[LINK_{i}]", url)
                    
                logger.info(f"[AI] Spintax generation complete using {model_name}. Generated Template: \n{rewritten}")
                return rewritten
                
        except genai_errors.APIError as e:
            logger.warning(f"[AI] API Error with model {model_name}: {e}. Falling back to next model...")
            continue # Try next model
        except Exception as e:
            logger.error(f"[AI] Unexpected error with model {model_name}: {e}")
            continue
            
    # Safety fallback if all AI attempts fail
    logger.error("[AI] All AI Spintax generation attempts failed. Falling back to original message.")
    return original_message
# -------------------------

def parse_normal_spintax(text):
    """Parses standard spintax like: {Hi|Hello|Hey} there!"""
    if not text:
        return text
    
    import re
    import random
    
    pattern = re.compile(r'\{([^{}]*)\}')
    match = pattern.search(text)
    
    while match:
        options = match.group(1).split('|')
        choice = random.choice(options)
        text = text[:match.start()] + choice + text[match.end():]
        match = pattern.search(text)
        
    return text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
active_campaigns = {}
campaign_statuses = {}

message_selectors = [

        'div[data-testid="conversation-compose-box-input"]'
        'div[contenteditable="true"][data-lexical-editor="true"]'
        'div[contenteditable="true"][role="textbox"]'

        # Fixed CSS selectors (escaped quotes or single quotes)
        "div[contenteditable='true'][data-tab=\"10\"]",  # Double quotes for inner value
        "div[contenteditable='true'][data-tab='10']",    # Single quotes (this was causing the error)
        
        # Better approaches - use single quotes around attribute values
        'div[contenteditable="true"][data-tab="10"]',    # Double quotes for attribute values
        
        # XPath selectors (these should work fine)
        "//div[@contenteditable='true' and @data-tab='10']",
        
        # More generic selectors (fallbacks)
        "div[contenteditable='true'][role='textbox'][data-lexical-editor='true']",
        "//div[@contenteditable='true' and @role='textbox' and @data-lexical-editor='true']",
        
        # Even more generic
        "div[contenteditable='true'][aria-label*='Type']",
        "//div[@contenteditable='true' and contains(@aria-label, 'Type')]",
        "div[role='textbox'][contenteditable='true']",
        "div[data-lexical-editor='true']",
        "div[contenteditable='true']",
        "div[role='textbox']",
        
        # Additional WhatsApp-specific selectors
        "div[data-testid='conversation-compose-box-input']",
        "div[data-testid='compose-btn-send']",
        "div._ak1r",  # WhatsApp class (may change)
        "div._13mgZ",  # WhatsApp class (may change)
        
        # Try with different quote combinations
        'div[contenteditable="true"][data-tab="10"]',
        "div[contenteditable=\"true\"][data-tab=\"10\"]",
]

def cleanup_existing_chrome_processes():
    """Clean up any existing Chrome processes on startup"""
    try:
        WhatsAppAccount.kill_chrome_processes()
        WhatsAppAccount.clear_chrome_temp_files()
        logger.info("Cleaned up existing Chrome processes and temp files")
    except Exception as e:
        logger.warning(f"Error during cleanup: {e}")


cleanup_existing_chrome_processes()

active_campaigns = {}
campaign_statuses = {}


def get_chrome_options():
    options = Options()
    options.headless = False
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get("https://google.com")
    profile_dir = os.path.join(settings.BASE_DIR, 'whatsapp_persistent_profile')
    os.makedirs(profile_dir, exist_ok=True)
    options.add_argument(f"user-data-dir={profile_dir}")
    
   
    debug_port = random.randint(9000, 9999)
    options.add_argument(f"--remote-debugging-port={debug_port}")
    
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-software-rasterizer")
    options.add_argument("--disable-extensions")
    options.add_argument("--disable-features=VizDisplayCompositor")
    options.add_argument("--disable-web-security")
    options.add_argument("--allow-running-insecure-content")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--disable-background-timer-throttling")
    options.add_argument("--disable-backgrounding-occluded-windows")
    options.add_argument("--disable-renderer-backgrounding")
    
    options.add_argument("--allow-file-access-from-files")
    
    options.binary_location = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
    
    return options


def validate_phone_number(number):
    """Validate and format phone number using phonenumbers library"""
    try:
        parsed = phonenumbers.parse(number, None)
        if not phonenumbers.is_valid_number(parsed):
            return None
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164).lstrip('+')
    except Exception:
        return None
class CustomUserCreationForm(UserCreationForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].help_text = "Required* Letters, digits and @/./+/-/_ "

def signup_view(request):
    if request.method == 'POST':
        form = CustomUserCreationForm(request.POST)  
        if form.is_valid(): 
            form.save()     
            messages.success(request, "Account created successfully!")
            return redirect('login')
        else:
            messages.error(request, 'Please correct the error below.')
    else:
        form = CustomUserCreationForm()
    return render(request, 'signup.html', {'form': form})
    
def login_view(request):
    if request.method == 'POST':
        username = request.POST['username']
        password = request.POST['password']
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('index')  
        else:
            messages.error(request, 'Invalid credentials')
    return render(request, 'login.html')

def logout_view(request):
    logout(request)
    return redirect('login')

def create_webdriver(user_data_dir=None):
    try:
        options = webdriver.ChromeOptions()
        
        if user_data_dir and os.path.exists(user_data_dir):
            options.add_argument(f"--user-data-dir={user_data_dir}")
            print(f" Using user data dir: {user_data_dir}")
        
        # Add common options to avoid common errors
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-gpu")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-notifications")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option('useAutomationExtension', False)
        
        # Try to create driver
        service = webdriver.chrome.service.Service()
        driver = webdriver.Chrome(service=service, options=options)
        
        return driver
        
    except Exception as e:
        print(f" Failed to create WebDriver: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def index(request):
    from bulk.models import AppSetting
    try:
        gemini_api_key = AppSetting.objects.get(key='GEMINI_API_KEY').value
    except AppSetting.DoesNotExist:
        gemini_api_key = ""

    if request.user.is_authenticated:
        accounts = WhatsAppAccount.objects.filter(user=request.user)
        has_campaigns = WhatsAppCampaign.objects.filter(user=request.user).exists()
    else:
        accounts = WhatsAppAccount.objects.none()
        has_campaigns = False

    return render(request, 'index.html', {
        'accounts': accounts,
        'has_campaigns': has_campaigns,
        'gemini_api_key': gemini_api_key
    })



@login_required
def initiate_qr_scan(request, account_id):
    account = get_object_or_404(WhatsAppAccount, id=account_id, user=request.user)

    session_path = os.path.join(
        settings.WHATSAPP_SESSIONS_DIR,
        f"acct_{account.id}_{account.number}"
    )

    os.makedirs(session_path, exist_ok=True)

    account.session_path = session_path
    account.save(update_fields=["session_path"])

    # Use sync Playwright
    launch_browser(session_path)

    return JsonResponse({"status": "success", "message": "QR scan initiated"})

def launch_browser(session_path):
    import threading
    
    def run_browser():
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=session_path,
                    headless=False,
                    args=[
                        "--no-first-run",
                        "--no-default-browser-check",
                        "--disable-blink-features=AutomationControlled",
                        "--no-sandbox",
                    ]
                )
                
                page = browser.new_page()
                page.goto("https://web.whatsapp.com", wait_until="networkidle")
                
                # Wait for QR code to appear or user to be logged in
                try:
                    # Wait for either QR code or chat interface (indicating login)
                    page.wait_for_selector('canvas[aria-label*="QR"], [data-testid="chat-list"]', timeout=60000)
                    print("WhatsApp Web loaded successfully. Ready for QR scan or already logged in.")
                    
                    # Keep the browser open with a loop instead of infinite timeout
                    import time
                    while True:
                        try:
                            # Check if browser is still alive
                            page.title()  # This will throw if browser is closed
                            time.sleep(random.uniform(4.0, 7.0))  # Wait 5 seconds before checking again
                        except:
                            # Browser was closed, exit loop
                            print("Browser session ended")
                            break
                    
                except Exception as e:
                    print(f"Error waiting for WhatsApp Web: {e}")
                
            except Exception as e:
                print(f"Error launching browser: {e}")
    
    # Run browser in a separate thread so it doesn't block Django
    browser_thread = threading.Thread(target=run_browser, daemon=True)
    browser_thread.start()

def format_number_safely(number, default_country_code='+91'):
    """
    Safely formats a phone number using the phonenumbers library.
    If valid, returns E164 format without the + (e.g. 919876543210) for WhatsApp API.
    If it fails or is invalid, returns the raw digits to prevent breaking existing fallback logic.
    """
    number_str = str(number).strip()
    if number_str.endswith('.0'):
        number_str = number_str[:-2]
        
    raw_digits = ''.join(filter(str.isdigit, number_str))
    
    if not number_str.startswith('+'):
        # Try prepending the default country code
        test_number = str(default_country_code) + raw_digits
    else:
        test_number = number_str
        
    try:
        import phonenumbers
        parsed = phonenumbers.parse(test_number, None)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164).lstrip('+')
    except Exception:
        pass
        
    # If the library proves it is completely invalid or fake, we reject it 
    # so the bot doesn't waste 10+ seconds trying to open a broken chat.
    return ""

@login_required
def check_scan_status(request):
    """Check if QR scan has been completed"""
    return JsonResponse({
        'scan_completed': request.session.get('qr_scanned', False),
        'message': 'QR scanned successfully' if request.session.get('qr_scanned') else 'Waiting for scan'
    })

@login_required
def save_campaign(request):
    """Save campaign with proper Excel, manual number handling, and attachment support"""
    numbers_list = []
    all_numbers = []

    if request.method == 'POST':
        # Get all form data
        campaign_name_input = request.POST.get('campaign_name')
        if campaign_name_input and campaign_name_input.strip():
            campaign_name = campaign_name_input.strip()
        else:
            from datetime import datetime
            campaign_name = f"Campaign #{datetime.now().strftime('%b %d, %I:%M %p')}"
        selected_accounts = request.POST.getlist('selected_accounts')
        message_1 = request.POST.get('message_1')
        message_2 = request.POST.get('message_2')
        excel_file = request.FILES.get('excel_file')
        attachment = request.FILES.get('attachment')  #  ADD: Get attachment file
        manual_numbers = request.POST.get('manual_numbers')
        country_code = request.POST.get('country_code')
        whatsapp_group = request.POST.get('whatsapp_group')
        deduplicate = request.POST.get('deduplicate') == 'on'
        safe_mode = request.POST.get('safe_mode') == 'on'
        unsafe_mode = request.POST.get('unsafe_mode') == 'on'
        swipe_after = request.POST.get('swipe_after')
        delay = request.POST.get('delay')
        schedule_time_raw = request.POST.get('schedule_time')
        friendly_numbers = request.POST.get('friendly_numbers') == 'on'
        send_as_caption = request.POST.get('send_as_caption') == 'on'
        use_normal_spintax = request.POST.get('use_normal_spintax') == 'on'
        use_ai_spintax = request.POST.get('use_ai_spintax') == 'on'

        # Handle schedule time
        if schedule_time_raw:
            try:
                schedule_time = datetime.strptime(schedule_time_raw, "%Y-%m-%dT%H:%M")
            except ValueError:
                schedule_time = None
        else:
            schedule_time = None

        print(f" DEBUG - Starting number processing...")
        print(f" Manual numbers input: {repr(manual_numbers)}")
        print(f" Excel file: {excel_file.name if excel_file else 'None'}")
        print(f" Attachment file: {attachment.name if attachment else 'None'}")  #  ADD: Debug attachment

        invalid_numbers = [] # Track rejected numbers here
        
        #  Handle manual numbers
        if manual_numbers:
            print(" Processing manual numbers...")
            for idx, num in enumerate(manual_numbers.split(","), start=1):
                clean_num = num.strip()
                if clean_num:
                    formatted_num = format_number_safely(clean_num, country_code or '+91')
                    if formatted_num:
                        all_numbers.append(formatted_num)
                        numbers_list.append({
                            "sl": idx,
                            "number": formatted_num,
                            "name": "-"
                        })
                        print(f" Added manual number: {formatted_num}")
                    else:
                        invalid_numbers.append(clean_num)
                        print(f" Skipped invalid manual number: {clean_num}")
            print(f" Manual numbers processed: {len(all_numbers)}")
        else:
            print(" No manual numbers provided")

        #  Handle Excel numbers
        if excel_file:
            print(f" Excel file received: {excel_file.name}")
            print(f" Excel file size: {excel_file.size}")
            print(f" Excel file content type: {excel_file.content_type}")
            
            try:
                # Read the Excel or CSV file as strings to prevent scientific notation corruption
                file_ext = os.path.splitext(excel_file.name)[1].lower()
                if file_ext == '.csv':
                    df = pd.read_csv(excel_file, dtype=str)
                else:
                    df = pd.read_excel(excel_file, dtype=str)
                
                print(f" Excel shape: {df.shape}")
                print(f" Excel columns: {df.columns.tolist()}")
                print(f" Excel dtypes: {df.dtypes.tolist()}")
                print(f" Raw DataFrame:")
                print(df)
                
                #  Check if DataFrame is empty but has columns (headers as data)
                if df.empty and len(df.columns) > 0:
                    print(" Empty DataFrame but has columns - treating headers as data")
                    # Convert column headers to a row
                    header_data = df.columns.tolist()
                    print(f" Header data: {header_data}")
                    
                    # Process the header data as if it's the first row
                    if len(header_data) > 0:
                        number_value = header_data[0]
                        print(f" Processing header as number: {number_value} (type: {type(number_value)})")
                        
                        if number_value is not None:
                            formatted_num = format_number_safely(number_value, country_code or '+91')
                            if formatted_num:
                                all_numbers.append(formatted_num)
                                numbers_list.append({
                                    "sl": len(numbers_list) + 1,
                                    "number": formatted_num,
                                    "name": header_data[1] if len(header_data) > 1 else "-"
                                })
                                print(f" Added valid number from header: {formatted_num}")
                            else:
                                invalid_numbers.append(str(number_value))
                                print(f" Invalid number in header: '{number_value}'")
                
                elif not df.empty:
                    # Normal processing for properly formatted Excel
                    print(" Processing normal Excel data...")
                    excel_count = 0
                    
                    for idx, row in df.iterrows():
                        print(f" Processing row {idx}: {row.values}")
                        
                        if len(df.columns) > 0:
                            number_value = row.iloc[0]
                            print(f" First column value: {number_value} (type: {type(number_value)})")
                            
                            if pd.notna(number_value):
                                formatted_num = format_number_safely(number_value, country_code or '+91')
                                if formatted_num and str(number_value).strip().lower() != 'nan':
                                    all_numbers.append(formatted_num)
                                    excel_count += 1
                                    numbers_list.append({
                                        "sl": len(numbers_list) + 1,
                                        "number": formatted_num,
                                        "name": str(row.iloc[1]) if len(df.columns) > 1 and pd.notna(row.iloc[1]) else "-"
                                    })
                                    print(f" Added valid Excel number: {formatted_num}")
                                else:
                                    invalid_numbers.append(str(number_value))
                                    print(f" Skipped invalid Excel entry: '{number_value}'")
                            else:
                                print(f" NaN value in row {idx}")
                else:
                    print(" Excel file is completely empty!")
                    
                print(f" Total Excel numbers processed: {len([n for n in all_numbers if n])}")
                
            except Exception as e:
                print(f" Error reading Excel: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(" No Excel file uploaded")

        print(f" Total valid numbers collected: {len(all_numbers)}")
        print(f" All numbers before deduplication: {all_numbers}")

        #  Remove duplicates if enabled
        if deduplicate:
            original_count = len(all_numbers)
            all_numbers = list(dict.fromkeys(all_numbers))  # Preserve order
            print(f" After deduplication: {len(all_numbers)} (removed {original_count - len(all_numbers)})")

        #  Convert to string for database storage
        combined_numbers = "\n".join(all_numbers)
        print(f" Combined numbers for database: {repr(combined_numbers)}")
        print(f" Combined numbers length: {len(combined_numbers)}")

        #  Save campaign WITH ATTACHMENT
        try:
            campaign = WhatsAppCampaign.objects.create(
                name=campaign_name,
                message1=message_1,
                message2=message_2,
                excel_file=excel_file,
                attachment=attachment,  #  ADD: Save attachment
                numbers=combined_numbers,  # All numbers (manual + Excel)
                country_code=country_code or '+91',  # Default country code
                whatsapp_group=whatsapp_group if whatsapp_group else None,
                deduplicate=deduplicate,
                safe_mode=safe_mode,
                unsafe_mode=unsafe_mode,
                swipe_after=int(swipe_after) if swipe_after else 2,
                delay=max(1, int(delay)) if delay else 5,
                batch_break_interval=max(1, int(request.POST.get('batch_break_interval', 15) or 15)),
                break_duration=max(1, int(request.POST.get('break_duration', 3) or 3)),
                schedule_time=schedule_time,
                friendly_numbers=friendly_numbers,
                send_as_caption=send_as_caption,
                use_normal_spintax=use_normal_spintax,
                use_ai_spintax=use_ai_spintax,
                user=request.user
            )

            #  DEBUG: Check what was actually saved
            print(f" Campaign created with ID: {campaign.id}")
            print(f" Campaign name saved: {campaign.name}")
            print(f" Numbers saved to DB: {repr(campaign.numbers)}")
            print(f" Numbers length in DB: {len(campaign.numbers) if campaign.numbers else 0}")
            print(f" Attachment saved: {campaign.attachment.name if campaign.attachment else 'None'}")  #  ADD: Debug attachment

            #  Re-fetch from database to double-check
            saved_campaign = WhatsAppCampaign.objects.get(id=campaign.id)
            print(f" Re-fetched from DB - numbers: {repr(saved_campaign.numbers)}")
            print(f" Re-fetched from DB - numbers length: {len(saved_campaign.numbers) if saved_campaign.numbers else 0}")
            print(f" Re-fetched from DB - attachment: {saved_campaign.attachment.name if saved_campaign.attachment else 'None'}")  #  ADD: Debug attachment

        except Exception as e:
            print(f" Error saving campaign: {e}")
            import traceback
            traceback.print_exc()
            return render(request, 'index.html', {
                'error': f'Error saving campaign: {e}',
                'accounts': WhatsAppAccount.objects.filter(user=request.user),
                'numbers_list': numbers_list
            })

        print(f" Campaign {campaign.id} saved with {len(all_numbers)} numbers")

        #  Assign WhatsApp account
        if selected_accounts:
            try:
                account = WhatsAppAccount.objects.filter(
                    id__in=selected_accounts, user=request.user
                ).first()
                if account:
                    campaign.whatsapp_account = account
                    campaign.save()
                    print(f" Assigned WhatsApp account: {account.number}")
                else:
                    print(" No valid WhatsApp account found")
            except Exception as e:
                print(f" Error assigning WhatsApp account: {e}")

        if invalid_numbers:
            from django.contrib import messages
            invalid_str = ", ".join(invalid_numbers)
            if len(invalid_str) > 80:
                invalid_str = invalid_str[:77] + "..."
            messages.warning(request, f"Filtered out {len(invalid_numbers)} fake/invalid numbers automatically: {invalid_str}")
            
        return redirect('deploy_campaign', campaign_id=campaign.id)

    # GET request - show form
    accounts = WhatsAppAccount.objects.filter(user=request.user)
    return render(request, 'index.html', {
        'accounts': accounts,
        'numbers_list': numbers_list
    })

@login_required
def delete_campaign(request, campaign_id):
    campaign = get_object_or_404(WhatsAppCampaign, id=campaign_id, user=request.user)
    campaign.delete()
    messages.success(request, "Campaign deleted successfully.")
    
    # Redirect back to History page
    referer = request.META.get('HTTP_REFERER')
    if referer and 'history' in referer:
        return redirect(referer)
    return redirect('campaign_history')

def kill_existing_chrome_processes(user_data_dir=None):
    for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
        try:
            if 'chrome' in proc.info['name'].lower():
                if user_data_dir and user_data_dir in ' '.join(proc.info['cmdline']):
                    proc.kill()
                elif not user_data_dir:
                    proc.kill()
        except Exception:
            pass

def send_campaign_messages(
    campaign=None,
    valid_numbers=None,
    message1=None,
    message2=None,
    attachment_path=None,
    whatsapp_account=None,
    session_exists=False,
    campaign_id=None
):
    """Improved campaign message sender with Chrome browser"""
    
    logger.info(" Starting WhatsApp campaign with Chrome")
    
    # Debug attachment path
    if attachment_path:
        if os.path.exists(attachment_path):
            logger.info(f" Attachment found: {attachment_path}")
        else:
            logger.warning(f" Attachment path not found: {attachment_path}")
            attachment_path = None
    else:
        logger.info(" No attachment for this campaign")
    
    # Validate inputs
    if not campaign and not campaign_id:
        return {"success": False, "error": "Campaign or campaign_id required"}
    if not valid_numbers:
        return {"success": False, "error": "No valid numbers provided"}
    
    # Fetch campaign if only ID provided
    if campaign_id and not campaign:
        try:
            from .models import WhatsAppCampaign
            campaign = WhatsAppCampaign.objects.get(id=campaign_id)
        except Exception as e:
            logger.error(f"Could not fetch campaign {campaign_id}: {e}")
            return {"success": False, "error": f"Invalid campaign ID: {campaign_id}"}

    with sync_playwright() as p:
        browser = None
        try:
            # Use Chrome instead of Chromium for better stability
            user_data_dir = whatsapp_account.session_path if whatsapp_account else f"./whatsapp_session_{campaign_id}"
            
            # Ensure session directory exists
            os.makedirs(user_data_dir, exist_ok=True)
            
            # Launch Chrome with persistent context
            browser = p.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                channel="chrome",  # Use Chrome instead of Chromium
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    "--disable-backgrounding-occluded-windows",
                    "--disable-ipc-flooding-protection",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-extensions-except",
                    "--disable-default-apps",
                    "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ],
                viewport={'width': 1366, 'height': 768},
                locale='en-US',
                timezone_id='America/New_York'
            )
            
            page = browser.new_page()
            page.set_default_timeout(60000)
            
            logger.info(f" Navigating to WhatsApp Web with Chrome...")
            page.goto("https://web.whatsapp.com", wait_until='networkidle')
            
            # Enhanced session validation
            session_valid = validate_whatsapp_session(page, whatsapp_account)
            
            if not session_valid:
                return {"success": False, "error": "session_expired"}
            
            logger.info(" Session validated, starting message sending")
            
            success_count = 0
            failed_count = 0
            
            # Process each number
            for i, phone_number in enumerate(valid_numbers, 1):
                try:
                    # Check for stop/pause signals
                    if campaign_id in active_campaigns:
                        if active_campaigns[campaign_id].get('stopped', False):
                            logger.info(" Campaign stopped by user")
                            break
                        
                        while active_campaigns[campaign_id].get('paused', False):
                            time.sleep(random.uniform(1.5, 3.5))
                            if active_campaigns[campaign_id].get('stopped', False):
                                break
                    
                    logger.info(f" Processing {phone_number} ({i}/{len(valid_numbers)})")
                    update_status(campaign_id, phone_number, 'Processing')
                    
                    # Send first message with attachment
                    if message1 and message1.strip():
                        success = send_message_to_number(page, phone_number, message1, campaign_id, attachment_path)
                        if success:
                            success_count += 1
                            update_status(campaign_id, phone_number, 'Sent')
                            
                            # Send second message if provided (without attachment)
                            if message2 and message2.strip():
                                time.sleep(random.uniform(1.5, 3.5))  # Brief pause between messages
                                success2 = send_message_to_number(page, phone_number, message2, campaign_id, None)
                                if not success2:
                                    logger.warning(f" Second message failed for {phone_number}")
                        else:
                            failed_count += 1
                            update_status(campaign_id, phone_number, 'Failed')
                    
                    # Delay between contacts
                    if i < len(valid_numbers):
                        delay = getattr(campaign, 'delay', 8) or 8
                        delay = max(delay, 5)  # Minimum 5 seconds
                        human_delay = delay + random.uniform(2.5, 7.5)
                        logger.info(f" Waiting {human_delay:.1f} seconds...")
                        time.sleep(human_delay)
                
                except Exception as e:
                    logger.error(f" Error processing {phone_number}: {e}")
                    failed_count += 1
                    update_status(campaign_id, phone_number, 'Failed')
                    continue
            
            # Update campaign status
            if hasattr(campaign, 'is_sent'):
                campaign.is_sent = True
                campaign.save()
            
            result = {
                "success": True, 
                "sent": success_count, 
                "failed": failed_count, 
                "total": len(valid_numbers)
            }
            
            logger.info(f" Campaign completed - Success: {success_count}, Failed: {failed_count}")
            return result
            
        except Exception as e:
            logger.error(f" Campaign error: {e}")
            
            return {"success": False, "error": str(e)}
            
        finally:
            if browser:
                try:
                    browser.close()
                    logger.info(" Chrome browser closed")
                except Exception as e:
                    logger.warning(f" Error closing browser: {e}")



def validate_whatsapp_session(page, whatsapp_account, timeout=60):
    """Enhanced session validation with better detection"""
    try:
        logger.info(" Validating WhatsApp session...")
        time.sleep(random.uniform(4.0, 7.0))  # Allow initial page load
        
        start_time = time.time()
        
        while (time.time() - start_time) < timeout:
            try:
                # Check for QR code (session expired)
                qr_selectors = [
                    "canvas[aria-label*='qr' i]",
                    "[data-ref*='qr']",
                    "[data-testid*='qr']",
                    "canvas[role='img']",
                    "div[data-testid='qr-code-container']"
                ]
                
                qr_found = any(
                    page.locator(selector).is_visible() 
                    for selector in qr_selectors 
                    if page.locator(selector).count() > 0
                )
                
                if qr_found:
                    logger.error(" QR code detected - session expired")
                    if whatsapp_account:
                        whatsapp_account.is_active = False
                        whatsapp_account.save()
                    return False
                
                # Check for main chat interface (session valid)
                chat_selectors = [
                    "#side",
                    "[data-testid='chat-list']",
                    "div[title='Chats']",
                    "[aria-label*='Chat list' i]",
                    "div[data-testid='contact-list']",
                    "footer[data-testid='compose']"  # Also check for compose area
                ]
                
                chat_found = any(
                    page.locator(selector).is_visible() 
                    for selector in chat_selectors 
                    if page.locator(selector).count() > 0
                )
                
                if chat_found:
                    logger.info(" WhatsApp session is valid")
                    if whatsapp_account:
                        whatsapp_account.is_active = True
                        whatsapp_account.save()
                    return True
                
                # Wait and retry
                time.sleep(random.uniform(1.5, 3.5))
                
            except Exception as e:
                logger.warning(f" Session validation error: {e}")
                time.sleep(random.uniform(1.5, 3.5))
        
        logger.error(" Session validation timeout")
        return False
        
    except Exception as e:
        logger.error(f" Session validation failed: {e}")
        return False




def process_campaign_background(campaign_id):
    """Background campaign processor with improved error handling"""
    try:
        from .models import WhatsAppCampaign
        campaign = WhatsAppCampaign.objects.get(id=campaign_id)
        phone_numbers = [num.strip() for num in campaign.numbers.splitlines() if num.strip()]
        
        # Initialize statuses
        for number in phone_numbers:
            update_status(campaign_id, number, 'Pending')
        
        # Create WhatsApp account object if needed
        whatsapp_account = getattr(campaign, 'whatsapp_account', None)
        
        #  FIX: Get attachment path correctly
        attachment_path = None
        if campaign.attachment:
            try:
                attachment_path = campaign.attachment.path
                print(f" Attachment found: {attachment_path}")
            except Exception as e:
                print(f" Error getting attachment path: {e}")
                attachment_path = None
        else:
            print(" No attachment for this campaign")
        
        # Send messages
        result = send_campaign_messages(
            campaign=campaign,
            valid_numbers=phone_numbers,
            message1=campaign.message1,
            message2=getattr(campaign, 'message2', None),
            attachment_path=attachment_path,  #  Now passes correct attachment path
            whatsapp_account=whatsapp_account,
            campaign_id=campaign_id
        )
        
        # Update campaign status
        if campaign_id in active_campaigns:
            if result['success']:
                active_campaigns[campaign_id]['status'] = 'Completed'
            else:
                active_campaigns[campaign_id]['status'] = 'Failed'
                active_campaigns[campaign_id]['error'] = result.get('error', 'Unknown error')
        
        logger.info(f" Campaign {campaign_id} processed: {result}")
        
    except Exception as e:
        logger.error(f" Background campaign {campaign_id} failed: {e}")
        if campaign_id in active_campaigns:
            active_campaigns[campaign_id]['status'] = 'Failed'
            active_campaigns[campaign_id]['error'] = str(e)


def send_message_with_box(page, message_box, message):
    """Helper function to send a message using a found message box"""
    try:
        message_box.click()
        message_box.fill("")  # Clear any existing text
        message_box.type(message, delay=random.randint(40, 150))
        page.keyboard.press("Enter")
        return True
    except Exception as e:
        logger.error(f"Failed to send message with message box: {e}")
        return False


def send_message(page, message_box, message):
    """Helper function to send a message using Playwright"""
    try:
        message_box.click()
        message_box.fill("")  # Clear existing text
        message_box.type(message, delay=random.randint(40, 150))
        page.keyboard.press("Enter")
        return True
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return False






async def find_best_drop_target(page):
    """
    Find the best element to drop files onto.
    """
    # Priority order of drop targets
    drop_target_selectors = [
        # WhatsApp Web specific
        '[data-testid="conversation-panel"]',
        'div[data-tab="1"]',  # WhatsApp chat area
        'div[role="application"]',

        # Generic chat applications
        '[data-testid="main"]',
        'div[contenteditable="true"]',  # Message input areas
        '.message-input',
        '.chat-input',
        '.conversation-panel',
        '[role="textbox"]',
        'main',

        # Fallback
        'body'
    ]

    for selector in drop_target_selectors:
        try:
            element = await page.query_selector(selector)
            if element:
                is_visible = await element.is_visible()
                if is_visible:
                    print(f" Selected drop target: {selector}")
                    return element
        except Exception as e:
            print(f" Selector {selector} failed: {e}")
            continue

    print(" Using body as fallback drop target")
    return await page.query_selector('body')


async def perform_drag_drop(page, file_path, drop_target):
    """
    Perform the actual drag and drop using JavaScript events.
    """
    try:
        # Read file and prepare data
        file_name = os.path.basename(file_path)
        with open(file_path, 'rb') as f:
            file_content = base64.b64encode(f.read()).decode()

        # Get MIME type
        mime_type, _ = mimetypes.guess_type(file_path)
        if not mime_type:
            # Fallback MIME type map
            ext = os.path.splitext(file_path)[1].lower()
            mime_map = {
                '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
                '.gif': 'image/gif', '.mp4': 'video/mp4', '.mov': 'video/quicktime',
                '.pdf': 'application/pdf', '.doc': 'application/msword'
            }
            mime_type = mime_map.get(ext, 'application/octet-stream')

        print(f" File: {file_name} ({mime_type})")

        # Execute drag and drop simulation
        result = await page.evaluate("""
        async ({ fileName, mimeType, fileBase64, dropTarget }) => {
            try {
                console.log('Starting drag and drop simulation...');

                const response = await fetch(`data:${mimeType};base64,${fileBase64}`);
                const blob = await response.blob();
                const file = new File([blob], fileName, {
                    type: mimeType,
                    lastModified: Date.now()
                });

                console.log('Created file object:', file.name, file.type, file.size);

                const dataTransfer = new DataTransfer();
                dataTransfer.items.add(file);

                const target = dropTarget;
                if (!target) {
                    console.error('Drop target not found');
                    return false;
                }

                console.log('Drop target:', target.tagName, target.className);

                const originalBorder = target.style.border;
                target.style.border = '3px dashed #007bff';
                target.style.backgroundColor = 'rgba(0, 123, 255, 0.1)';

                const events = [
                    { type: 'dragstart', target: document.body },
                    { type: 'dragenter', target: target },
                    { type: 'dragover', target: target },
                    { type: 'drop', target: target },
                    { type: 'dragend', target: document.body }
                ];

                for (const eventInfo of events) {
                    const event = new DragEvent(eventInfo.type, {
                        bubbles: true,
                        cancelable: true,
                        dataTransfer: dataTransfer,
                        clientX: 100,
                        clientY: 100
                    });

                    if (eventInfo.type === 'dragover') {
                        eventInfo.target.addEventListener('dragover', (e) => {
                            e.preventDefault();
                        }, { once: true });
                    }

                    console.log(`Dispatching ${eventInfo.type} event`);
                    eventInfo.target.dispatchEvent(event);

                    await new Promise(resolve => setTimeout(resolve, 100));
                }

                setTimeout(() => {
                    target.style.border = originalBorder;
                    target.style.backgroundColor = '';
                }, 1000);

                console.log('Drag and drop sequence completed');
                return true;

            } catch (error) {
                console.error('Drag and drop simulation error:', error);
                return false;
            }
        }
        """, {
            'fileName': file_name,
            'mimeType': mime_type,
            'fileBase64': file_content,
            'dropTarget': drop_target
        })

        return result

    except Exception as e:
        print(f" Drag and drop execution failed: {e}")
        return False




# Additional helper function to debug page structure
def debug_page_elements(driver):
    """Helper function to inspect page elements for debugging"""
    print(f" DEBUG: Analyzing page structure...")
   
    try:
        # Get page title
        print(f"Page title: {driver.title}")
       
        # Find all buttons
        buttons = driver.find_elements(By.TAG_NAME, "button")
        print(f"Found {len(buttons)} button elements:")
       
        for i, btn in enumerate(buttons[:10]):  # Limit to first 10
            try:
                attrs = {
                    'text': btn.text,
                    'aria-label': btn.get_attribute('aria-label'),
                    'data-testid': btn.get_attribute('data-testid'),
                    'title': btn.get_attribute('title'),
                    'class': btn.get_attribute('class'),
                    'id': btn.get_attribute('id')
                }
                # Filter out None values
                attrs = {k: v for k, v in attrs.items() if v}
                if attrs:
                    print(f"  Button {i+1}: {attrs}")
            except:
                continue
               
        # Find all inputs
        inputs = driver.find_elements(By.TAG_NAME, "input")
        print(f"Found {len(inputs)} input elements:")
       
        for i, inp in enumerate(inputs):
            try:
                inp_type = inp.get_attribute('type')
                accept = inp.get_attribute('accept')
                if inp_type or accept:
                    print(f"  Input {i+1}: type='{inp_type}', accept='{accept}'")
            except:
                continue
               
    except Exception as e:
        print(f"Debug error: {e}")



# Additional helper function to debug page structure
def debug_page_elements(driver):
    """Helper function to inspect page elements for debugging"""
    print(f" DEBUG: Analyzing page structure...")
   
    try:
        # Get page title
        print(f"Page title: {driver.title}")
       
        # Find all buttons
        buttons = driver.find_elements(By.TAG_NAME, "button")
        print(f"Found {len(buttons)} button elements:")
       
        for i, btn in enumerate(buttons[:10]):  # Limit to first 10
            try:
                attrs = {
                    'text': btn.text,
                    'aria-label': btn.get_attribute('aria-label'),
                    'data-testid': btn.get_attribute('data-testid'),
                    'title': btn.get_attribute('title'),
                    'class': btn.get_attribute('class'),
                    'id': btn.get_attribute('id')
                }
                # Filter out None values
                attrs = {k: v for k, v in attrs.items() if v}
                if attrs:
                    print(f"  Button {i+1}: {attrs}")
            except:
                continue
               
        # Find all inputs
        inputs = driver.find_elements(By.TAG_NAME, "input")
        print(f"Found {len(inputs)} input elements:")
       
        for i, inp in enumerate(inputs):
            try:
                inp_type = inp.get_attribute('type')
                accept = inp.get_attribute('accept')
                if inp_type or accept:
                    print(f"  Input {i+1}: type='{inp_type}', accept='{accept}'")
            except:
                continue
               
    except Exception as e:
        print(f"Debug error: {e}")


# Usage example:
# Uncomment the line below to debug the page structure first
# debug_page_elements(driver)

# Then call the improved function
# result = send_attachment(driver, wait, "/path/to/your/file.jpg")



def check_session_validity(session_path):
    """Enhanced session validity check"""
    if not session_path or not os.path.exists(session_path):
        return False
    
    # Check for WhatsApp Web session files
    session_indicators = [
        'Default/Local Storage',
        'Default/Session Storage', 
        'Default/IndexedDB',
        'Local Storage',
        'Session Storage',
        'IndexedDB'
    ]
    
    valid_indicators_found = 0
    try:
        for root, dirs, files in os.walk(session_path):
            for indicator in session_indicators:
                if indicator in root:
                    valid_indicators_found += 1
                    break
    except OSError:
        return False
    
    # Need at least 2 session indicators for valid session
    return valid_indicators_found >= 2

def create_unique_driver(campaign_id, user_id):
    """Create a Chrome driver with unique user data directory"""
    import tempfile
    import uuid
    from selenium.webdriver.chrome.service import Service
    from webdriver_manager.chrome import ChromeDriverManager
    
    # Create unique temporary directory for this campaign
    unique_id = f"{user_id}_{campaign_id}_{int(time.time())}_{uuid.uuid4().hex[:8]}"
    temp_dir = tempfile.mkdtemp(prefix=f"whatsapp_campaign_{unique_id}_")
    
    chrome_options = webdriver.ChromeOptions()
    chrome_options.add_argument(f"--user-data-dir={temp_dir}")
    chrome_options.add_argument("--profile-directory=Default")
    
    # Stability arguments
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-web-security")
    chrome_options.add_argument("--disable-features=VizDisplayCompositor")
    chrome_options.add_argument("--disable-background-networking")
    chrome_options.add_argument("--disable-notifications")
    chrome_options.add_argument("--disable-default-apps")
    chrome_options.add_argument("--disable-sync")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--no-first-run")
    chrome_options.add_argument("--disable-logging")
    chrome_options.add_argument("--log-level=3")
    chrome_options.add_argument("--window-size=1200,800")
    chrome_options.add_argument("--remote-debugging-port=0")  # Use random port
    
    # Anti-detection
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    
    # Use webdriver manager for automatic driver management
    service = Service(ChromeDriverManager().install())
    
    driver = webdriver.Chrome(service=service, options=chrome_options)
    
    # Add script to hide webdriver property
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    
    return driver


def update_status(campaign_id, phone_number, status, error=None):
    """Update status for a specific phone number"""
    if campaign_id not in campaign_statuses:
        campaign_statuses[campaign_id] = {}
    
    campaign_statuses[campaign_id][phone_number] = {
        'status': status,
        'error': error,
        'timestamp': time.time()
    }

def send_message_to_number(page, phone_number, message, campaign_id, attachment_path=None):
    """Send message with optional attachment to a specific number"""
    try:
        # Navigate to chat
        chat_url = f"https://web.whatsapp.com/send?phone={phone_number}"
        logger.info(f" Navigating to: {chat_url}")
        page.goto(chat_url, wait_until='networkidle', timeout=30000)
        
        # Wait for chat interface
        time.sleep(random.uniform(4.0, 7.0))
        
        # Check if chat loaded properly
        chat_selectors = [
            'footer div[contenteditable="true"]',
            'div[title="Type a message"]',
            'div[data-tab="10"]'
        ]
        
        chat_ready = False
        for selector in chat_selectors:
            try:
                if page.wait_for_selector(selector, timeout=10000):
                    logger.info(f" Chat interface ready - found: {selector}")
                    chat_ready = True
                    break
            except:
                continue
        
        if not chat_ready:
            logger.error(f" Chat interface not ready for {phone_number}")
            return False
        
        # Send attachment first if provided
        if attachment_path and os.path.exists(attachment_path):
            logger.info(f" Sending attachment to {phone_number}")
            try:
                # Click attachment button (paperclip icon)
                attachment_selectors = [
                    'div[title="Attach"]',
                    'span[data-icon="attach-menu-plus"]',
                    'button[title="Attach"]',
                    'div[role="button"][title="Attach"]',
                    'span[data-icon="clip"]',
                    'div[title="Attach"] span',
                    'button[aria-label="Attach"]'
                ]
                
                attachment_button = None
                for selector in attachment_selectors:
                    try:
                        attachment_button = page.wait_for_selector(selector, timeout=5000)
                        if attachment_button:
                            logger.info(f" Found attachment button: {selector}")
                            break
                    except:
                        continue
                
                if attachment_button:
                    attachment_button.click()
                    logger.info(" Clicked attachment button")
                    time.sleep(random.uniform(1.5, 3.5))
                    
                    # Look for file input
                    file_input_selectors = [
                        'input[accept*="*"]',
                        'input[type="file"]'
                    ]
                    
                    file_input = None
                    for selector in file_input_selectors:
                        try:
                            file_input = page.wait_for_selector(selector, timeout=5000)
                            if file_input:
                                logger.info(f" Found file input: {selector}")
                                break
                        except:
                            continue
                    
                    if file_input:
                        # Upload the file
                        file_input.set_input_files(attachment_path)
                        logger.info(f" File uploaded: {attachment_path}")
                        time.sleep(random.uniform(2.0, 4.5))  # Wait for file to process
                        
                        # Look for send button in attachment dialog
                        send_selectors = [
                            'span[data-icon="send"]',
                            'button[aria-label="Send"]',
                            'div[title="Send"]',
                            'span[data-icon="send-light"]'
                        ]
                        
                        send_button = None
                        for selector in send_selectors:
                            try:
                                send_button = page.wait_for_selector(selector, timeout=10000)
                                if send_button:
                                    logger.info(f" Found attachment send button: {selector}")
                                    break
                            except:
                                continue
                        
                        if send_button:
                            send_button.click()
                            logger.info(f" Attachment sent to {phone_number}")
                            time.sleep(random.uniform(2.0, 4.5))  # Wait for attachment to be sent
                        else:
                            logger.warning(f" Could not find attachment send button for {phone_number}")
                    else:
                        logger.warning(f" Could not find file input for {phone_number}")
                else:
                    logger.warning(f" Could not find attachment button for {phone_number}")
                    
            except Exception as e:
                logger.warning(f" Attachment failed for {phone_number}: {e}")
        
        # Send text message if provided
        if message and message.strip():
            logger.info(f" Sending text message to {phone_number}")
            
            # Find message input
            message_input = None
            message_selectors = [
                'footer div[contenteditable="true"][role="textbox"]',
                'div[title="Type a message"]',
                'footer div[contenteditable="true"]'
            ]
            
            for selector in message_selectors:
                try:
                    message_input = page.wait_for_selector(selector, timeout=5000)
                    if message_input:
                        logger.info(f" Found message input: {selector}")
                        break
                except:
                    continue
            
            if message_input:
                # Send the message
                message_input.click()
                message_input.fill("")  # Clear any existing text
                message_input.type(message, delay=random.randint(40, 150))
                page.keyboard.press("Enter")
                logger.info(f" Message sent successfully to {phone_number}")
                return True
            else:
                logger.error(f" Could not find message input for {phone_number}")
                return False
        
        return True  # Return True if only attachment was sent
        
    except Exception as e:
        logger.error(f" Error sending to {phone_number}: {e}")
        return False


def wait_for_chat_interface(page, timeout=30000):
    """Wait for WhatsApp chat interface to fully load"""
    try:
        # Look for compose/footer area specifically (not search area)
        chat_indicators = [
            'footer[data-testid="compose"]',
            'div[data-testid="compose-box-input"]',
            'footer div[contenteditable="true"]',
            'div[data-testid="conversation-compose-box-input"]'
        ]
        
        start_time = time.time()
        while (time.time() - start_time) * 1000 < timeout:
            for indicator in chat_indicators:
                try:
                    element = page.locator(indicator).first
                    if element.is_visible():
                        logger.info(f" Chat interface ready - found: {indicator}")
                        return True
                except:
                    continue
            
            time.sleep(random.uniform(0.8, 1.8))
        
        logger.warning(" Chat interface not ready within timeout")
        return False
        
    except Exception as e:
        logger.error(f" Error waiting for chat interface: {e}")
        return False
def find_message_input_specific(page):
    """Find ONLY the message composition input, NOT search or other inputs"""
    try:
        logger.info(" Looking for message composition input specifically...")
        
        # Strategy 1: Most specific WhatsApp message compose selectors
        compose_specific_selectors = [
            # Most specific - conversation compose box
            'div[data-testid="conversation-compose-box-input"]',
            # Footer area compose inputs
            'footer[data-testid="compose"] div[contenteditable="true"]',
            'footer div[contenteditable="true"][role="textbox"]',
            # Modern WhatsApp compose selectors
            'div[data-testid="compose-box-input"]',
            'footer div[data-lexical-editor="true"]',
            # Compose area with specific attributes
            'div[contenteditable="true"][data-tab="10"]'  # This tab index is specific to message input
        ]
        
        for selector in compose_specific_selectors:
            try:
                elements = page.locator(selector).all()
                for element in elements:
                    if element.is_visible() and element.is_enabled():
                        # Double-check it's not in header/search area
                        if not is_in_search_area(element):
                            logger.info(f" Found message input: {selector}")
                            return element
            except Exception as e:
                logger.debug(f"Selector {selector} failed: {e}")
                continue
        
        # Strategy 2: Find compose footer first, then input inside it
        try:
            footer_selectors = [
                'footer[data-testid="compose"]',
                'footer[class*="compose"]',
                'div[data-testid="compose-box"]'
            ]
            
            for footer_selector in footer_selectors:
                footer = page.locator(footer_selector).first
                if footer.is_visible():
                    # Look for contenteditable inside this footer
                    inputs_in_footer = footer.locator('div[contenteditable="true"]').all()
                    for input_elem in inputs_in_footer:
                        if input_elem.is_visible() and input_elem.is_enabled():
                            logger.info(f" Found message input inside footer: {footer_selector}")
                            return input_elem
        except Exception as e:
            logger.debug(f"Footer strategy failed: {e}")
        
        # Strategy 3: Position-based detection - find contenteditable in bottom area only
        try:
            viewport = page.viewport_size
            if viewport:
                bottom_threshold = viewport['height'] * 0.75  # Bottom 25% of screen
                
                all_contenteditable = page.locator('div[contenteditable="true"]').all()
                logger.info(f"Found {len(all_contenteditable)} contenteditable elements, filtering by position...")
                
                for element in all_contenteditable:
                    if element.is_visible() and element.is_enabled():
                        bounding_box = element.bounding_box()
                        if bounding_box and bounding_box['y'] > bottom_threshold:
                            # Additional check - not in search area
                            if not is_in_search_area(element):
                                logger.info(f" Found message input via position (y={bounding_box['y']})")
                                return element
        except Exception as e:
            logger.debug(f"Position strategy failed: {e}")
        
        # Strategy 4: Try clicking in compose area to activate input
        try:
            compose_areas = [
                'footer[data-testid="compose"]',
                'div[data-testid="compose-box"]'
            ]
            
            for area_selector in compose_areas:
                try:
                    area = page.locator(area_selector).first
                    if area.is_visible():
                        # Click in the center of compose area
                        area.click()
                        time.sleep(random.uniform(0.8, 1.8))
                        
                        # Try finding input again after activation
                        activated_input = area.locator('div[contenteditable="true"]').first
                        if activated_input.is_visible():
                            logger.info(f" Found input after clicking compose area")
                            return activated_input
                except Exception as e:
                    logger.debug(f"Click activation failed for {area_selector}: {e}")
                    continue
        except Exception as e:
            logger.debug(f"Click activation strategy failed: {e}")
        
        logger.error(" Could not find message composition input")
        return None
        
    except Exception as e:
        logger.error(f" Error finding message input: {e}")
        return None



def is_in_search_area(element):
    """Check if element is in search/header area (to avoid selecting search input)"""
    try:
        bounding_box = element.bounding_box()
        if not bounding_box:
            return False
        
        # If element is in top 30% of screen, likely search area
        viewport = element.page.viewport_size
        if viewport and bounding_box['y'] < viewport['height'] * 0.3:
            logger.debug("Element appears to be in search area (top 30%)")
            return True
        
        # Check if parent elements contain search-related attributes
        try:
            # Get parent elements and check for search indicators
            parent_html = element.evaluate("""
                el => {
                    let current = el;
                    let parents_info = [];
                    for (let i = 0; i < 5 && current; i++) {
                        parents_info.push({
                            class: current.className || '',
                            id: current.id || '',
                            testid: current.getAttribute('data-testid') || '',
                            arialabel: current.getAttribute('aria-label') || ''
                        });
                        current = current.parentElement;
                    }
                    return parents_info;
                }
            """)
            
            search_indicators = ['search', 'header', 'side', 'contact', 'chat-list']
            for parent_info in parent_html:
                for key, value in parent_info.items():
                    if any(indicator in value.lower() for indicator in search_indicators):
                        logger.debug(f"Element in search area - parent {key}: {value}")
                        return True
                        
        except Exception as e:
            logger.debug(f"Parent check failed: {e}")
        
        return False
        
    except Exception as e:
        logger.debug(f"Search area check failed: {e}")
        return False
    
def find_message_input_reliable(page):
    """Find message input with multiple fallback strategies"""
    try:
        # Strategy 1: Modern WhatsApp selectors (priority order)
        modern_selectors = [
            '[data-testid="conversation-compose-box-input"]',
            'div[contenteditable="true"][data-lexical-editor="true"]',
            'div[contenteditable="true"][role="textbox"]',
            'div[data-testid="compose-box-input"]',
            'div[contenteditable="true"][data-tab="10"]'
        ]
        
        for selector in modern_selectors:
            try:
                element = page.locator(selector).first
                if element.is_visible() and element.is_enabled():
                    logger.info(f" Found message input: {selector}")
                    return element
            except:
                continue
        
        # Strategy 2: Generic contenteditable in footer/compose area
        try:
            footer_inputs = page.locator('footer div[contenteditable="true"]').all()
            for element in footer_inputs:
                if element.is_visible() and element.is_enabled():
                    logger.info(" Found message input in footer")
                    return element
        except:
            pass
        
        # Strategy 3: Any visible contenteditable textbox
        try:
            all_contenteditable = page.locator('div[contenteditable="true"]').all()
            for element in all_contenteditable:
                if element.is_visible() and element.is_enabled():
                    # Check if it's in the bottom part of screen (likely message input)
                    bounding_box = element.bounding_box()
                    if bounding_box:
                        viewport = page.viewport_size
                        if viewport and bounding_box['y'] > viewport['height'] * 0.7:
                            logger.info(" Found message input via position detection")
                            return element
        except:
            pass
        
        # Strategy 4: Try to activate input by clicking in compose area
        try:
            compose_selectors = [
                'footer[data-testid="compose"]',
                'div[data-testid="compose-box"]',
                'div[class*="compose"]'
            ]
            
            for selector in compose_selectors:
                try:
                    compose_area = page.locator(selector).first
                    if compose_area.is_visible():
                        compose_area.click()
                        time.sleep(random.uniform(0.8, 1.8))
                        
                        # Try finding input again after click
                        for modern_selector in modern_selectors[:3]:
                            try:
                                element = page.locator(modern_selector).first
                                if element.is_visible():
                                    logger.info(f" Found input after clicking compose: {modern_selector}")
                                    return element
                            except:
                                continue
                except:
                    continue
        except:
            pass
        
        logger.error(" Could not find message input with any strategy")
        return None
        
    except Exception as e:
        logger.error(f" Error finding message input: {e}")
        return None

# ------------------------------------------
# Separate function (outside the above)
# ------------------------------------------
def send_message(campaign, valid_numbers, message1, message2, attachment_path, whatsapp_account):
    driver = None
    try:
        user_data_dir = whatsapp_account.session_path if whatsapp_account and whatsapp_account.session_path else None
        if not user_data_dir or not os.path.exists(user_data_dir):
            print(" No valid session path found. Aborting.")
            return

        print(f" Launching WebDriver with session: {user_data_dir}")
        driver = create_webdriver(user_data_dir=user_data_dir)
        driver.get("https://web.whatsapp.com")
        time.sleep(random.uniform(4.0, 7.0))

        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "side"))
        )
        print(" WhatsApp Web loaded with existing session")

        success_count, failed_numbers = 0, []

        for number in valid_numbers:
            try:
                print(f" Sending to {number}")
                driver.get(f"https://web.whatsapp.com/send?phone={number}")

                msg_box = WebDriverWait(driver, 25).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.XPATH, "//div[@title='Type a message']")),
                        EC.presence_of_element_located((By.XPATH, "//div[@contenteditable='true'][@data-tab='10']")),
                        EC.presence_of_element_located((By.XPATH, "//div[@data-testid='conversation-compose-box-input']"))
                    )
                )

                combined = "\n".join(filter(None, [message1, message2]))
                send_message(driver, None, msg_box, combined)

                success_count += 1
                time.sleep(random.uniform(3, 6))

            except Exception as e:
                print(f" Failed to send to {number}: {e}")
                failed_numbers.append(number)

        print(f" Sent: {success_count} |  Failed: {len(failed_numbers)}")
        campaign.is_sent = True
        campaign.save()

    except Exception as e:
        print(f" Background error: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except:
                pass
        if attachment_path and os.path.exists(attachment_path):
            try:
                os.remove(attachment_path)
            except:
                pass

def send_attachment_playwright(page, attachment_path, caption_message=None):
    """Send attachment using Playwright with explicit file type handling to prevent sticker conversion"""
    try:
        if not os.path.exists(attachment_path):
            logger.error(f" Attachment file not found: {attachment_path}")
            return False
 
        file_size = os.path.getsize(attachment_path)
        if file_size > 100 * 1024 * 1024:
            logger.error(f" File too large: {file_size} bytes")
            return False
 
        logger.info(f" Preparing to send attachment: {attachment_path}")
 
        # Get file information
        file_path = Path(attachment_path)
        file_name = file_path.name
        file_extension = file_path.suffix.lower()
 
        # Determine correct MIME type
        mime_type, _ = mimetypes.guess_type(attachment_path)
        if not mime_type:
            mime_map = {
                '.jpg': 'image/jpeg',
                '.jpeg': 'image/jpeg',
                '.png': 'image/png',
                '.gif': 'image/gif',
                '.webp': 'image/webp',
                '.bmp': 'image/bmp',
                '.pdf': 'application/pdf',
                '.doc': 'application/msword',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.mp4': 'video/mp4',
                '.mov': 'video/quicktime'
            }
            mime_type = mime_map.get(file_extension, 'application/octet-stream')
 
        is_media = mime_type.startswith('image/') or mime_type.startswith('video/')
        logger.info(f" File: {file_name}, Extension: {file_extension}, MIME: {mime_type}, Is Media: {is_media}")
 
        # Find attachment button
        attachment_selectors = [
            'span[data-icon="plus-rounded"]',
            'span[data-icon="plus"]',
            'span[data-icon="attach-menu-plus"]',
            'div[title="Attach"]',
            'div[aria-label="Attach"]',
            'button[aria-label="Attach"]'
        ]
        attachment_button = None
        for selector in attachment_selectors:
            try:
                page.wait_for_selector(selector, state='visible', timeout=5000)
                attachment_button = page.query_selector(selector)
                if attachment_button and attachment_button.is_visible():
                    logger.info(f" Found attachment button: {selector}")
                    break
            except Exception as e:
                logger.debug(f"Selector {selector} failed: {str(e)}")
                continue
 
        if not attachment_button:
            logger.error(" Attachment button not found")
            return False
 
        logger.info(" Clicking attachment button...")
        attachment_button.click()
        # Click the visual button in the menu and intercept the file dialog
        try:
            with page.expect_file_chooser(timeout=5000) as fc_info:
                if is_media:
                    logger.info(" Clicking 'Photos & videos' menu option...")
                    # Click the menu item using ARIA labels (WhatsApp removed data-testids)
                    menu_item = page.locator('button[aria-label="Photos & videos"], [role="menuitem"][aria-label="Photos & videos"], [data-testid="attach-image"]').first
                    menu_item.click()
                else:
                    logger.info(" Clicking 'Document' menu option...")
                    # Click the menu item using ARIA labels (WhatsApp removed data-testids)
                    menu_item = page.locator('button[aria-label="Document"], [role="menuitem"][aria-label="Document"], [data-testid="attach-document"]').first
                    menu_item.click()
                    
            logger.info(" Intercepted file chooser, injecting file...")
            file_chooser = fc_info.value
            file_chooser.set_files(attachment_path)
            logger.info(f" File injected: {attachment_path}")
        except Exception as e:
            logger.error(f" Error during menu click or file chooser interception: {str(e)}")
            return False
        page.wait_for_timeout(random.randint(2500, 7000))  # Allow file processing
 
        # Verify file preview if media
        if is_media:
            try:
                preview_selector = 'img[data-testid="image-preview"], [data-testid="media-preview"], video'
                page.wait_for_selector(preview_selector, state='visible', timeout=5000)
                if page.query_selector(preview_selector):
                    logger.info(" Media preview detected, file uploaded correctly")
                else:
                    logger.warning(" No media preview detected")
            except Exception as e:
                logger.warning(f" Error checking media preview: {str(e)}")
 
        # Type caption if provided and press Enter
        if caption_message and caption_message.strip():
            logger.info(" Typing message as attachment caption...")
            message_lines = caption_message.splitlines()
            for j, line in enumerate(message_lines):
                if line.strip():
                    page.keyboard.type(line, delay=random.randint(35, 110))
                if j < len(message_lines) - 1:
                    page.keyboard.down('Shift')
                    page.keyboard.press('Enter')
                    page.keyboard.up('Shift')
            page.wait_for_timeout(random.randint(400, 800))

        # Press Enter to send attachment (bypassing broken click buttons)
        logger.info(" Pressing Enter to send attachment...")
        page.keyboard.press('Enter')
        page.wait_for_timeout(random.randint(1500, 3000))
        return True
 
    except Exception as e:
        logger.error(f" Exception during attachment send: {str(e)}")
        logger.error(traceback.format_exc())
        return False
 
def click_send_button(page):
    """Find and click the send button"""
    try:
        send_selectors = [
            'div[aria-label="Send"]',
            'button[aria-label="Send"]',
            'span[data-icon="send"]',
            'div[data-testid="send"]',
            '[data-testid="send"]',
            'button:has-text("Send")'
        ]
 
        for selector in send_selectors:
            try:
                page.wait_for_selector(selector, state='visible', timeout=5000)
                send_button = page.query_selector(selector)
                if send_button and send_button.is_visible() and send_button.is_enabled():
                    logger.info(f" Clicking send button: {selector}")
                    send_button.click()
                    page.wait_for_timeout(random.randint(1500, 3000))  # Allow send to complete
                    return True
            except Exception as e:
                logger.debug(f"Send button selector {selector} failed: {str(e)}")
                continue
 
        # Fallback: Try Enter key
        logger.info(" Using Enter key as fallback")
        page.keyboard.press('Enter')
        page.wait_for_timeout(random.randint(1500, 3000))
        return True
 
    except Exception as e:
        logger.error(f" Error clicking send button: {str(e)}")
        return False
    
    
def click_send_button(page):
    """Find and click the send button"""
    try:
        send_selectors = [
            'div[aria-label="Send"]',
            'button[aria-label="Send"]',
            'span[data-icon="send"]',
            'div[data-testid="send"]',
            '[data-testid="send"]',
            'button:has-text("Send")'
        ]

        for selector in send_selectors:
            try:
                send_button = page.query_selector(selector)
                if send_button and send_button.is_visible() and send_button.is_enabled():
                    logger.info(f" Clicking send button: {selector}")
                    send_button.click()
                    time.sleep(random.uniform(1.5, 3.5))  # Allow send to complete
                    return True
            except Exception as e:
                logger.debug(f"Send button selector {selector} failed: {str(e)}")
                continue

        # Fallback: Try Enter key
        logger.info(" Using Enter key as fallback")
        page.keyboard.press('Enter')
        time.sleep(random.uniform(1.5, 3.5))
        return True

    except Exception as e:
        logger.error(f" Error clicking send button: {str(e)}")
        return False


def send_message_to_number(page, phone_number, message, campaign_id, attachment_path=None, send_as_caption=True, message2=None):
    """Send message to a specific phone number using Playwright"""
    try:
        update_status(campaign_id, phone_number, 'Processing')
        
        # Clean phone number
        clean_number = ''.join(filter(str.isdigit, phone_number))
        if not clean_number:
            logger.error(f" Invalid phone number: {phone_number}")
            update_status(campaign_id, phone_number, 'Invalid')
            return False
        
        # --- NEW CHAT UI NAVIGATION ---
        logger.info(f" Initiating New Chat UI Search for {clean_number}...")
        
        # 1. Click New Chat button with retries & human pre-action pause
        time.sleep(random.uniform(0.8, 1.8))
        new_chat_clicked = False
        new_chat_selectors = [
            'div[title="New chat"]',
            'button[aria-label="New chat"]',
            'span[data-icon="chat"]'
        ]
        
        for attempt in range(3):
            for selector in new_chat_selectors:
                try:
                    if page.locator(selector).first.is_visible(timeout=2000):
                        logger.info(f" Clicking 'New Chat' button using selector: {selector} (Attempt {attempt+1})")
                        human_click(page, selector)
                        new_chat_clicked = True
                        break
                except Exception as e:
                    logger.debug(f" New Chat selector '{selector}' failed attempt {attempt+1}: {str(e)}")
                    continue
            if new_chat_clicked:
                break
            time.sleep(1.0)
            
        if not new_chat_clicked:
            error_reason = "Failed to click 'New Chat' button: Element not found or not clickable after 3 attempts."
            logger.error(f" [{phone_number}] {error_reason}")
            update_status(campaign_id, phone_number, 'Failed', error_reason)
            return False
            
        logger.info(f" [{phone_number}] 'New Chat' button clicked successfully.")
        
        # 2. Wait for New Chat panel & Search Bar to load dynamically
        textbox_selectors = [
            'input[placeholder*="Search name"]',
            'input[aria-label*="Search name"]',
            'div[contenteditable="true"][title="Search name or number"]',
            'div[contenteditable="true"][data-tab="3"]',
            'input[data-tab="3"]',
            'label div[contenteditable="true"]'
        ]
        
        search_box = None
        for tb_sel in textbox_selectors:
            try:
                el = page.wait_for_selector(tb_sel, state='visible', timeout=4000)
                if el:
                    search_box = el
                    logger.info(f" [{phone_number}] Found search bar with selector '{tb_sel}'.")
                    break
            except Exception as e:
                logger.debug(f" Search bar selector '{tb_sel}' failed: {str(e)}")
                continue
                
        if not search_box:
            error_reason = "Failed to load New Chat search bar: Search input element did not appear in sidebar."
            logger.error(f" [{phone_number}] {error_reason}")
            update_status(campaign_id, phone_number, 'Failed', error_reason)
            page.keyboard.press("Escape")
            return False
            
        logger.info(f" [{phone_number}] New Chat search bar loaded successfully.")
        
        # 3. Select Search Bar & Type Phone Number (with realistic human pauses)
        try:
            time.sleep(random.uniform(0.5, 1.2))
            try:
                search_box.focus()
            except Exception:
                search_box.click(force=True)
                
            time.sleep(0.4)
            page.keyboard.press('Control+a')
            page.keyboard.press('Backspace')
            time.sleep(0.4)
            
            # Type with realistic human hesitations
            for char in clean_number:
                page.keyboard.type(char, delay=random.randint(60, 160))
                if random.random() < 0.15:  # Occasional human hesitation
                    time.sleep(random.uniform(0.2, 0.5))
                    
            logger.info(f" [{phone_number}] Typed phone number {clean_number} into search bar successfully.")
        except Exception as e:
            error_reason = f"Failed to type phone number into search bar: {str(e)}"
            logger.error(f" [{phone_number}] {error_reason}")
            update_status(campaign_id, phone_number, 'Failed', error_reason)
            page.keyboard.press("Escape")
            return False
            
        # 4. Wait for Search Results & Select Contact (with Double-Check & Option 1 Recovery)
        # 4. Wait for Search Results & Select Contact (Maximum Effort First)
        logger.info(f" [{phone_number}] Giving search results breathing space to load...")
        time.sleep(random.uniform(4.0, 5.5))

        # Matching by last 8 digits handles WhatsApp's formatted numbers (+91 80758 21508)
        short_number = clean_number[-8:] if len(clean_number) >= 8 else clean_number
        
        contact_opened = False
        for attempt in range(3):
            logger.info(f" [{phone_number}] Attempting to open contact chat (Attempt {attempt+1}/3)...")
            
            # 1. Try pressing Enter key first (WhatsApp Web automatically opens top search result on Enter!)
            try:
                page.keyboard.press('Enter')
                time.sleep(random.uniform(2.5, 4.0))
                
                search_panel_open = False
                for panel_sel in ['input[placeholder*="Search name"]', 'input[aria-label*="Search name"]']:
                    try:
                        if page.locator(panel_sel).first.is_visible(timeout=500):
                            search_panel_open = True
                            break
                    except Exception:
                        pass
                        
                msg_box_visible = page.locator('div[contenteditable="true"][data-tab="10"]').first.is_visible(timeout=1500)
                
                if not search_panel_open and msg_box_visible:
                    logger.info(f" [{phone_number}] Confirmed: Search panel closed & chat opened via Enter key!")
                    contact_opened = True
                    break
            except Exception as ee:
                logger.debug(f" Enter key attempt {attempt+1} exception: {str(ee)}")

            # 2. Universal Result Selectors for Business & Personal Accounts (Saved & Unsaved)
            result_selectors = [
                f'div[role="button"]:has-text("{short_number}")',
                f'div[role="listitem"]:has-text("{short_number}")',
                f'span:has-text("{short_number}")',
                'div[role="button"]:has-text("Chat with")',
                'div[role="listitem"]',
                'div[data-testid="cell-frame-container"]'
            ]
            
            for selector in result_selectors:
                try:
                    elements = page.locator(selector)
                    count = elements.count()
                    if count > 0:
                        for i in range(count):
                            el = elements.nth(i)
                            if el.is_visible(timeout=1000):
                                logger.info(f" [{phone_number}] Found result cell with '{selector}'. Clicking...")
                                human_click(page, selector)
                                time.sleep(random.uniform(2.0, 3.5))
                                
                                # Confirmation check: Triple Lock
                                search_panel_open = False
                                for panel_sel in ['input[placeholder*="Search name"]', 'input[aria-label*="Search name"]']:
                                    try:
                                        if page.locator(panel_sel).first.is_visible(timeout=500):
                                            search_panel_open = True
                                            break
                                    except Exception:
                                        pass
                                        
                                new_chat_btn_back = False
                                for btn_sel in ['div[title="New chat"]', 'button[aria-label="New chat"]', 'span[data-icon="chat"]']:
                                    try:
                                        if page.locator(btn_sel).first.is_visible(timeout=500):
                                            new_chat_btn_back = True
                                            break
                                    except Exception:
                                        pass
                                        
                                msg_box_visible = page.locator('div[contenteditable="true"][data-tab="10"]').first.is_visible(timeout=1500)
                                
                                if (not search_panel_open or new_chat_btn_back) and msg_box_visible:
                                    logger.info(f" [{phone_number}] Triple Lock Confirmed: Search panel closed & chat opened!")
                                    contact_opened = True
                                    break
                except Exception as e:
                    logger.debug(f" Result selector '{selector}' failed attempt {attempt+1}: {str(e)}")
                    continue
                    
                if contact_opened:
                    break
                    
            if contact_opened:
                break
                
            time.sleep(random.uniform(1.5, 2.5))
            
        # Check for Invalid ONLY if chat failed to open after all 3 attempts
        if not contact_opened:
            is_genuinely_invalid = False
            try:
                invalid_selector = 'div:has-text("No results found"), div:has-text("No contacts found"), span:has-text("No results found"), span:has-text("No contacts found")'
                if page.locator(invalid_selector).first.is_visible(timeout=2000):
                    time.sleep(1.5)
                    if page.locator(invalid_selector).first.is_visible(timeout=1000):
                        is_genuinely_invalid = True
            except Exception:
                pass
                
            if is_genuinely_invalid:
                error_reason = "Number not found on WhatsApp (Double-checked: 'No results found' displayed)."
                logger.warning(f" [{phone_number}] {error_reason}")
                update_status(campaign_id, phone_number, 'Invalid', error_reason)
            else:
                error_reason = "Failed to select contact: Search result did not open chat after maximum attempts."
                logger.error(f" [{phone_number}] {error_reason}")
                update_status(campaign_id, phone_number, 'Failed', error_reason)
                
            # Recovery: Click Back Button / Escape to reset UI for next recipient
            logger.info(f" [{phone_number}] Resetting search drawer via Back button for next recipient...")
            recovered = False
            for back_sel in ['span[data-icon="back"]', 'button[aria-label="Back"]', 'div[title="Back"]']:
                try:
                    if page.locator(back_sel).first.is_visible(timeout=800):
                        human_click(page, back_sel)
                        recovered = True
                        break
                except Exception:
                    pass
            if not recovered:
                page.keyboard.press("Escape")
                time.sleep(0.5)
                page.keyboard.press("Escape")
            return False
            
        logger.info(f" [{phone_number}] Selected contact and opened chat for {clean_number} successfully.")
        
        # 5. Verify Chat Interface Loaded
        try:
            page.wait_for_selector('div[contenteditable="true"][data-tab="10"]', timeout=10000)
            logger.info(f" [{phone_number}] Chat opened for {clean_number} successfully.")
            time.sleep(random.uniform(1.0, 2.0))
        except PlaywrightTimeoutError:
            error_reason = "Chat Box Blocked: Contact was clicked, but the message input box did not appear."
            logger.error(f" [{phone_number}] {error_reason}")
            update_status(campaign_id, phone_number, 'Failed', error_reason)
            return False
        
        # Send attachment first if provided
        attachment_sent_with_caption = False
        if attachment_path:
            # Pass the message to be used as a caption only if preference is True
            caption_to_send = message if send_as_caption else None
            attachment_success = send_attachment_playwright(page, attachment_path, caption_message=caption_to_send)
            if not attachment_success:
                logger.warning(f" Failed to send attachment to {phone_number}")
                # Continue with text message even if attachment fails
            else:
                if send_as_caption:
                    attachment_sent_with_caption = True
        
        # Send text message if provided (only if we didn't just send it as a caption)
        if message and message.strip() and not attachment_sent_with_caption:
            try:
                # Find message input box with multiple selectors
                message_selectors = [
                    'div[contenteditable="true"][data-tab="10"]',
                    'div[contenteditable="true"][role="textbox"]',
                    'div[data-testid="conversation-compose-box-input"]'
                ]
                
                message_box = None
                for selector in message_selectors:
                    try:
                        message_box = page.wait_for_selector(selector, timeout=5000)
                        if message_box and message_box.is_visible():
                            break
                    except PlaywrightTimeoutError:
                        continue
                
                if not message_box:
                    logger.error(f" Could not find message input for {phone_number}")
                    update_status(campaign_id, phone_number, 'Failed')
                    return False
                
                # Clear any existing text and type new message
                message_box.click()
                time.sleep(random.uniform(1.5, 3.5))
                
                # Clear existing content
                page.keyboard.press('Control+a')
                page.keyboard.press('Delete')
                
                # Type the message handling newlines properly for WhatsApp Web
                message_lines = message.splitlines()
                for j, line in enumerate(message_lines):
                    if line:
                        message_box.type(line, delay=random.randint(40, 150))
                    if j < len(message_lines) - 1:
                        page.keyboard.down('Shift')
                        page.keyboard.press('Enter')
                        page.keyboard.up('Shift')
                
                time.sleep(random.uniform(1.5, 3.5))
                
                # Send message
                page.keyboard.press('Enter')
                time.sleep(random.uniform(1.5, 3.5))
                logger.info(f" Message sent to {phone_number}")
                
            except Exception as e:
                logger.error(f" Error sending text message to {phone_number}: {str(e)}")
                update_status(campaign_id, phone_number, 'Failed')
                return False
                
        # --- SEND MESSAGE 2 (IF EXISTS) ---
        if message2 and message2.strip():
            try:
                logger.info(f" Sending Message 2 to {phone_number}...")
                time.sleep(random.uniform(2.5, 6.0))
                
                message_selectors = [
                    'div[contenteditable="true"][data-tab="10"]',
                    'div[contenteditable="true"][role="textbox"]',
                    'div[data-testid="conversation-compose-box-input"]'
                ]
                
                message_box2 = None
                for selector in message_selectors:
                    try:
                        message_box2 = page.wait_for_selector(selector, timeout=5000)
                        if message_box2 and message_box2.is_visible():
                            break
                    except:
                        continue
                
                if message_box2:
                    message_box2.click()
                    time.sleep(random.uniform(1.0, 2.0))
                    message_box2.type(message2, delay=random.randint(40, 150))
                    time.sleep(random.uniform(1.5, 3.5))
                    page.keyboard.press('Enter')
                    time.sleep(random.uniform(1.5, 3.5))
                else:
                    logger.error(f" Could not find message input for Message 2 to {phone_number}")
                    
            except Exception as e:
                logger.error(f" Error sending Message 2 to {phone_number}: {str(e)}")
        # ----------------------------------
        
        update_status(campaign_id, phone_number, 'Sent')
        return True
        
    except Exception as e:
        logger.error(f" Error sending message to {phone_number}: {str(e)}")
        update_status(campaign_id, phone_number, 'Failed')
        return False

def update_status(campaign_id, phone_number, status, error=None):
    """Update the status of a phone number in the campaign"""
    if campaign_id not in campaign_statuses:
        campaign_statuses[campaign_id] = {}
    
    campaign_statuses[campaign_id][phone_number] = {
        'status': status,
        'error': error,
        'timestamp': time.time()
    }

def process_campaign_background(campaign_id, account_id):
    """Background function to process the entire WhatsApp campaign using Playwright"""
    # FIX: Allow Django ORM to run inside Playwright's event loop thread
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
    
    try:
        # Import your models here to avoid circular imports
        from bulk.models import WhatsAppCampaign, WhatsAppAccount, FriendlyNumber  # Replace with actual import
        
        campaign = WhatsAppCampaign.objects.get(id=campaign_id)
        
        # Get the WhatsApp account from database
        try:
            whatsapp_account = WhatsAppAccount.objects.get(id=account_id)
            selected_account_number = whatsapp_account.number
        except WhatsAppAccount.DoesNotExist:
            logger.error(f"WhatsApp account with ID {account_id} not found")
            if campaign_id in active_campaigns:
                active_campaigns[campaign_id]['status'] = 'Failed'
                active_campaigns[campaign_id]['error'] = f"WhatsApp account with ID {account_id} not found"
            return
        
        # whatsapp sessions path
        phone_numbers = [num.strip() for num in campaign.numbers.splitlines() if num.strip()]
        
        # --- INIT DB HISTORY ---
        campaign.status = 'Running'
        campaign.total_messages = len(phone_numbers)
        campaign.total_sent = 0
        campaign.total_failed = 0
        campaign.save()
        # -----------------------
        
        # Initialize statuses in memory so the frontend shows 'Pending'
        for number in phone_numbers:
            update_status(campaign_id, number, 'Pending')
            
        # Get AppData
        app_data = os.environ.get('APPDATA')
        if app_data:
            session_root = os.path.join(app_data, "WhatsApp Commune", "whatsapp_sessions")
        else:
            session_root = os.path.join(settings.BASE_DIR, "whatsapp_sessions")
            
        session_path = os.path.join(session_root, f"acct_{whatsapp_account.user.id}_{selected_account_number}")
        
        # Fetch friendly numbers for the account BEFORE entering async context
        friendly_numbers = []
        if getattr(campaign, 'friendly_numbers', False):
            friendly_numbers = list(FriendlyNumber.objects.filter(account_id=account_id, is_active=True).values_list('number', flat=True))
            logger.info(f"Loaded {len(friendly_numbers)} friendly numbers for interleaved sending.")
        else:
            logger.info("Friendly numbers injection disabled for this campaign.")
            
        # --- PRE-GENERATE AI SPINTAX TEMPLATES ---
        ai_template1 = campaign.message1
        ai_template2 = getattr(campaign, 'message2', None)

        # (AI Generation moved below browser launch)
        
        # Initialize next friendly target if enabled
        next_friendly_target = random.randint(5, 12) if friendly_numbers else -1
        messages_sent_since_friendly = 0

        # Launch Playwright browser with persistent session
        with sync_playwright() as p:
            try:
                browser = p.chromium.launch_persistent_context(
                    user_data_dir=str(session_path),
                    headless=False,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-web-security",
                        "--disable-features=VizDisplayCompositor"
                    ]
                )
                
                page = browser.new_page()
                
                # Store page in active_campaigns for potential reuse
                active_campaigns[campaign_id]['page'] = page
                active_campaigns[campaign_id]['browser'] = browser
                
                # Open WhatsApp Web (with automatic network retry protection)
                logger.info(" Opening WhatsApp Web...")
                goto_success = False
                for goto_attempt in range(3):
                    try:
                        page.goto("https://web.whatsapp.com", timeout=60000, wait_until="domcontentloaded")
                        goto_success = True
                        break
                    except Exception as goto_err:
                        logger.warning(f" Network hiccup during navigation (Attempt {goto_attempt+1}/3): {str(goto_err)}")
                        time.sleep(3.0)
                if not goto_success:
                    raise Exception("Failed to resolve web.whatsapp.com. Please check your internet/DNS connection.")
                
                # --- PRE-GENERATE AI SPINTAX TEMPLATES (In background while WA loads) ---
                if getattr(campaign, 'use_ai_spintax', False):
                    logger.info(" Generating AI Spintax templates while WhatsApp loads...")
                    ai_template1 = generate_ai_spintax_template(ai_template1)
                    if ai_template2 and ai_template2.strip():
                        ai_template2 = generate_ai_spintax_template(ai_template2.strip())
                # -----------------------------------------
                
                # Wait for WhatsApp to load
                logger.info(" Waiting for WhatsApp Web to fully load...")
                try:
                    # Wait for either QR code or chat list
                    page.wait_for_selector('div[data-testid="qr-code"], canvas[aria-label*="QR"], [data-testid="chat-list"]', timeout=120000)
                    
                    # Check if QR code is present (not logged in)
                    if page.query_selector('div[data-testid="qr-code"], canvas[aria-label*="QR"]'):
                        logger.warning(" QR Code detected - please scan to login")
                        # Wait for login
                        page.wait_for_selector('[data-testid="chat-list"]', timeout=300000)  # 5 minutes to login
                    
                except PlaywrightTimeoutError:
                    logger.error(" WhatsApp Web failed to load properly")
                    active_campaigns[campaign_id]['status'] = 'Failed'
                    active_campaigns[campaign_id]['error'] = 'WhatsApp Web failed to load'
                    campaign.status = 'Failed'
                    campaign.save(update_fields=['status'])
                    return
                
                logger.info(" WhatsApp Web loaded, starting campaign")
                time.sleep(2.0)
                
                # Get attachment path if exists
                attachment_path = getattr(campaign, 'attachment', None)
                if attachment_path and hasattr(attachment_path, 'path'):
                    attachment_path = attachment_path.path
                
                last_friendly_num = None
                
                # --- BATCH COOLING TRACKER ---
                batch_counter = 0
                user_break_interval = getattr(campaign, 'batch_break_interval', 20) or 20
                batch_limit = user_break_interval
                
                # Loop through each number
                for i, phone_number in enumerate(phone_numbers):
                    # --- BATCH COOL-DOWN BREAK CHECK ---
                    if batch_counter >= batch_limit:
                        user_break_mins = getattr(campaign, 'break_duration', 3) or 3
                        # Add slight human fuzz (+/- 20s) around user's break duration
                        fuzz_secs = random.uniform(-20, 20)
                        break_seconds = max(30, int(user_break_mins * 60 + fuzz_secs))
                        start_break = time.time()
                        
                        logger.info(f" [Anti-Ban] Reached batch break interval ({batch_limit} msgs). Cooling down for ~{user_break_mins} minutes ({break_seconds}s total)...")
                        
                        while True:
                            elapsed = time.time() - start_break
                            remaining_sec = max(0, int(break_seconds - elapsed))
                            if remaining_sec <= 0:
                                break
                                
                            if campaign_id not in active_campaigns or active_campaigns[campaign_id].get('stopped', False):
                                break
                                
                            rem_m = remaining_sec // 60
                            rem_s = remaining_sec % 60
                            status_str = f'Taking a Break ({rem_m}m {rem_s}s)' if rem_m > 0 else f'Taking a Break ({rem_s}s)'
                            
                            campaign.status = status_str
                            campaign.save(update_fields=['status'])
                            
                            # Sleep 2 seconds for live smooth updates
                            time.sleep(2)
                            if random.random() < 0.15:
                                execute_human_idle_action(page)
                                
                        batch_counter = 0
                        batch_limit = getattr(campaign, 'batch_break_interval', 20) or 20
                        campaign.status = 'Running'
                        campaign.save(update_fields=['status'])
                        logger.info(" [Anti-Ban] Cool-down finished. Resuming humanized campaign...")
                        
                    batch_counter += 1
                    # -----------------------------------

                    # Stop or pause checks
                    if campaign_id not in active_campaigns or active_campaigns[campaign_id].get('stopped', False):
                        campaign.status = 'Stopped'
                        campaign.save(update_fields=['status'])
                        break
                    
                    while active_campaigns[campaign_id].get('paused', False):
                        time.sleep(random.uniform(1.5, 3.5))
                        if active_campaigns[campaign_id].get('stopped', False):
                            break
                    
                    if active_campaigns[campaign_id].get('stopped', False):
                        campaign.status = 'Stopped'
                        campaign.save(update_fields=['status'])
                        break
                        
                    logger.info(f" Sending message to {phone_number} ({i+1}/{len(phone_numbers)})")
                    
                    # --- DUAL SPINTAX ORCHESTRATION ---
                    logger.info(f"[LOCAL] Expanding variation for recipient {phone_number}...")
                    
                    final_message = ai_template1
                    # Parse normal spintax (which now also handles AI-generated spintax options)
                    if getattr(campaign, 'use_normal_spintax', False) or getattr(campaign, 'use_ai_spintax', False):
                        final_message = parse_normal_spintax(final_message)
                        
                    final_message2 = None
                    if ai_template2 and ai_template2.strip():
                        final_message2 = ai_template2.strip()
                        if getattr(campaign, 'use_normal_spintax', False) or getattr(campaign, 'use_ai_spintax', False):
                            final_message2 = parse_normal_spintax(final_message2)
                    # ----------------------------------
                    
                    success = send_message_to_number(page, phone_number, final_message, campaign_id, attachment_path, getattr(campaign, 'send_as_caption', True), message2=final_message2)
                    
                    # --- UPDATE DB METRICS ---
                    if success:
                        campaign.total_sent += 1
                    else:
                        campaign.total_failed += 1
                    campaign.detailed_report = campaign_statuses.get(campaign_id, {})
                    campaign.save(update_fields=['total_sent', 'total_failed', 'detailed_report'])
                    # -------------------------
                    
                    # --- FRIENDLY NUMBER LOGIC ---
                    if friendly_numbers and next_friendly_target > 0:
                        messages_sent_since_friendly += 1
                        if messages_sent_since_friendly >= next_friendly_target:
                            available_friendly_numbers = [n for n in friendly_numbers if n != last_friendly_num]
                            if not available_friendly_numbers:
                                available_friendly_numbers = friendly_numbers
                                
                            friendly_num = random.choice(available_friendly_numbers)
                            last_friendly_num = friendly_num
                            
                            logger.info(f" [Friendly Number] Interleaving friendly message to {friendly_num} to keep account warm.")
                            try:
                                # Small pause before friendly message
                                time.sleep(random.uniform(2.0, 5.0))
                                
                                # Send friendly message (isolated from campaign metrics using -1 as campaign_id)
                                friendly_msg = random.choice([
                                    "Hey how are you?", "Checking in, all good?", 
                                    "Just testing my phone", "Hello!", 
                                    "Good morning", "Hope you're having a good day!"
                                ])
                                send_message_to_number(page, friendly_num, friendly_msg, -1, None, False)
                                
                                # Reset counters
                                messages_sent_since_friendly = 0
                                next_friendly_target = random.randint(5, 12)
                            except Exception as fe:
                                logger.warning(f" [Friendly Number] Failed to send to {friendly_num}: {fe}. Continuing normal campaign...")
                    # -----------------------------
                    
                    # Delay between messages using Gaussian bell-curve and wallpaper mouse drift
                    if i < len(phone_numbers) - 1:
                        human_delay = get_gaussian_delay(mean=12.0, stddev=3.0, min_delay=6.0, max_delay=20.0)
                        logger.info(f" [Anti-Ban] Waiting {human_delay:.1f}s (Gaussian bell-curve) before next message...")
                        time.sleep(human_delay / 2)
                        execute_human_idle_action(page)
                        time.sleep(human_delay / 2)
                
                # Mark campaign as completed if not stopped
                if campaign.status != 'Stopped':
                    active_campaigns[campaign_id]['status'] = 'Completed'
                    campaign.status = 'Completed'
                    campaign.detailed_report = campaign_statuses.get(campaign_id, {})
                    campaign.save(update_fields=['status', 'detailed_report'])
                    logger.info(f" Campaign {campaign_id} completed successfully")
                
            except Exception as e:
                logger.error(f"Browser error in campaign {campaign_id}: {str(e)}")
                raise
            finally:
                # Clean up browser
                try:
                    if 'page' in active_campaigns.get(campaign_id, {}):
                        active_campaigns[campaign_id]['page'].close()
                    if 'browser' in active_campaigns.get(campaign_id, {}):
                        active_campaigns[campaign_id]['browser'].close()
                except Exception as e:
                    logger.error(f"Error closing browser: {str(e)}")
                
    except Exception as e:
        error_msg = str(e)
        if "Call log:" in error_msg:
            error_msg = error_msg.split("Call log:")[0].strip()
        if "Target page, context or browser has been closed" in error_msg:
            error_msg = "WhatsApp Web was closed unexpectedly."
            
        logger.error(f"Campaign {campaign_id} failed: {error_msg}")
        if campaign_id in active_campaigns:
            active_campaigns[campaign_id]['status'] = 'Failed'
            active_campaigns[campaign_id]['error'] = error_msg
        # Update DB on fatal exception
        try:
            from bulk.models import WhatsAppCampaign
            c = WhatsAppCampaign.objects.get(id=campaign_id)
            c.status = 'Failed'
            c.detailed_report = campaign_statuses.get(campaign_id, {})
            c.save(update_fields=['status', 'detailed_report'])
        except:
            pass

@login_required
def start_messaging(request, campaign_id):
    """Start the WhatsApp campaign"""
    # Import your models here
    from bulk.models import WhatsAppCampaign  # Replace with actual import
    
    campaign = get_object_or_404(WhatsAppCampaign, id=campaign_id, user=request.user)
    
    account_id = request.GET.get('account_id')
    if not account_id:
        return JsonResponse({
            "success": False, 
            "message": "Account ID is required"
        }, status=400)
    
    # Check if campaign is already running
    if campaign_id in active_campaigns and active_campaigns[campaign_id]['status'] == 'Running':
        return JsonResponse({"success": False, "message": "Campaign is already running!"}, status=400)
    
    # Clean up any existing campaign
    if campaign_id in active_campaigns:
        try:
            if 'browser' in active_campaigns[campaign_id]:
                active_campaigns[campaign_id]['browser'].close()
        except Exception as e:
            logger.error(f"Error cleaning up existing campaign: {str(e)}")
        del active_campaigns[campaign_id]
    
    try:
        # Store campaign info
        active_campaigns[campaign_id] = {
            'status': 'Running',
            'paused': False,
            'stopped': False,
            'started_at': time.time()
        }
        
        # Synchronously initialize status storage so frontend doesn't falsely think it's completed on first poll
        campaign_statuses[campaign_id] = {}
        phone_numbers = [num.strip() for num in campaign.numbers.splitlines() if num.strip()]
        for number in phone_numbers:
            update_status(campaign_id, number, 'Pending')
        
        # Start background thread
        thread = threading.Thread(
            target=process_campaign_background,
            args=(campaign_id, account_id),
            daemon=True
        )
        thread.start()
        
        return JsonResponse({
            "success": True, 
            "message": "Campaign started successfully!"
        })
        
    except Exception as e:
        logger.error(f"Failed to start campaign {campaign_id}: {str(e)}")
        return JsonResponse({
            "success": False, 
            "message": f"Failed to start campaign: {str(e)}"
        }, status=500)

@login_required
def campaign_status(request, campaign_id):
    """Get real-time status of the campaign"""
    # Import your models here
    from bulk.models import WhatsAppCampaign  # Replace with actual import
    
    campaign = get_object_or_404(WhatsAppCampaign, id=campaign_id, user=request.user)
    
    # Get statuses from memory
    statuses = campaign_statuses.get(campaign_id, {})
    
    # Convert to the format expected by frontend
    formatted_statuses = {}
    counts = {'Pending': 0, 'Processing': 0, 'Sent': 0, 'Failed': 0, 'Invalid': 0}
    
    for phone, data in statuses.items():
        status = data.get('status', 'Pending')
        
        timestamp_str = "-"
        if 'timestamp' in data and data['timestamp']:
            import datetime
            timestamp_str = datetime.datetime.fromtimestamp(data['timestamp']).strftime("%I:%M:%S %p")
            
        formatted_statuses[phone] = {
            'status': status,
            'timestamp': timestamp_str
        }
        counts[status] = counts.get(status, 0) + 1
    
    # Determine overall status
    campaign_info = active_campaigns.get(campaign_id, {})
    if campaign_info.get('paused', False):
        overall_status = "Paused"
    elif campaign_info.get('stopped', False):
        overall_status = "Stopped"
    elif campaign.status and ("Taking a Break" in campaign.status or "Cooling" in campaign.status or "Break" in campaign.status):
        overall_status = campaign.status
    elif campaign_info.get('status') == 'Running':
        if counts['Processing'] > 0:
            overall_status = "Running"
        elif counts['Pending'] == 0 and counts['Processing'] == 0:
            overall_status = "Completed"
        else:
            overall_status = "Running"
    elif campaign_info.get('status') == 'Completed':
        overall_status = "Completed"
    elif campaign_info.get('status') == 'Failed':
        overall_status = "Failed"
    else:
        overall_status = campaign.status if campaign.status else "Not Started"
    
    return JsonResponse({
        "overall_status": overall_status,
        "statuses": formatted_statuses,
        "counts": counts,
        "error": campaign_info.get('error', None)
    })

@login_required
def pause_campaign(request, campaign_id):
    """Pause the running campaign"""
    from bulk.models import WhatsAppCampaign
    if campaign_id in active_campaigns:
        active_campaigns[campaign_id]['paused'] = True
    try:
        c = WhatsAppCampaign.objects.get(id=campaign_id, user=request.user)
        c.status = 'Paused'
        c.save(update_fields=['status'])
    except Exception:
        pass
    return JsonResponse({"success": True, "message": "Campaign paused"})

@login_required
def resume_campaign(request, campaign_id):
    """Resume the paused campaign"""
    from bulk.models import WhatsAppCampaign
    if campaign_id in active_campaigns:
        active_campaigns[campaign_id]['paused'] = False
    try:
        c = WhatsAppCampaign.objects.get(id=campaign_id, user=request.user)
        c.status = 'Running'
        c.save(update_fields=['status'])
    except Exception:
        pass
    return JsonResponse({"success": True, "message": "Campaign resumed"})

@login_required
def stop_campaign(request, campaign_id):
    """Stop the running campaign"""
    from bulk.models import WhatsAppCampaign
    if campaign_id in active_campaigns:
        active_campaigns[campaign_id]['stopped'] = True
        active_campaigns[campaign_id]['status'] = 'Stopped'
        
        # Cleanup browser
        try:
            if 'browser' in active_campaigns[campaign_id]:
                active_campaigns[campaign_id]['browser'].close()
        except Exception as e:
            logger.error(f"Error closing browser during stop: {str(e)}")
        
        # Remove from active campaigns
        del active_campaigns[campaign_id]

    try:
        c = WhatsAppCampaign.objects.get(id=campaign_id, user=request.user)
        c.status = 'Stopped'
        c.save(update_fields=['status'])
    except Exception:
        pass
        
    return JsonResponse({"success": True, "message": "Campaign stopped"})

@login_required
def relaunch_campaign(request, campaign_id):
    """Duplicates a past campaign and opens its deploy page for immediate re-sending."""
    from bulk.models import WhatsAppCampaign
    old_campaign = get_object_or_404(WhatsAppCampaign, id=campaign_id, user=request.user)
    
    # Create cloned campaign instance
    new_campaign = WhatsAppCampaign.objects.create(
        user=request.user,
        name=f"Resend: {old_campaign.name}" if not old_campaign.name.startswith("Resend:") else old_campaign.name,
        message1=old_campaign.message1,
        message2=old_campaign.message2,
        numbers=old_campaign.numbers,
        country_code=old_campaign.country_code,
        attachment=old_campaign.attachment,
        whatsapp_account=old_campaign.whatsapp_account,
        delay=old_campaign.delay,
        batch_break_interval=getattr(old_campaign, 'batch_break_interval', 15) or 15,
        break_duration=getattr(old_campaign, 'break_duration', 3) or 3,
        friendly_numbers=old_campaign.friendly_numbers,
        send_as_caption=old_campaign.send_as_caption,
        use_normal_spintax=old_campaign.use_normal_spintax,
        use_ai_spintax=old_campaign.use_ai_spintax,
        status='Pending'
    )
    
    messages.success(request, f"Campaign cloned! Ready to resend '{new_campaign.name}'.")
    return redirect('deploy_campaign', campaign_id=new_campaign.id)

def check_session_validity(session_path):
    """Check if WhatsApp session is valid and contains necessary data"""
    try:
        # Check for Local Storage data
        local_storage_path = os.path.join(session_path, "Default", "Local Storage", "leveldb")
        if not os.path.exists(local_storage_path):
            return False
            
        # Check for Session Storage
        session_storage_path = os.path.join(session_path, "Default", "Session Storage")
        if not os.path.exists(session_storage_path):
            return False
            
        # Check for Cookies
        cookies_path = os.path.join(session_path, "Default", "Cookies")
        if not os.path.exists(cookies_path):
            return False
            
        # Check if Local Storage has WhatsApp-specific data
        try:
            # Look for WhatsApp Web specific files that indicate an active session
            ls_files = os.listdir(local_storage_path)
            has_whatsapp_data = any("whatsapp" in f.lower() for f in ls_files)
            
            # Also check file sizes - empty session would have very small files
            total_size = sum(os.path.getsize(os.path.join(local_storage_path, f)) 
                           for f in ls_files if os.path.isfile(os.path.join(local_storage_path, f)))
            
            return has_whatsapp_data and total_size > 1000  # At least 1KB of data
        except Exception as e:
            logger.error(f"Error checking WhatsApp data: {str(e)}")
            return False
            
    except Exception as e:
        logger.error(f"Session validation error: {str(e)}")
        return False


def settings_view(request):
    from bulk.models import AppSetting
    
    if request.method == 'POST':
        gemini_key = request.POST.get('gemini_api_key', '').strip()
        
        # Save or update the key
        setting, created = AppSetting.objects.get_or_create(key='GEMINI_API_KEY')
        setting.value = gemini_key
        setting.save()

        if request.headers.get('x-requested-with') == 'XMLHttpRequest':
            return JsonResponse({"success": True, "has_key": bool(gemini_key)})

        messages.success(request, "Gemini API Key saved successfully.")
        return redirect('settings_view')

    # Fetch the existing key to pre-fill the form (if it exists)
    try:
        gemini_api_key = AppSetting.objects.get(key='GEMINI_API_KEY').value
    except AppSetting.DoesNotExist:
        gemini_api_key = ""

    return render(request, 'settings.html', {'gemini_api_key': gemini_api_key})


@login_required
def add_account(request):
    if request.method == "POST":
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

        form = WhatsAppAccountForm(request.POST, request.FILES)
        if form.is_valid():
            account = form.save(commit=False)
            
            #  Prevent a single user from adding the exact same number twice
            # (Different users CAN share a number because they get different folders)
            if WhatsAppAccount.objects.filter(user=request.user, number=account.number).exists():
                if is_ajax:
                    return JsonResponse({
                        "success": False,
                        "message": "You have already added this WhatsApp number to your dashboard."
                    })
                messages.error(request, "You have already added this WhatsApp number.")
                return redirect("add_account")
                
            account.user = request.user
            account.save()

            #  Make this account default
            WhatsAppAccount.objects.filter(user=request.user).exclude(id=account.id).update(is_default=False)
            account.is_default = True
            account.save()

            #  Create session folder
            app_data = os.environ.get('APPDATA')
            if app_data:
                session_root = os.path.join(app_data, "WhatsApp Commune", "whatsapp_sessions")
            else:
                session_root = os.path.join(settings.BASE_DIR, "whatsapp_sessions")
                
            os.makedirs(session_root, exist_ok=True)
            session_path = os.path.join(session_root, f"acct_{request.user.id}_{account.number}")
            os.makedirs(session_path, exist_ok=True)

            #  Store session path but dont run Selenium immediately
            account.session_path = session_path
            account.is_active = False
            account.save()

            if is_ajax:
                return JsonResponse({
                    "success": True,
                    "message": "Account saved successfully. Now initiate QR scan.",
                    "account_id": account.id
                })
            else:
                messages.success(request, f"Account {account.name} saved. Now initiate QR scan.")
                return redirect("add_account")

        else:
            print("FORM ERRORS:", form.errors)
            if is_ajax:
                # Extract first error as a clean string to bypass frontend cache issues
                try:
                    error_dict = form.errors.get_json_data()
                    first_field = list(error_dict.keys())[0]
                    first_error_msg = error_dict[first_field][0]['message']
                    error_msg = f"{first_field.capitalize()}: {first_error_msg}"
                except:
                    error_msg = "Form validation failed (check fields)"

                return JsonResponse({
                    "success": False,
                    "message": error_msg,
                    "errors": form.errors.as_json()
                })
            messages.error(request, f"Form validation failed: {form.errors}")
            return redirect("add_account")

    # GET request  return empty form
    form = WhatsAppAccountForm()
    return render(request, "addaccount.html", {"form": form})




 



# @csrf_exempt  
# def add_account_and_scan_qr(request):
#     if request.method == 'POST':
#         form = WhatsAppAccountForm(request.POST)
#         if form.is_valid():
#             account = form.save(commit=False)
#             account.user = request.user
#             account.save()

           
#             WhatsAppAccount.objects.filter(user=request.user).exclude(id=account.id).update(is_default=False)
#             account.is_default = True
#             account.save()

#             try:
#                 profile_dir = os.path.join(settings.BASE_DIR, 'sessions', f'session_{account.id}')
#                 os.makedirs(profile_dir, exist_ok=True)

#                 chrome_options = Options()
#                 chrome_options.add_argument(f"--user-data-dir={profile_dir}")
#                 chrome_options.add_argument("--profile-directory=Default")
#                 chrome_options.add_argument("--start-maximized")

#                 driver = webdriver.Chrome(options=chrome_options)
#                 driver.get("https://web.whatsapp.com")
#                 time.sleep(random.uniform(16.0, 30.0))
#                 driver.quit()

#                 return JsonResponse({'success': True, 'message': 'Account added and QR scanned', 'account_id': account.id})
#             except Exception as e:
#                 return JsonResponse({'success': False, 'message': f'Selenium error: {str(e)}'})
#         else:
#             return JsonResponse({'success': False, 'message': 'Form error', 'errors': form.errors})
#     return JsonResponse({'success': False, 'message': 'Invalid request'})

def login_view(request):
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)

        if user is not None:
            login(request, user)
            return redirect('index')  
        else:
            messages.error(request, 'Invalid username or password')
    return render(request, 'login.html')

@login_required
def delete_account(request, account_id):
    account = get_object_or_404(WhatsAppAccount, id=account_id, user=request.user)
    
    print(f"About to delete account: {account.id}")
    
    try:
        account.delete()
        print(f"Delete successful for account: {account_id}")
        
        remaining = WhatsAppAccount.objects.filter(id=account_id).exists()
        print(f"Account still exists: {remaining}")
        
    except Exception as e:
        print(f"Delete failed: {e}")
        messages.error(request, f"Failed to delete account: {e}")
        return redirect('index')
    
    messages.success(request, "Account deleted successfully.")
    return redirect('index')

def deploy(request, campaign_id):
    campaign = get_object_or_404(WhatsAppCampaign, id=campaign_id, user=request.user)
    account = WhatsAppAccount.objects.filter(user=request.user, is_default=True).first()
    
    return render(request, 'deploy.html', {
        'campaign': campaign,
        'account': account,
    })

@login_required
def deploy_campaign(request, campaign_id):
    campaign = get_object_or_404(WhatsAppCampaign, id=campaign_id, user=request.user)
    account = WhatsAppAccount.objects.filter(user=request.user, is_default=True).first()

    if request.method == 'POST':
        return redirect('start_messaging', campaign_id=campaign.id)

    return render(request, 'deploy.html', {
        'campaign': campaign,
        'account': account,
    })

@login_required
def deploy_latest(request):
    campaign = WhatsAppCampaign.objects.filter(user=request.user).order_by('-id').first()
    if campaign:
        return redirect('deploy', campaign_id=campaign.id)  
    else:
        messages.error(request, "No campaign available.")
        return redirect('index')

# --- FRIENDLY NUMBERS API ---

@login_required
def get_friendly_numbers(request):
    try:
        account = WhatsAppAccount.objects.filter(user=request.user, is_default=True).first() or WhatsAppAccount.objects.filter(user=request.user).first()
        if not account:
            return JsonResponse({"error": "No active WhatsApp account found"}, status=400)
        
        numbers = FriendlyNumber.objects.filter(account=account).order_by('-created_at')
        data = [{
            "id": n.id,
            "number": n.number,
            "name": n.name,
            "is_active": n.is_active
        } for n in numbers]
        
        return JsonResponse({"success": True, "numbers": data})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)

@login_required
def save_friendly_numbers(request):
    try:
        if request.method != 'POST':
            return JsonResponse({"error": "Invalid method"}, status=405)
            
        account = WhatsAppAccount.objects.filter(user=request.user, is_default=True).first() or WhatsAppAccount.objects.filter(user=request.user).first()
        if not account:
            return JsonResponse({"error": "No active WhatsApp account found"}, status=400)
            
        manual_numbers = request.POST.get('manual_numbers', '')
        excel_file = request.FILES.get('excel_file')
        
        added = 0
        duplicates = 0
        invalid = 0
        
        import pandas as pd
        import json
        from django.db import IntegrityError
        
        def process_number(raw_num, name=""):
            nonlocal added, duplicates, invalid
            if not raw_num: return
            
            clean_num = str(raw_num).strip()
            if not clean_num: return
            
            # Remove pandas .0 float artifact
            if clean_num.endswith('.0'):
                clean_num = clean_num[:-2]
                
            # Validation using digits count
            digits_only = ''.join(filter(str.isdigit, clean_num))
            if len(digits_only) >= 7 and clean_num.lower() != 'nan':
                try:
                    FriendlyNumber.objects.create(
                        account=account,
                        number=clean_num,
                        name=str(name).strip() if pd.notna(name) else ""
                    )
                    added += 1
                except IntegrityError:
                    duplicates += 1
            else:
                invalid += 1

        # Process Manual
        if manual_numbers:
            for num in manual_numbers.split(","):
                process_number(num)
                
        # Process File
        if excel_file:
            try:
                file_ext = os.path.splitext(excel_file.name)[1].lower()
                if file_ext == '.csv':
                    df = pd.read_csv(excel_file, dtype=str)
                elif file_ext == '.xlsx':
                    df = pd.read_excel(excel_file, dtype=str)
                else:
                    return JsonResponse({"error": "Invalid file format. Use .csv or .xlsx"}, status=400)
                    
                if df.empty and len(df.columns) > 0:
                    header_data = df.columns.tolist()
                    process_number(header_data[0], header_data[1] if len(header_data) > 1 else "")
                elif not df.empty:
                    for _, row in df.iterrows():
                        if len(df.columns) > 0:
                            process_number(row.iloc[0], row.iloc[1] if len(df.columns) > 1 else "")
            except Exception as e:
                return JsonResponse({"error": f"Error parsing file: {str(e)}"}, status=400)
                
        return JsonResponse({
            "success": True,
            "added": added,
            "duplicates": duplicates,
            "invalid": invalid
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({"error": str(e)}, status=500)

@login_required
def toggle_friendly_number(request, number_id):
    if request.method != 'POST':
        return JsonResponse({"error": "Invalid method"}, status=405)
        
    num = get_object_or_404(FriendlyNumber, id=number_id, account__user=request.user)
    num.is_active = not num.is_active
    num.save()
    
    return JsonResponse({"success": True, "is_active": num.is_active})

@login_required
def delete_friendly_number(request, number_id):
    if request.method != 'POST':
        return JsonResponse({"error": "Invalid method"}, status=405)
        
    num = get_object_or_404(FriendlyNumber, id=number_id, account__user=request.user)
    num.delete()
    
    return JsonResponse({"success": True})

@login_required
def campaign_history(request):
    """View to display the history of all past campaigns"""
    from bulk.models import WhatsAppCampaign
    from django.core.paginator import Paginator
    
    # Sorting logic
    sort_order = request.GET.get('sort', 'newest')
    if sort_order == 'oldest':
        campaigns_query = WhatsAppCampaign.objects.filter(user=request.user).defer('numbers').order_by('created_at')
    else:
        campaigns_query = WhatsAppCampaign.objects.filter(user=request.user).defer('numbers').order_by('-created_at')
        
    # Pagination
    paginator = Paginator(campaigns_query, 10)
    page_number = request.GET.get('page')
    campaigns = paginator.get_page(page_number)
    
    return render(request, "history.html", {
        "campaigns": campaigns,
        "sort_order": sort_order
    })

@login_required
def view_campaign(request, campaign_id):
    """API view to fetch campaign details for the view modal"""
    from bulk.models import WhatsAppCampaign
    campaign = get_object_or_404(WhatsAppCampaign, id=campaign_id, user=request.user)
    
    return JsonResponse({
        "success": True,
        "name": campaign.name,
        "created_at": campaign.created_at.strftime("%b %d, %Y %I:%M %p"),
        "account": campaign.whatsapp_account.number if campaign.whatsapp_account else "Deleted Account",
        "message1": campaign.message1,
        "message2": campaign.message2,
        "delay": campaign.delay,
        "numbers": campaign.numbers,
        "safe_mode": campaign.safe_mode,
        "deduplicate": campaign.deduplicate,
        "use_ai_spintax": getattr(campaign, 'use_ai_spintax', False),
        "use_normal_spintax": getattr(campaign, 'use_normal_spintax', False),
        "friendly_numbers": getattr(campaign, 'friendly_numbers', False)
    })


@login_required
def download_campaign_report(request, campaign_id):
    """Generate and download a detailed CSV report of the campaign's success/failures."""
    from bulk.models import WhatsAppCampaign
    from django.shortcuts import get_object_or_404
    import datetime
    import csv
    
    campaign = get_object_or_404(WhatsAppCampaign, id=campaign_id, user=request.user)
    
    # Create the HTTP response with CSV headers
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="campaign_{campaign_id}_report.csv"'
    
    writer = csv.writer(response)
    writer.writerow(['Phone Number', 'Status', 'Exact Error Reason', 'Timestamp'])
    
    # Try database detailed_report first, then in-memory campaign_statuses
    detailed_report = campaign.detailed_report or {}
    if not detailed_report and campaign_id in campaign_statuses:
        detailed_report = campaign_statuses[campaign_id]
        
    if not detailed_report:
        # Fallback for older campaigns: export recipient numbers list
        phone_numbers = [num.strip() for num in campaign.numbers.splitlines() if num.strip()]
        for phone in phone_numbers:
            writer.writerow([phone, 'Completed' if campaign.status == 'Completed' else campaign.status, 'No detailed logs saved for older campaign', '-'])
        return response
        
    for phone, info in detailed_report.items():
        if isinstance(info, dict):
            status = info.get('status', 'Unknown')
            error = info.get('error', '')
            timestamp_val = info.get('timestamp')
        else:
            status = str(info)
            error = ''
            timestamp_val = None
            
        time_str = "-"
        if timestamp_val:
            try:
                time_str = datetime.datetime.fromtimestamp(float(timestamp_val)).strftime("%Y-%m-%d %I:%M:%S %p")
            except Exception:
                time_str = str(timestamp_val)
            
        writer.writerow([phone, status, error, time_str])
        
    return response

