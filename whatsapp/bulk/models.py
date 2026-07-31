import os
import shutil
import time
import logging
import psutil
import subprocess
import tempfile
from django.contrib.auth.models import User
from django.db import models
from django.conf import settings

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


     
    def __str__(self):
        return self.name

   
   