import os
import time
import phonenumbers
import random
import psutil
import shutil 
import logging
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
from .models import WhatsAppCampaign, WhatsAppAccount
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

def signup_view(request):
    if request.method == 'POST':
        form = UserCreationForm(request.POST)  
        if form.is_valid(): 
            form.save()     
            messages.success(request, "Account created successfully!")
            return redirect('login') 
    else:
        form = UserCreationForm()  

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
            print(f"📁 Using user data dir: {user_data_dir}")
        
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
        print(f"❌ Failed to create WebDriver: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def index(request):
    if request.user.is_authenticated:
        accounts = WhatsAppAccount.objects.filter(user=request.user)
        has_campaigns = WhatsAppCampaign.objects.filter(user=request.user).exists()
    else:
        accounts = WhatsAppAccount.objects.none()
        has_campaigns = False

    return render(request, 'index.html', {
        'accounts': accounts,
        'has_campaigns': has_campaigns
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
                            time.sleep(5)  # Wait 5 seconds before checking again
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
        campaign_name = request.POST.get('campaign_name')
        selected_accounts = request.POST.getlist('selected_accounts')
        message_1 = request.POST.get('message_1')
        message_2 = request.POST.get('message_2')
        excel_file = request.FILES.get('excel_file')
        attachment = request.FILES.get('attachment')  # ✅ ADD: Get attachment file
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

        # Handle schedule time
        if schedule_time_raw:
            try:
                schedule_time = datetime.strptime(schedule_time_raw, "%Y-%m-%dT%H:%M")
            except ValueError:
                schedule_time = None
        else:
            schedule_time = None

        print("🔍 DEBUG - Starting number processing...")
        print(f"🔍 Manual numbers input: {repr(manual_numbers)}")
        print(f"🔍 Excel file: {excel_file.name if excel_file else 'None'}")
        print(f"🔍 Attachment file: {attachment.name if attachment else 'None'}")  # ✅ ADD: Debug attachment

        # ✅ Handle manual numbers
        if manual_numbers:
            print("🔍 Processing manual numbers...")
            for idx, num in enumerate(manual_numbers.split(","), start=1):
                clean_num = num.strip()
                if clean_num:
                    # Validate manual number
                    digits_only = ''.join(filter(str.isdigit, clean_num))
                    if len(digits_only) >= 7:
                        all_numbers.append(clean_num)
                        numbers_list.append({
                            "sl": idx,
                            "number": clean_num,
                            "name": "-"
                        })
                        print(f"✅ Added manual number: {clean_num}")
                    else:
                        print(f"⚠️ Skipped invalid manual number: {clean_num}")
            print(f"🔍 Manual numbers processed: {len(all_numbers)}")
        else:
            print("🔍 No manual numbers provided")

        # ✅ Handle Excel numbers
        if excel_file:
            print(f"🔍 Excel file received: {excel_file.name}")
            print(f"🔍 Excel file size: {excel_file.size}")
            print(f"🔍 Excel file content type: {excel_file.content_type}")
            
            try:
                # Read the Excel file
                df = pd.read_excel(excel_file)
                print(f"🔍 Excel shape: {df.shape}")
                print(f"🔍 Excel columns: {df.columns.tolist()}")
                print(f"🔍 Excel dtypes: {df.dtypes.tolist()}")
                print(f"🔍 Raw DataFrame:")
                print(df)
                
                # ✅ Check if DataFrame is empty but has columns (headers as data)
                if df.empty and len(df.columns) > 0:
                    print("🔍 Empty DataFrame but has columns - treating headers as data")
                    # Convert column headers to a row
                    header_data = df.columns.tolist()
                    print(f"🔍 Header data: {header_data}")
                    
                    # Process the header data as if it's the first row
                    if len(header_data) > 0:
                        number_value = header_data[0]
                        print(f"🔍 Processing header as number: {number_value} (type: {type(number_value)})")
                        
                        if number_value is not None:
                            clean_num = str(number_value).strip()
                            print(f"🔍 Clean number from header: '{clean_num}'")
                            
                            # Remove .0 if present
                            if clean_num.endswith('.0'):
                                clean_num = clean_num[:-2]
                                print(f"🔍 After removing .0: '{clean_num}'")
                            
                            # Validate
                            digits_only = ''.join(filter(str.isdigit, clean_num))
                            print(f"🔍 Digits only: '{digits_only}' (length: {len(digits_only)})")
                            
                            if len(digits_only) >= 7:
                                all_numbers.append(clean_num)
                                numbers_list.append({
                                    "sl": len(numbers_list) + 1,
                                    "number": clean_num,
                                    "name": header_data[1] if len(header_data) > 1 else "-"
                                })
                                print(f"✅ Added valid number from header: {clean_num}")
                            else:
                                print(f"⚠️ Invalid number in header: '{clean_num}'")
                
                elif not df.empty:
                    # Normal processing for properly formatted Excel
                    print("🔍 Processing normal Excel data...")
                    excel_count = 0
                    
                    for idx, row in df.iterrows():
                        print(f"🔍 Processing row {idx}: {row.values}")
                        
                        if len(df.columns) > 0:
                            number_value = row.iloc[0]
                            print(f"🔍 First column value: {number_value} (type: {type(number_value)})")
                            
                            if pd.notna(number_value):
                                clean_num = str(number_value).strip()
                                print(f"🔍 Clean number: '{clean_num}'")
                                
                                if clean_num.endswith('.0'):
                                    clean_num = clean_num[:-2]
                                    print(f"🔍 After removing .0: '{clean_num}'")
                                
                                digits_only = ''.join(filter(str.isdigit, clean_num))
                                print(f"🔍 Digits only: '{digits_only}' (length: {len(digits_only)})")
                                
                                if len(digits_only) >= 7 and clean_num.lower() != 'nan':
                                    all_numbers.append(clean_num)
                                    excel_count += 1
                                    numbers_list.append({
                                        "sl": len(numbers_list) + 1,
                                        "number": clean_num,
                                        "name": str(row.iloc[1]) if len(df.columns) > 1 and pd.notna(row.iloc[1]) else "-"
                                    })
                                    print(f"✅ Added valid Excel number: {clean_num}")
                                else:
                                    print(f"⚠️ Skipped invalid Excel entry: '{clean_num}'")
                            else:
                                print(f"⚠️ NaN value in row {idx}")
                else:
                    print("⚠️ Excel file is completely empty!")
                    
                print(f"🔍 Total Excel numbers processed: {len([n for n in all_numbers if n])}")
                
            except Exception as e:
                print(f"❌ Error reading Excel: {e}")
                import traceback
                traceback.print_exc()
        else:
            print("🔍 No Excel file uploaded")

        print(f"🔍 Total valid numbers collected: {len(all_numbers)}")
        print(f"🔍 All numbers before deduplication: {all_numbers}")

        # ✅ Remove duplicates if enabled
        if deduplicate:
            original_count = len(all_numbers)
            all_numbers = list(dict.fromkeys(all_numbers))  # Preserve order
            print(f"🔍 After deduplication: {len(all_numbers)} (removed {original_count - len(all_numbers)})")

        # ✅ Convert to string for database storage
        combined_numbers = "\n".join(all_numbers)
        print(f"🔍 Combined numbers for database: {repr(combined_numbers)}")
        print(f"🔍 Combined numbers length: {len(combined_numbers)}")

        # ✅ Save campaign WITH ATTACHMENT
        try:
            campaign = WhatsAppCampaign.objects.create(
                name=campaign_name,
                message1=message_1,
                message2=message_2,
                excel_file=excel_file,
                attachment=attachment,  # ✅ ADD: Save attachment
                numbers=combined_numbers,  # All numbers (manual + Excel)
                country_code=country_code or '+91',  # Default country code
                whatsapp_group=whatsapp_group if whatsapp_group else None,
                deduplicate=deduplicate,
                safe_mode=safe_mode,
                unsafe_mode=unsafe_mode,
                swipe_after=int(swipe_after) if swipe_after else 2,
                delay=int(delay) if delay else 5,
                schedule_time=schedule_time,
                friendly_numbers=friendly_numbers,
                user=request.user
            )

            # 🔍 DEBUG: Check what was actually saved
            print(f"🔍 Campaign created with ID: {campaign.id}")
            print(f"🔍 Campaign name saved: {campaign.name}")
            print(f"🔍 Numbers saved to DB: {repr(campaign.numbers)}")
            print(f"🔍 Numbers length in DB: {len(campaign.numbers) if campaign.numbers else 0}")
            print(f"🔍 Attachment saved: {campaign.attachment.name if campaign.attachment else 'None'}")  # ✅ ADD: Debug attachment

            # 🔍 Re-fetch from database to double-check
            saved_campaign = WhatsAppCampaign.objects.get(id=campaign.id)
            print(f"🔍 Re-fetched from DB - numbers: {repr(saved_campaign.numbers)}")
            print(f"🔍 Re-fetched from DB - numbers length: {len(saved_campaign.numbers) if saved_campaign.numbers else 0}")
            print(f"🔍 Re-fetched from DB - attachment: {saved_campaign.attachment.name if saved_campaign.attachment else 'None'}")  # ✅ ADD: Debug attachment

        except Exception as e:
            print(f"❌ Error saving campaign: {e}")
            import traceback
            traceback.print_exc()
            return render(request, 'index.html', {
                'error': f'Error saving campaign: {e}',
                'accounts': WhatsAppAccount.objects.filter(user=request.user),
                'numbers_list': numbers_list
            })

        print(f"🔍 Campaign {campaign.id} saved with {len(all_numbers)} numbers")

        # ✅ Assign WhatsApp account
        if selected_accounts:
            try:
                account = WhatsAppAccount.objects.filter(
                    id__in=selected_accounts, user=request.user
                ).first()
                if account:
                    campaign.whatsapp_account = account
                    campaign.save()
                    print(f"🔍 Assigned WhatsApp account: {account.number}")
                else:
                    print("⚠️ No valid WhatsApp account found")
            except Exception as e:
                print(f"❌ Error assigning WhatsApp account: {e}")

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
    messages.success(request, "🗑️ Campaign deleted successfully.")
    return redirect('index')  

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
    
    logger.info("🚀 Starting WhatsApp campaign with Chrome")
    
    # Debug attachment path
    if attachment_path:
        if os.path.exists(attachment_path):
            logger.info(f"📎 Attachment found: {attachment_path}")
        else:
            logger.warning(f"⚠️ Attachment path not found: {attachment_path}")
            attachment_path = None
    else:
        logger.info("📝 No attachment for this campaign")
    
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
            
            logger.info(f"🌐 Navigating to WhatsApp Web with Chrome...")
            page.goto("https://web.whatsapp.com", wait_until='networkidle')
            
            # Enhanced session validation
            session_valid = validate_whatsapp_session(page, whatsapp_account)
            
            if not session_valid:
                return {"success": False, "error": "session_expired"}
            
            logger.info("✅ Session validated, starting message sending")
            
            success_count = 0
            failed_count = 0
            
            # Process each number
            for i, phone_number in enumerate(valid_numbers, 1):
                try:
                    # Check for stop/pause signals
                    if campaign_id in active_campaigns:
                        if active_campaigns[campaign_id].get('stopped', False):
                            logger.info("🛑 Campaign stopped by user")
                            break
                        
                        while active_campaigns[campaign_id].get('paused', False):
                            time.sleep(2)
                            if active_campaigns[campaign_id].get('stopped', False):
                                break
                    
                    logger.info(f"📱 Processing {phone_number} ({i}/{len(valid_numbers)})")
                    update_status(campaign_id, phone_number, 'Processing')
                    
                    # Send first message with attachment
                    if message1 and message1.strip():
                        success = send_message_to_number(page, phone_number, message1, campaign_id, attachment_path)
                        if success:
                            success_count += 1
                            update_status(campaign_id, phone_number, 'Sent')
                            
                            # Send second message if provided (without attachment)
                            if message2 and message2.strip():
                                time.sleep(2)  # Brief pause between messages
                                success2 = send_message_to_number(page, phone_number, message2, campaign_id, None)
                                if not success2:
                                    logger.warning(f"⚠️ Second message failed for {phone_number}")
                        else:
                            failed_count += 1
                            update_status(campaign_id, phone_number, 'Failed')
                    
                    # Delay between contacts
                    if i < len(valid_numbers):
                        delay = getattr(campaign, 'delay', 8) or 8
                        delay = max(delay, 5)  # Minimum 5 seconds
                        logger.info(f"⏸️ Waiting {delay} seconds...")
                        time.sleep(delay)
                
                except Exception as e:
                    logger.error(f"❌ Error processing {phone_number}: {e}")
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
            
            logger.info(f"📊 Campaign completed - Success: {success_count}, Failed: {failed_count}")
            return result
            
        except Exception as e:
            logger.error(f"❌ Campaign error: {e}")
            
            return {"success": False, "error": str(e)}
            
        finally:
            if browser:
                try:
                    browser.close()
                    logger.info("🔄 Chrome browser closed")
                except Exception as e:
                    logger.warning(f"⚠️ Error closing browser: {e}")



def validate_whatsapp_session(page, whatsapp_account, timeout=60):
    """Enhanced session validation with better detection"""
    try:
        logger.info("🔍 Validating WhatsApp session...")
        time.sleep(5)  # Allow initial page load
        
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
                    logger.error("❌ QR code detected - session expired")
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
                    logger.info("✅ WhatsApp session is valid")
                    if whatsapp_account:
                        whatsapp_account.is_active = True
                        whatsapp_account.save()
                    return True
                
                # Wait and retry
                time.sleep(2)
                
            except Exception as e:
                logger.warning(f"⚠️ Session validation error: {e}")
                time.sleep(2)
        
        logger.error("❌ Session validation timeout")
        return False
        
    except Exception as e:
        logger.error(f"❌ Session validation failed: {e}")
        return False


def send_attachment(page, attachment_path):
    """Send attachment with improved reliability"""
    try:
        print(f"DEBUG: Trying to send attachment: {attachment_path}")
        
        # Look for attachment button
        attachment_button_selectors = [
            '[data-testid="clip"]',
            '[data-icon="clip"]',
            'button[aria-label*="Attach" i]'
        ]
        
        button_found = False
        for selector in attachment_button_selectors:
            try:
                button = page.locator(selector).first
                if button.is_visible():
                    print(f"DEBUG: Found attachment button: {selector}")
                    button.click()
                    time.sleep(1)
                    button_found = True
                    break
            except Exception as e:
                print(f"DEBUG: Button {selector} failed: {str(e)}")
                continue
        
        if not button_found:
            print("DEBUG: No attachment button found")
            return False
        
        # Upload file
        try:
            file_input = page.locator('input[type="file"]').first
            print("DEBUG: Found file input, uploading...")
            file_input.set_input_files(attachment_path)
            print("DEBUG: File uploaded")
        except Exception as e:
            print(f"DEBUG: File upload failed: {str(e)}")
            return False
        
        # Wait for file to process
        time.sleep(3)
        
        # Send attachment
        send_button_selectors = [
            '[data-testid="send"]',
            '[data-icon="send"]',
            'button[aria-label*="Send" i]'
        ]
        
        for selector in send_button_selectors:
            try:
                send_btn = page.locator(selector).first
                if send_btn.is_visible():
                    print(f"DEBUG: Found send button: {selector}")
                    send_btn.click()
                    time.sleep(2)
                    print("DEBUG: Attachment sent successfully!")
                    return True
            except Exception as e:
                print(f"DEBUG: Send button {selector} failed: {str(e)}")
                continue
        
        print("DEBUG: No send button found")
        return False
        
    except Exception as e:
        print(f"DEBUG: Overall error: {str(e)}")
        logger.error(f"❌ Attachment send error: {e}")
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
        
        # ✅ FIX: Get attachment path correctly
        attachment_path = None
        if campaign.attachment:
            try:
                attachment_path = campaign.attachment.path
                print(f"🔍 Attachment found: {attachment_path}")
            except Exception as e:
                print(f"❌ Error getting attachment path: {e}")
                attachment_path = None
        else:
            print("🔍 No attachment for this campaign")
        
        # Send messages
        result = send_campaign_messages(
            campaign=campaign,
            valid_numbers=phone_numbers,
            message1=campaign.message1,
            message2=getattr(campaign, 'message2', None),
            attachment_path=attachment_path,  # ✅ Now passes correct attachment path
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
        
        logger.info(f"🎉 Campaign {campaign_id} processed: {result}")
        
    except Exception as e:
        logger.error(f"❌ Background campaign {campaign_id} failed: {e}")
        if campaign_id in active_campaigns:
            active_campaigns[campaign_id]['status'] = 'Failed'
            active_campaigns[campaign_id]['error'] = str(e)


def send_message_with_box(page, message_box, message):
    """Helper function to send a message using a found message box"""
    try:
        message_box.click()
        message_box.fill("")  # Clear any existing text
        message_box.type(message)
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
        message_box.type(message)
        page.keyboard.press("Enter")
        return True
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return False


def send_attachment(page, attachment_path):
    """Direct WhatsApp file injection - bypasses all UI"""
    try:
        # Step 1: Force create multiple file inputs
        page.evaluate('''
            () => {
                // Remove any existing file inputs first
                document.querySelectorAll('input[type="file"]').forEach(input => input.remove());
                
                // Create multiple file inputs with different configurations
                for (let i = 0; i < 3; i++) {
                    const input = document.createElement('input');
                    input.type = 'file';
                    input.accept = '*/*';
                    input.multiple = true;
                    input.style.position = 'fixed';
                    input.style.top = '-1000px';
                    input.style.left = '-1000px';
                    input.style.opacity = '0';
                    input.style.pointerEvents = 'none';
                    input.setAttribute('data-injected', 'true');
                    document.body.appendChild(input);
                }
            }
        ''')

        time.sleep(0.5)

        # Step 2: Upload to all inputs
        file_inputs = page.locator('input[type="file"]').all()
        uploaded = False

        for file_input in file_inputs:
            try:
                file_input.set_input_files(attachment_path)
                uploaded = True
                break
            except:
                continue

        if not uploaded:
            return False

        time.sleep(2)

        # Step 3: Trigger WhatsApp's file processing
        page.evaluate('''
            () => {
                const inputs = document.querySelectorAll('input[type="file"]');
                inputs.forEach(input => {
                    if (input.files && input.files.length > 0) {
                        // Trigger change event
                        const event = new Event('change', { bubbles: true });
                        input.dispatchEvent(event);
                        
                        // Try input event too
                        const inputEvent = new Event('input', { bubbles: true });
                        input.dispatchEvent(inputEvent);
                    }
                });
            }
        ''')

        time.sleep(3)

        # Step 4: Look for and click send button aggressively
        send_attempts = 0
        max_attempts = 10

        while send_attempts < max_attempts:
            try:
                # Try all possible send button selectors
                send_selectors = [
                    '[data-testid="send"]',
                    '[data-icon="send"]',
                    'button[aria-label*="Send"]',
                    'span[data-testid="send"]',
                    'div[data-testid="send"]',
                    '[role="button"][aria-label*="Send"]'
                ]

                for selector in send_selectors:
                    elements = page.locator(selector).all()
                    for element in elements:
                        try:
                            if element.is_visible():
                                element.click()
                                time.sleep(1)
                                return True
                        except:
                            continue

                send_attempts += 1
                time.sleep(0.5)

            except:
                send_attempts += 1
                continue

        try:
            page.keyboard.press('Enter')
            time.sleep(1)
            return True
        except:
            pass

        return False
        
    except Exception as e:
        logger.error(f"❌ Attachment error: {e}")
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
                    print(f"✅ Selected drop target: {selector}")
                    return element
        except Exception as e:
            print(f"⚠️ Selector {selector} failed: {e}")
            continue

    print("⚠️ Using body as fallback drop target")
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

        print(f"📁 File: {file_name} ({mime_type})")

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
        print(f"❌ Drag and drop execution failed: {e}")
        return False


async def send_attachment_playwright_native(page, attachment_path):
    """
    Alternative method using Playwright's native drag and drop.
    """
    try:
        print(f"📤 Native Playwright drag & drop: {os.path.basename(attachment_path)}")

        # Create temporary file input
        await page.evaluate("""
        () => {
            const existing = document.querySelector('#temp-file-input');
            if (existing) existing.remove();

            const input = document.createElement('input');
            input.type = 'file';
            input.id = 'temp-file-input';
            input.accept = 'image/*,video/*,application/*';
            input.multiple = false;
            input.style.position = 'absolute';
            input.style.left = '-9999px';
            input.style.top = '-9999px';
            document.body.appendChild(input);
        }
        """)

        await page.set_input_files('#temp-file-input', attachment_path)

        # Simulate drag & drop from temp input to drop target
        result = await page.evaluate("""
        () => {
            const input = document.querySelector('#temp-file-input');
            const file = input.files[0];

            if (!file) return false;

            const targets = [
                '[data-testid="conversation-panel"]',
                '[data-testid="main"]',
                'div[contenteditable="true"]',
                'main',
                'body'
            ];

            let dropTarget = null;
            for (const selector of targets) {
                dropTarget = document.querySelector(selector);
                if (dropTarget && dropTarget.offsetParent !== null) break;
            }

            if (!dropTarget) return false;

            const dataTransfer = new DataTransfer();
            dataTransfer.items.add(file);

            const dropEvent = new DragEvent('drop', {
                bubbles: true,
                cancelable: true,
                dataTransfer: dataTransfer
            });

            dropTarget.dispatchEvent(dropEvent);

            input.remove();
            return true;
        }
        """)

        if result:
            print("✅ Native drag and drop completed")
            await page.wait_for_timeout(3000)
            return True
        else:
            print("❌ Native method failed")
            return False

    except Exception as e:
        print(f"❌ Native method error: {e}")
        return False


# Additional helper function to debug page structure
def debug_page_elements(driver):
    """Helper function to inspect page elements for debugging"""
    print("🔍 DEBUG: Analyzing page structure...")
   
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
    print("🔍 DEBUG: Analyzing page structure...")
   
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
        logger.info(f"🔗 Navigating to: {chat_url}")
        page.goto(chat_url, wait_until='networkidle', timeout=30000)
        
        # Wait for chat interface
        time.sleep(5)
        
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
                    logger.info(f"✅ Chat interface ready - found: {selector}")
                    chat_ready = True
                    break
            except:
                continue
        
        if not chat_ready:
            logger.error(f"❌ Chat interface not ready for {phone_number}")
            return False
        
        # Send attachment first if provided
        if attachment_path and os.path.exists(attachment_path):
            logger.info(f"📎 Sending attachment to {phone_number}")
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
                            logger.info(f"✅ Found attachment button: {selector}")
                            break
                    except:
                        continue
                
                if attachment_button:
                    attachment_button.click()
                    logger.info("🔗 Clicked attachment button")
                    time.sleep(2)
                    
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
                                logger.info(f"✅ Found file input: {selector}")
                                break
                        except:
                            continue
                    
                    if file_input:
                        # Upload the file
                        file_input.set_input_files(attachment_path)
                        logger.info(f"📤 File uploaded: {attachment_path}")
                        time.sleep(3)  # Wait for file to process
                        
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
                                    logger.info(f"✅ Found attachment send button: {selector}")
                                    break
                            except:
                                continue
                        
                        if send_button:
                            send_button.click()
                            logger.info(f"✅ Attachment sent to {phone_number}")
                            time.sleep(3)  # Wait for attachment to be sent
                        else:
                            logger.warning(f"⚠️ Could not find attachment send button for {phone_number}")
                    else:
                        logger.warning(f"⚠️ Could not find file input for {phone_number}")
                else:
                    logger.warning(f"⚠️ Could not find attachment button for {phone_number}")
                    
            except Exception as e:
                logger.warning(f"⚠️ Attachment failed for {phone_number}: {e}")
        
        # Send text message if provided
        if message and message.strip():
            logger.info(f"💬 Sending text message to {phone_number}")
            
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
                        logger.info(f"✅ Found message input: {selector}")
                        break
                except:
                    continue
            
            if message_input:
                # Send the message
                message_input.click()
                message_input.fill("")  # Clear any existing text
                message_input.type(message)
                page.keyboard.press("Enter")
                logger.info(f"✅ Message sent successfully to {phone_number}")
                return True
            else:
                logger.error(f"❌ Could not find message input for {phone_number}")
                return False
        
        return True  # Return True if only attachment was sent
        
    except Exception as e:
        logger.error(f"❌ Error sending to {phone_number}: {e}")
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
                        logger.info(f"✅ Chat interface ready - found: {indicator}")
                        return True
                except:
                    continue
            
            time.sleep(1)
        
        logger.warning("⚠️ Chat interface not ready within timeout")
        return False
        
    except Exception as e:
        logger.error(f"❌ Error waiting for chat interface: {e}")
        return False
def find_message_input_specific(page):
    """Find ONLY the message composition input, NOT search or other inputs"""
    try:
        logger.info("🔍 Looking for message composition input specifically...")
        
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
                            logger.info(f"✅ Found message input: {selector}")
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
                            logger.info(f"✅ Found message input inside footer: {footer_selector}")
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
                                logger.info(f"✅ Found message input via position (y={bounding_box['y']})")
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
                        time.sleep(1)
                        
                        # Try finding input again after activation
                        activated_input = area.locator('div[contenteditable="true"]').first
                        if activated_input.is_visible():
                            logger.info(f"✅ Found input after clicking compose area")
                            return activated_input
                except Exception as e:
                    logger.debug(f"Click activation failed for {area_selector}: {e}")
                    continue
        except Exception as e:
            logger.debug(f"Click activation strategy failed: {e}")
        
        logger.error("❌ Could not find message composition input")
        return None
        
    except Exception as e:
        logger.error(f"❌ Error finding message input: {e}")
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
                    logger.info(f"✅ Found message input: {selector}")
                    return element
            except:
                continue
        
        # Strategy 2: Generic contenteditable in footer/compose area
        try:
            footer_inputs = page.locator('footer div[contenteditable="true"]').all()
            for element in footer_inputs:
                if element.is_visible() and element.is_enabled():
                    logger.info("✅ Found message input in footer")
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
                            logger.info("✅ Found message input via position detection")
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
                        time.sleep(1)
                        
                        # Try finding input again after click
                        for modern_selector in modern_selectors[:3]:
                            try:
                                element = page.locator(modern_selector).first
                                if element.is_visible():
                                    logger.info(f"✅ Found input after clicking compose: {modern_selector}")
                                    return element
                            except:
                                continue
                except:
                    continue
        except:
            pass
        
        logger.error("❌ Could not find message input with any strategy")
        return None
        
    except Exception as e:
        logger.error(f"❌ Error finding message input: {e}")
        return None

# ------------------------------------------
# Separate function (outside the above)
# ------------------------------------------
def send_message(campaign, valid_numbers, message1, message2, attachment_path, whatsapp_account):
    driver = None
    try:
        user_data_dir = whatsapp_account.session_path if whatsapp_account and whatsapp_account.session_path else None
        if not user_data_dir or not os.path.exists(user_data_dir):
            print("❌ No valid session path found. Aborting.")
            return

        print(f"🚀 Launching WebDriver with session: {user_data_dir}")
        driver = create_webdriver(user_data_dir=user_data_dir)
        driver.get("https://web.whatsapp.com")
        time.sleep(5)

        WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.ID, "side"))
        )
        print("✅ WhatsApp Web loaded with existing session")

        success_count, failed_numbers = 0, []

        for number in valid_numbers:
            try:
                print(f"📤 Sending to {number}")
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
                print(f"❌ Failed to send to {number}: {e}")
                failed_numbers.append(number)

        print(f"✅ Sent: {success_count} | ❌ Failed: {len(failed_numbers)}")
        campaign.is_sent = True
        campaign.save()

    except Exception as e:
        print(f"❌ Background error: {e}")
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

def send_attachment_playwright(page, attachment_path):
    """Send attachment using Playwright with explicit file type handling to prevent sticker conversion"""
    try:
        if not os.path.exists(attachment_path):
            logger.error(f"❌ Attachment file not found: {attachment_path}")
            return False
 
        file_size = os.path.getsize(attachment_path)
        if file_size > 100 * 1024 * 1024:
            logger.error(f"❌ File too large: {file_size} bytes")
            return False
 
        logger.info(f"📎 Preparing to send attachment: {attachment_path}")
 
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
        logger.info(f"📁 File: {file_name}, Extension: {file_extension}, MIME: {mime_type}, Is Media: {is_media}")
 
        # Find attachment button
        attachment_selectors = [
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
                    logger.info(f"✅ Found attachment button: {selector}")
                    break
            except Exception as e:
                logger.debug(f"Selector {selector} failed: {str(e)}")
                continue
 
        if not attachment_button:
            logger.error("❌ Attachment button not found")
            return False
 
        logger.info("📎 Clicking attachment button...")
        attachment_button.click()
        page.wait_for_timeout(2000)  # Wait for menu and inputs to appear
 
        # Select appropriate file input based on type
        if is_media:
            logger.info("🖼️ Using media file input for image/video...")
            file_input_selector = 'input[accept="image/*,video/mp4,video/3gpp,video/quicktime"]'
        else:
            logger.info("📄 Using document file input for non-media...")
            file_input_selector = 'input[accept="*"]'
 
        try:
            page.wait_for_selector(file_input_selector, state='attached', timeout=5000)  # Use 'attached' since inputs may be hidden
            file_input = page.query_selector(file_input_selector)
            if not file_input:
                logger.error("❌ File input not found")
                return False
        except Exception as e:
            logger.error(f"❌ Error finding file input: {str(e)}")
            return False
 
        logger.info("📁 Uploading file...")
        file_input.set_input_files(attachment_path)
        logger.info(f"📤 File uploaded: {attachment_path}")
        page.wait_for_timeout(5000)  # Allow file processing
 
        # Verify file preview if media
        if is_media:
            try:
                preview_selector = 'img[data-testid="image-preview"], [data-testid="media-preview"], video'
                page.wait_for_selector(preview_selector, state='visible', timeout=5000)
                if page.query_selector(preview_selector):
                    logger.info("✅ Media preview detected, file uploaded correctly")
                else:
                    logger.warning("⚠️ No media preview detected")
            except Exception as e:
                logger.warning(f"⚠️ Error checking media preview: {str(e)}")
 
        # Click send button
        return click_send_button(page)
 
    except Exception as e:
        logger.error(f"❌ Exception during attachment send: {str(e)}")
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
                    logger.info(f"✅ Clicking send button: {selector}")
                    send_button.click()
                    page.wait_for_timeout(2000)  # Allow send to complete
                    return True
            except Exception as e:
                logger.debug(f"Send button selector {selector} failed: {str(e)}")
                continue
 
        # Fallback: Try Enter key
        logger.info("🔄 Using Enter key as fallback")
        page.keyboard.press('Enter')
        page.wait_for_timeout(2000)
        return True
 
    except Exception as e:
        logger.error(f"❌ Error clicking send button: {str(e)}")
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
                    logger.info(f"✅ Clicking send button: {selector}")
                    send_button.click()
                    time.sleep(2)  # Allow send to complete
                    return True
            except Exception as e:
                logger.debug(f"Send button selector {selector} failed: {str(e)}")
                continue

        # Fallback: Try Enter key
        logger.info("🔄 Using Enter key as fallback")
        page.keyboard.press('Enter')
        time.sleep(2)
        return True

    except Exception as e:
        logger.error(f"❌ Error clicking send button: {str(e)}")
        return False


def send_message_to_number(page, phone_number, message, campaign_id, attachment_path=None):
    """Send message to a specific phone number using Playwright"""
    try:
        update_status(campaign_id, phone_number, 'Processing')
        
        # Clean phone number
        clean_number = ''.join(filter(str.isdigit, phone_number))
        if not clean_number:
            logger.error(f"❌ Invalid phone number: {phone_number}")
            update_status(campaign_id, phone_number, 'Invalid')
            return False
        
        # Open chat with the number
        whatsapp_url = f"https://web.whatsapp.com/send?phone={clean_number}"
        logger.info(f"🔗 Opening chat: {whatsapp_url}")
        
        try:
            page.goto(whatsapp_url, timeout=30000)
            page.wait_for_load_state('networkidle', timeout=30000)
        except PlaywrightTimeoutError:
            logger.error(f"❌ Timeout loading WhatsApp for {phone_number}")
            update_status(campaign_id, phone_number, 'Failed')
            return False
        
        # Wait for chat to load - check for either message box or invalid number indicator
        try:
            # Wait for either message input or error indicator
            page.wait_for_selector('div[contenteditable="true"][data-tab="10"]', timeout=15000)
        except PlaywrightTimeoutError:
            # Check if it's an invalid number
            try:
                invalid_selectors = [
                    'div[data-testid="invalid-phone-number"]',
                    'div:has-text("Phone number shared via url is invalid")',
                    'div:has-text("couldn\'t be reached")'
                ]
                
                for selector in invalid_selectors:
                    if page.query_selector(selector):
                        logger.warning(f"⚠️ Invalid phone number: {phone_number}")
                        update_status(campaign_id, phone_number, 'Invalid')
                        return False
            except:
                pass
            
            logger.error(f"❌ Could not load chat for {phone_number}")
            update_status(campaign_id, phone_number, 'Failed')
            return False
        
        # Send attachment first if provided
        if attachment_path:
            attachment_success = send_attachment_playwright(page, attachment_path)
            if not attachment_success:
                logger.warning(f"⚠️ Failed to send attachment to {phone_number}")
                # Continue with text message even if attachment fails
        
        # Send text message if provided
        if message and message.strip():
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
                    logger.error(f"❌ Could not find message input for {phone_number}")
                    update_status(campaign_id, phone_number, 'Failed')
                    return False
                
                # Clear any existing text and type new message
                message_box.click()
                time.sleep(1)
                
                # Clear existing content
                page.keyboard.press('Control+a')
                page.keyboard.press('Delete')
                
                # Type the message
                message_box.type(message)
                time.sleep(2)
                
                # Send message
                page.keyboard.press('Enter')
                time.sleep(2)
                
                logger.info(f"✅ Message sent to {phone_number}")
                
            except Exception as e:
                logger.error(f"❌ Error sending text message to {phone_number}: {str(e)}")
                update_status(campaign_id, phone_number, 'Failed')
                return False
        
        update_status(campaign_id, phone_number, 'Sent')
        return True
        
    except Exception as e:
        logger.error(f"❌ Error sending message to {phone_number}: {str(e)}")
        update_status(campaign_id, phone_number, 'Failed')
        return False

def update_status(campaign_id, phone_number, status):
    """Update the status of a phone number in the campaign"""
    if campaign_id not in campaign_statuses:
        campaign_statuses[campaign_id] = {}
    
    campaign_statuses[campaign_id][phone_number] = {
        'status': status,
        'timestamp': time.time()
    }

def process_campaign_background(campaign_id, account_id):
    """Background function to process the entire WhatsApp campaign using Playwright"""
    try:
        # Import your models here to avoid circular imports
        from bulk.models import WhatsAppCampaign, WhatsAppAccount  # Replace with actual import
        
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
        
        phone_numbers = [num.strip() for num in campaign.numbers.splitlines() if num.strip()]
        session_path = Path(r"C:\Users\Gopesh\OneDrive\Desktop\cummuno\whatsapp\whatsapp_sessions") / f"acct_{account_id}_{selected_account_number}"
        
        # Initialize statuses
        for number in phone_numbers:
            update_status(campaign_id, number, 'Pending')
        
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
                
                # Open WhatsApp Web
                logger.info("🚀 Opening WhatsApp Web...")
                page.goto("https://web.whatsapp.com", timeout=60000)
                page.wait_for_load_state('networkidle', timeout=60000)
                
                # Wait for WhatsApp to load
                logger.info("⏳ Waiting for WhatsApp Web to fully load...")
                try:
                    # Wait for either QR code or chat interface
                    page.wait_for_selector('div[data-testid="qr-code"], div[role="textbox"], canvas', timeout=120000)
                    
                    # Check if QR code is present (not logged in)
                    if page.query_selector('div[data-testid="qr-code"], canvas'):
                        logger.warning("⚠️ QR Code detected - please scan to login")
                        # Wait for login
                        page.wait_for_selector('div[role="textbox"]', timeout=300000)  # 5 minutes to login
                    
                except PlaywrightTimeoutError:
                    logger.error("❌ WhatsApp Web failed to load properly")
                    active_campaigns[campaign_id]['status'] = 'Failed'
                    active_campaigns[campaign_id]['error'] = 'WhatsApp Web failed to load'
                    return
                
                logger.info("✅ WhatsApp Web loaded, starting campaign")
                
                # Get attachment path if exists
                attachment_path = getattr(campaign, 'attachment', None)
                if attachment_path and hasattr(attachment_path, 'path'):
                    attachment_path = attachment_path.path
                
                # Loop through each number
                for i, phone_number in enumerate(phone_numbers):
                    # Stop or pause checks
                    if campaign_id not in active_campaigns or active_campaigns[campaign_id].get('stopped', False):
                        break
                    
                    while active_campaigns[campaign_id].get('paused', False):
                        time.sleep(2)
                        if active_campaigns[campaign_id].get('stopped', False):
                            break
                    
                    if active_campaigns[campaign_id].get('stopped', False):
                        break
                    
                    logger.info(f"📱 Sending message to {phone_number} ({i+1}/{len(phone_numbers)})")
                    success = send_message_to_number(page, phone_number, campaign.message1, campaign_id, attachment_path)
                    
                    # Delay between messages
                    if i < len(phone_numbers) - 1:
                        delay = getattr(campaign, 'delay', 8) or 8
                        time.sleep(delay)
                
                # Mark campaign as completed
                active_campaigns[campaign_id]['status'] = 'Completed'
                logger.info(f"🎉 Campaign {campaign_id} completed successfully")
                
            except Exception as e:
                logger.error(f"Browser error in campaign {campaign_id}: {str(e)}")
                raise
            finally:
                # Clean up browser
                try:
                    if 'browser' in active_campaigns.get(campaign_id, {}):
                        active_campaigns[campaign_id]['browser'].close()
                except Exception as e:
                    logger.error(f"Error closing browser: {str(e)}")
                
    except Exception as e:
        logger.error(f"Campaign {campaign_id} failed: {str(e)}")
        if campaign_id in active_campaigns:
            active_campaigns[campaign_id]['status'] = 'Failed'
            active_campaigns[campaign_id]['error'] = str(e)

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
        
        # Initialize status storage
        campaign_statuses[campaign_id] = {}
        
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
        status = data['status']
        formatted_statuses[phone] = status
        counts[status] = counts.get(status, 0) + 1
    
    # Determine overall status
    campaign_info = active_campaigns.get(campaign_id, {})
    if campaign_info.get('paused', False):
        overall_status = "Paused"
    elif campaign_info.get('stopped', False):
        overall_status = "Stopped"
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
        overall_status = "Not Started"
    
    return JsonResponse({
        "overall_status": overall_status,
        "statuses": formatted_statuses,
        "counts": counts
    })

@login_required
def pause_campaign(request, campaign_id):
    """Pause the running campaign"""
    if campaign_id in active_campaigns:
        active_campaigns[campaign_id]['paused'] = True
        return JsonResponse({"success": True, "message": "Campaign paused"})
    return JsonResponse({"success": False, "message": "Campaign not found"}, status=404)

@login_required
def resume_campaign(request, campaign_id):
    """Resume the paused campaign"""
    if campaign_id in active_campaigns:
        active_campaigns[campaign_id]['paused'] = False
        return JsonResponse({"success": True, "message": "Campaign resumed"})
    return JsonResponse({"success": False, "message": "Campaign not found"}, status=404)

@login_required
def stop_campaign(request, campaign_id):
    """Stop the running campaign"""
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
        
        return JsonResponse({"success": True, "message": "Campaign stopped"})
    return JsonResponse({"success": False, "message": "Campaign not found"}, status=404)

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
    if request.method == 'POST':
        nickname = request.POST.get('nickname')
        active = request.POST.get('activeStatus') == 'on'
        send_at = request.POST.get('send_at')
        repeat = request.POST.get('repeatSchedule') == 'on'
        logging = request.POST.get('logging')
        encryption = request.POST.get('encryption') == 'on'
        backup = request.POST.get('backup') == 'on'


        print("Nickname:", nickname)
        print("Active:", active)
        print("Send At:", send_at)
        print("Repeat:", repeat)
        print("Logging:", logging)
        print("Encryption:", encryption)
        print("Backup:", backup)

        messages.success(request, "Settings saved successfully.")
        return redirect('settings_view')

    return render(request, 'settings.html')


@login_required
def add_account(request):
    if request.method == "POST":
        is_ajax = request.headers.get("x-requested-with") == "XMLHttpRequest"

        form = WhatsAppAccountForm(request.POST, request.FILES)
        if form.is_valid():
            account = form.save(commit=False)
            account.user = request.user
            account.save()

            # ✅ Make this account default
            WhatsAppAccount.objects.filter(user=request.user).exclude(id=account.id).update(is_default=False)
            account.is_default = True
            account.save()

            # ✅ Create session folder
            session_root = os.path.join(settings.BASE_DIR, "whatsapp_sessions")
            os.makedirs(session_root, exist_ok=True)
            session_path = os.path.join(session_root, f"acct_{request.user.id}_{account.number}")
            os.makedirs(session_path, exist_ok=True)

            # ✅ Store session path but don’t run Selenium immediately
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
            if is_ajax:
                return JsonResponse({
                    "success": False,
                    "message": "Form validation failed",
                    "errors": form.errors.as_json()
                })
            messages.error(request, f"Form validation failed: {form.errors}")
            return redirect("add_account")

    # GET request → return empty form
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
#                 time.sleep(20)
#                 driver.quit()

#                 return JsonResponse({'success': True, 'message': 'Account added and QR scanned', 'account_id': account.id})
#             except Exception as e:
#                 return JsonResponse({'success': False, 'message': f'Selenium error: {str(e)}'})
#         else:
#             return JsonResponse({'success': False, 'message': 'Form error', 'errors': form.errors})
#     return JsonResponse({'success': False, 'message': 'Invalid request'})

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

   