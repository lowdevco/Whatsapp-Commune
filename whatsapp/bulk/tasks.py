# bulk/tasks.py
import os
import time
import random
import logging
from typing import List
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException
import threading

logger = logging.getLogger(__name__)

def create_webdriver(user_data_dir=None):
    """Your existing create_webdriver function - import it here or copy the implementation"""
    from .utils import create_webdriver as create_driver  # Assuming it's in utils.py
    return create_driver(user_data_dir)

def send_campaign_messages(campaign, valid_numbers, message1, message2, attachment_path, whatsapp_account):
    """
    Send campaign messages to a list of phone numbers using WhatsApp Web
    """
    driver = None
    try:
        # Validate session path
        user_data_dir = whatsapp_account.session_path if whatsapp_account and whatsapp_account.session_path else None
        if not user_data_dir or not os.path.exists(user_data_dir):
            logger.error("No valid session path found. Aborting campaign.")
            campaign.status = 'failed'
            campaign.error_message = "No valid WhatsApp session found"
            campaign.save()
            return

        logger.info(f"🚀 Launching WebDriver with session: {user_data_dir}")
        driver = create_webdriver(user_data_dir=user_data_dir)
        driver.get("https://web.whatsapp.com")
        time.sleep(5)

        # Wait for WhatsApp to load
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.ID, "side"))
            )
            logger.info("✅ WhatsApp Web loaded with existing session")
        except TimeoutException:
            logger.error("Failed to load WhatsApp Web - session may be expired")
            campaign.status = 'failed'
            campaign.error_message = "WhatsApp session expired"
            campaign.save()
            return

        success_count = 0
        failed_numbers = []
        total_numbers = len(valid_numbers)

        # Update campaign status
        campaign.status = 'sending'
        campaign.total_recipients = total_numbers
        campaign.save()

        for i, number in enumerate(valid_numbers, 1):
            try:
                logger.info(f"📤 Sending to {number} ({i}/{total_numbers})")
                
                # Navigate to WhatsApp chat
                driver.get(f"https://web.whatsapp.com/send?phone={number}")
                
                # Wait for message box to appear
                msg_box = WebDriverWait(driver, 25).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.XPATH, "//div[@title='Type a message']")),
                        EC.presence_of_element_located((By.XPATH, "//div[@contenteditable='true'][@data-tab='10']")),
                        EC.presence_of_element_located((By.XPATH, "//div[@data-testid='conversation-compose-box-input']"))
                    )
                )
                
                # Combine messages
                combined_message = "\n".join(filter(None, [message1, message2]))
                
                # Clear and send message
                msg_box.clear()
                msg_box.send_keys(combined_message)
                
                # Handle attachment if provided
                if attachment_path and os.path.exists(attachment_path):
                    try:
                        # Click attachment button
                        attach_btn = driver.find_element(By.XPATH, "//div[@title='Attach']")
                        attach_btn.click()
                        
                        # Upload file
                        file_input = driver.find_element(By.XPATH, "//input[@accept='*']")
                        file_input.send_keys(attachment_path)
                        
                        # Wait and send
                        time.sleep(2)
                        send_btn = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, "//span[@data-testid='send']"))
                        )
                        send_btn.click()
                    except Exception as attach_error:
                        logger.warning(f"Failed to send attachment to {number}: {attach_error}")
                        # Send text message anyway
                        msg_box.send_keys(Keys.ENTER)
                else:
                    # Send text message
                    msg_box.send_keys(Keys.ENTER)

                success_count += 1
                logger.info(f"✅ Sent to {number}")
                
                # Update campaign progress
                campaign.sent_count = success_count
                campaign.save()
                
                # Random delay between messages (3-6 seconds)
                delay = random.uniform(3, 6)
                logger.debug(f"Waiting {delay:.1f}s before next message...")
                time.sleep(delay)

            except TimeoutException:
                error_msg = f"Timeout waiting for message box for {number}"
                logger.error(error_msg)
                failed_numbers.append({"number": number, "error": "Timeout"})
                
            except Exception as e:
                error_msg = f"Failed to send to {number}: {str(e)}"
                logger.error(error_msg)
                failed_numbers.append({"number": number, "error": str(e)})

        # Update campaign completion status
        logger.info(f"📊 Campaign Complete - Sent: {success_count} | Failed: {len(failed_numbers)}")
        
        campaign.status = 'completed' if len(failed_numbers) == 0 else 'partial'
        campaign.sent_count = success_count
        campaign.failed_count = len(failed_numbers)
        campaign.is_sent = True
        campaign.completed_at = timezone.now()
        
        if failed_numbers:
            campaign.failed_numbers = failed_numbers  # Store failed numbers as JSON field
        
        campaign.save()

    except Exception as e:
        logger.error(f"💥 Campaign error: {str(e)}", exc_info=True)
        campaign.status = 'failed'
        campaign.error_message = str(e)
        campaign.save()
        
    finally:
        # Cleanup
        if driver:
            try:
                driver.quit()
                logger.info("🔒 WebDriver closed")
            except Exception as cleanup_error:
                logger.warning(f"Error closing driver: {cleanup_error}")
        
        # Remove temporary attachment file
        if attachment_path and os.path.exists(attachment_path):
            try:
                os.remove(attachment_path)
                logger.info(f"🗑️ Removed temporary file: {attachment_path}")
            except Exception as file_error:
                logger.warning(f"Error removing temporary file: {file_error}")

def send_campaign_messages_async(campaign_id, valid_numbers, message1, message2, attachment_path=None):
    """
    Async wrapper for campaign sending - can be used with Celery or threading
    """
    from .models import WhatsAppCampaign, WhatsAppAccount  # Import here to avoid circular imports
    from django.utils import timezone
    
    try:
        # Get campaign and related data
        campaign = WhatsAppCampaign.objects.get(id=campaign_id)
        whatsapp_account = campaign.whatsapp_account
        
        if not valid_numbers:
            logger.error(f"No valid numbers provided for campaign {campaign_id}")
            campaign.status = 'failed'
            campaign.error_message = "No valid recipient numbers"
            campaign.save()
            return
        
        # Start the campaign
        campaign.started_at = timezone.now()
        campaign.save()
        
        # Send messages
        send_campaign_messages(
            campaign=campaign,
            valid_numbers=valid_numbers,
            message1=message1,
            message2=message2,
            attachment_path=attachment_path,
            whatsapp_account=whatsapp_account
        )
        
    except WhatsAppCampaign.DoesNotExist:
        logger.error(f"Campaign {campaign_id} not found")
    except Exception as e:
        logger.error(f"Error in async campaign {campaign_id}: {str(e)}", exc_info=True)

# If using Celery, uncomment this:
# from celery import shared_task
# 
# @shared_task
# def send_campaign_messages_celery(campaign_id, message1, message2, attachment_path=None):
#     """Celery task wrapper"""
#     return send_campaign_messages_async(campaign_id, message1, message2, attachment_path)

# If using threading (simple approach):

def send_campaign_messages_thread(campaign_id, valid_numbers, message1, message2, attachment_path=None):
    """
    Start campaign in background thread (simple approach)
    """
    thread = threading.Thread(
        target=send_campaign_messages_async,
        args=(campaign_id, valid_numbers, message1, message2, attachment_path)
    )
    thread.daemon = True
    thread.start()
    return thread