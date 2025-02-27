from fastapi import FastAPI, WebSocket, UploadFile, HTTPException
from fastapi.responses import FileResponse
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

@app.websocket("/ws/{file_id}")
async def websocket_endpoint(websocket: WebSocket, file_id: str):
    """ Handles WebSocket communication for document processing """
    await websocket.accept()
    
    if file_id not in tasks:
        await websocket.send_json({"status": "error", "message": "Invalid file ID"})
        await websocket.close()
        return

    try:
        file_path = tasks[file_id]["file_path"]

        # Check if file exists
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File {file_path} not found")

        with open(file_path, "rb") as file:
            docx_bytes = file.read()
        log.info(f"File {file_path} read successfully")

        image_paths = extract_images_from_docx(docx_bytes)
        if not image_paths:
            await websocket.send_json({"status": "error", "message": "No images found in document."})
            await websocket.close()
            return
        
        await websocket.send_json({"status": "processing", "progress": 33})

        alt_texts = get_alt_texts(image_paths, file_id)
        log.info("Extracted alt texts")
        await websocket.send_json({"status": "processing", "progress": 66})

        for img_path, alt_text in alt_texts.items():
            try:
                txt_filename = os.path.join(TEXT_DIR, f"{img_path.split(".")[0]}.txt")
                with open(txt_filename, "w") as txt_file:
                    txt_file.write(alt_text)
            except Exception as e:
                log.error(f"Failed to write alt text for {img_path}: {e}")

        create_zip(file_id)
        log.info("Created ZIP file")
        await websocket.send_json({"status": "processing", "progress": 90})

        # Processing complete
        tasks[file_id]["status"] = "completed"
        download_url = f"/download/{file_id}"
        
        await websocket.send_json({"status": "completed", "progress": 100, "download_url": download_url})
        await websocket.close()

        # Cleanup temporary files
        

    except FileNotFoundError as e:
        log.error(f"File error: {e}")
        await websocket.send_json({"status": "error", "message": "File not found"})
        await websocket.close()
    
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        await websocket.send_json({"status": "error", "message": "Internal server error"})
        await websocket.close()



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
    