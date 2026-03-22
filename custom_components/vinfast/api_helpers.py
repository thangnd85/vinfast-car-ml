import requests
import time
import uuid
import logging
import json
import math
import sys

# Tăng giới hạn đệ quy cho thuật toán RDP nếu mảng quá lớn
sys.setrecursionlimit(5000)

_LOGGER = logging.getLogger(__name__)

def safe_float(val, default=0.0):
    try:
        if val is None or str(val).strip() == "": return default
        return float(val)
    except Exception: return default

def get_address_from_osm(lat, lon):
    try:
        res = requests.get(f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18", headers={"User-Agent": f"HA-VinFast-{uuid.uuid4().hex[:6]}"}, timeout=5)
        if res.status_code == 200: 
            addr = res.json().get("display_name")
            if addr and any(c.isalpha() for c in addr): return addr
    except Exception: pass
    return None

def get_weather_data(lat, lon):
    try:
        res = requests.get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true", timeout=10)
        if res.status_code == 200:
            data = res.json()
            current = data.get("current_weather", {})
            temp = current.get("temperature")
            wind = current.get("windspeed")
            code = current.get("weathercode", 0)
            
            if temp is not None:
                condition = "Quang đãng"
                if code in [1, 2, 3]: condition = "Có mây"
                elif code in [45, 48]: condition = "Sương mù"
                elif code in [51, 53, 55, 61, 63, 65, 80, 81, 82]: condition = "Trời mưa"
                elif code in [71, 73, 75, 85, 86]: condition = "Tuyết rơi"
                elif code in [95, 96, 99]: condition = "Sấm chớp"
                
                hvac = "Bình thường"
                if temp >= 35: hvac = "Rất cao (Làm mát tối đa)"
                elif temp >= 30: hvac = "Cao (Làm mát nhanh)"
                elif temp <= 15: hvac = "Cao (Sưởi ấm)"
                
                return {"temp": temp, "condition": condition, "hvac": hvac, "code": code}
    except Exception: pass
    return None

def get_osrm_route(lat1, lon1, lat2, lon2):
    try:
        url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=full&geometries=geojson&continue_straight=true"
        res = requests.get(url, timeout=5)
        if res.status_code == 200:
            data = res.json()
            if data.get("code") == "Ok":
                coords = data["routes"][0]["geometry"]["coordinates"]
                return [[p[1], p[0]] for p in coords]
    except Exception: pass
    return None

# =========================================================================
# BỘ CÔNG CỤ XỬ LÝ GPS NÂNG CAO
# =========================================================================

def perpendicular_distance(pt, line_start, line_end):
    """Tính khoảng cách vuông góc từ một điểm tới một đoạn thẳng (Mét)."""
    x0, y0 = pt[1], pt[0]
    x1, y1 = line_start[1], line_start[0]
    x2, y2 = line_end[1], line_end[0]
    
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(x0 - x1, y0 - y1) * 111320.0
    
    t = ((x0 - x1) * dx + (y0 - y1) * dy) / (dx * dx + dy * dy)
    t = max(0, min(1, t))
    px = x1 + t * dx
    py = y1 + t * dy
    return math.hypot(x0 - px, y0 - py) * 111320.0

def rdp_simplify(coords, epsilon=3.0):
    """Thuật toán Ramer-Douglas-Peucker: Lược bỏ điểm thừa, GIỮ LẠI GÓC CUA."""
    if len(coords) < 3:
        return coords
    
    dmax = 0.0
    index = 0
    end = len(coords) - 1
    
    for i in range(1, end):
        d = perpendicular_distance(coords[i], coords[0], coords[end])
        if d > dmax:
            index = i
            dmax = d
            
    if dmax > epsilon:
        rec_results1 = rdp_simplify(coords[:index+1], epsilon)
        rec_results2 = rdp_simplify(coords[index:], epsilon)
        return rec_results1[:-1] + rec_results2
    else:
        return [coords[0], coords[end]]

def offset_route_right(coords, offset_meters=1.5):
    """Tịnh tiến xe dạt phải thông minh bằng Vector Central Difference."""
    if not coords or len(coords) < 2: return coords
    shifted = []
    n = len(coords)
    
    for i in range(n):
        lat = coords[i][0]
        lon = coords[i][1]
        speed = coords[i][2] if len(coords[i]) > 2 else 0

        # Lấy vector trung tâm (Từ điểm trước đó đến điểm kế tiếp) để góc xoay mượt nhất
        if i == 0:
            dx = coords[i+1][1] - lon
            dy = coords[i+1][0] - lat
        elif i == n - 1:
            dx = lon - coords[i-1][1]
            dy = lat - coords[i-1][0]
        else:
            dx = coords[i+1][1] - coords[i-1][1]
            dy = coords[i+1][0] - coords[i-1][0]

        if dx == 0 and dy == 0:
            shifted.append([round(lat, 6), round(lon, 6), round(speed, 1)])
            continue

        angle = math.atan2(dy, dx)
        right_angle = angle - (math.pi / 2.0)

        lat_offset = (offset_meters / 111320.0) * math.sin(right_angle)
        lon_offset = (offset_meters / (111320.0 * math.cos(math.radians(lat)))) * math.cos(right_angle)

        shifted.append([round(lat + lat_offset, 6), round(lon + lon_offset, 6), round(speed, 1)])
    
    return shifted

def snap_to_road(coords):
    """PIPELINE TỐI THƯỢNG: RDP Lọc -> Chunk Match OSRM -> Tịnh Tiến Phải."""
    if not coords or len(coords) < 2: return coords
    
    # 1. RDP Lọc thông minh (Giữ cua, loại đường thẳng thừa)
    # Epsilon = 3.0 mét đảm bảo mọi góc cua đều được bắt trọn vẹn
    simplified = rdp_simplify(coords, epsilon=3.0)
    if len(simplified) < 2: simplified = coords
    
    # 2. Xử lý Chunking để gọi OSRM không bị giới hạn URL
    CHUNK_SIZE = 70
    matched_full_route = []
    
    for i in range(0, len(simplified), CHUNK_SIZE - 1):
        chunk = simplified[i:i+CHUNK_SIZE]
        if len(chunk) < 2: continue
        
        coord_str = ";".join([f"{p[1]:.6f},{p[0]:.6f}" for p in chunk])
        try:
            url = f"http://router.project-osrm.org/match/v1/driving/{coord_str}?overview=full&geometries=geojson&tidy=true"
            res = requests.get(url, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data.get("code") == "Ok":
                    matched_coords = data["matchings"][0]["geometry"]["coordinates"]
                    # Nối mảng, bỏ điểm đầu của chunk sau để tránh giật lùi
                    if i > 0 and len(matched_full_route) > 0 and len(matched_coords) > 0:
                        matched_full_route.extend(matched_coords[1:])
                    else:
                        matched_full_route.extend(matched_coords)
                else:
                    matched_full_route.extend([[p[1], p[0]] for p in chunk])
            else:
                matched_full_route.extend([[p[1], p[0]] for p in chunk])
        except Exception as e:
            _LOGGER.error(f"VinFast Map Match Error: {e}")
            matched_full_route.extend([[p[1], p[0]] for p in chunk])
            
    if not matched_full_route:
        matched_full_route = [[p[1], p[0]] for p in simplified]

    # 3. Nội suy tốc độ & Lọc Sparsification (Bỏ các điểm sát nhau < 1 mét)
    final_matched_with_speed = []
    last_added_pt = None
    
    for mp in matched_full_route:
        m_lon, m_lat = mp[0], mp[1]
        
        # Bỏ qua nếu điểm mới sinh ra cách điểm trước đó quá gần
        if last_added_pt:
            dist_to_last = math.hypot(m_lat - last_added_pt[0], m_lon - last_added_pt[1]) * 111320.0
            if dist_to_last < 1.0: continue
            
        closest_speed = 0
        min_dist = float('inf')
        
        for sp in coords:
            dist = (sp[0] - m_lat)**2 + (sp[1] - m_lon)**2
            if dist < min_dist:
                min_dist = dist
                closest_speed = sp[2] if len(sp) > 2 else 0
                
        pt_to_add = [m_lat, m_lon, closest_speed]
        final_matched_with_speed.append(pt_to_add)
        last_added_pt = pt_to_add

    # 4. Tịnh tiến mượt mà sang làn bên phải 1.5 mét
    return offset_route_right(final_matched_with_speed, offset_meters=1.5)

# =========================================================================

def get_ai_advice(api_key, ai_model, mode, data_payload, context_data):
    if not api_key or api_key.strip() == "":
        return "Vui lòng nhập Google Gemini API Key để AI đánh giá."

    temp = context_data.get("temp", "Không rõ")
    cond = context_data.get("cond", "Không rõ")
    hvac = context_data.get("hvac", "Bình thường")
    expected_km_per_1 = context_data.get("expected_km_per_1", 2.1)

    prompt = ""

    if mode == "weather" and data_payload:
        w_temp = data_payload.get('temp', temp)
        w_cond = data_payload.get('cond', cond)
        prompt = (
            f"CẢNH BÁO THỜI TIẾT CỰC ĐOAN: Nhiệt độ ngoài trời đang là {w_temp} độ C, thời tiết: {w_cond}. "
            f"Đóng vai chuyên gia AI của xe VinFast, viết MỘT câu tiếng Việt cực kỳ ngắn gọn (dưới 40 từ) "
            "khuyên tài xế cách chỉnh điều hòa và lái xe để an toàn và tiết kiệm pin nhất lúc này."
        )
    elif mode == "anomaly" and data_payload:
        dist = round(data_payload.get('dist', 0), 2)
        drop = round(data_payload.get('drop', 0), 2)
        expected = round(data_payload.get('expected', 0), 2)
        speed = round(data_payload.get('speed', 0), 1)
        prompt = (
            f"CẢNH BÁO SỤT PIN: Xe vừa mất {drop}% pin chỉ để đi {dist}km (vận tốc {speed}km/h). "
            f"Bình thường 1% phải đi được {expected}km. Điều hòa: {hvac}, Nhiệt độ: {temp}C. "
            "Viết MỘT câu giải thích lý do sụt pin (có thể do đạp ga gấp, đèo dốc, hoặc điều hòa) và đưa ra lời khuyên ngắn gọn."
        )
    else:
        dist = context_data.get("trip_dist", 0)
        speed = context_data.get("trip_avg_speed", 0)
        prompt = (
            f"TỔNG KẾT CHUYẾN ĐI: Vừa hoàn thành quãng đường {dist}km, tốc độ trung bình {speed}km/h. "
            f"Thời tiết: {temp}C, {cond}. Đánh giá xem hiệu suất chuyến đi này là xuất sắc, bình thường hay kém và đưa ra 1 lời khuyên."
        )

    clean_key = api_key.strip()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{ai_model}:generateContent"
    headers = {"Content-Type": "application/json", "x-goog-api-key": clean_key}
    payload = {"contents": [{"parts": [{"text": prompt}]}]}
    
    for attempt in range(3):
        try:
            res = requests.post(url, json=payload, headers=headers, timeout=30)
            if res.status_code == 200:
                ai_text = res.json().get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
                return ai_text.replace("*", "").strip() if ai_text else "Google AI không phản hồi nội dung."
            elif res.status_code == 403: return "❌ Lỗi 403: API Key bị sai."
            elif res.status_code == 404: return f"❌ Lỗi 404: Model '{ai_model}' không tồn tại."
            elif res.status_code == 400: return "❌ Lỗi 400: Định dạng API Key không hợp lệ."
            elif res.status_code in [503, 429]:
                if attempt < 2: 
                    time.sleep(3)
                    continue
                return f"⏳ Google AI đang quá tải (Lỗi {res.status_code})."
            else:
                return f"❌ Google báo lỗi {res.status_code}."
        except Exception:
            if attempt < 2: time.sleep(3)
    return "❌ Lỗi kết nối đến Google AI."