from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
import os
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from dotenv import load_dotenv
from google.api_core import retry
from typing_extensions import TypedDict,List
import shutil
import logging
import colorlog

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
log.setLevel(logging.INFO)

os.makedirs("compressed_images", exist_ok=True)

app = FastAPI()

# Load environment variables from .env file
load_dotenv()

# Access API Key
api_key = os.getenv("API_KEY")
print(api_key)

class AltTexts(TypedDict):
    texts: List[str]

def add_to_database(alt_texts: AltTexts):
    pass


# Configure Gemini API
genai.configure(api_key=api_key)
model = genai.GenerativeModel(model_name="gemini-2.0-flash", tools=[add_to_database])


def get_alt_texts(image_paths, batch_size=8):
    """Processes images in batches and retrieves alt texts."""
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

            response = model.generate_content(
                contents=[
                    {"role": "user", "parts": [
                        {"text": "Generate a one-line alt text for each image. Return a list, one alt text per line. Dont say anything like 'here are the alt texts' or any other generated text from your end. DONT RETURN ANYTHING ELSE BUT THE ALT TEXTS."}
                    ] + image_data}
                ],request_options={"timeout": 1000,'retry':retry.Retry()},
                safety_settings={
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                },tool_config={'function_calling_config':'ANY'}
            )
            fc = response.candidates[0].content.parts[0].function_call
            alt_text_list = type(fc).to_dict(fc)["args"]["alt_texts"]["texts"]

            for img, alt_text in zip(batch, alt_text_list):
                alt_texts[img.split('/')[-1]] = alt_text

            log.info(f"✅ Batch processed: {alt_text_list[0]}...")

        except Exception as e:
            alt_texts[img_path.split("/")[-1]] = f"Error: {str(e)}"

    return alt_texts


@app.post("/generate-alt-texts")
def generate_alt_texts(files: List[UploadFile] = File(...)):
    for file in files:
        shutil.copyfileobj(file.file, open(f"compressed_images/{file.filename}", "wb"))

    image_paths = [f"compressed_images/{file.filename}" for file in files]
    alt_texts = get_alt_texts(image_paths)

    return JSONResponse(content=alt_texts)