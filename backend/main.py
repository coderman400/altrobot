import os
import io
import shutil
import zipfile
from fastapi import FastAPI, UploadFile, File, Response
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

def compress_gif(image_path, output_path, max_size_kb, max_attempts=3):
    """Compress a GIF while preserving animation."""
    image = Image.open(image_path)
    if not isinstance(image, GifImagePlugin.GifImageFile):
        print(f"Skipping {image_path}: Not a valid GIF")
        return

    # Store original dimensions for scale calculation
    original_width, original_height = image.size
    
    frames = []
    durations = []
    
    # Extract frames and durations
    try:
        for frame in range(image.n_frames):
            image.seek(frame)
            frame_image = image.copy()
            frames.append(frame_image)
            durations.append(max(20, int(image.info.get("duration", 100) * 0.8)))  # More aggressive duration reduction
    except EOFError:
        pass  # Handle corruption gracefully
        
    attempt = 0
    scale_factor = 1.0
    
    # Start with more aggressive initial reduction
    current_colors = 256
    while attempt < max_attempts:
        # Calculate new dimensions
        new_width = max(50, int(original_width * scale_factor))
        new_height = max(50, int(original_height * scale_factor))
        
        # Process frames with current settings
        processed_frames = []
        for frame in frames:
            # Resize first
            resized = frame.resize((new_width, new_height), Image.Resampling.LANCZOS)
            # Then reduce colors
            processed = resized.convert("P", palette=Image.ADAPTIVE, colors=current_colors)
            processed_frames.append(processed)
            
        # Save current attempt
        try:
            processed_frames[0].save(
                output_path,
                format="GIF",
                save_all=True,
                append_images=processed_frames[1:],
                optimize=True,
                loop=image.info.get("loop", 0),
                duration=durations,
                disposal=2
            )
            
            compressed_size_kb = os.path.getsize(output_path) / 1024
            print(f"Attempt {attempt + 1}: Compressed GIF size = {compressed_size_kb:.2f} KB")
            print(f"Current dimensions: {new_width}x{new_height}, Colors: {current_colors}")
            
            if compressed_size_kb <= max_size_kb:
                print("✅ GIF compression successful")
                return True
                
        except Exception as e:
            print(f"Error during save attempt: {e}")
            
        # More aggressive reduction strategy
        if attempt < 1:
            # First tries: reduce colors
            scale_factor *= 0.7 
            current_colors = max(64, current_colors // 2)
        else:
            # Later tries: reduce both size and colors
            scale_factor *= 0.7  # More aggressive size reduction
            current_colors = max(64, current_colors - 32)  # Gradual color reduction
            
        attempt += 1
        
    print("⚠️ GIF compression failed to reach the desired size limit.")
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
        # Clean up before starting new process
        if os.path.exists(ZIP_PATH):
            try:
                os.remove(ZIP_PATH)
            except Exception as e:
                print(f"Could not remove existing ZIP: {e}")
                
        # Clean directories but keep the structure
        for folder in [IMAGE_DIR, TEXT_DIR]:
            if os.path.exists(folder):
                for filename in os.listdir(folder):
                    file_path = os.path.join(folder, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.unlink(file_path)
                    except Exception as e:
                        print(f"Error deleting {file_path}: {e}")

        # Process the file
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
        
        # Read the ZIP file into memory before sending
        with open(ZIP_PATH, 'rb') as f:
            zip_data = f.read()
            
        # Clean up after reading the file
        try:
            for folder in [IMAGE_DIR, TEXT_DIR]:
                for filename in os.listdir(folder):
                    file_path = os.path.join(folder, filename)
                    try:
                        if os.path.isfile(file_path):
                            os.unlink(file_path)
                    except Exception as e:
                        print(f"Error during cleanup: {e}")
                        
            if os.path.exists(ZIP_PATH):
                os.unlink(ZIP_PATH)
        except Exception as e:
            print(f"Cleanup error: {e}")

        # Return the ZIP data from memory
        return Response(
            content=zip_data,
            media_type="application/zip",
            headers={
                "Content-Disposition": "attachment; filename=compressed_results.zip"
            }
        )

    except Exception as e:
        return {"error": str(e)}