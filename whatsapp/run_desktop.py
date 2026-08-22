import os
import sys

import io

# Force Python to use UTF-8 globally
os.environ["PYTHONIOENCODING"] = "utf-8"
os.environ["PYTHONUTF8"] = "1"

# Redirect stdout and stderr to persistent log file in APPDATA
appdata = os.environ.get('APPDATA', os.path.expanduser('~'))
log_dir = os.path.join(appdata, 'WhatsApp Commune')
os.makedirs(log_dir, exist_ok=True)
log_file_path = os.path.join(log_dir, 'desktop_app.log')

try:
    log_file = open(log_file_path, 'a', encoding='utf-8', buffering=1)
    sys.stdout = log_file
    sys.stderr = log_file
except Exception:
    if sys.stdout is None: sys.stdout = io.StringIO()
    if sys.stderr is None: sys.stderr = io.StringIO()

import threading
import time
import webview
from waitress import serve
from django.core.wsgi import get_wsgi_application

from django.core.management import call_command

def start_django_server():
    """
    1. Waitress Server: This replaces 'manage.py runserver'
    It runs completely silently in the background.
    """
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'whatsapp.settings')
    
    import django
    django.setup()
    try:
        call_command('migrate', interactive=False)
    except Exception as e:
        print(f"Migration notice: {e}")
    
    application = get_wsgi_application()
    
    # Starts your backend on a hidden local port
    serve(application, host='127.0.0.1', port=8000)

def check_django_ready(window):
    """
    Background thread that pings the Django server until it's ready,
    then redirects the webview window to the app.
    """
    import urllib.request
    import urllib.error
    import time
    
    # Wait until the server responds cleanly
    for _ in range(60):
        try:
            req = urllib.request.Request("http://127.0.0.1:8000/", headers={'User-Agent': 'Mozilla/5.0'})
            resp = urllib.request.urlopen(req)
            if resp.getcode() in (200, 302):
                break
        except urllib.error.HTTPError as e:
            if e.code in (200, 302):
                break
            time.sleep(0.5)
        except Exception:
            time.sleep(0.5)
            
    # Give it a tiny extra buffer to fully settle
    time.sleep(0.5)
    
    # Redirect the native window to the loaded app!
    window.load_url(f'http://127.0.0.1:8000/?nocache={time.time()}')

def create_desktop_window():
    """
    2. PyWebView: This creates the native Windows UI frame.
    It immediately shows a loading spinner while Django boots in the background.
    """
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body {
                background-color: #ffffff;
                display: flex;
                flex-direction: column;
                justify-content: center;
                align-items: center;
                height: 100vh;
                margin: 0;
                font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            }
            .spinner {
                width: 40px;
                height: 40px;
                border: 4px solid #e9ecef;
                border-top: 4px solid #198754;
                border-radius: 50%;
                animation: spin 1s linear infinite;
                margin-bottom: 20px;
            }
            .text {
                color: #212529;
                font-size: 1.2rem;
                font-weight: 600;
                letter-spacing: 0.5px;
            }
            .subtext {
                color: #6c757d;
                font-size: 0.9rem;
                margin-top: 8px;
            }
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
        </style>
    </head>
    <body>
        <div class="spinner"></div>
        <div class="text">Starting WhatsApp Commune...</div>
        <div class="subtext">Loading server</div>
    </body>
    </html>
    """

    window = webview.create_window(
        title='WhatsApp Commune', 
        html=html_content,
        width=1280,
        height=800,
        resizable=True,
        background_color='#ffffff'
    )
    
    # Start the native window loop, and run our check_django_ready function in the background
    webview.start(check_django_ready, window, private_mode=False)

if __name__ == '__main__':
    # Start the backend server in a separate daemon thread so it dies when the window closes
    server_thread = threading.Thread(target=start_django_server, daemon=True)
    server_thread.start()

    # Launch the sleek Windows Desktop App immediately (no more time.sleep!)
    create_desktop_window()

