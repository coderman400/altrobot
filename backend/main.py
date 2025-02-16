import os
import fitz  # PyMuPDF
import io
import shutil
import zipfile
from fastapi import FastAPI, UploadFile, File
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image, GifImagePlugin
import imageio.v3 as iio  # For GIF compression
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

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
genai.configure(api_key="AIzaSyDsDjyc12Kugg9yvPqo8ZKPm1nv6ldrgbA")
model = genai.GenerativeModel(model_name="gemini-2.0-flash")

# Directories
TEMP_DIR = "temp_files"
IMAGE_DIR = os.path.join(TEMP_DIR, "compressed_images")
TEXT_DIR = os.path.join(TEMP_DIR, "alt_texts")
ZIP_PATH = os.path.join(TEMP_DIR, "compressed_results.zip")

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(TEXT_DIR, exist_ok=True)

# Function to extract images from PDF
def extract_images_from_pdf(pdf_bytes):
    pdf_document = fitz.open(stream=pdf_bytes, filetype="pdf")
    extracted_images = []

    for page_num in range(len(pdf_document)):
        for img_index, img in enumerate(pdf_document[page_num].get_images(full=True)):
            xref = img[0]
            base_image = pdf_document.extract_image(xref)
            img_bytes = base_image["image"]
            img_ext = base_image["ext"]

            # Save original image
            image_filename = f"page_{page_num + 1}_img_{img_index}.{img_ext}"
            original_path = os.path.join(IMAGE_DIR, image_filename)
            with open(original_path, "wb") as f:
                f.write(img_bytes)

            # Compress images
            compressed_path = os.path.join(IMAGE_DIR, f"compressed_{image_filename}")
            if img_ext in ["jpeg", "jpg", "png"]:
                compress_image(original_path, compressed_path, 100)  # Compress to 100KB
            elif img_ext == "gif":
                compress_gif(original_path, compressed_path, 500)  # Compress to 500KB
            else:
                os.rename(original_path, compressed_path)  # Keep original if unsupported

            extracted_images.append(compressed_path)

    return extracted_images

# Function to compress images
def compress_image(image_path, output_path, max_size_kb):
    """Compress an image (JPG/PNG) to a max size in KB."""
    image = Image.open(image_path)

    # Reduce quality in a loop until it fits the size
    quality = 95
    while quality > 10:
        image.save(output_path, "JPEG", quality=quality)
        if os.path.getsize(output_path) <= max_size_kb * 1024:
            break
        quality -= 5  # Reduce quality if still too big

def compress_gif(image_path, output_path, max_size_kb):
    """Compress a GIF to a max size in KB."""
    image = Image.open(image_path)
    
    if not isinstance(image, GifImagePlugin.GifImageFile):
        return  # Skip if not GIF

    image.save(output_path, format="GIF", optimize=True)
    
    # If still too big, reduce colors
    while os.path.getsize(output_path) > max_size_kb * 1024:
        image = image.convert("P", palette=Image.ADAPTIVE, colors=128)
        image.save(output_path, format="GIF", optimize=True)
# Function to generate alt texts

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

            # Save as a .txt file
            text_filename = os.path.join(TEXT_DIR, os.path.basename(img_path) + ".txt")
            with open(text_filename, "w", encoding="utf-8") as txt_file:
                txt_file.write(alt_text)

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

# Upload PDF and return ZIP file
@app.post("/upload_pdf/")
async def upload_pdf(file: UploadFile = File(...)):
    try:
        pdf_bytes = await file.read()
        image_paths = extract_images_from_pdf(pdf_bytes)

        if not image_paths:
            return {"error": "No images found in PDF."}

        # Generate alt texts
        alt_texts = get_alt_texts(image_paths)

        # Save alt texts to text files
        for img_path, alt_text in alt_texts.items():
            txt_filename = os.path.join(TEXT_DIR, f"{os.path.basename(img_path)}.txt")
            with open(txt_filename, "w") as txt_file:
                txt_file.write(alt_text)

        # Create ZIP archive
        with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zipf:
            for folder, _, files in os.walk(TEMP_DIR):
                for file in files:
                    file_path = os.path.join(folder, file)
                    zipf.write(file_path, os.path.relpath(file_path, TEMP_DIR))

        return FileResponse(ZIP_PATH, filename="compressed_results.zip", media_type="application/zip")

    except Exception as e:
        return {"error": str(e)}