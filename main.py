# /my_streaming_project/main.py

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# Import các router từ thư mục api
from api import file_processing

# --- KHỞI TẠO ỨNG DỤNG FASTAPI CHÍNH ---
app = FastAPI(
    title="Main Project API",
    description="Một API tích hợp cả WebRTC Signaling và Dịch vụ Xử lý File.",
    version="1.0.0"
)

# --- CẤU HÌNH MIDDLEWARE CHUNG ---
# Middleware này sẽ được áp dụng cho TẤT CẢ các router được gắn vào.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/ui", StaticFiles(directory="ui"), name="ui")

# 2. UI production
app.mount("/productionui", StaticFiles(directory="productionui"), name="productionui")


# Gắn router xử lý file
app.include_router(
    file_processing.router,
    prefix="/files", # Tất cả các URL trong router này sẽ có tiền tố /files
    tags=["File Processing"] # Gom nhóm các API trong trang docs
)

# --- ENDPOINT GỐC ĐỂ KIỂM TRA ---
@app.get("/", tags=["Root"])
def read_root():
    return {"message": "Chào mừng đến với API chính! Truy cập /docs để xem chi tiết."}

# Bạn có thể bỏ khối if __name__ == "__main__": đi
# để chạy hoàn toàn bằng command line uvicorn main:app