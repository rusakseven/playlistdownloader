from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import yt_dlp
import spotdl
import os
import uuid
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

app = FastAPI()
templates = Jinja2Templates(directory="templates")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

executor = ThreadPoolExecutor(max_workers=2)

jobs = {}

def download_youtube(url: str, job_id: str, format: str = "mp3"):
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(DOWNLOAD_DIR / f'{job_id}_%(title)s.%(ext)s'),
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': format,
                'preferredquality': '192',
            }],
            'quiet': True,
            'no_warnings': True,
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            base = os.path.splitext(filename)[0] + f".{format}"
            return {"status": "done", "file": base, "title": info.get('title', 'unknown')}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def download_spotify(url: str, job_id: str, format: str = "mp3"):
    try:
        from spotdl import Spotdl
        from spotdl.types.song import Song
        from spotdl.utils.config import get_config
        
        config = get_config()
        spotdl_client = Spotdl(client_id=config.client_id, client_secret=config.client_secret)
        
        songs = spotdl_client.search([url])
        if not songs:
            return {"status": "error", "error": "No songs found"}
        
        results = []
        for song in songs:
            spotdl_client.download_song(song)
            # spotdl saves to current dir, find the file
            for f in Path(".").glob(f"*{song.title}*.{format}"):
                target = DOWNLOAD_DIR / f"{job_id}_{f.name}"
                f.rename(target)
                results.append({"file": str(target), "title": song.title})
        
        return {"status": "done", "results": results}
    except Exception as e:
        return {"status": "error", "error": str(e)}

def run_download(job_id: str, url: str, format: str):
    jobs[job_id] = {"status": "running", "progress": 0}
    try:
        if "spotify.com" in url or "open.spotify.com" in url:
            result = download_spotify(url, job_id, format)
        else:
            result = download_youtube(url, job_id, format)
        jobs[job_id] = {"status": "done", **result}
    except Exception as e:
        jobs[job_id] = {"status": "error", "error": str(e)}

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/download")
async def download(url: str = Form(...), format: str = Form("mp3")):
    job_id = str(uuid.uuid4())[:8]
    loop = asyncio.get_event_loop()
    loop.run_in_executor(executor, run_download, job_id, url, format)
    return {"job_id": job_id}

@app.get("/status/{job_id}")
async def status(job_id: str):
    return jobs.get(job_id, {"status": "not_found"})

@app.get("/file/{job_id}/{filename}")
async def get_file(job_id: str, filename: str):
    file_path = DOWNLOAD_DIR / f"{job_id}_{filename}"
    if file_path.exists():
        return FileResponse(file_path, filename=filename)
    return JSONResponse({"error": "File not found"}, status_code=404)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)