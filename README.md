# 🧠 AI Product Detector with HS Code

🚀 **AI Product Detector** là một hệ thống API dựa trên **Flask**, sử dụng mô hình **Google Gemini 2.0 Flash** (via Vertex AI) để phát hiện **thuộc tính sản phẩm** và **HS Code (Harmonized System Code)** từ mô tả sản phẩm.

API được thiết kế **bất đồng bộ (async)**, **chịu lỗi cao**, và có thể trích xuất các thuộc tính như `country`, `size`, `material`, `target_user` và `hscode` theo cấu trúc **JSON**.

---

## 📋 Giới thiệu

- **Mục đích**: Phân tích văn bản sản phẩm từ e-commerce để:
  - Xác định nguồn gốc sản xuất (Country of Origin)
  - Trích xuất thuộc tính sản phẩm (Size, Material, Target User)
  - Phân loại HS Code cho mục đích hải quan (theo Japan Post)
- **Phiên bản**: `3.0.0`
- **Ngôn ngữ chính**: Python 3.12+
- **AI Model**: Google Gemini 2.0 Flash (Vertex AI)

---

## ✨ Tính năng chính

### 🗺️ Phát hiện quốc gia

Trả về mảng mã **ISO 3166-1 alpha-3** (ví dụ: `["JPN", "VNM"]`) cùng bằng chứng (`evidence`) và độ tin cậy (`confidence`) 0.0–1.0.

### 📦 Phân loại HS Code

Xác định mã HS Code 6 chữ số dựa trên bảng phân loại của Japan Post.

### 🎨 Trích xuất thuộc tính

Bao gồm `size`, `material`, `target_user` — với cấu trúc JSON chi tiết (`value`, `evidence`, `confidence`).

### ⚡ Xử lý bất đồng bộ (Async)

Tận dụng `asyncio` và Vertex AI async để gọi API, hỗ trợ batch song song (`asyncio.gather`) cho hiệu suất tối đa.

### 🛡️ Xử lý lỗi chi tiết

Tự động bắt các lỗi cụ thể và trả về mã lỗi JSON rõ ràng, không làm crash API.

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

| Method | Endpoint                | Yêu cầu X-API-KEY | Mô tả                                   |
| :----- | :---------------------- | :---------------- | :-------------------------------------- |
| POST   | `/detect-product`       | ✅ Có             | Phát hiện thuộc tính + HS Code (đơn lẻ) |
| POST   | `/batch-detect-product` | ✅ Có             | Phát hiện hàng loạt (song song)         |
| POST   | `/clear-cache`          | ✅ Có             | Xóa toàn bộ cache                       |
| GET    | `/health`               | ❌ Không          | Kiểm tra tình trạng API                 |
| GET    | `/metrics`              | ❌ Không          | Xuất Prometheus metrics                 |

---

## 🧱 Prerequisites

- 🐍 Python 3.12+
- 🧭 Git
- 🐳 Docker & Docker Compose (nếu chạy container)
- 🔑 Google Cloud Service Account với quyền Vertex AI
- 🔑 Biến `API_KEYS` trong `.env` để xác thực client

---

## ⚙️ Cài đặt

### 1️⃣ Clone repository

```bash
git clone https://github.com/your-repo/ai-country-detector.git
cd ai-country-detector
```

Cấu trúc thư mục:

```bash
ai-country-detector/
├── app.py                  # Flask main file
├── requirements.txt
├── utils/
│   ├── gemini_detector.py  # Gemini AI logic
│   └── validator.py        # Country validation
├── Dockerfile
├── docker-compose.yml
└── .env.example            # Copy thành .env
```

### 2️⃣ Tạo file .env

```bash
cp .env.example .env
```

Ví dụ nội dung `.env`:

```bash
# Vertex AI Configuration
GOOGLE_CLOUD_PROJECT=your-project-id
GCP_LOCATION=us-central1
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# API Security
API_KEYS=your-api-key-1,your-api-key-2

# Application Settings
LOG_LEVEL=INFO
FLASK_DEBUG=False
PORT=5000
```

### 3️⃣ Cài dependencies

```bash
pip install -r requirements.txt
```

---

## 🚀 Chạy ứng dụng

### 🔹 Local Dev Mode (Flask)

```bash
python app.py
```

Ứng dụng chạy tại: http://localhost:5000

### 🔹 Production-like (Gunicorn)

```bash
gunicorn --bind 0.0.0.0:5000 --workers 4 --timeout 30 app:app
```

### 🔹 Docker Compose (Khuyến nghị)

```bash
docker-compose up --build        # Build & run
docker-compose up -d --build     # Run background
docker-compose logs -f           # Xem logs
docker-compose down              # Dừng
```

---

## 🧠 Sử dụng API

### Headers yêu cầu

```
Content-Type: application/json
X-API-KEY: <your_api_key_in_env>
```

---

### 🔸 1. Single Detection `/detect-product`

**Request:**

```bash
POST /detect-product
Content-Type: application/json
X-API-KEY: your-api-key

{
  "title": "レディース ストレートパンツ",
  "description": "素材: ポリエステル95% ポリウレタン5%、サイズ: S/M/L",
  "model": "gemini-2.5-flash"  // optional - custom model
}
```

**Input Parameters:**

| Parameter     | Type   | Required | Description                                      |
| :------------ | :----- | :------- | :----------------------------------------------- |
| `title`       | string | No\*     | Tiêu đề sản phẩm                                 |
| `description` | string | No\*     | Mô tả chi tiết sản phẩm                          |
| `model`       | string | No       | Custom Gemini model (mặc định: gemini-2.0-flash) |

> **Lưu ý:** Ít nhất một trong hai trường `title` hoặc `description` là bắt buộc.

**Response thành công:**

```json
{
  "result": "OK",
  "data": {
    "attributes": {
      "country": {
        "value": [],
        "evidence": "説明文に製造国や原産国に関する記載がありません。",
        "confidence": 0.0
      },
      "size": {
        "value": "S, M, L",
        "evidence": "サイズ: S/M/L",
        "confidence": 0.9
      },
      "material": {
        "value": "ポリエステル, ポリウレタン",
        "evidence": "素材: ポリエステル95% ポリウレタン5%",
        "confidence": 1.0
      },
      "target_user": {
        "value": ["women"],
        "evidence": "レディース ストレートパンツ",
        "confidence": 0.8
      },
      "hscode": {
        "value": "620463",
        "evidence": "女子用ズボン、合成繊維製",
        "confidence": 0.95
      }
    },
    "cache": false,
    "time": 2500,
    "model": "gemini-2.5-flash"
  }
}
```

---

### 🔸 2. Batch Detection `/batch-detect-product`

**Request:**

```bash
POST /batch-detect-product
Content-Type: application/json
X-API-KEY: your-api-key

{
  "items": [
    {
      "title": "Men's Cotton T-Shirt",
      "description": "Made in Vietnam, 100% cotton, Size L"
    },
    {
      "title": "Women's Silk Dress",
      "description": "原産国: 日本、シルク100%"
    }
  ],
  "model": "gemini-2.0-flash"  // optional
}
```

**Input Parameters:**

| Parameter | Type   | Required | Description                     |
| :-------- | :----- | :------- | :------------------------------ |
| `items`   | array  | Yes      | Mảng các sản phẩm cần phân tích |
| `model`   | string | No       | Custom Gemini model             |

**Response:**

```json
{
  "result": "OK",
  "data": {
    "results": [
      {
        "attributes": {
          "country": {
            "value": ["VNM"],
            "evidence": "Made in Vietnam",
            "confidence": 1.0
          },
          "size": { "value": "L", "evidence": "Size L", "confidence": 0.9 },
          "material": {
            "value": "cotton",
            "evidence": "100% cotton",
            "confidence": 1.0
          },
          "target_user": {
            "value": ["men"],
            "evidence": "Men's Cotton T-Shirt",
            "confidence": 0.9
          },
          "hscode": {
            "value": "610910",
            "evidence": "Men's T-shirt, cotton",
            "confidence": 0.9
          }
        },
        "cache": false
      },
      {
        "attributes": {
          "country": {
            "value": ["JPN"],
            "evidence": "原産国: 日本",
            "confidence": 1.0
          },
          "material": {
            "value": "シルク",
            "evidence": "シルク100%",
            "confidence": 1.0
          },
          "target_user": {
            "value": ["women"],
            "evidence": "Women's Silk Dress",
            "confidence": 0.9
          },
          "hscode": {
            "value": "620442",
            "evidence": "Women's dress, silk",
            "confidence": 0.85
          }
        },
        "cache": false
      }
    ],
    "total": 2,
    "cache_hits": 0,
    "ai_calls": 2,
    "model": "gemini-2.0-flash",
    "time": 3500
  }
}
```

---

### 🔸 3. Health Check `/health`

```bash
GET /health
```

Response:

```json
{
  "status": "healthy",
  "service": "Product Detector with HS Code",
  "version": "3.0.0"
}
```

---

### 🔸 4. Clear Cache `/clear-cache`

```bash
POST /clear-cache
X-API-KEY: your-api-key
```

Response:

```json
{ "result": "OK", "message": "Cache cleared successfully", "items_cleared": 15 }
```

---

### 🔸 5. Metrics `/metrics`

Xuất định dạng Prometheus (dùng cho Grafana / Prometheus dashboard).

---

## ❌ Error Responses

### Validation Errors (400)

```json
{
  "result": "Failed",
  "errors": [
    {
      "code": "VALIDATION_ERROR",
      "message": "At least one of 'title' or 'description' is required"
    }
  ]
}
```

### Authentication Error (401)

```json
{
  "result": "Failed",
  "errors": [{ "code": "AUTH_ERROR", "message": "Invalid API Key" }]
}
```

### Quota Error (503)

```json
{
  "result": "Failed",
  "errors": [
    {
      "code": "QUOTA_ERROR",
      "message": "Vertex AI quota exceeded. Please try again later."
    }
  ]
}
```

### Initialization Error (500)

```json
{
  "result": "Failed",
  "errors": [
    {
      "code": "INIT_ERROR",
      "message": "Failed to initialize detector: GOOGLE_APPLICATION_CREDENTIALS is required"
    }
  ]
}
```

---

## 🧪 Testing với Postman

### Test Cases

#### ✅ Case 1: Chỉ có title

```json
POST /detect-product
{
  "title": "Men's Cotton T-Shirt Made in Vietnam"
}
```

#### ✅ Case 2: Chỉ có description

```json
POST /detect-product
{
  "description": "原産国: 日本、シルク100%、サイズM"
}
```

#### ✅ Case 3: Cả title và description

```json
POST /detect-product
{
  "title": "レディース ストレートパンツ",
  "description": "素材: ポリエステル95% ポリウレタン5%、詳細サイズ: S/M/L"
}
```

#### ❌ Case 4: Thiếu cả title và description

```json
POST /detect-product
{}
```

→ Response: `400 VALIDATION_ERROR`

#### ❌ Case 5: Thiếu API Key

```
POST /detect-product
(No X-API-KEY header)
```

→ Response: `401 AUTH_ERROR`

#### ❌ Case 6: Model rỗng

```json
POST /detect-product
{
  "title": "Test",
  "model": ""
}
```

→ Response: `400 VALIDATION_ERROR`

---

## 📊 HS Code Reference

Dựa theo bảng phân loại của [Japan Post](https://www.post.japanpost.jp/int/use/publication/contentslist/index.php?lang=_ja):

| Category                     | HS Code | Example                |
| :--------------------------- | :------ | :--------------------- |
| Women's cotton dress         | 620442  | ワンピース、綿製       |
| Men's T-shirt (cotton)       | 610910  | T シャツ、綿製         |
| Women's trousers (synthetic) | 620463  | 女性用パンツ、合成繊維 |
| Laptop computer              | 847130  | ノートパソコン         |
| Eyeshadow                    | 330420  | アイシャドウ           |
| Earring                      | 711790  | イヤリング             |

> **Lưu ý số chữ số HS Code:**
>
> - Ireland: 10 chữ số
> - France + lãnh thổ hải ngoại: 8 chữ số
> - Các nước khác: 6 chữ số

---

## 📈 Monitoring & Logs

- **Logs**: Console & `app.log` (xoay vòng, 10MB × 5 files)
- **Metrics**: `/metrics` → Prometheus counters
- **Cache**: Lưu cache nếu confidence > 0.5

---

## 🧩 Troubleshooting

| Vấn đề                  | Nguyên nhân & Giải pháp                                            |
| :---------------------- | :----------------------------------------------------------------- |
| ❌ 401 Unauthorized     | Quên gửi `X-API-KEY` hoặc sai key                                  |
| ❌ 400 VALIDATION_ERROR | Thiếu cả `title` và `description`                                  |
| ❌ 500 INIT_ERROR       | Thiếu `GOOGLE_APPLICATION_CREDENTIALS` hoặc `GOOGLE_CLOUD_PROJECT` |
| ❌ 503 QUOTA_ERROR      | Hết quota Vertex AI                                                |
| ❌ 503 AUTH_ERROR       | Sai credentials hoặc không có quyền Vertex AI                      |
| 🔄 Port conflict        | Đổi `PORT` trong `.env` hoặc `docker-compose.yml`                  |

---

## 🧩 Tech Stack

| Thành phần    | Công nghệ               |
| :------------ | :---------------------- |
| Backend       | Flask 3.x               |
| AI Model      | Google Gemini 2.0 Flash |
| AI Platform   | Vertex AI               |
| Async Runtime | asyncio                 |
| Metrics       | prometheus-client       |
| Container     | Docker / Docker Compose |
| Logging       | RotatingFileHandler     |
| Python        | 3.12+                   |

---

## 📜 License

Bản quyền © 2025-2026 AIOT Inc.

Phát triển bởi AIOT_AI_LAB
