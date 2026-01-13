"""
API FastAPI para análisis de canales de YouTube

Endpoints:
- POST /analyze - Analiza múltiples canales en background y devuelve URL de Google Sheet
- GET /health - Health check para Render
"""

import os
import uuid
from typing import Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from dotenv import load_dotenv
from apify_client import ApifyClient

# Importar servicio de YouTube
from ejecucion.youtube_service import (
    analizar_canal,
    exportar_multiples_canales_a_sheets
)

# Cargar variables de entorno
load_dotenv()

APIFY_API_TOKEN = os.getenv('APIFY_API_TOKEN')
GOOGLE_SHEETS_ID = os.getenv('GOOGLE_SHEETS_ID')

# Almacén de jobs en memoria (en producción usarías Redis)
jobs_store: dict = {}

# Crear app FastAPI
app = FastAPI(
    title="YouTube Channel Analyzer API",
    description="Analiza múltiples canales de YouTube y exporta resultados a Google Sheets",
    version="1.0.0"
)

# Configurar CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Modelos Pydantic ---

class AnalyzeRequest(BaseModel):
    """Request para analizar canales de YouTube."""
    channels: list[str] = Field(
        ...,
        description="Lista de URLs de canales de YouTube",
        example=[
            "https://www.youtube.com/@nicksaraev",
            "https://www.youtube.com/@miancho"
        ]
    )
    spreadsheet_id: Optional[str] = Field(
        None,
        description="ID del Google Sheet (opcional, usa el default si no se proporciona)"
    )


class AnalyzeResponse(BaseModel):
    """Response del endpoint /analyze."""
    success: bool
    job_id: str
    status: str
    spreadsheet_url: str
    message: str


class JobStatus(BaseModel):
    """Estado de un job de análisis."""
    job_id: str
    status: str  # pending, processing, completed, error
    channels: list[str]
    spreadsheet_url: str
    started_at: str
    completed_at: Optional[str] = None
    error: Optional[str] = None
    channels_processed: int = 0
    total_channels: int = 0


# --- Background Task ---

def process_channels_background(
    job_id: str,
    channels: list[str],
    spreadsheet_id: str
):
    """Procesa los canales en background y actualiza el job store."""
    try:
        jobs_store[job_id]["status"] = "processing"
        jobs_store[job_id]["total_channels"] = len(channels)

        client = ApifyClient(APIFY_API_TOKEN)
        resultados = []

        for i, channel_url in enumerate(channels):
            try:
                resultado = analizar_canal(client, channel_url)
                resultados.append(resultado)
                jobs_store[job_id]["channels_processed"] = i + 1
            except Exception as e:
                resultados.append({
                    'channel_name': 'Error',
                    'channel_url': channel_url,
                    'error': str(e),
                    'videos': [],
                    'top_5': [],
                    'promedio_score': 0
                })

        # Exportar a Google Sheets
        spreadsheet_url = exportar_multiples_canales_a_sheets(
            resultados,
            spreadsheet_id
        )

        jobs_store[job_id]["status"] = "completed"
        jobs_store[job_id]["completed_at"] = datetime.now().isoformat()
        jobs_store[job_id]["spreadsheet_url"] = spreadsheet_url

    except Exception as e:
        jobs_store[job_id]["status"] = "error"
        jobs_store[job_id]["error"] = str(e)
        jobs_store[job_id]["completed_at"] = datetime.now().isoformat()


# --- Endpoints ---

@app.get("/")
async def root():
    """Endpoint raíz con información de la API."""
    return {
        "name": "YouTube Channel Analyzer API",
        "version": "1.0.0",
        "endpoints": {
            "POST /analyze": "Inicia análisis de canales (background job)",
            "GET /job/{job_id}": "Consulta estado de un job",
            "GET /health": "Health check"
        }
    }


@app.get("/health")
async def health_check():
    """Health check para Render."""
    return {
        "status": "healthy",
        "apify_configured": bool(APIFY_API_TOKEN),
        "sheets_configured": bool(GOOGLE_SHEETS_ID)
    }


@app.post("/analyze", response_model=AnalyzeResponse)
async def analyze_channels(request: AnalyzeRequest, background_tasks: BackgroundTasks):
    """
    Inicia el análisis de múltiples canales de YouTube en background.

    El análisis se ejecuta en segundo plano. Usa GET /job/{job_id} para
    consultar el estado y obtener los resultados cuando termine.

    Returns:
        job_id para consultar el estado y la URL del spreadsheet
    """
    # Validar configuración
    if not APIFY_API_TOKEN:
        raise HTTPException(
            status_code=500,
            detail="APIFY_API_TOKEN no está configurado"
        )

    spreadsheet_id = request.spreadsheet_id or GOOGLE_SHEETS_ID
    if not spreadsheet_id:
        raise HTTPException(
            status_code=400,
            detail="Debes proporcionar spreadsheet_id o configurar GOOGLE_SHEETS_ID"
        )

    if not request.channels:
        raise HTTPException(
            status_code=400,
            detail="Debes proporcionar al menos un canal"
        )

    # Crear job
    job_id = str(uuid.uuid4())[:8]
    spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"

    jobs_store[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "channels": request.channels,
        "spreadsheet_url": spreadsheet_url,
        "started_at": datetime.now().isoformat(),
        "completed_at": None,
        "error": None,
        "channels_processed": 0,
        "total_channels": len(request.channels)
    }

    # Iniciar tarea en background
    background_tasks.add_task(
        process_channels_background,
        job_id,
        request.channels,
        spreadsheet_id
    )

    return AnalyzeResponse(
        success=True,
        job_id=job_id,
        status="pending",
        spreadsheet_url=spreadsheet_url,
        message=f"Análisis iniciado. {len(request.channels)} canales en cola. "
                f"Consulta GET /job/{job_id} para ver el progreso. "
                f"Los resultados aparecerán en el Google Sheet cuando termine."
    )


@app.get("/job/{job_id}", response_model=JobStatus)
async def get_job_status(job_id: str):
    """
    Consulta el estado de un job de análisis.

    Returns:
        Estado actual del job, progreso y URL del spreadsheet
    """
    if job_id not in jobs_store:
        raise HTTPException(
            status_code=404,
            detail=f"Job {job_id} no encontrado"
        )

    return JobStatus(**jobs_store[job_id])


@app.get("/jobs")
async def list_jobs():
    """Lista todos los jobs (últimos 50)."""
    jobs = list(jobs_store.values())[-50:]
    return {
        "total": len(jobs_store),
        "jobs": jobs
    }


# --- Para desarrollo local ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
