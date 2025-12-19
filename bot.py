import os
import logging
import asyncio
import requests
from pyrogram import Client, filters, errors
from aiohttp import web

# --- Configuration ---
API_ID = int(os.environ.get("API_ID", "12345")) 
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
FACEBOOK_PAGE_ACCESS_TOKEN = os.environ.get("FB_TOKEN", "")
FACEBOOK_PAGE_ID = os.environ.get("FB_PAGE_ID", "")

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Pyrogram Bot Client ---
app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def upload_to_facebook(video_path, caption):
    """Uploads a video file to Facebook Graph API"""
    url = f"https://graph-video.facebook.com/v18.0/{FACEBOOK_PAGE_ID}/videos"
    
    payload = {
        'access_token': FACEBOOK_PAGE_ACCESS_TOKEN,
        'description': caption or "Uploaded via Telegram Bot"
    }
    
    # Open file and send
    try:
        with open(video_path, 'rb') as file:
            files = {'source': file}
            logger.info("Starting upload to Facebook...")
            response = requests.post(url, data=payload, files=files)
            return response.json()
    except Exception as e:
        return {'error': {'message': str(e)}}

@app.on_message(filters.video & filters.private)
async def handle_video(client, message):
    status_msg = await message.reply_text("📥 Downloading video from Telegram...")
    file_path = None
    
    try:
        # 1. Download Video from Telegram
        file_path = await message.download()
        
        try:
            await status_msg.edit_text("📤 Uploading to Facebook...")
        except errors.MessageNotModified:
            pass # Ignore if text didn't change

        # 2. Upload to Facebook (Run in a separate thread)
        loop = asyncio.get_event_loop()
        caption = message.caption if message.caption else ""
        
        fb_response = await loop.run_in_executor(None, upload_to_facebook, file_path, caption)

        # 3. Cleanup and Notify
        if 'id' in fb_response:
            try:
                await status_msg.edit_text(f"✅ **Success!**\nVideo uploaded to Facebook.\nPost ID: `{fb_response['id']}`")
            except errors.MessageNotModified:
                pass 
        else:
            error_msg = fb_response.get('error', {}).get('message', 'Unknown error')
            try:
                await status_msg.edit_text(f"❌ **Failed**\nFacebook Error: {error_msg}")
            except errors.MessageNotModified:
                pass

    except Exception as e:
        logger.error(f"Error: {e}")
        try:
            await status_msg.edit_text(f"❌ Error occurred: {str(e)}")
        except:
            pass
    
    finally:
        # Delete local file to save space
        if file_path and os.path.exists(file_path):
            os.remove(file_path)

# --- Dummy Web Server for Render ---
async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    port = int(os.environ.get("PORT", 8080))
    app_runner = web.AppRunner(web.Application())
    await app_runner.setup()
    bind_address = "0.0.0.0"
    site = web.TCPSite(app_runner, bind_address, port)
    await site.start()

# --- Main Entry Point ---
if __name__ == "__main__":
    from pyrogram import idle
    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_web_server())
    
    app.start()
    print("Bot is running...")
    idle()
    app.stop()
