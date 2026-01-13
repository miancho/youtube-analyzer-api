"""
API FastAPI para análisis de canales de YouTube

Endpoints:
- POST /analyze - Analiza múltiples canales y devuelve URL de Google Sheet
- GET /health - Health check para Render
"""

import os
from typing import Optional
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


class ChannelResult(BaseModel):
    """Resultado del análisis de un canal."""
    channel_name: str
    channel_url: str
    total_videos: int
    promedio_score: float
    top_video_title: Optional[str] = None
    top_video_score: Optional[float] = None
    top_video_views: Optional[int] = None
    error: Optional[str] = None


class AnalyzeResponse(BaseModel):
    """Response del endpoint /analyze."""
    success: bool
    spreadsheet_url: str
    channels_analyzed: int
    results: list[ChannelResult]
    message: str


# --- Endpoints ---

@app.get("/")
async def root():
    """Endpoint raíz con información de la API."""
    return {
        "name": "YouTube Channel Analyzer API",
        "version": "1.0.0",
        "endpoints": {
            "POST /analyze": "Analiza múltiples canales de YouTube",
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
async def analyze_channels(request: AnalyzeRequest):
    """
    Analiza múltiples canales de YouTube.

    Recibe un array de URLs de canales, analiza los últimos 10 videos de cada uno,
    y exporta los resultados a un Google Sheet.

    Returns:
        URL del Google Sheet con los resultados
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

    # Inicializar cliente de Apify
    client = ApifyClient(APIFY_API_TOKEN)

    # Analizar cada canal
    resultados = []
    channel_results = []

    for channel_url in request.channels:
        try:
            resultado = analizar_canal(client, channel_url)
            resultados.append(resultado)

            # Crear resumen para la respuesta
            top_video = resultado['top_5'][0] if resultado.get('top_5') else None
            channel_results.append(ChannelResult(
                channel_name=resultado['channel_name'],
                channel_url=channel_url,
                total_videos=resultado.get('total_videos', 0),
                promedio_score=resultado.get('promedio_score', 0),
                top_video_title=top_video['title'] if top_video else None,
                top_video_score=top_video['score'] if top_video else None,
                top_video_views=top_video['views'] if top_video else None,
                error=resultado.get('error')
            ))

        except Exception as e:
            channel_results.append(ChannelResult(
                channel_name="Error",
                channel_url=channel_url,
                total_videos=0,
                promedio_score=0,
                error=str(e)
            ))

    # Exportar a Google Sheets
    try:
        spreadsheet_url = exportar_multiples_canales_a_sheets(
            resultados,
            spreadsheet_id
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error al exportar a Google Sheets: {str(e)}"
        )

    return AnalyzeResponse(
        success=True,
        spreadsheet_url=spreadsheet_url,
        channels_analyzed=len(request.channels),
        results=channel_results,
        message=f"Análisis completado. {len(resultados)} canales procesados."
    )


# --- Para desarrollo local ---
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
