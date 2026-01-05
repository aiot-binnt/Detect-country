# 📬 Hướng Dẫn Test API trên Postman

## 📋 Mục Lục

1. [Setup Postman](#setup-postman)
2. [Cấu hình Environment](#cấu-hình-environment)
3. [Test API /detect-country](#test-api-detect-country)
4. [Test API /batch-detect](#test-api-batch-detect)
5. [Test Cases](#test-cases)
6. [Tips & Tricks](#tips--tricks)

---

## 🔧 Setup Postman

### 1. Cài đặt Postman

- Download tại: https://www.postman.com/downloads/
- Hoặc sử dụng Postman Web: https://web.postman.com/

### 2. Tạo Collection Mới

1. Mở Postman
2. Click **"New"** → **"Collection"**
3. Đặt tên: `AI Country Detector API`
4. Thêm description: `API để phát hiện quốc gia sản xuất từ mô tả sản phẩm`

---

## 🌍 Cấu hình Environment

### Tạo Environment:

1. Click icon ⚙️ (Settings) ở góc phải trên
2. Chọn **"Environments"** → **"Create Environment"**
3. Đặt tên: `Local Development`

### Variables cần thiết:

| Variable         | Type    | Initial Value           | Current Value              |
| ---------------- | ------- | ----------------------- | -------------------------- |
| `base_url`       | default | `http://localhost:5000` | `http://localhost:5000`    |
| `api_key`        | secret  | `Az01219493...`         | _(API key từ .env)_        |
| `gemini_api_key` | secret  | _(optional)_            | _(Gemini API key của bạn)_ |

**Cách thêm variable:**

1. Click **"Add a new variable"**
2. Nhập tên variable
3. Chọn type (secret cho API key)
4. Nhập value
5. Click **"Save"**

**Kích hoạt environment:**

- Chọn `Local Development` từ dropdown ở góc phải trên

---

## 🎯 Test API /detect-country

### Test 1: Sử dụng Config Mặc Định

#### 1. Tạo Request Mới

- Click **"Add request"** trong Collection
- Đặt tên: `Detect Country - Default Config`

#### 2. Cấu hình Request

**Method:** `POST`

**URL:**

```
{{base_url}}/detect-country
```

**Headers:**
| Key | Value |
|-----|-------|
| `Content-Type` | `application/json` |
| `X-API-KEY` | `{{api_key}}` |

**Body:** Chọn `raw` → `JSON`

```json
{
  "description": "日本製、サイズM、赤いNikeシャツ"
}
```

#### 3. Send Request

Click **"Send"**

**Expected Response (200 OK):**

```json
{
  "result": "OK",
  "data": {
    "attributes": {
      "country": {
        "value": ["JP"],
        "evidence": "日本製",
        "confidence": 1.0
      },
      "size": {
        "value": "M",
        "evidence": "サイズM",
        "confidence": 1.0
      },
      "material": {
        "value": "none",
        "evidence": "none",
        "confidence": 0.0
      }
    },
    "model": "gemini-2.0-flash",
    "is_custom": false,
    "cache": false,
    "time": 250
  }
}
```

---

### Test 2: Sử dụng Custom Model & API Key

#### 1. Tạo Request Mới

- Duplicate request trước: Right-click → **"Duplicate"**
- Đổi tên: `Detect Country - Custom Config`

#### 2. Cấu hình Request

**Method:** `POST`

**URL:**

```
{{base_url}}/detect-country
```

**Headers:** (giống Test 1)

**Body:**

```json
{
  "description": "Made in China, size L, cotton material",
  "model": "gemini-2.5-flash",
  "api_key": "{{gemini_api_key}}"
}
```

> ⚠️ **Lưu ý:** Cần có Gemini API key hợp lệ trong environment variable `gemini_api_key`

#### 3. Send Request

**Expected Response (200 OK):**

```json
{
  "result": "OK",
  "data": {
    "attributes": {
      "country": {
        "value": ["CN"],
        "evidence": "Made in China",
        "confidence": 0.95
      },
      "size": {
        "value": "L",
        "evidence": "size L",
        "confidence": 0.9
      },
      "material": {
        "value": "cotton",
        "evidence": "cotton material",
        "confidence": 0.85
      }
    },
    "model": "gemini-2.5-flash",
    "is_custom": true,
    "cache": false,
    "time": 300
  }
}
```

---

### Test 3: Test Validation Error (Model Only)

#### Body:

```json
{
  "description": "Made in Japan",
  "model": "gemini-2.5-flash"
}
```

**Expected Response (400 Bad Request):**

```json
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

---

### Test 4: Test Validation Error (API Key Only)

#### Body:

```json
{
  "description": "Made in Japan",
  "api_key": "test-api-key-that-is-long-enough"
}
```

**Expected Response (400 Bad Request):**

```json
{
  "result": "Failed",
  "errors": [
    {
      "code": "VALIDATION_ERROR",
      "message": "Custom api_key requires custom model. Please provide both 'model' and 'api_key' together, or omit both to use defaults."
    }
  ]
}
```

---

### Test 5: Test Invalid API Key Format

#### Body:

```json
{
  "description": "Made in Japan",
  "model": "gemini-2.5-flash",
  "api_key": "short"
}
```

**Expected Response (400 Bad Request):**

```json
{
  "result": "Failed",
  "errors": [
    {
      "code": "VALIDATION_ERROR",
      "message": "Invalid API key format"
    }
  ]
}
```

---

### Test 6: Test Missing Description

#### Body:

```json
{}
```

**Expected Response (400 Bad Request):**

```json
{
  "result": "Failed",
  "errors": [
    {
      "code": "VALIDATION_ERROR",
      "message": "Missing description"
    }
  ]
}
```

---

## 📦 Test API /batch-detect

### Test 1: Batch - Default Config

#### 1. Tạo Request Mới

- Đặt tên: `Batch Detect - Default Config`

#### 2. Cấu hình Request

**Method:** `POST`

**URL:**

```
{{base_url}}/batch-detect
```

**Headers:**
| Key | Value |
|-----|-------|
| `Content-Type` | `application/json` |
| `X-API-KEY` | `{{api_key}}` |

**Body:**

```json
{
  "descriptions": [
    "Made in Wales, wool sweater",
    "原産国: Indonesia / Vietnam、サイズ23cm/24cm",
    "日本製チタン製品"
  ]
}
```

#### 3. Send Request

**Expected Response (200 OK):**

```json
{
  "result": "OK",
  "data": {
    "results": [
      {
        "attributes": {
          "country": {
            "value": ["GB"],
            "evidence": "Made in Wales",
            "confidence": 1.0
          },
          "size": {...},
          "material": {...}
        },
        "cache": false
      },
      {
        "attributes": {
          "country": {
            "value": ["ID", "VN"],
            "evidence": "原産国: Indonesia / Vietnam",
            "confidence": 1.0
          },
          "size": {...},
          "material": {...}
        },
        "cache": false
      },
      {
        "attributes": {
          "country": {
            "value": ["JP"],
            "evidence": "日本製",
            "confidence": 1.0
          },
          "size": {...},
          "material": {...}
        },
        "cache": false
      }
    ],
    "total": 3,
    "cache_hits": 0,
    "ai_calls": 3,
    "model": "gemini-2.0-flash",
    "is_custom": false,
    "time": 800
  }
}
```

---

### Test 2: Batch - Custom Config

#### Body:

```json
{
  "descriptions": ["Made in Wales", "原産国: Indonesia / Vietnam"],
  "model": "gemini-2.5-flash",
  "api_key": "{{gemini_api_key}}"
}
```

**Expected Response (200 OK):**

```json
{
  "result": "OK",
  "data": {
    "results": [...],
    "total": 2,
    "cache_hits": 0,
    "ai_calls": 2,
    "model": "gemini-2.5-flash",
    "is_custom": true,
    "time": 600
  }
}
```

---

### Test 3: Batch - Validation Error

#### Body:

```json
{
  "descriptions": ["Made in Wales"],
  "model": "gemini-2.5-flash"
}
```

**Expected Response (400 Bad Request):**

```json
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

---

## ✅ Test Cases Summary

### Tạo Folder Structure trong Collection:

```
📁 AI Country Detector API
├── 📁 /detect-country
│   ├── ✅ 1. Default Config
│   ├── ✅ 2. Custom Config
│   ├── ❌ 3. Validation - Model Only
│   ├── ❌ 4. Validation - API Key Only
│   ├── ❌ 5. Invalid API Key Format
│   └── ❌ 6. Missing Description
│
├── 📁 /batch-detect
│   ├── ✅ 1. Default Config
│   ├── ✅ 2. Custom Config
│   └── ❌ 3. Validation Error
│
└── 📁 Utility
    ├── GET /health
    └── GET /metrics
```

---

## 🎨 Tips & Tricks

### 1. Sử dụng Tests Tab

Thêm script tự động kiểm tra response:

**Chọn tab "Tests"** trong request, thêm:

```javascript
// Test status code
pm.test("Status code is 200", function () {
  pm.response.to.have.status(200);
});

// Test response structure
pm.test("Response has result OK", function () {
  var jsonData = pm.response.json();
  pm.expect(jsonData.result).to.eql("OK");
});

// Test custom flag for custom config requests
pm.test("Using custom config", function () {
  var jsonData = pm.response.json();
  pm.expect(jsonData.data.is_custom).to.eql(true);
});

// Test country detected
pm.test("Country detected successfully", function () {
  var jsonData = pm.response.json();
  pm.expect(jsonData.data.attributes.country.value).to.be.an("array");
  pm.expect(jsonData.data.attributes.country.value.length).to.be.above(0);
});
```

### 2. Sử dụng Pre-request Script

Tạo timestamp động:

```javascript
// Generate timestamp
pm.environment.set("timestamp", new Date().toISOString());

// Log request
console.log("Sending request to: " + pm.request.url);
```

### 3. Save Responses

- Click **"Save Response"** để lưu example responses
- Hữu ích để so sánh sau này

### 4. Collection Runner

**Chạy tất cả tests tự động:**

1. Click Collection → **"Run"**
2. Chọn requests cần test
3. Click **"Run AI Country Detector API"**
4. Xem kết quả tổng hợp

### 5. Export Collection

**Chia sẻ với team:**

1. Right-click Collection → **"Export"**
2. Chọn **Collection v2.1**
3. Save file `.json`
4. Team import vào Postman của họ

---

## 🔍 Debugging

### 1. View Console

- Click **"Console"** (bottom left)
- Xem request/response details
- Debug network issues

### 2. Check Response Time

- Xem thời gian ở góc phải của response
- Compare với `time` field trong response body

### 3. Beautify JSON

- Click **"Pretty"** tab trong response
- Dễ đọc hơn raw JSON

### 4. Copy as cURL

- Right-click request → **"Code"**
- Chọn **"cURL"**
- Copy để test trên terminal

---

## 📊 Monitor Performance

### Create Monitor:

1. Click Collection → **"..."** → **"Monitor collection"**
2. Đặt tên: `AI Country Detector Health Check`
3. Chọn frequency: Every 5 minutes
4. Nhận email khi API down

---

## 🎯 Quick Reference

### Environment Variables:

```
{{base_url}}        → http://localhost:5000
{{api_key}}         → Your API key from .env
{{gemini_api_key}}  → Your Gemini API key (optional)
```

### Common Headers:

```
Content-Type: application/json
X-API-KEY: {{api_key}}
```

### Request Body Templates:

**Default:**

```json
{
  "description": "Product description here"
}
```

**Custom:**

```json
{
  "description": "Product description here",
  "model": "gemini-2.5-flash",
  "api_key": "{{gemini_api_key}}"
}
```

**Batch:**

```json
{
  "descriptions": ["desc1", "desc2", "desc3"]
}
```

---

## 📝 Checklist

Trước khi test, đảm bảo:

- [ ] Server đang chạy (`python app.py`)
- [ ] Environment được kích hoạt trong Postman
- [ ] `base_url` = `http://localhost:5000`
- [ ] `api_key` đã được set (từ `.env` file)
- [ ] (Optional) `gemini_api_key` đã được set nếu test custom config

---

## 🚀 Bắt Đầu Nhanh

1. ✅ Import environment variables
2. ✅ Tạo request `/detect-country` - Default
3. ✅ Test với description đơn giản
4. ✅ Kiểm tra response có `is_custom: false`
5. ✅ Thử thêm `model` và `api_key`
6. ✅ Test validation errors
7. ✅ Test batch endpoint
8. ✅ Chạy Collection Runner

---

## 📞 Support

Gặp vấn đề? Kiểm tra:

1. Server đang chạy? → `curl http://localhost:5000/health`
2. API key đúng? → Check `.env` file
3. Headers đúng format? → `Content-Type: application/json`
4. Body đúng JSON? → Use Postman's JSON validator
5. Check logs → `app.log`

---

**Happy Testing! 🎉**
