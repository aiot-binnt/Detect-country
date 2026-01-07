# 🧠 AI Country Detector

🚀 **AI Country Detector** là một hệ thống API dựa trên **Flask**, sử dụng mô hình **OpenAI GPT-4o-mini** để phát hiện **quốc gia sản xuất (country of origin)** từ mô tả sản phẩm.  
API được thiết kế **bất đồng bộ (async)**, **chịu lỗi cao**, và có thể **trích xuất thuộc tính sản phẩm** như `size`, `color`, `material`, `brand` theo cấu trúc **JSON lồng nhau**.

---

## 📋 Giới thiệu

- **Mục đích**: Phân tích văn bản sản phẩm từ e-commerce để xác định nguồn gốc sản xuất chính xác (ví dụ: `"Made in Japan"` → `["JP"]`), tránh suy đoán từ brand hoặc địa chỉ.
- **Phiên bản**: `1.4.1`
- **Ngôn ngữ chính**: Python 3.12+
- **Dependencies**: Xem `requirements.txt`

---

## ✨ Tính năng chính

### 🗺️ Phát hiện quốc gia

Trả về mảng mã **ISO 3166-1 alpha-2** (ví dụ: `["JP", "VN"]`) cùng bằng chứng (`evidence`) và độ tin cậy (`confidence`) 0.0–1.0.

### 🎨 Trích xuất thuộc tính

Bao gồm `size`, `color`, `material`, `brand` — với cấu trúc JSON lồng nhau chi tiết (`value`, `evidence`, `confidence`).

### ⚡ Xử lý bất đồng bộ (Async)

Tận dụng `asyncio` và `AsyncOpenAI (v1.x+)` để gọi API OpenAI, hỗ trợ batch song song (`asyncio.gather`) cho hiệu suất tối đa.

### 🛡️ Xử lý lỗi chi tiết

Tự động bắt các lỗi cụ thể từ OpenAI (`RateLimitError`, `AuthenticationError`, v.v.) và trả về mã lỗi JSON rõ ràng, không làm crash API.

### ⚙️ Tối ưu hóa

- Cache LRU (1000 entries)
- Logging xoay vòng
- Prometheus metrics
- Làm sạch HTML / ký tự rác tự động

### 🧩 Fallback

Tự động dùng heuristic **regex** nếu AI trả về JSON không hợp lệ.

---

## 🔌 Endpoints

> Tất cả các endpoint (ngoại trừ `/health` và `/metrics`) yêu cầu header `X-API-KEY` để xác thực.

| Method | Endpoint          | Yêu cầu X-API-KEY | Mô tả                           |
| :----- | :---------------- | :---------------- | :------------------------------ |
| POST   | `/detect-country` | ✅ Có             | Phân tích mô tả đơn lẻ          |
| POST   | `/batch-detect`   | ✅ Có             | Phân tích hàng loạt (song song) |
| GET    | `/health`         | ❌ Không          | Kiểm tra tình trạng API         |
| GET    | `/metrics`        | ❌ Không          | Xuất Prometheus metrics         |

---

## 🧱 Prerequisites

- 🐍 Python 3.12+
- 🧭 Git
- 🐳 Docker & Docker Compose (nếu chạy container)
- 🔑 Tài khoản OpenAI API để lấy `OPENAI_API_KEY`
- 🔑 Biến `API_KEYS` trong `.env` để xác thực client

---

## ⚙️ Cài đặt

### 1️⃣ Clone repository

```bash
# Cách 1: Clone trực tiếp
git clone https://aiot-inc.backlog.com/git/AIOT_AI_LAB/aal-product-information-extraction.git
cd aal-product-information-extraction

# Cách 2: Clone qua SSH
git clone git@aiot-inc.backlog.com:AIOT_AI_LAB/aal-product-information-extraction.git
cd aal-product-information-extraction
```

Cấu trúc thư mục:

```bash
aal-product-information-extraction/
├── app.py                  # Flask main file
├── requirements.txt
├── utils/
│   ├── openai_detector.py  # Async logic
│   └── validator.py        # Country validation
├── Dockerfile
├── docker-compose.yml
└── .env.example            # Copy thành .env
```

### 2️⃣ Tạo file .env

```bash
cp .env.example .env
```

Ví dụ nội dung .env:

```bash
# OpenAI API Key (service)
OPENAI_API_KEY="sk-..."

# API Keys (cho client, cách nhau bằng dấu phẩy)
API_KEYS="key_client_1,key_client_2"

# Config
PORT=5000
LOG_LEVEL=INFO
FLASK_DEBUG=False
```

### 3️⃣ Cài dependencies

```bash
pip install -r requirements.txt
```

### 🚀 Chạy ứng dụng

#### 🔹 Cách 1: Local Dev Mode (Flask)

```bash
export FLASK_APP=app.py
python app.py
```

Ứng dụng chạy tại: http://localhost:5000

Test nhanh:

```bash
curl -X POST http://localhost:5000/detect-country \
  -H "Content-Type: application/json" \
  -H "X-API-KEY: <your_api_key_in_env>" \
  -d '{"description": "日本製、サイズM、赤いNikeシャツ"}'
```

Kết quả mẫu:

```bash
{
  "result": "OK",
  "data": {
    "attributes": {
      "country": {"value": ["JP"], "evidence": "日本製", "confidence": 1.0},
      "size": {"value": "M", "evidence": "サイズM", "confidence": 1.0},
      "color": {"value": "赤い", "evidence": "赤いNikeシャツ", "confidence": 0.8},
      "material": {"value": "none", "evidence": "none", "confidence": 0.0},
      "brand": {"value": "Nike", "evidence": "赤いNikeシャツ", "confidence": 0.9}
    },
    "cache": false,
    "time": 250
  }
}
```

#### 🔹 Cách 2: Production-like (Gunicorn)

```bash
pip install gunicorn
gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 30 --log-level info app:app
```

#### 🔹 Cách 3: Docker Compose (Khuyến nghị)

```bash
docker-compose up --build        # Build & run
docker-compose up -d --build     # Run background
docker-compose logs -f           # Xem logs
docker-compose down              # Dừng
```

Ứng dụng chạy tại: http://localhost:5000

### 🧠 Sử dụng API

Tất cả request cần có header:

```bash
Content-Type: application/json
X-API-KEY: <your_api_key_in_env>
```

#### 🔸 1. Single Detection /detect-country

**Request mặc định (sử dụng config của server):**

```bash
POST /detect-country
{
  "description": "Mô tả sản phẩm"
}
```

**Request với custom model và api_key:**

```bash
POST /detect-country
{
  "description": "日本製、サイズM、赤いNikeシャツ",
  "model": "gemini-2.5-flash",
  "api_key": "your-custom-gemini-api-key"
}
```

> **⚠️ Lưu ý:** Nếu cung cấp `model`, bạn **bắt buộc** phải cung cấp `api_key`, và ngược lại. Hoặc bỏ qua cả hai để dùng config mặc định.

**Response thành công:**

```bash
{
  "result": "OK",
  "data": {
    "attributes": {
      "country": {"value": ["JP"], "evidence": "日本製", "confidence": 1.0},
      "size": {"value": "M", "evidence": "サイズM", "confidence": 1.0},
      "material": {"value": "none", "evidence": "none", "confidence": 0.0}
    },
    "model": "gemini-2.5-flash",
    "is_custom": true,
    "cache": false,
    "time": 250
  }
}
```

Response (Lỗi Validation):

```bash
{
  "result": "Failed",
  "errors": [
    {
      "code": "VALIDATION_ERROR",
      "message": "Custom model requires custom api_key. Please provide both 'model' and 'api_key' together, or omit both to use defaults."
    }
  ]
}
```

Response (Lỗi API Key):

```bash
{
  "result": "Failed",
  "errors": [
    {
      "code": "AUTH_ERROR",
      "message": "Invalid Gemini API key. Please check your credentials."
    }
  ]
}
```

Response (Lỗi Gemini):

```bash
{
  "result": "Failed",
  "errors": [
    {
      "code": "QUOTA_ERROR",
      "message": "Gemini quota exceeded or rate limit hit."
    }
  ]
}
```

#### 🔸 2. Batch Detection /batch-detect

**Request mặc định:**

```bash
POST /batch-detect
{
  "descriptions": ["Made in Wales", "原産国: Indonesia / Vietnam"]
}
```

**Request với custom model và api_key:**

```bash
POST /batch-detect
{
  "descriptions": ["Made in Wales", "原産国: Indonesia / Vietnam"],
  "model": "gemini-2.5-flash",
  "api_key": "your-custom-gemini-api-key"
}
```

**Response (Batch):**

```bash
{
  "result": "OK",
  "data": {
    "results": [
      {
        "attributes": { "country": {"value": ["GB"], "evidence": "Made in Wales"} },
        "cache": false
      },
      {
        "attributes": { "country": {"value": ["ID", "VN"], "evidence": "原産国: Indonesia / Vietnam"} },
        "cache": false
      }
    ],
    "total": 2,
    "cache_hits": 0,
    "ai_calls": 2,
    "model": "gemini-2.5-flash",
    "is_custom": true,
    "time": 500
  }
}
```

#### 🔸 3. Health Check /health

```bash
GET /health
```

Response:

```bash
{"status": "healthy", "service": "AI Country Detector", "version": "1.4.1"}
```

#### 🔸 4. Metrics /metrics

Xuất định dạng Prometheus (dùng cho Grafana / Prometheus dashboard).

### 🧪 Testing

Manual test:

```bash
curl http://localhost:5000/health
```

Ví dụ mô tả:

| Mô tả                                                  | Kết quả        |
| :----------------------------------------------------- | :------------- |
| 🇯🇵 `"原産国: Indonesia / Vietnam、サイズ23cm/24cm"`    | `["ID", "VN"]` |
| 🇬🇧 `"Made in China, black cotton Nike shirt"`          | `["CN"]`       |
| 🏴 `"Made in Wales. RASWカシミヤセーター、アイボリー"` | `["GB"]`       |
| 🧨 (Rỗng)                                              | `["ZZ"]`       |

### 📈 Monitoring & Logs

Logs: Console & app.log (xoay vòng, 10MB × 5 files)

Metrics: /metrics → Prometheus counters

api_requests_total

api_request_duration_seconds

Cache: Lưu cache nếu confidence > 0.5

### 🧩 Troubleshooting

| Vấn đề                  | Nguyên nhân & Giải pháp                                   |
| :---------------------- | :-------------------------------------------------------- |
| ❌ 401 Unauthorized     | Quên gửi `X-API-KEY` hoặc sai key                         |
| ❌ 400 VALIDATION_ERROR | Cung cấp `model` mà không có `api_key`, hoặc ngược lại    |
| ❌ 400 INIT_ERROR       | API key format không hợp lệ hoặc quá ngắn                 |
| ❌ 503 AUTH_ERROR       | Sai `GEMINI_API_KEY` hoặc API key không có quyền truy cập |
| ❌ 503 QUOTA_ERROR      | Hết quota Gemini API                                      |
| ❌ 503 MODEL_NOT_FOUND  | Model name không tồn tại hoặc không accessible            |
| ⚠️ JSON parse error     | AI trả về text không hợp lệ → fallback regex              |
| 🔄 Port conflict        | Đổi `PORT` trong `.env` hoặc `docker-compose.yml`         |
| 🐳 Docker build fail    | Cập nhật Docker / base image                              |

### 🧩 Tech Stack

| Thành phần        | Công nghệ               |
| :---------------- | :---------------------- |
| Backend           | Flask 3.x               |
| AI Model          | Google Gemini 2.0 Flash |
| AI Client (Async) | google-generativeai     |
| Async Runtime     | asyncio                 |
| Metrics           | prometheus-client       |
| Container         | Docker / Docker Compose |
| Logging           | RotatingFileHandler     |
| Python            | 3.12+                   |

### 📜 License

Bản quyền © 2025 AIOT Inc.

Phát triển bởi AIOT_AI_LAB
