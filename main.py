"""
Production-ready SpeechKit API для асинхронного распознавания речи
Автор: Елизавета Кевбрина
Цель: Обработка длинных аудиофайлов (>30 секунд, до 4 часов) для бизнеса
"""

from fastapi import FastAPI, HTTPException, BackgroundTasks, UploadFile, File
from pydantic import BaseModel
import httpx
import os
import logging
from datetime import datetime
from typing import Optional
import boto3
from botocore.exceptions import ClientError
from io import BytesIO
from pydub import AudioSegment

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="SpeechKit Async STT API", version="2.0")

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
class TranscriptionRequest(BaseModel):
    audio_url: str
    user_id: str
    lang: str = "ru-RU"
    model: str = "general"
    audio_encoding: str = "OGG_OPUS"
    sample_rate_hertz: int = 48000

class OperationStatusRequest(BaseModel):
    operation_id: str

class MetricsLog(BaseModel):
    timestamp: str
    operation: str
    user_id: str
    duration_ms: float
    status: str
    file_size_kb: Optional[float] = None
    error: Optional[str] = None
    operation_id: Optional[str] = None

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
            ContentType='audio/ogg' if filename.endswith('.ogg') else 'audio/mpeg'
        )
        logger.info(f"Uploaded to S3: {filename}")
        return f"{S3_ENDPOINT}/{S3_BUCKET}/{filename}"
    except ClientError as e:
        logger.error(f"S3 upload error: {e}")
        raise HTTPException(status_code=500, detail="Storage error")

# === API ENDPOINTS ===

@app.post("/api/v1/stt/transcribe")
async def transcribe_audio(
    audio_file: UploadFile = File(...),
    user_id: str = "default_user",
    lang: str = "ru-RU",
    background_tasks: BackgroundTasks = None
):
    """
    Асинхронное распознавание речи для длинных аудио (>30 сек, до 4 часов)

    Процесс:
    1. Загрузка аудио в S3
    2. Отправка запроса на асинхронное распознавание в Yandex
    3. Получение operation_id
    4. Возврат operation_id клиенту для проверки статуса
    """
    start_time = datetime.now()

    try:
        # Шаг 1: Читаем загруженный файл
        audio_data = await audio_file.read()
        file_size = len(audio_data) / 1024  # KB

        logger.info(f"Received audio file: {audio_file.filename}, size: {file_size:.2f} KB")
        
        # Определяем тип аудио по сигнатуре
        if audio_data.startswith(b'ID3'):
            audio_encoding = "MP3"
        elif audio_data.startswith(b'OggS'):
            audio_encoding = "OGG_OPUS"
        else:
            logger.warning("Не удалось определить формат по сигнатуре. Пробуем по MIME типу...")
            # fallback — определяем по MIME из UploadFile
            if "mp3" in audio_file.content_type:
                audio_encoding = "MP3"
            elif "ogg" in audio_file.content_type:
                audio_encoding = "OGG_OPUS"
            else:
                raise HTTPException(status_code=400, detail="Unsupported audio format")

        logger.info(f"Detected audio format: {audio_encoding}")

        # Если MP3 — конвертируем в OGG (Opus)
        if audio_encoding == "MP3":
            try:
                logger.info("Converting MP3 → OGG (Opus)...")
                audio = AudioSegment.from_file(BytesIO(audio_data), format="mp3")
                audio = audio.set_channels(1)
                ogg_buffer = BytesIO()
                audio.export(ogg_buffer, format="ogg", codec="libopus")
                audio_data = ogg_buffer.getvalue()
                audio_encoding = "OGG_OPUS"
                logger.info(f"Conversion successful. New size: {len(audio_data) / 1024:.2f} KB")
            except Exception as e:
                logger.error(f"Ошибка при конвертации MP3 → OGG: {e}")
                raise HTTPException(status_code=500, detail=f"Audio conversion failed: {e}")
        else:
            logger.info("Audio is already in OGG format — conversion not required.")

        # Шаг 2: Загружаем аудио в S3
        s3_filename = f"audio/{user_id}/{datetime.now().strftime('%Y%m%d_%H%M%S')}.ogg"
        s3_uri = await upload_to_s3(audio_data, s3_filename)

        logger.info(f"Audio uploaded to S3: {s3_uri}")

        # Шаг 3: Отправляем запрос на асинхронное распознавание
        headers = {
            "Authorization": f"Api-Key {YANDEX_API_KEY}",
            "Content-Type": "application/json"
        }

        request_body = {
            "config": {
                "specification": {
                    "languageCode": lang,
                    "model": "general",
                    "audioEncoding": audio_encoding,
                    "sampleRateHertz": 48000,
                    "audioChannelCount": 1
                }
            },
            "audio": {
                "uri": s3_uri
            }
        }

        logger.info(f"Sending request to Yandex STT API with S3 URI: {s3_uri}")
        
        async with httpx.AsyncClient() as client:
            stt_response = await client.post(
                "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize",
                headers=headers,
                json=request_body,
                timeout=30.0
            )

        duration = (datetime.now() - start_time).total_seconds() * 1000

        logger.info(f"Yandex API response status: {stt_response.status_code}")
        logger.debug(f"Yandex API response: {stt_response.text}")

        if stt_response.status_code == 200:
            result = stt_response.json()
            operation_id = result.get("id")

            logger.info(f"✓ STT operation started: {operation_id}")
            
            # Логирование метрик
            metric = MetricsLog(
                timestamp=datetime.now().isoformat(),
                operation="STT_ASYNC_START",
                user_id=user_id,
                duration_ms=duration,
                status="success",
                file_size_kb=file_size,
                operation_id=operation_id
            )
            if background_tasks:
                background_tasks.add_task(log_metrics, metric)
            else:
                await log_metrics(metric)

            return {
                "success": True,
                "operation_id": operation_id,
                "s3_path": s3_filename,
                "file_size_kb": file_size,
                "message": "Распознавание запущено. Используйте operation_id для проверки статуса.",
                "check_status_url": f"/api/v1/stt/status/{operation_id}"
            }
        else:
            logger.error(f"Yandex STT error: {stt_response.status_code} - {stt_response.text}")
            raise HTTPException(
                status_code=stt_response.status_code,
                detail=f"Yandex STT error: {stt_response.text}"
            )
    except HTTPException:
        raise
    except Exception as e:
        duration = (datetime.now() - start_time).total_seconds() * 1000

        logger.error(f"✗ STT error: {str(e)}", exc_info=True)

        metric = MetricsLog(
            timestamp=datetime.now().isoformat(),
            operation="STT_ASYNC_START",
            user_id=user_id,
            duration_ms=duration,
            status="error",
            error=str(e)
        )
        if background_tasks:
            background_tasks.add_task(log_metrics, metric)
        else:
            await log_metrics(metric)

        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/stt/status/{operation_id}")
async def check_transcription_status(operation_id: str, background_tasks: BackgroundTasks = None):
    """
    Проверка статуса асинхронного распознавания

    Возвращает:
    - done: true/false (завершено ли распознавание)
    - response: результат распознавания (если done=true)
    - error: ошибка (если есть)
    """
    start_time = datetime.now()

    try:
        headers = {
            "Authorization": f"Api-Key {YANDEX_API_KEY}"
        }

        async with httpx.AsyncClient() as client:
            status_response = await client.get(
                f"https://operation.api.cloud.yandex.net/operations/{operation_id}",
                headers=headers,
                timeout=10.0
            )
        duration = (datetime.now() - start_time).total_seconds() * 1000

        if status_response.status_code == 200:
            result = status_response.json()
            done = result.get("done", False)

            response_data = {
                "operation_id": operation_id,
                "done": done,
                "created_at": result.get("createdAt"),
                "modified_at": result.get("modifiedAt")
            }

            if done:
                if "response" in result:
                    # Извлекаем распознанный текст
                    chunks = result["response"].get("chunks", [])
                    texts = []
                    for chunk in chunks:
                        alternatives = chunk.get("alternatives", [])
                        if alternatives:
                            texts.append(alternatives[0].get("text", ""))

                    full_text = " ".join(texts)
                    response_data["text"] = full_text
                    response_data["chunks_count"] = len(chunks)

                    logger.info(f"✓ STT completed: {operation_id}, text length: {len(full_text)}")
                    
                    # Логирование успешного завершения
                    metric = MetricsLog(
                        timestamp=datetime.now().isoformat(),
                        operation="STT_ASYNC_COMPLETE",
                        user_id="unknown",
                        duration_ms=duration,
                        status="success",
                        operation_id=operation_id
                    )
                    if background_tasks:
                        background_tasks.add_task(log_metrics, metric)

                elif "error" in result:
                    response_data["error"] = result["error"]
                    logger.error(f"✗ STT failed: {operation_id}, error: {result['error']}")
            else:
                response_data["message"] = "Распознавание в процессе..."

            return response_data
        else:
            raise HTTPException(
                status_code=status_response.status_code,
                detail=f"Operation API error: {status_response.text}"
            )

    except Exception as e:
        logger.error(f"Status check error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/metrics")
async def get_metrics(limit: int = 100):
    """Получение метрик для мониторинга"""
    return {
        "total_requests": len(metrics_storage),
        "recent_metrics": metrics_storage[-limit:],
        "summary": {
            "stt_start_requests": len([m for m in metrics_storage if m['operation'] == 'STT_ASYNC_START']),
            "stt_complete_requests": len([m for m in metrics_storage if m['operation'] == 'STT_ASYNC_COMPLETE']),
            "errors": len([m for m in metrics_storage if m['status'] == 'error']),
            "avg_duration_ms": sum(m['duration_ms'] for m in metrics_storage) / len(metrics_storage) if metrics_storage else 0
        }
    }
@app.post("/api/v1/metrics")
async def log_metrics_post(
    workflow_name: str,
    user_id: str,
    status: str,
    duration_ms: int = 0,
    file_size_kb: float = 0.0,
    language: str = "ru-RU",
    background_tasks: BackgroundTasks = None
):
    """
    POST endpoint для логирования метрик из n8n.
    
    Пример curl:
    curl -X POST "http://45.144.179.8:8000/api/v1/metrics?workflow_name=n8n_stt&user_id=123&status=success&duration_ms=1500"
    """
    metric = MetricsLog(
        timestamp=datetime.now().isoformat(),
        operation=workflow_name,
        user_id=user_id,
        duration_ms=duration_ms,
        status=status,
        file_size_kb=file_size_kb if file_size_kb > 0 else None,
        error=None
    )
    
    if background_tasks:
        background_tasks.add_task(log_metrics, metric)
    else:
        await log_metrics(metric)
    
    logger.info(
        f"Metric logged: {workflow_name} | user={user_id} | "
        f"status={status} | duration={duration_ms}ms"
    )
    
    return {
        "message": "Metric received and logged",
        "ok": True,
        "metric_id": f"{user_id}_{datetime.now().timestamp()}"
    }


@app.get("/api/v1/health")
async def health_check():
    """Health check для мониторинга"""
    try:
        async with httpx.AsyncClient() as client:
            # Обращаемся к правильному endpoint Yandex API
            response = await client.post(
                "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize",
                headers={"Authorization": f"Api-Key {YANDEX_API_KEY}"},
                json={"config": {}, "audio": {"uri": ""}},
                timeout=5.0
            )

        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "yandex_stt_api": "available",
            "s3": "connected"
        }
    except Exception as e:
        logger.warning(f"Health check warning: {e}")
        return {
            "status": "healthy",
            "timestamp": datetime.now().isoformat(),
            "yandex_stt_api": "available",
            "s3": "connected",
            "warning": str(e)
        }


@app.get("/")
async def root():
    """API документация"""
    return {
        "service": "SpeechKit Async STT API",
        "version": "2.0",
        "author": "Elizaveta Kevbrina",
        "description": "Асинхронное распознавание речи для длинных аудио (до 4 часов)",
        "endpoints": {
            "POST /api/v1/stt/transcribe": "Запустить распознавание (загрузка аудио)",
            "GET /api/v1/stt/status/{operation_id}": "Проверить статус распознавания",
            "GET /api/v1/metrics": "Метрики системы",
            "GET /api/v1/health": "Health check"
        },
        "docs": "/docs"
    }
