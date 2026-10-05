import os
import re
import time
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from flask import Flask, render_template, request, jsonify, send_from_directory

UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")
WORKERS = 4
RETRIES = 3
DOWNLOAD_ROOT = os.path.abspath("downloads")
os.makedirs(DOWNLOAD_ROOT, exist_ok=True)

EXT_RE = r"(?:jpe?g|png|webp|gif|bmp)"
IMG_TAG = re.compile(r"<img\b[^>]*>", re.I | re.S)
ANY_URL = re.compile(r'''(?:https?:)?//[^\s"'<>\\()]+?\.''' + EXT_RE + r'''(?:\?[^\s"'<>\\()]*)?''', re.I)
QUOTED = re.compile(r'''["']([^"'<>\s]+?\.''' + EXT_RE + r'''(?:\?[^"'<>\s]*)?)["']''', re.I)

app = Flask(__name__)
jobs = {}
jobs_lock = threading.Lock()


def fetch(url, referer):
    req = Request(url, headers={"User-Agent": UA, "Referer": referer, "Accept": "*/*"})
    return urlopen(req, timeout=30)


def extract_images(html, base):
    html = html.replace("\\/", "/").replace("&amp;", "&")
    found = ANY_URL.findall(html)
    for tag in IMG_TAG.findall(html):
        found += QUOTED.findall(tag)
    seen, out = set(), []
    for link in found:
        link = urljoin(base, link)
        if link not in seen:
            seen.add(link)
            out.append(link)
    return out


def download(url, dest_dir, referer, idx):
    parsed = urlparse(url)
    name = os.path.basename(parsed.path) or f"img_{idx}.jpg"
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)[:180]
    path = os.path.join(dest_dir, f"{idx:03d}_{name}")
    for attempt in range(1, RETRIES + 1):
        try:
            with fetch(url, referer) as r, open(path, "wb") as f:
                while True:
                    chunk = r.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
            return True
        except Exception:
            if attempt < RETRIES:
                time.sleep(attempt)
    return False


def update(job_id, **values):
    with jobs_lock:
        jobs[job_id].update(values)


def run_job(job_id, links):
    try:
        jobs_found = []
        for n, link in enumerate(links, 1):
            update(job_id, status=f"Lecture de la page {n}/{len(links)}…")
            try:
                with fetch(link, link) as r:
                    html = r.read().decode("utf-8", "ignore")
            except Exception as e:
                update(job_id, status=f"Page {n} impossible à lire : {e}")
                continue
            part = [p for p in urlparse(link).path.split("/") if p]
            album_name = re.sub(r"[^A-Za-z0-9._-]", "_", part[-1] if part else "page")
            sub = os.path.join(DOWNLOAD_ROOT, job_id, f"album_{n}_{album_name}")
            os.makedirs(sub, exist_ok=True)
            for i, img in enumerate(extract_images(html, link), 1):
                jobs_found.append((img, sub, link, i))
            del html

        total = len(jobs_found)
        update(job_id, total=total, status="Téléchargement…")
        if not total:
            update(job_id, done=True, status="Aucune image trouvée dans le HTML.", progress=100)
            return

        done = 0
        fail = 0
        lock = threading.Lock()

        def task(j):
            nonlocal done, fail
            ok = download(*j)
            with lock:
                done += 1
                if not ok:
                    fail += 1
                update(job_id, done_count=done, failed=fail,
                       progress=round(done * 100 / total),
                       status=f"{done}/{total} images" + (f" · {fail} échec(s)" if fail else ""))

        with ThreadPoolExecutor(WORKERS) as ex:
            list(ex.map(task, jobs_found))

        update(job_id, done=True, progress=100,
               status=f"Terminé : {total - fail}/{total} image(s) téléchargée(s).")
    except Exception as e:
        update(job_id, done=True, error=True, status=f"Erreur : {e}")


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/start")
def start():
    data = request.get_json(silent=True) or {}
    raw = data.get("urls", "")
    links = [u.strip() for u in raw.splitlines() if u.strip()]
    if not links:
        return jsonify({"error": "Colle au moins un lien Yupoo."}), 400
    for link in links:
        p = urlparse(link)
        if p.scheme not in ("http", "https") or not p.netloc:
            return jsonify({"error": f"Lien invalide : {link}"}), 400
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"progress": 0, "done_count": 0, "failed": 0, "total": 0,
                        "status": "Préparation…", "done": False, "error": False}
    threading.Thread(target=run_job, args=(job_id, links), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.get("/api/status/<job_id>")
def status(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Tâche introuvable."}), 404
    return jsonify(job)


@app.get("/api/download/<job_id>")
def download_zip(job_id):
    # Zip created on demand to keep the downloader simple.
    import shutil
    import zipfile
    root = os.path.join(DOWNLOAD_ROOT, job_id)
    if not os.path.isdir(root):
        return jsonify({"error": "Téléchargement introuvable."}), 404
    zip_path = os.path.join(DOWNLOAD_ROOT, f"yupoo_{job_id}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for base, _, files in os.walk(root):
            for name in files:
                path = os.path.join(base, name)
                z.write(path, os.path.relpath(path, root))
    return send_from_directory(DOWNLOAD_ROOT, os.path.basename(zip_path), as_attachment=True)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
