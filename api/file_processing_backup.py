# /my_streaming_project/api/file_processing.py

import io
import zipfile
import httpx
import os
import json
from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import StreamingResponse
from fpdf import FPDF

# Tạo một router
router = APIRouter()

# --- CÁC HẰNG SỐ VÀ LỚP HỖ TRỢ ---
EXTERNAL_API_URL = "https://workflow.emg.edu.vn:5678/webhook/file-handle"
FONT_PATH = 'OpenSans-Regular.ttf' # Font file giờ ở thư mục gốc

class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not os.path.exists(FONT_PATH):
            raise FileNotFoundError(f"LỖI: Không tìm thấy file font '{FONT_PATH}'.")
        self.add_font('OpenSans', '', FONT_PATH, uni=True)
        self.set_font('OpenSans', '', 12)

    def add_multiline_text(self, text):
        self.add_page()
        self.multi_cell(0, 10, text)

# --- ENDPOINT CỦA ROUTER ---
@router.post("/process-and-zip/")
async def process_file_and_return_zip(file: UploadFile = File(...)):
    """
    Nhận file, gửi tới API ngoài, xử lý, tạo PDF, nén ZIP và trả về.
    """
    try:
        async with httpx.AsyncClient() as client:
            file_content = await file.read()
            files = {'file': (file.filename, file_content, file.content_type)}
            response = await client.post(EXTERNAL_API_URL, files=files, timeout=60.0)
            response.raise_for_status()
            api_data = response.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Lỗi khi gọi API ngoài: {exc}")

    # (Phần logic xử lý JSON, tạo PDF và ZIP giữ nguyên như cũ)
    def find_results_recursively(data):
        if isinstance(data, dict):
            if 'results' in data and isinstance(data['results'], list): return data['results']
            for value in data.values():
                found = find_results_recursively(value)
                if found is not None: return found
        elif isinstance(data, list):
            for item in data:
                found = find_results_recursively(item)
                if found is not None: return found
        return None

    text_chunks = find_results_recursively(api_data)
    if text_chunks is None:
        raise HTTPException(status_code=500, detail="Không tìm thấy key 'results' trong response.")

    pdf_files_in_memory = []
    for i, chunk in enumerate(text_chunks):
        pdf = PDF()
        pdf.add_multiline_text(str(chunk))
        pdf_output = pdf.output(dest='S') # Dữ liệu đã là bytes, không cần encode 
        pdf_files_in_memory.append((f"ket_qua_{i}.pdf", pdf_output))

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_name, data in pdf_files_in_memory:
            zip_file.writestr(file_name, data)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=tong_hop_ket_qua.zip"}
    )