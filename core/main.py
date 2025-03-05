from fastapi import FastAPI, UploadFile, HTTPException,BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
import os
import uuid
from utils import *
import asyncio

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

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

tasks = {}

@app.get("/wakeup")
async def wakeup():
    return JSONResponse(content={"status": "awake"})

@app.post("/upload/")
async def upload_file(file: UploadFile):
    """ Uploads a file and returns a file ID """
    file_id = str(uuid.uuid4())
    file_path = os.path.join(UPLOAD_FOLDER, file_id + "_" + file.filename)
    
    try:
        # Read file content asynchronously
        content = await file.read()
        
        # Write to disk using an async thread pool
        await asyncio.to_thread(lambda: open(file_path, "wb").write(content))

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

        # Read the file asynchronously using a thread pool
        docx_bytes = await asyncio.to_thread(lambda: open(file_path, "rb").read())
        await delete_path(file_path)
        log.debug(f"File {os.path.basename(file_path)} read successfully")

        # Extract images asynchronously
        image_paths = await extract_images_from_docx(docx_bytes, file_id)
        if not image_paths:
            raise HTTPException(status_code=400, detail="No images found in document")
        
        # Update task status
        tasks[file_id]["status"] = "processing"
        tasks[file_id]["progress"] = 33

        # Get alt texts asynchronously
        alt_texts = await get_alt_texts(image_paths, file_id)
        log.debug("Extracted alt texts")
        tasks[file_id]["progress"] = 66

        # Write alt texts to files asynchronously
        write_tasks = []
        for img_path in image_paths:
            img_name = os.path.basename(img_path)
            if img_name in alt_texts:
                alt_text = alt_texts[img_name]
                txt_filename = os.path.join(TEXT_DIR(file_id), f"{os.path.splitext(img_name)[0]}.txt")
                
                # Create a task to write each alt text file
                async def write_alt_text(filename, text):
                    await asyncio.to_thread(lambda: open(filename, "w").write(text))
                
                write_tasks.append(write_alt_text(txt_filename, alt_text))
        
        # Wait for all text files to be written
        await asyncio.gather(*write_tasks)

        # Create zip file asynchronously
        await create_zip(file_id)
        log.debug("Created ZIP file")
        tasks[file_id]["progress"] = 90

        # Processing complete
        tasks[file_id]["status"] = "completed"
        tasks[file_id]["progress"] = 100
        download_url = f"/download/{file_id}"
        
        await clean_temp_files(file_id)
        return {"status": "completed", "download_url": download_url}

    except FileNotFoundError as e:
        log.error(f"File error: {e}")
        raise HTTPException(status_code=404, detail="File not found")
    
    except Exception as e:
        log.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get("/download/{file_id}")
async def download_file(file_id: str, background_tasks: BackgroundTasks):
    """ Allows the client to download the processed file """
    try:
        zip_file = zip_path(file_id)
        if file_id in tasks and os.path.exists(zip_file):
            background_tasks.add_task(delete_path, zip_file)
            return FileResponse(zip_file, filename=os.path.basename(zip_file))
        raise FileNotFoundError(f"ZIP file {zip_file} not found")
        
    except FileNotFoundError as e:
        log.error(e)
        raise HTTPException(status_code=404, detail="File not found")

    except Exception as e:
        log.error(f"File download failed: {e}")
        raise HTTPException(status_code=500, detail="Internal Server Error")