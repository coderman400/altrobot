import os
import io
import shutil
import zipfile
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image, GifImagePlugin
from dotenv import load_dotenv
from xml.etree import ElementTree
from google.api_core import retry
from typing_extensions import TypedDict,List
import logging
import colorlog
import requests

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

class AltTexts(TypedDict):
    texts: List[str]

def add_to_database(alt_texts: AltTexts):
    pass

# Load environment variables from .env file
load_dotenv()

# Access API Key
api_key = os.getenv("API_KEY")


# Configure Gemini API
genai.configure(api_key=api_key)
model = genai.GenerativeModel(model_name="gemini-2.0-flash", tools=[add_to_database])

# Directories
TEMP_DIR = "temp_files"
ZIP_DIR = "results"
UPLOADS_DIR = "uploads"
RESULTS_DIR = "results"
IMAGE_DIR = os.path.join(TEMP_DIR, "compressed_images")
TEXT_DIR = os.path.join(TEMP_DIR, "alt_texts")
ZIP_PATH = os.path.join(ZIP_DIR, "compressed_results.zip")
zip_path = lambda file_id : ZIP_PATH.split(".")[0]+"_"+file_id+".zip"

os.makedirs(ZIP_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(TEXT_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

def extract_images_from_docx(docx_bytes):
    """Extract images from DOCX while preserving their order in the document."""
    extracted_images = []
    image_rels = {}  # Map relationship IDs to image files
    image_order = []  # Store the order of images as they appear

    with zipfile.ZipFile(io.BytesIO(docx_bytes), "r") as docx_zip:
        # First, get the relationship mappings
        try:
            rels_content = docx_zip.read('word/_rels/document.xml.rels')
            rels_tree = ElementTree.fromstring(rels_content)

            # Map relationship IDs to image filenames
            for rel in rels_tree.findall('.//{http://schemas.openxmlformats.org/package/2006/relationships}Relationship'):
                rid = rel.get('Id')
                target = rel.get('Target')
                if 'media/' in target:
                    image_rels[rid] = target.split('/')[-1]
        except Exception as e:
            log.error(f"Error reading relationships: {e}")

        # Read the main document to get image order
        try:
            doc_content = docx_zip.read('word/document.xml')
            doc_tree = ElementTree.fromstring(doc_content)

            namespace = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
                        'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
                        'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}

            for img in doc_tree.findall('.//a:blip', namespace):
                rid = img.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed')
                if rid in image_rels:
                    image_order.append(image_rels[rid])
        except Exception as e:
            log.error(f"Error reading document structure: {e}")

        if not image_order:
            image_order = [name.split('/')[-1] for name in docx_zip.namelist()
                          if name.startswith('word/media/')]

        for idx, img_name in enumerate(image_order, 1):
            try:
                img_data = docx_zip.read(f'word/media/{img_name}')
                file_path = os.path.join(IMAGE_DIR, img_name)

                with open(file_path, "wb") as img_file:
                    img_file.write(img_data)

                base_name = f"{idx:03d}"
                if img_name.lower().endswith(("jpeg", "jpg")):
                    compressed_path = os.path.join(IMAGE_DIR, f"compressed_{base_name}.jpg")
                elif img_name.lower().endswith("png"):
                    compressed_path = os.path.join(IMAGE_DIR, f"compressed_{base_name}.jpg")  # Convert PNG to JPG
                elif img_name.lower().endswith("gif"):
                    compressed_path = os.path.join(IMAGE_DIR, f"compressed_{base_name}.gif")
                else:
                    compressed_path = os.path.join(IMAGE_DIR, f"compressed_{base_name}.jpg")  # Default to JPG

                if img_name.lower().endswith(("jpeg", "jpg", "png")):
                    compress_image(file_path, compressed_path, 95)
                elif img_name.lower().endswith("gif"):
                    compress_gif(file_path, compressed_path, 500)
                else:
                    try:
                        # If the image has a palette mode (P), convert it to RGB
                        if img.mode == 'P':
                            img = img.convert("RGBA")  # Convert P to RGBA first (preserves transparency)

                        # If the image has transparency, we need to remove it before converting to JPEG
                        if img.mode == 'RGBA':
                            background = Image.new("RGB", img.size, (255, 255, 255))  # Create a white background
                            img = Image.alpha_composite(background, img).convert("RGB")  # Merge and remove transparency

                        img.save(compressed_path, "JPEG", quality=95)
                    except Exception as e:
                        print(f"Error converting unknown format: {e}")
                        continue

                if os.path.exists(file_path):
                    os.remove(file_path)
                extracted_images.append(compressed_path)

            except Exception as e:
                log.error(f"Error processing image {img_name}: {e}")

    return sorted(extracted_images)

def compress_image(image_path, output_path, max_size_kb):
    """Compress an image (JPG/PNG) to a max size in KB."""
    image = Image.open(image_path)

    if image.mode == "RGBA":
        image = image.convert("RGB")

    quality = 95
    while quality > 10:
        image.save(output_path, "JPEG", quality=quality)
        if os.path.getsize(output_path) <= max_size_kb * 1024:
            break
        quality -= 5

def compress_gif(image_path, output_path, max_size_kb, max_attempts=3):
    """Compress a GIF while preserving animation."""
    image = Image.open(image_path)
    if not isinstance(image, GifImagePlugin.GifImageFile):
        log.warning(f"Skipping {image_path}: Not a valid GIF")
        return

    original_width, original_height = image.size
    frames = []
    durations = []

    try:
        for frame in range(image.n_frames):
            image.seek(frame)
            frame_image = image.copy()
            frames.append(frame_image)
            durations.append(max(20, int(image.info.get("duration", 100) * 0.8)))
    except EOFError:
        pass

    attempt = 0
    scale_factor = 1.0
    current_colors = 256

    while attempt < max_attempts:
        new_width = max(50, int(original_width * scale_factor))
        new_height = max(50, int(original_height * scale_factor))

        processed_frames = []
        for frame in frames:
            resized = frame.resize((new_width, new_height), Image.Resampling.LANCZOS)
            processed = resized.convert("P", palette=Image.ADAPTIVE, colors=current_colors)
            processed_frames.append(processed)

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
            if compressed_size_kb <= max_size_kb:
                return True

        except Exception as e:
            log.error("Error during save attempt: {e}")

        if attempt < 1:
            scale_factor *= 0.7
            current_colors = max(64, current_colors // 2)
        else:
            scale_factor *= 0.7
            current_colors = max(64, current_colors - 32)

        attempt += 1

    return False

def get_alt_texts(image_paths, batch_size=8):
    files_data = []
    for path in image_paths:
        with open(f"{path}", "rb") as img_file:
            files_data.append(("files", (os.path.basename(path), img_file.read(), "image/jpeg")))
    
    response = requests.post("http://127.0.0.1:8001/generate-alt-texts", files=files_data)
    return response.json()


def create_zip(file_id):
    with zipfile.ZipFile(zip_path(file_id), "w", zipfile.ZIP_DEFLATED) as zipf:
        for folder in [IMAGE_DIR, TEXT_DIR]:
            for root, _, files in os.walk(folder):
                for file in files:
                    file_path = os.path.join(root, file)
                    zipf.write(file_path, os.path.relpath(file_path, TEMP_DIR))
    log.info(f"ZIP file created: {zip_path(file_id)}")
    return zip_path(file_id)


def clean_dir(dir):
    try:
        if os.path.exists(dir):
            shutil.rmtree(dir)
            log.info(f"✅ Deleted: {dir}")
        else:
            log.error(f"⚠️ Not found: {dir}")
    except Exception as e:
        log.error(f"❌ Error deleting: {e}")

    os.makedirs(RESULTS_DIR,exist_ok=True)


def clean_temp_files():
    try:
        if os.path.exists(TEMP_DIR):
            shutil.rmtree(TEMP_DIR)
            log.info(f"✅ Deleted: {TEMP_DIR}")
        else:
            log.error(f"⚠️ Not found: {TEMP_DIR}")

        if os.path.exists(UPLOADS_DIR):
            shutil.rmtree(UPLOADS_DIR)
            log.info(f"✅ Deleted: {UPLOADS_DIR}")
        else:
            log.error(f"⚠️ Not found: {UPLOADS_DIR}")

    except Exception as e:
        log.error(f"❌ Error deleting: {e}")

    # Recreate directories
    os.makedirs(UPLOADS_DIR, exist_ok=True)
    os.makedirs(IMAGE_DIR, exist_ok=True)
    os.makedirs(TEXT_DIR, exist_ok=True)
    log.info("✅ Directories recreated.")