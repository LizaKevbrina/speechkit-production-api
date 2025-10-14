
"""
Production-ready SpeechKit API для масштабирования
Автор: Елизавета Кевбрина
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
import httpx
import os
import logging
from datetime import datetime
from typing import Optional
import boto3
from botocore.exceptions import ClientError

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SpeechKit API", version="2.0")

# Конфигурация из переменных окружения
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")
S3_BUCKET = os.getenv("S3_BUCKET_NAME")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "https://storage.yandexcloud.net")
AWS_ACCESS_KEY = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")

# Инициализация S3 клиента
s3_client = boto3.client(
    's3',
    endpoint_url=S3_ENDPOINT,
    aws_access_key_id=AWS_ACCESS_KEY,
    aws_secret_access_key=AWS_SECRET_KEY,
    region_name='ru-central1'
)

# Модели данных
class SynthesisRequest(BaseModel):
    text: str
    lang: str = "ru-RU"
    voice: str = "jane"
    user_id: str
    format: str = "oggopus"

class MetricsLog(BaseModel):
    timestamp: str
    operation: str
    user_id: str
    duration_ms: float
    status: str
    tokens_used: Optional[int] = None
    file_size_kb: Optional[float] = None
    error: Optional[str] = None

# Хранилище метрик
metrics_storage = []

# === CORE FUNCTIONS ===

async def log_metrics(metric: MetricsLog):
    """Асинхронное логирование метрик"""
    metrics_storage.append(metric.dict())
    logger.info(f"Metric logged: {metric.operation} - {metric.status}")

async def upload_to_s3(file_data: bytes, filename: str) -> str:
    """Загрузка файла в Object Storage"""
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=filename,
            Body=file_data,
            ContentType='audio/ogg'
        )
        logger.info(f"Uploaded to S3: {filename}")
        return f"{S3_ENDPOINT}/{S3_BUCKET}/{filename}"
    except ClientError as e:
        logger.error(f"S3 upload error: {e}")
        raise HTTPException(status_code=500, detail="Storage error")

# === API ENDPOINTS ===

@app.post("/api/v1/tts/synthesize")
async def synthesize_speech(request: SynthesisRequest, background_tasks: BackgroundTasks):
    """Синтез речи с метриками"""
    start_time = datetime.now()

    try:
        # Отправка в Yandex TTS
        headers = {
            "Authorization": f"Api-Key {YANDEX_API_KEY}"
        }

        data = {
            "text": request.text,
            "lang": request.lang,
            "voice": request.voice,
            "format": request.format,
            "folderId": YANDEX_FOLDER_ID
        }

        async with httpx.AsyncClient() as client:
            tts_response = await client.post(
                "https://tts.api.cloud.yandex.net/speech/v1/tts:synthesize",
                headers=headers,
                data=data,
                timeout=60.0
            )

        if tts_response.status_code == 200:
            audio_data = tts_response.content
            file_size = len(audio_data) / 1024

            # Сохранение в S3
            s3_filename = f"synthesized/{request.user_id}/{datetime.now().strftime('%Y%m%d_%H%M%S')}.ogg"
            await upload_to_s3(audio_data, s3_filename)

            duration = (datetime.now() - start_time).total_seconds() * 1000

            # Логирование метрик
            metric = MetricsLog(
                timestamp=datetime.now().isoformat(),
                operation="TTS",
                user_id=request.user_id,
                duration_ms=duration,
                status="success",
                file_size_kb=file_size,
                tokens_used=len(request.text.split())
            )
            background_tasks.add_task(log_metrics, metric)

            return StreamingResponse(
                iter([audio_data]),
                media_type="audio/ogg",
                headers={
                    "X-S3-Path": s3_filename,
                    "X-Duration-Ms": str(duration),
                    "X-File-Size-KB": str(file_size)
                }
            )
        else:
            raise HTTPException(status_code=tts_response.status_code,
                              detail=tts_response.text)

    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000

        metric = MetricsLog(
            timestamp=datetime.now().isoformat(),
            operation="TTS",
            user_id=request.user_id,
            duration_ms=duration,
            status="error",
            error=str(e)
        )
        background_tasks.add_task(log_metrics, metric)

        logger.error(f"TTS error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/v1/metrics")
async def get_metrics(limit: int = 100):
    """Получение метрик для мониторинга"""
    return {
        "total_requests": len(metrics_storage),
        "recent_metrics": metrics_storage[-limit:],
        "summary": {
            "tts_requests": len([m for m in metrics_storage if m['operation'] == 'TTS']),
            "errors": len([m for m in metrics_storage if m['status'] == 'error']),
            "avg_duration_ms": sum(m['duration_ms'] for m in metrics_storage) / len(metrics_storage) if metrics_storage else 0
        }
    }


@app.get("/api/v1/health")
async def health_check():
    """Health check для мониторинга"""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                "https://stt.api.cloud.yandex.net/",
                timeout=5.0
            )

        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "yandex_api": "available",
            "s3": "connected"
        }
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@app.get("/")
async def root():
    """API документация"""
    return {
        "service": "SpeechKit API",
        "version": "2.0",
        "author": "Elizaveta Kevbrina",
        "endpoints": {
            "POST /api/v1/tts/synthesize": "Text-to-Speech",
            "GET /api/v1/metrics": "Metrics dashboard",
            "GET /api/v1/health": "Health check"
        },
        "docs": "/docs"
    }
