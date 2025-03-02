import os
import io
import shutil
import zipfile
from PIL import Image, GifImagePlugin
from xml.etree import ElementTree
from typing_extensions import TypedDict, List
import logging
import colorlog
import httpx
import asyncio

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

class AltTexts(TypedDict):
    texts: List[str]

def add_to_database(alt_texts: AltTexts):
    pass

# Directories
TEMP_DIR = "temp_files"
ZIP_DIR = "results"
UPLOADS_DIR = "uploads"
RESULTS_DIR = "results"
IMAGE_DIR = lambda file_id: os.path.join(TEMP_DIR, file_id, "compressed_images")
TEXT_DIR = lambda file_id: os.path.join(TEMP_DIR, file_id, "alt_texts")
ZIP_PATH = os.path.join(ZIP_DIR, "compressed_results.zip")
zip_path = lambda file_id: ZIP_PATH.split(".")[0]+"_"+file_id+".zip"
temp_path = lambda file_id: os.path.join(TEMP_DIR, file_id)

os.makedirs(ZIP_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

async def extract_images_from_docx(docx_bytes, file_id):
    """Extract images from DOCX while preserving their order in the document."""
    extracted_images = []
    image_rels = {}  # Map relationship IDs to image files
    image_order = []  # Store the order of images as they appear
    
    # Create directories for this file ID
    temp_dir = os.path.join(TEMP_DIR, file_id)
    os.makedirs(temp_dir, exist_ok=True)
    os.makedirs(IMAGE_DIR(file_id), exist_ok=True)
    os.makedirs(TEXT_DIR(file_id), exist_ok=True)
    
    log.info("Extracting images from DOCX...")
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

        # Process images concurrently using asyncio tasks
        tasks = []
        for idx, img_name in enumerate(image_order, 1):
            tasks.append(
                process_image(docx_zip, img_name, idx, file_id)
            )
        
        # Wait for all image processing tasks to complete
        extracted_images = await asyncio.gather(*tasks)
        
    # Filter out None values from extracted_images (failed processing)
    extracted_images = [img for img in extracted_images if img]
    return sorted(extracted_images)

async def process_image(docx_zip, img_name, idx, file_id):
    try:
        img_data = docx_zip.read(f'word/media/{img_name}')
        temp_path = os.path.join(TEMP_DIR, file_id, f"temp_{img_name}")

        with open(temp_path, "wb") as img_file:
            img_file.write(img_data)

        base_name = f"{idx:03d}"
        if img_name.lower().endswith(("jpeg", "jpg")):
            compressed_path = os.path.join(IMAGE_DIR(file_id), f"compressed_{base_name}.jpg")
        elif img_name.lower().endswith("png"):
            compressed_path = os.path.join(IMAGE_DIR(file_id), f"compressed_{base_name}.jpg")  # Convert PNG to JPG
        elif img_name.lower().endswith("gif"):
            compressed_path = os.path.join(IMAGE_DIR(file_id), f"compressed_{base_name}.gif")
        else:
            compressed_path = os.path.join(IMAGE_DIR(file_id), f"compressed_{base_name}.jpg")  # Default to JPG

        # Run compression in a thread pool to not block the event loop
        if img_name.lower().endswith(("jpeg", "jpg", "png")):
            await asyncio.to_thread(compress_image, temp_path, compressed_path, 95)
        elif img_name.lower().endswith("gif"):
            await asyncio.to_thread(compress_gif, temp_path, compressed_path, 500)
        else:
            # Handle other formats
            try:
                img = Image.open(temp_path)
                # If the image has a palette mode (P), convert it to RGB
                if img.mode == 'P':
                    img = img.convert("RGBA")  # Convert P to RGBA first (preserves transparency)

                # If the image has transparency, we need to remove it before converting to JPEG
                if img.mode == 'RGBA':
                    background = Image.new("RGB", img.size, (255, 255, 255))  # Create a white background
                    img = Image.alpha_composite(background, img).convert("RGB")  # Merge and remove transparency

                img.save(compressed_path, "JPEG", quality=95)
            except Exception as e:
                log.error(f"Error converting unknown format: {e}")
                return None

        if os.path.exists(temp_path):
            os.remove(temp_path)
        
        return compressed_path

    except Exception as e:
        log.error(f"Error processing image {img_name}: {e}")
        return None

def compress_image(image_path, output_path, max_size_kb):
    log.debug(f"Compressing image: {image_path}...")
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
    log.debug(f"Compressing GIF: {image_path}...")
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
            log.error(f"Error during save attempt: {e}")

        if attempt < 1:
            scale_factor *= 0.7
            current_colors = max(64, current_colors // 2)
        else:
            scale_factor *= 0.7
            current_colors = max(64, current_colors - 32)

        attempt += 1

    return False

async def get_alt_texts(image_paths, file_id):
    log.debug("Processing images for alt text...")
    
    # Using httpx for async HTTP requests
    async with httpx.AsyncClient(timeout=60.0) as client:
        files_data = []
        for path in image_paths:
            with open(path, "rb") as img_file:
                img_content = img_file.read()
                files_data.append(("files", (os.path.basename(path), img_content, "image/jpeg")))
        
        try:
            response = await client.post("http://127.0.0.1:8001/generate-alt-texts", files=files_data)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            log.error(f"Error getting alt texts: {e}")
            # Return empty alt texts for all images as fallback
            return {os.path.basename(path): f"Image {i+1}" for i, path in enumerate(image_paths)}

async def create_zip(file_id):
    log.debug("Creating ZIP file...")
    # Run ZIP creation in a thread pool to not block the event loop
    return await asyncio.to_thread(_create_zip_sync, file_id)

def _create_zip_sync(file_id):
    """Synchronous version of create_zip for running in a thread pool"""
    with zipfile.ZipFile(zip_path(file_id), "w", zipfile.ZIP_DEFLATED) as zipf:
        for folder_func in [IMAGE_DIR, TEXT_DIR]:
            folder = folder_func(file_id)
            if os.path.exists(folder):
                for root, _, files in os.walk(folder):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zipf.write(file_path, os.path.relpath(file_path, os.path.join(TEMP_DIR, file_id)))
    log.debug(f"ZIP file created: {zip_path(file_id)}")
    return zip_path(file_id)

async def clean_dir(dir):
    try:
        if os.path.exists(dir):
            # Run removal in a thread pool to not block the event loop
            await asyncio.to_thread(shutil.rmtree, dir)
            log.info(f"✅ Deleted: {dir}")
        else:
            log.error(f"⚠️ Not found: {dir}")
    except Exception as e:
        log.error(f"❌ Error deleting: {e}")

    os.makedirs(RESULTS_DIR, exist_ok=True)

async def clean_temp_files(file_id):
    temp = temp_path(file_id)
    try:
        if os.path.exists(temp):
            # Run removal in a thread pool to not block the event loop
            await asyncio.to_thread(shutil.rmtree, temp)
            log.info(f"✅ Deleted: {temp}")
        else:
            log.error(f"⚠️ Not found: {temp}")

    except Exception as e:
        log.error(f"❌ Error deleting: {e}")
    

async def delete_path(path: str):
    """Asynchronously deletes a file or directory."""
    if not os.path.exists(path):
        return  # Path doesn't exist, nothing to delete

    try:
        if os.path.isfile(path) or os.path.islink(path):
            await asyncio.to_thread(os.remove, path)  # Remove file or symlink
        elif os.path.isdir(path):
            await asyncio.to_thread(shutil.rmtree, path)  # Remove directory and contents
    except Exception as e:
        print(f"Error deleting {path}: {e}")  # Replace with logging if needed