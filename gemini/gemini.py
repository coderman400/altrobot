from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from dotenv import load_dotenv
from google.api_core import retry
from typing_extensions import TypedDict, List
import shutil
import logging
import colorlog
import asyncio
from fastapi.middleware.cors import CORSMiddleware

formatter = colorlog.ColoredFormatter(
    "%(log_color)s%(levelname)s:%(reset)s %(message)s",
    log_colors={
        "DEBUG": "cyan",
        "INFO": "green",
        "WARNING": "yellow",
        "ERROR": "red",
        "CRITICAL": "bold_red",
    }
)

handler = logging.StreamHandler()
handler.setFormatter(formatter)
log = logging.getLogger()
log.addHandler(handler)
log.setLevel(logging.DEBUG)

os.makedirs("compressed_images", exist_ok=True)

app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change this to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load environment variables from .env file
load_dotenv()

# Access API Key
api_key = os.getenv("API_KEY")


class AltTexts(TypedDict):
    texts: List[str]

def add_to_database(alt_texts: AltTexts):
    pass


# Configure Gemini API
genai.configure(api_key=api_key)
model = genai.GenerativeModel(model_name="gemini-2.0-flash", tools=[add_to_database])


async def get_alt_texts(image_paths, batch_size=8):
    """Processes images in batches and retrieves alt texts asynchronously."""
    alt_texts = {}

    for i in range(0, len(image_paths), batch_size):
        batch = image_paths[i:i + batch_size]

        try:
            log.info(f"🖼️ Processing batch: {batch[0]}...")

            image_data = []
            for img_path in batch:
                with open(img_path, "rb") as img_file:
                    img_data = img_file.read()
                    image_data.append({"inline_data": {"mime_type": "image/jpeg", "data": img_data}})

            # Run Gemini API call in a thread pool to not block the event loop
            response = await asyncio.to_thread(
                model.generate_content,
                contents=[
                    {"role": "user", "parts": [
                        {"text": "Generate a one-line alt text for each image. Return a list, one alt text per line. Dont say anything like 'here are the alt texts' or any other generated text from your end. DONT RETURN ANYTHING ELSE BUT THE ALT TEXTS."}
                    ] + image_data}
                ],
                request_options={"timeout": 1000, 'retry': retry.Retry()},
                safety_settings={
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                },
                tool_config={'function_calling_config': 'ANY'}
            )
            
            fc = response.candidates[0].content.parts[0].function_call
            alt_text_list = type(fc).to_dict(fc)["args"]["alt_texts"]["texts"]

            for img, alt_text in zip(batch, alt_text_list):
                alt_texts[img.split('/')[-1]] = alt_text

            log.info(f"✅ Batch processed: {alt_text_list[0]}...")

        except Exception as e:
            log.error(f"Error processing batch: {e}")
            for img_path in batch:
                alt_texts[img_path.split("/")[-1]] = f"Error: {str(e)}"

    return alt_texts

@app.get("/wakeup")
async def wakeup():
    return JSONResponse(content={"status": "awake"})

@app.post("/generate-alt-texts")
async def generate_alt_texts(files: List[UploadFile] = File(...)):
    # Save files asynchronously
    for file in files:
        file_content = await file.read()
        with open(f"compressed_images/{file.filename}", "wb") as f:
            f.write(file_content)

    image_paths = [f"compressed_images/{file.filename}" for file in files]
    alt_texts = await get_alt_texts(image_paths)

    return JSONResponse(content=alt_texts)