from fastapi import FastAPI,UploadFile, HTTPException
from fastapi.responses import FileResponse, JSONResponse
import os
import uuid
from utils import *

from fastapi.middleware.cors import CORSMiddleware

# Add CORS middleware


app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Change this to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Setup logging


UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

tasks = {}

@app.get("/wakeup")
async def wakeup():
    return JSONResponse(content={"status": "awake"})

@app.post("/upload/")
async def upload_file(file: UploadFile):
    """ Uploads a file and returns a file ID """
    clean_dir(RESULTS_DIR)
    file_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_FOLDER, file_id + "_" + file.filename)
    
    try:
        with open(file_path, "wb") as f:
            f.write(await file.read())

        tasks[file_id] = {"status": "queued", "progress": 0, "file_path": file_path}
        return {"file_id": file_id, "message": "File uploaded successfully"}

    except Exception as e:
        log.error(f"File upload failed: {e}")
        raise HTTPException(status_code=500, detail="File upload failed")

@app.post("/process/{file_id}")
async def process_file(file_id: str):
    """ Processes a previously uploaded file and returns download URL """
    if file_id not in tasks:
        raise HTTPException(status_code=404, detail="Invalid file ID")

    try:
        file_path = tasks[file_id]["file_path"]

        # Check if file exists
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail="File not found")

        with open(file_path, "rb") as file:
            docx_bytes = file.read()
        log.info(f"File {file_path} read successfully")

        # Extract images
        image_paths = extract_images_from_docx(docx_bytes)
        if not image_paths:
            raise HTTPException(status_code=400, detail="No images found in document")
        
        # Update task status
        tasks[file_id]["status"] = "processing"
        tasks[file_id]["progress"] = 33

        # Get alt texts
        alt_texts = get_alt_texts(image_paths, file_id)
        log.info("Extracted alt texts")
        tasks[file_id]["progress"] = 66

        # Write alt texts to files
        for img_path, alt_text in alt_texts.items():
            try:
                txt_filename = os.path.join(TEXT_DIR, f"{img_path.split('.')[0]}.txt")
                with open(txt_filename, "w") as txt_file:
                    txt_file.write(alt_text)
            except Exception as e:
                log.error(f"Failed to write alt text for {img_path}: {e}")

        # Create zip file
        create_zip(file_id)
        log.info("Created ZIP file")
        tasks[file_id]["progress"] = 90

        # Processing complete
        tasks[file_id]["status"] = "completed"
        tasks[file_id]["progress"] = 100
        download_url = f"/download/{file_id}"
        
        return {"status": "completed", "download_url": download_url}

    except FileNotFoundError as e:
        log.error(f"File error: {e}")
        raise HTTPException(status_code=404, detail="File not found")
    
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")



@app.get("/download/{file_id}")
async def download_file(file_id: str):
    """ Allows the client to download the processed file """
    try:
        clean_temp_files()
        zip_file = zip_path(file_id)
        if file_id in tasks and os.path.exists(zip_file):
            return FileResponse(zip_file, filename=os.path.basename(zip_file))
        raise FileNotFoundError(f"ZIP file {zip_file} not found")
        
    except FileNotFoundError as e:
        log.error(e)
        raise HTTPException(status_code=404, detail="File not found")

    except Exception as e:
        log.error(f"File download failed: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")
    