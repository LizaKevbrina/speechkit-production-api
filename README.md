# speechkit-production
Production Audio Processing Platform: FastAPI + n8n + Yandex Cloud

Готовая к использованию платформа для создания голосовых помощников на базе искусственного интеллекта с архитектурой микросервисов, асинхронной оркестровкой конвейеров и возможностями бесшовной интеграции LLM.

Основная возможность: преобразование длинных аудиофайлов (до 4 часов) в текст с помощью асинхронного распознавания речи с интеллектуальной логикой повторных попыток и отслеживанием прогресса в реальном времени.

💡 Варианты использования: 

Для Fintech:

- Аналитика поддержки клиентов — автоматическая расшифровка звонков для анализа качества
- Соответствие требованиям и риски — автоматизированные аудиторские журналы и обнаружение фраз риска
- Голосовой банкинг — включите голосовые команды через платформы обмена сообщениями

Для предприятий:

- Анализ собраний — автоматическая расшифровка собраний с извлечением пунктов повестки дня
- Создание контента — преобразование голоса в текст для социальных сетей и маркетинга
- База знаний — аудиоархив с возможностью поиска и семантическим поиском

Готов к интеграции LLM:

- Добавить RAG для семантического поиска по транскриптам
- Многоагентные рабочие процессы: STT → Анализ → Действие → Ответ
- Вызов функции для автоматизированного создания задачи

Технологический стек:
Backend: Python 3.11, FastAPI, httpx, Pydantic, pydub
Orchestration: n8n workflows, Telegram Bot API
Storage: S3-compatible (boto3), KMS encryption
AI Service: Yandex SpeechKit (async STT API)
Infrastructure: Docker, Docker Compose

Архитектура: Микросервисы с раздельными уровнями оркестровки (n8n) и обработки (FastAPI), облачным хранилищем (S3) и интеграцией внешних сервисов ИИ (Yandex SpeechKit).

┌─────────────────────────────────────────────────────────────┐
│                    TELEGRAM USER                             │
│                 (or any messaging platform)                  │
└──────────────────┬──────────────────────────────────────────┘
                   │ Voice/Audio Message
                   ▼
┌─────────────────────────────────────────────────────────────┐
│            ORCHESTRATION LAYER (n8n)                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ • Telegram Webhook Trigger                           │  │
│  │ • Conditional Logic (voice detection)                │  │
│  │ • File Download & Upload                             │  │
│  │ • Async Polling with State Management                │  │
│  │ • Retry Logic (20 attempts, timeout handling)        │  │
│  │ • User Notifications (progress updates)              │  │
│  │ • Metrics Logging                                    │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────┬──────────────────────────────────────────┘
                   │ HTTP POST /api/v1/stt/transcribe
                   ▼
┌─────────────────────────────────────────────────────────────┐
│           PROCESSING SERVICE (FastAPI)                       │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ • REST API with versioning                           │  │
│  │ • Multipart form-data handling                       │  │
│  │ • Audio format detection (magic bytes)               │  │
│  │ • MP3 → OGG conversion (pydub)                       │  │
│  │ • S3 upload with KMS encryption                      │  │
│  │ • Yandex SpeechKit API integration                   │  │
│  │ • Background task management                         │  │
│  │ • Health checks & metrics endpoints                  │  │
│  └──────────────────────────────────────────────────────┘  │
└──────────────────┬──────────────────────────────────────────┘
                   │
        ┌──────────┴──────────┐
        │                     │
        ▼                     ▼
┌──────────────┐    ┌──────────────────┐
│ OBJECT       │    │ YANDEX SPEECHKIT │
│ STORAGE      │    │ (STT API)        │
│              │    │                  │
│ • Audio files│    │ • Async STT      │
│ • KMS keys   │    │ • Operation ID   │
│ • Backup     │    │ • Polling API    │
└──────────────┘    └──────────────────┘

🚀 Быстрый старт
'''bash
Clone and setup
git clone https://github.com/yourusername/speechkit-platform.git
cd speechkit-platform
cp .env.example .env

# Configure .env with your credentials
# YANDEX_API_KEY, S3_BUCKET_NAME, AWS_ACCESS_KEY_ID, etc.

# Run with Docker
docker-compose up -d

# Test
curl http://localhost:8000/api/v1/health
'''

Загрузить аудио:
'''bash
curl -X POST http://localhost:8000/api/v1/stt/transcribe \
  -F "audio_file=@voice.ogg" \
  -F "user_id=test" \
  -F "lang=ru-RU"
'''
Проверить статус:
'''bash
curl http://localhost:8000/api/v1/stt/status/{operation_id}
'''


                  📊 API Endpoints
Endpoint	              Method	         Description
/api/v1/stt/transcribe	 POST	      Start async transcription
/api/v1/stt/status/{id}	 GET	       Check operation status
/api/v1/metrics	         GET	       System metrics and stats
/api/v1/health	         GET	             Health check
/docs	                   GET	          Interactive API doc


Расширение с LLM
Этот проект — основа для ИИ-помощников. Легко расширяется:
'''bash
# Example: RAG integration
from langchain.vectorstores import Pinecone
transcription = result["text"]
vectorstore.add_texts([transcription], metadatas=[...])

# Example: Multi-agent workflow
tools = [transcribe_tool, analyze_tool, summarize_tool]
agent = initialize_agent(tools, llm=OpenAI())
'''

📄 License
MIT License - see LICENSE

👤 Author
Elizaveta Kevbrina - — AI Developer & Workflow Engineer 

GitHub: @LizaKevbrina
Email: elisa.kevbrina@yandex.ru

🙏 Acknowledgments
Built with: FastAPI • n8n • Yandex Cloud • Docker

<div align="center">
⭐ Поставьте этому репозиторию звездочку, если он оказался вам полезен!
Сделано с ❤️ для сообщества ИИ
</div>
