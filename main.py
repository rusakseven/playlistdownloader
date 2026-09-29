from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import yt_dlp
import uuid
import zipfile
import asyncio
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

app = FastAPI()
templates = Jinja2Templates(directory="templates")

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

executor = ThreadPoolExecutor(max_workers=2)

# ponytail: registry in-memory; hilang kalau server restart. Pindah ke redis kalau perlu persist.
jobs = {}


def finalize(job_id: str):
    """Zip semua hasil job, lalu hapus sumbernya. Sama untuk 1 lagu maupun playlist."""
    files = sorted(f for f in DOWNLOAD_DIR.glob(f"{job_id}_*") if f.suffix != ".zip")
    if not files:
        return {"status": "error", "error": "Tidak ada file hasil download"}

    zip_path = DOWNLOAD_DIR / f"{job_id}.zip"
    # ponytail: ZIP_STORED — mp3/m4a sudah terkompresi, deflate cuma buang CPU
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as z:
        for f in files:
            z.write(f, f.name[len(job_id) + 1:])

    count = len(files)
    for f in files:
        f.unlink()  # ponytail: langsung hapus, cegah disk numpuk (195MB sebelumnya)
    return {"status": "done", "zip": zip_path.name, "count": count}


def download_youtube(url: str, job_id: str, format: str = "mp3"):
    def hook(d):
        # ponytail: persen per-item, digabung posisi playlist sehingga jadi progres keseluruhan
        info = d.get('info_dict') or {}
        n = info.get('n_entries') or 1
        idx = info.get('playlist_index') or 1
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            done = d.get('downloaded_bytes') or 0
            frac = done / total if total else 0
            pct = ((idx - 1 + frac) / n) * 100
            # ponytail: clamp 99; 100 hanya saat job benar-benar selesai (post-processing jalan setelah unduh)
            jobs[job_id].update(progress=min(round(pct, 1), 99.0), title=info.get('title', ''))
        elif d['status'] == 'finished':
            jobs[job_id].update(progress=min(round(idx / n * 100, 1), 99.0))

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
        'progress_hooks': [hook],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.extract_info(url, download=True)


def download_spotify(url: str, job_id: str, format: str = "mp3"):
    from spotdl import Spotdl
    from spotdl.utils.config import get_config

    config = get_config()
    spotdl_client = Spotdl(client_id=config.client_id, client_secret=config.client_secret)

    songs = spotdl_client.search([url])
    if not songs:
        raise RuntimeError("No songs found")

    for i, song in enumerate(songs, 1):
        jobs[job_id].update(progress=min(round((i - 1) / len(songs) * 100, 1), 99.0), title=song.title)
        spotdl_client.download_song(song)
        for f in Path(".").glob(f"*{song.title}*.{format}"):
            f.rename(DOWNLOAD_DIR / f"{job_id}_{f.name}")


def run_download(job_id: str, url: str, format: str):
    jobs[job_id] = {"status": "running", "progress": 0}
    try:
        if "spotify.com" in url:
            download_spotify(url, job_id, format)
        else:
            download_youtube(url, job_id, format)
        jobs[job_id] = finalize(job_id)
    except Exception as e:
        jobs[job_id] = {"status": "error", "error": str(e)}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request},
        headers={"Cache-Control": "no-store"},  # ponytail: cegah HP memakai HTML lama
    )


@app.post("/download")
async def download(url: str = Form(...), format: str = Form("mp3")):
    job_id = str(uuid.uuid4())[:8]
    asyncio.get_event_loop().run_in_executor(executor, run_download, job_id, url, format)
    return {"job_id": job_id}


@app.get("/status/{job_id}")
async def status(job_id: str):
    return jobs.get(job_id, {"status": "not_found"})


@app.get("/zip/{job_id}")
async def get_zip(job_id: str):
    p = DOWNLOAD_DIR / f"{job_id}.zip"
    if p.exists():
        return FileResponse(p, filename=p.name, media_type="application/zip")
    return JSONResponse({"error": "Zip tidak ditemukan"}, status_code=404)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
