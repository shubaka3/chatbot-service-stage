import io
import zipfile
import httpx
import os
import re
import json
from fastapi import APIRouter, File, UploadFile, Form, HTTPException
from fastapi.responses import StreamingResponse
from fpdf import FPDF
from unidecode import unidecode 

# Tạo một router
router = APIRouter()

# --- CÁC HẰNG SỐ VÀ LỚP HỖ TRỢ ---
EXTERNAL_API_URL = "https://workflow.emg.edu.vn:5678/webhook/file-handle"
FONT_PATH = 'OpenSans-Regular.ttf'

class PDF(FPDF):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            # Giả định font đã được đặt đúng chỗ
            self.add_font('OpenSans', '', FONT_PATH, uni=True)
            self.set_font('OpenSans', '', 12)
        except Exception as e:
            # Nếu không tìm thấy font, chuyển sang font mặc định (sẽ gây lỗi hiển thị TV nếu không có font TV)
            print(f"CẢNH BÁO: Không thể thêm font '{FONT_PATH}'. Sẽ sử dụng font mặc định. Lỗi: {e}")
            self.set_font('Arial', '', 12)

    def add_multiline_text(self, text):
        self.add_page()
        try:
            self.set_font('OpenSans', '', 12)
        except Exception:
            self.set_font('Arial', '', 12)

        self.multi_cell(0, 5, text) # Giảm chiều cao dòng để hiển thị tốt hơn

# Hàm chuẩn hóa tên file từ tiêu đề (slugify)
def slugify_filename(title: str) -> str:
    """Chuyển tiêu đề thành tên file không dấu, chữ thường, gạch dưới."""
    text = unidecode(title).strip().lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '_', text)
    return text.strip('_')

# --- ENDPOINT CỦA ROUTER ---
@router.post("/process-and-zip/")
async def process_file_and_return_zip(
    file: UploadFile = File(...),
    chapter_name: str = Form(..., description="Tên chương để đặt tên file và tham chiếu.")
):
    """
    Nhận file và tên chương, gửi file tới API ngoài, xử lý, tạo PDF, nén ZIP và trả về.
    """
    try:
        async with httpx.AsyncClient() as client:
            file_content = await file.read()
            
            # Chuẩn bị files (nhị phân) và data (chuỗi) để gửi tới API ngoài
            files = {'file': (file.filename, file_content, file.content_type)}
            data = {'chapter_name': chapter_name} 

            # Gửi request với cả files (binary) và data (chuỗi/text)
            response = await client.post(
                EXTERNAL_API_URL, 
                files=files, 
                data=data,  
                timeout=60.0
            )
            
            response.raise_for_status()
            api_data = response.json()
            
            # --- DEBUG LOG ---
            print("--- DEBUG API RESPONSE START ---")
            print("API DATA TYPE:", type(api_data))
            if isinstance(api_data, list) and api_data:
                 print("API DATA FIRST ITEM KEYS:", api_data[0].keys())
            print("--- DEBUG API RESPONSE END ---")
            # --- DEBUG LOG ---
            
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Lỗi khi gọi API ngoài: {exc}")
    except httpx.HTTPStatusError as exc:
        # Nếu n8n trả về lỗi HTTP, ta hiển thị lỗi của n8n
        raise HTTPException(status_code=exc.response.status_code, detail=f"API ngoài trả về lỗi HTTP: {exc.response.text}")
    except json.JSONDecodeError as exc:
        # Xử lý nếu phản hồi không phải là JSON hợp lệ
        print(f"LỖI JSON DECODE: {exc}")
        raise HTTPException(status_code=500, detail=f"API ngoài trả về dữ liệu không phải JSON hợp lệ.")

    # LOGIC: Truy cập dữ liệu với Try-Except chi tiết và linh hoạt hơn (Xử lý cả Dict và List bọc)
    try:
        data_container = None
        
        if isinstance(api_data, list) and api_data:
            # Trường hợp 1: [ { "data": [...] } ] 
            data_container = api_data[0]
        elif isinstance(api_data, dict):
            # Trường hợp 2: { "data": [...] } 
            data_container = api_data
        else:
            raise ValueError("Phản hồi không phải là List cũng không phải Dictionary.")

        if 'data' not in data_container or not isinstance(data_container['data'], list):
            raise ValueError("Thiếu key 'data' hoặc 'data' không phải là một mảng (List).")

        text_chunks = data_container['data']
        
        # Kiểm tra cuối cùng: đảm bảo các chunk có key 'chunkContent'
        if not all(isinstance(chunk, dict) and 'chunkContent' in chunk for chunk in text_chunks):
             raise ValueError("Mảng 'data' không chứa các chunk hợp lệ (thiếu 'chunkContent').")

    except Exception as e:
        # Nếu bất kỳ lỗi truy cập nào xảy ra, chúng ta báo lỗi cấu trúc
        print(f"LỖI CẤU TRÚC CHI TIẾT: {e}") 
        raise HTTPException(status_code=500, detail=f"Cấu trúc dữ liệu API trả về không hợp lệ. Chi tiết: {e}")

    # --- TẠO PDF VÀ NÉN ZIP ---
    pdf_files_in_memory = []
    
    for i, chunk in enumerate(text_chunks):
        chunk_content = chunk.get("chunkContent", "")
        section_title = chunk.get("sectionTitle", f"ket_qua_{i}")
        section_number = chunk.get("sectionNumber", "")
        
        # Tạo tên file chuẩn hóa: VD: 1_1_thong_tin_va_quyet_dinh.pdf
        filename_base = slugify_filename(f"{section_number}_{section_title}" if section_number else section_title)
        
        pdf = PDF()
        pdf.add_multiline_text(chunk_content) 
        
        pdf_output = pdf.output(dest='S')
        
        pdf_files_in_memory.append((f"{filename_base}.pdf", pdf_output))

    # Nén ZIP và trả về
    zip_buffer = io.BytesIO()
    # Tên file zip sử dụng chapter_name
    zip_filename_slug = slugify_filename(chapter_name) if chapter_name else "tong_hop_ket_qua"
    
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_name, data in pdf_files_in_memory:
            zip_file.writestr(file_name, data)

    zip_buffer.seek(0)
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={zip_filename_slug}.zip"}
    )