# 🧠 AI Country Detector

> 🚀 **AI Country Detector** là một hệ thống API dựa trên **Flask**, sử dụng mô hình **OpenAI GPT-4o-mini** để phát hiện **quốc gia sản xuất (country of origin)** từ mô tả sản phẩm.  
> Hỗ trợ đa ngôn ngữ (🇯🇵 Nhật, 🇬🇧 Anh, 🇻🇳 Việt, 🇨🇳 Trung) và trích xuất thuộc tính sản phẩm như **size, color, material, brand**.

---

## 📋 Giới thiệu

**Mục đích:**  
Phân tích văn bản sản phẩm từ e-commerce để xác định **nguồn gốc sản xuất chính xác** (ví dụ: `"Made in Japan" → ["JP"]`), tránh suy đoán từ brand hoặc địa chỉ.

**Phiên bản:** 1.1.0  
**Ngôn ngữ chính:** Python 3.12  
**Dependencies:** Xem `requirements.txt`

---

## ✨ Tính năng chính

- 🗺️ **Phát hiện quốc gia**: Trả về mảng mã **ISO 3166-1 alpha-2** (vd: `["JP", "VN"]`) với **độ tin cậy (confidence)** 0.0–1.0  
- 🎨 **Trích xuất thuộc tính**: `size`, `color`, `material`, `brand`  
  → Hỗ trợ đa giá trị, ví dụ: `"Glacier Grey / Pure Silver"`
- 🌐 **Hỗ trợ đa ngôn ngữ**: Tự động phát hiện & dịch nếu cần (giữ nguyên JP/EN/VI/ZH)
- ⚙️ **Tối ưu hóa**:
  - Cache LRU (1000 entries)
  - Logging xoay vòng (rotating file)
  - Prometheus metrics
  - Làm sạch HTML/table
- 🧩 **Fallback**: Dùng heuristic regex nếu OpenAI lỗi

---

## 🔌 Endpoints

| Method | Endpoint | Mô tả |
|---------|-----------|-------|
| `POST` | `/detect-country` | Phân tích mô tả đơn lẻ |
| `POST` | `/batch-detect` | Phân tích hàng loạt |
| `GET`  | `/health` | Kiểm tra tình trạng API |
| `GET`  | `/metrics` | Xuất Prometheus metrics |

---

## 🧱 Prerequisites

- 🐍 Python **3.12+**
- 🧭 Git
- 🐳 Docker & Docker Compose (nếu chạy container)
- 🔑 Tài khoản OpenAI API để lấy `OPENAI_API_KEY`

---

## ⚙️ Cài đặt

### 1️⃣ Clone repository

Repo được host trên **Backlog Git**.

```bash
# Cách 1: Clone trực tiếp (cần quyền truy cập Backlog)
git clone https://aiot-inc.backlog.com/git/AIOT_AI_LAB/aal-product-information-extraction.git
cd aal-product-information-extraction

# Cách 2: Clone qua SSH
git clone git@aiot-inc.backlog.com:AIOT_AI_LAB/aal-product-information-extraction.git
cd aal-product-information-extraction

```

### Cấu trúc thư mục:
```bash
aal-product-information-extraction/
├── app.py
├── requirements.txt
├── utils/
│   ├── openai_detector.py
│   └── validator.py
├── Dockerfile
├── docker-compose.yml
└── .env.example  # Copy thành .env
```

### 2️⃣ Tạo file .env
Tạo từ mẫu .env.example hoặc tự viết mới:
```bash
cp .env.example .env
```
### 3️⃣ Cài đặt dependencies
```bash
pip install -r requirements.txt
```
🚀 Chạy ứng dụng
🔹 Cách 1: Local Dev Mode (Flask)
```bash
export FLASK_APP=app.py
python app.py
```
Ứng dụng chạy tại: http://localhost:5000
Test nhanh:
```bash
curl -X POST http://localhost:5000/detect-country \
  -H "Content-Type: application/json" \
  -d '{"description": "日本製、サイズM、赤いNikeシャツ"}'
```
Kết quả mẫu:
```bash
{
  "result": "OK",
  "data": {
    "country": ["JP"],
    "confidence": 1.0,
    "attributes": {
      "size": "M",
      "color": "red",
      "material": "none",
      "brand": "Nike"
    },
    "cache": false,
    "time": 250
  }
}
```
🔹 Cách 2: Production-like (Gunicorn)
```bash
pip install gunicorn
gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 30 --log-level info app:app
```
🔹 Cách 3: Docker Compose (Khuyến nghị)
```bash
# Build và chạy
docker-compose up --build

# Chạy background
docker-compose up -d --build

# Xem logs
docker-compose logs -f

# Dừng
docker-compose down
```
App chạy tại http://localhost:5000

Volume mount code cho hot-reload (dev), logs lưu tại ./app.log.

🧠 Sử dụng API
🔸 1. Single Detection /detect-country
```bash
POST /detect-country
Content-Type: application/json
{
  "description": "Mô tả sản phẩm"
}
```
🔸 2. Batch Detection /batch-detect
```bash
POST /batch-detect
Content-Type: application/json
{
  "descriptions": ["text1", "text2"]
}
```
Response:
```bash
{
  "result": "OK",
  "data": {
    "results": [{...}, {...}],
    "total": 2,
    "cache_hits": 0,
    "ai_calls": 2,
    "time": 500
  }
}
```
🔸 3. Health Check /health
```bash
{"status": "healthy", "service": "AI Country Detector", "version": "1.1.0"}
```
🔸 4. Metrics /metrics
Trả về định dạng Prometheus, dùng cho Grafana/Prometheus dashboard.

🧪 Testing

🧰 Manual test:
```bash
curl http://localhost:5000/health
```
🧩 Ví dụ mô tả:

🇯🇵 "原産国: Indonesia / Vietnam、サイズ23cm/24cm"

🇬🇧 "Made in China, black cotton Nike shirt"

🧨 Edge case: Rỗng → {"country": ["ZZ"], "confidence": 0.0}

📈 Monitoring & Logs

📜 Logs: Console hoặc ./app.log (xoay vòng, tối đa 10MB)

📊 Metrics: /metrics → Prometheus counters

api_requests_total

api_request_duration_seconds

💾 Cache: Tự động lưu với confidence > 0.5
🧩 Troubleshooting
| Vấn đề               | Nguyên nhân & Giải pháp                                |
| -------------------- | ------------------------------------------------------ |
| ❌ OpenAI lỗi         | Kiểm tra `OPENAI_API_KEY`, quota, hoặc API down        |
| ⚙️ Langdetect fail   | Với text ngắn → fallback giữ nguyên                    |
| 🔄 Port conflict     | Thay `PORT` trong `.env`                               |
| 🐳 Docker build fail | Cập nhật Docker version / pull base image mới          |
| ⚠️ JSON parse error  | Do prompt OpenAI → kiểm tra log, set `temperature=0.0` |


🧩 Tech Stack
| Thành phần         | Công nghệ               |
| ------------------ | ----------------------- |
| Backend            | Flask 3.x               |
| AI Model           | OpenAI GPT-4o-mini      |
| Language Detection | langdetect              |
| Metrics            | prometheus-client       |
| Container          | Docker / Docker Compose |
| Logging            | RotatingFileHandler     |
| Python             | 3.12                    |


📜 License

Bản quyền © 2025 AIOT Inc.
Phát triển bởi AIOT_AI_LAB