# /my_streaming_project/api/webrtc_signaling.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from typing import Dict, List
import logging

# Thay vì `app = FastAPI()`, chúng ta tạo một router
router = APIRouter()

# --- QUẢN LÝ TRẠNG THÁI (dành riêng cho router này) ---
rooms: Dict[str, List[WebSocket]] = {}

@router.get("/active-rooms")
async def get_active_rooms():
    """Trả về danh sách các phòng WebRTC đang hoạt động."""
    return {"active_rooms": list(rooms.keys())}


@router.websocket("/ws/{room_name}")
async def websocket_endpoint(websocket: WebSocket, room_name: str):
    """Endpoint WebSocket cho WebRTC Signaling."""
    await websocket.accept()
    logging.info(f"Client đã kết nối tới phòng WebRTC: {room_name}")

    if room_name not in rooms:
        rooms[room_name] = []
    rooms[room_name].append(websocket)

    try:
        while True:
            data = await websocket.receive_json()
            logging.info(f"Nhận tin nhắn trong phòng '{room_name}': {data}")
            for client in rooms[room_name]:
                if client != websocket:
                    await client.send_json(data)

    except WebSocketDisconnect:
        logging.info(f"Client đã ngắt kết nối khỏi phòng WebRTC: {room_name}")
    finally:
        if room_name in rooms and websocket in rooms[room_name]:
            rooms[room_name].remove(websocket)
            if not rooms[room_name]:
                del rooms[room_name]
                logging.info(f"Phòng WebRTC '{room_name}' đã trống và được xóa.")