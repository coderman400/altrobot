import os
import io
import shutil
import zipfile
from flask import Flask, request, send_file, jsonify
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from PIL import Image, GifImagePlugin
from tqdm import tqdm
from dotenv import load_dotenv
from xml.etree import ElementTree
from flask_cors import CORS
from google.api_core import retry
from typing_extensions import TypedDict,List

class AltTexts(TypedDict):
    texts: List[str]

def add_to_database(alt_texts: AltTexts):
    pass

# Load environment variables from .env file
load_dotenv()

# Access API Key
api_key = os.getenv("API_KEY")

# Initialize Flask
app = Flask(__name__)

CORS(app, resources={
    r"/upload_pdf": {
        "origins": "*",
        "methods": ["POST", "OPTIONS"],
        "allow_headers": ["Content-Type", "Authorization"]
    },
    r"/wakeup": {
        "origins": "*",
        "methods": ["GET", "OPTIONS"]
    }
})

# Configure Gemini API
genai.configure(api_key=api_key)
model = genai.GenerativeModel(model_name="gemini-2.0-flash",tools=[add_to_database])

# Directories
TEMP_DIR = "temp_files"
IMAGE_DIR = os.path.join(TEMP_DIR, "compressed_images")
TEXT_DIR = os.path.join(TEMP_DIR, "alt_texts")
ZIP_PATH = os.path.join(TEMP_DIR, "compressed_results.zip")

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(TEXT_DIR, exist_ok=True)

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
            print(f"Error reading relationships: {e}")

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
            print(f"Error reading document structure: {e}")

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
                    compress_image(file_path, compressed_path, 100)
                elif img_name.lower().endswith("gif"):
                    compress_gif(file_path, compressed_path, 500)
                else:
                    try:
                        img = Image.open(file_path)
                        if img.mode == "RGBA":
                            img = img.convert("RGB")
                        img.save(compressed_path, "JPEG", quality=95)
                    except Exception as e:
                        print(f"Error converting unknown format: {e}")
                        continue

                if os.path.exists(file_path):
                    os.remove(file_path)

                print(f"Processed image {idx}: {img_name}")
                extracted_images.append(compressed_path)

            except Exception as e:
                print(f"Error processing image {img_name}: {e}")

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
        print(f"Skipping {image_path}: Not a valid GIF")
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
            print(f"Attempt {attempt + 1}: Compressed GIF size = {compressed_size_kb:.2f} KB")
            print(f"Current dimensions: {new_width}x{new_height}, Colors: {current_colors}")

            if compressed_size_kb <= max_size_kb:
                print("✅ GIF compression successful")
                return True

        except Exception as e:
            print(f"Error during save attempt: {e}")

        if attempt < 1:
            scale_factor *= 0.7
            current_colors = max(64, current_colors // 2)
        else:
            scale_factor *= 0.7
            current_colors = max(64, current_colors - 32)

        attempt += 1

    print("⚠️ GIF compression failed to reach the desired size limit.")
    return False

def get_alt_texts(image_paths, batch_size=8):
    """Processes images in batches and retrieves alt texts."""
    alt_texts = {}

    for i in range(0, len(image_paths), batch_size):
        batch = image_paths[i:i + batch_size]

        try:
            print(f"🖼️ Processing batch: {batch}")

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
                alt_texts[img] = alt_text

            print(f"✅ Batch processed: {alt_text_list}")

        except Exception as e:
            alt_texts[img_path] = f"Error: {str(e)}"

    return alt_texts

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

@app.route("/upload_pdf", methods=["POST"])
def upload_pdf():
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file provided"}), 400

        file = request.files["file"]
        if file.filename == "":
            return jsonify({"error": "No file selected"}), 400

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
        docx_bytes = file.read()
        print("READ FILE!")
        image_paths = extract_images_from_docx(docx_bytes)
        if not image_paths:
            return jsonify({"error": "No images found in PDF."}), 400
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
            return jsonify({"error": f"ZIP file missing at {ZIP_PATH}"}), 500

        try:
            return send_file(
                ZIP_PATH,
                mimetype='application/zip',
                as_attachment=True,
                download_name='compressed_results.zip',
                max_age=0,  # Prevent caching
            )
        finally:
            # Clean up after sending the file
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

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/wakeup")
def wakeup():
    return jsonify({"message": "Backend is awake!"})

if __name__ == "__main__":
    app.run()