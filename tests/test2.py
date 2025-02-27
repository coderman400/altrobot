import requests
from typing import List
import os
from pathlib import Path

IMAGES_DIR = "temp_files/compressed_images"
os.makedirs("uploaded_images",exist_ok=True)

def call_alt_text_api(image_paths: List[str]):
    files_data = []
    for path in image_paths:
        with open(f"{IMAGES_DIR}/{path}", "rb") as img_file:
            files_data.append(("files", (path, img_file.read(), "image/jpeg")))
    
    response = requests.post("https://alt-generator.onrender.com/generate-alt-texts", files=files_data)
    return response.json()

images = os.listdir("temp_files/compressed_images")

print(call_alt_text_api(images))