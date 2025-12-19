import os
import logging
import asyncio
import requests
from pyrogram import Client, filters
from aiohttp import web

# --- Configuration ---
# Get these from your Environment Variables on Render
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
    with open(video_path, 'rb') as file:
        files = {'source': file}
        logger.info("Starting upload to Facebook...")
        response = requests.post(url, data=payload, files=files)
    
    return response.json()

@app.on_message(filters.video & filters.private)
async def handle_video(client, message):
    status_msg = await message.reply_text("📥 Downloading video from Telegram...")
    
    try:
        # 1. Download Video from Telegram
        file_path = await message.download()
        await status_msg.edit_text("📤 Uploading to Facebook...")

        # 2. Upload to Facebook (Run in a separate thread to not block async loop)
        loop = asyncio.get_event_loop()
        caption = message.caption if message.caption else ""
        
        # Using executor for blocking request
        fb_response = await loop.run_in_executor(None, upload_to_facebook, file_path, caption)

        # 3. Cleanup and Notify
        if 'id' in fb_response:
            await status_msg.edit_text(f"✅ **Success!**\nVideo uploaded to Facebook.\nPost ID: `{fb_response['id']}`")
        else:
            error_msg = fb_response.get('error', {}).get('message', 'Unknown error')
            await status_msg.edit_text(f"❌ **Failed**\nFacebook Error: {error_msg}")

    except Exception as e:
        logger.error(f"Error: {e}")
        await status_msg.edit_text(f"❌ Error occurred: {str(e)}")
    
    finally:
        # Delete local file to save space
        if os.path.exists(file_path):
            os.remove(file_path)

# --- Dummy Web Server for Render ---
async def health_check(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    # Render provides the PORT environment variable
    port = int(os.environ.get("PORT", 8080))
    app_runner = web.AppRunner(web.Application())
    await app_runner.setup()
    bind_address = "0.0.0.0"
    site = web.TCPSite(app_runner, bind_address, port)
    await site.start()

# --- Main Entry Point ---
async def main():
    # Start the Web Server (to keep Render happy)
    await start_web_server()
    
    # Start the Bot
    print("Bot started...")
    await app.start()
    
    # Keep the script running
    await pyrogram.idle()
    await app.stop()

if __name__ == "__main__":
    # Pyrogram's idle() handles the loop, but we need to run both server and bot
    # We use compose to run the bot and the web server together
    from pyrogram import idle
    
    loop = asyncio.get_event_loop()
    loop.run_until_complete(start_web_server())
    
    app.start()
    print("Bot is running...")
    idle()
    app.stop()
