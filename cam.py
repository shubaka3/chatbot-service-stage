# main.py
import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List

# --- KHỞI TẠO ỨNG DỤNG FASTAPI ---
app = FastAPI()

# Cho phép client từ bất kỳ đâu kết nối tới (quan trọng cho việc test)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- QUẢN LÝ TRẠNG THÁI CÁC "PHÒNG" ---
# Dùng một dictionary đơn giản để lưu trữ các kết nối WebSocket cho mỗi phòng.
# Key: tên phòng (ví dụ: "cam01")
# Value: danh sách các client (WebSocket) đang ở trong phòng đó.
# Lưu ý: Đây là cách lưu trữ trong bộ nhớ, khi server restart sẽ mất hết.
# Trong thực tế, có thể dùng Redis để quản lý trạng thái này.
rooms: Dict[str, List[WebSocket]] = {}


# --- API ĐƠN GIẢN ĐỂ KIỂM TRA CÁC PHÒNG ĐANG HOẠT ĐỘNG ---
@app.get("/api/rooms")
async def get_active_rooms():
    """Trả về danh sách các phòng đang có người kết nối."""
    return {"rooms": list(rooms.keys())}


# --- ENDPOINT WEBSOCKET CỐT LÕI (TỔNG ĐÀI) ---
@app.websocket("/ws/{room_name}")
async def websocket_endpoint(websocket: WebSocket, room_name: str):
    """
    Đây là "tổng đài" WebRTC Signaling.
    Nó chấp nhận kết nối WebSocket từ client và thêm họ vào một "phòng".
    Mọi tin nhắn nhận được từ một client sẽ được phát lại cho TẤT CẢ các client khác
    trong cùng một phòng.
    """
    # 1. Chấp nhận kết nối từ client
    await websocket.accept()
    print(f"Client đã kết nối tới phòng: {room_name}")

    # 2. Thêm client vào phòng tương ứng
    if room_name not in rooms:
        rooms[room_name] = []  # Nếu phòng chưa tồn tại, tạo mới
    rooms[room_name].append(websocket)

    try:
        # 3. Vòng lặp chính để lắng nghe và chuyển tiếp tin nhắn
        while True:
            # Chờ nhận tin nhắn từ client (tin nhắn này là JSON chứa thông tin WebRTC)
            data = await websocket.receive_json()
            print(f"Nhận được tin nhắn trong phòng '{room_name}': {data}")

            # Chuyển tiếp tin nhắn này cho tất cả các client khác trong cùng phòng
            for client in rooms[room_name]:
                if client != websocket:  # Không gửi lại cho chính người gửi
                    await client.send_json(data)
                    print(f"Đã chuyển tiếp tin nhắn tới client khác trong phòng '{room_name}'")

    except WebSocketDisconnect:
        # 4. Xử lý khi client ngắt kết nối
        print(f"Client đã ngắt kết nối khỏi phòng: {room_name}")
        rooms[room_name].remove(websocket)
        # Nếu phòng trống, xóa phòng đi để dọn dẹp
        if not rooms[room_name]:
            del rooms[room_name]
            print(f"Phòng '{room_name}' đã trống và được xóa.")

    except Exception as e:
        print(f"Lỗi: {e}")
        # Đảm bảo client được xóa khỏi phòng nếu có lỗi xảy ra
        if room_name in rooms and websocket in rooms[room_name]:
            rooms[room_name].remove(websocket)
            if not rooms[room_name]:
                del rooms[room_name]

# --- CHẠY SERVER ---
if __name__ == "__main__":
    # Chạy server trên tất cả các địa chỉ IP của máy, ở cổng 8000
    uvicorn.run(app, host="0.0.0.0", port=8000)