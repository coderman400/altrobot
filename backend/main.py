import os
import io
import shutil
import zipfile
from fastapi import FastAPI, UploadFile, File
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image, GifImagePlugin
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from tqdm import tqdm
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Access API Key
api_key = os.getenv("API_KEY")
# Initialize FastAPI
app = FastAPI()

# Allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Gemini API
genai.configure(api_key=api_key)
model = genai.GenerativeModel(model_name="gemini-2.0-flash")

# Directories
TEMP_DIR = "temp_files"
IMAGE_DIR = os.path.join(TEMP_DIR, "compressed_images")
TEXT_DIR = os.path.join(TEMP_DIR, "alt_texts")
ZIP_PATH = os.path.join(TEMP_DIR, "compressed_results.zip")

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(TEXT_DIR, exist_ok=True)

# Function to extract images from PDF
def extract_images_from_docx(docx_bytes):
    extracted_images = []
    
    with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as docx_zip:
        for file in docx_zip.namelist():
            if file.startswith("word/media/"):
                file_name = os.path.basename(file)
                file_path = os.path.join(IMAGE_DIR, file_name)

                with open(file_path, "wb") as img_file:
                    img_file.write(docx_zip.read(file))

                # Compress images
                compressed_path = os.path.join(IMAGE_DIR, f"compressed_{file_name}")
                if file_name.endswith(("jpeg", "jpg", "png")):
                    compress_image(file_path, compressed_path, 100)  # Compress to 100KB
                elif file_name.endswith("gif"):
                    compress_gif(file_path, compressed_path, 500)  # Compress GIFs
                else:
                    os.rename(file_path, compressed_path)  # Keep original if unsupported
                
                if os.path.exists(file_path):
                    os.remove(file_path)
                print(f"FILE ADDING!")
                extracted_images.append(compressed_path)

    return extracted_images

# Function to compress images
def compress_image(image_path, output_path, max_size_kb):
    """Compress an image (JPG/PNG) to a max size in KB."""
    image = Image.open(image_path)

    # Convert RGBA to RGB if necessary
    if image.mode == "RGBA":
        image = image.convert("RGB")

    # Reduce quality in a loop until it fits the size
    quality = 95
    while quality > 10:
        image.save(output_path, "JPEG", quality=quality)
        if os.path.getsize(output_path) <= max_size_kb * 1024:
            break
        quality -= 5  # Reduce quality if still too big

from PIL import Image
import os

def compress_gif(
    input_path: str,
    output_path: str,
    max_colors: int = 256,
    sample_factor: float = 1.0
) -> bool:
    try:
        # Open the GIF
        with Image.open(input_path) as img:
            # Get sequence of frames
            frames = []
            durations = []
            
            # Extract all frames and their durations
            try:
                while True:
                    # If resizing is requested
                    if sample_factor != 1.0:
                        new_size = tuple(int(dim * sample_factor) for dim in img.size)
                        frame = img.resize(new_size, Image.Resampling.LANCZOS)
                    else:
                        frame = img.copy()

                    # Convert to P mode with limited palette
                    if frame.mode != 'P':
                        frame = frame.convert(
                            'P', 
                            palette=Image.Palette.ADAPTIVE, 
                            colors=max_colors
                        )
                        
                    frames.append(frame)
                    durations.append(img.info.get('duration', 100))
                    img.seek(img.tell() + 1)
            except EOFError:
                pass  # Reached end of frame sequence
                
            # Save optimized GIF
            frames[0].save(
                output_path,
                save_all=True,
                append_images=frames[1:],
                optimize=True,
                duration=durations,
                loop=0,
                disposal=2,  # Restore to background color before rendering next frame
                quality=85   # Lower quality for better compression
            )
            
        # Print size comparison
        original_size = os.path.getsize(input_path) / 1024
        compressed_size = os.path.getsize(output_path) / 1024
        print(f"Original size: {original_size:.2f}KB")
        print(f"Compressed size: {compressed_size:.2f}KB")
        print(f"Reduction: {((original_size - compressed_size) / original_size * 100):.1f}%")
        
        return True
        
    except Exception as e:
        print(f"Error compressing GIF: {e}")
        return False

def get_alt_texts(image_paths, batch_size= 8):
    """Processes images in batches and retrieves alt texts."""
    alt_texts = {}

    for i in range(0, len(image_paths), batch_size):
        batch = image_paths[i:i + batch_size]

        try:
            print(f"🖼️ Processing batch: {batch}")

            # Read images as binary data
            image_data = []
            for img_path in batch:
                with open(img_path, "rb") as img_file:
                    img_data = img_file.read()
                    image_data.append({"inline_data": {"mime_type": "image/jpeg", "data": img_data}})
            
            # Send batch request to Gemini
            response = model.generate_content(
                contents=[
                    {"role": "user", "parts": [
                        {"text": "Generate a one-line alt text for each image. Return a list, one alt text per line. DONT RETURN ANYTHING ELSE BUT THE ALT TEXTS"}
                    ] + image_data}
                ],
                safety_settings={
                    HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
                    HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
                },
            )

            # Extract alt texts from response
            alt_text_list = response.text.strip().split("\n") if response.text else ["No alt text"] * len(batch)
            
            # Map images to their respective alt texts
            for img, alt_text in zip(batch, alt_text_list):
                alt_texts[img] = alt_text

            print(f"✅ Batch processed: {alt_text_list}")


        except Exception as e:
            alt_texts[img_path] = f"Error: {str(e)}"

    return alt_texts

# Function to create ZIP file
def create_zip():
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zipf:
        for folder in [IMAGE_DIR, TEXT_DIR]:
            for root, _, files in os.walk(folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, TEMP_DIR))

def clean_temp_files():
    shutil.rmtree(TEMP_DIR, ignore_errors=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(TEXT_DIR, exist_ok=True)

# Upload PDF and return ZIP file
@app.post("/upload_pdf/")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        docx_bytes = await file.read()
        print("READ FILE!")
        image_paths = extract_images_from_docx(docx_bytes)
        if not image_paths:
            return {"error": "No images found in PDF."}
        print("IMAGES GOTTED!")
        # Generate alt texts
        alt_texts = get_alt_texts(image_paths)
        print("ALT TEXT GOTTED!")
        # Save alt texts to text files
        for img_path, alt_text in alt_texts.items():
            txt_filename = os.path.join(TEXT_DIR, f"{os.path.splitext(os.path.basename(img_path))[0]}.txt")
            with open(txt_filename, "w") as txt_file:
                txt_file.write(alt_text)

        create_zip()

        # Debug: Check if ZIP exists
        if not os.path.exists(ZIP_PATH):
            return {"error": f"ZIP file missing at {ZIP_PATH}"}
        
        response = FileResponse(ZIP_PATH, filename="compressed_results.zip", media_type="application/zip")

        return response

    except Exception as e:
        return {"error": str(e)}
