"""
Servicio de análisis de YouTube - Lógica de negocio reutilizable
"""

import os
import re
from datetime import datetime, timezone
from apify_client import ApifyClient
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

# Actor de Apify para YouTube
YOUTUBE_SCRAPER_ACTOR = "streamers/youtube-scraper"

# Scopes para Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']


def obtener_info_canal(client: ApifyClient, channel_url: str) -> dict:
    """Obtiene información del canal usando Apify."""
    run_input = {
        "startUrls": [{"url": channel_url}],
        "maxResults": 1,
        "maxResultsShorts": 0,
        "maxResultStreams": 0,
    }

    run = client.actor(YOUTUBE_SCRAPER_ACTOR).call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

    if not items:
        raise ValueError(f"No se pudo obtener información del canal: {channel_url}")

    video_info = items[0]
    return {
        'channel_name': video_info.get('channelName', 'Desconocido'),
        'channel_url': video_info.get('channelUrl', channel_url),
    }


def obtener_videos_canal(client: ApifyClient, channel_url: str, max_videos: int = 10) -> list[dict]:
    """Obtiene los últimos N videos de un canal usando Apify."""
    run_input = {
        "startUrls": [{"url": channel_url}],
        "maxResults": max_videos,
        "maxResultsShorts": 0,
        "maxResultStreams": 0,
    }

    run = client.actor(YOUTUBE_SCRAPER_ACTOR).call(run_input=run_input)
    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

    videos = []
    ahora = datetime.now(timezone.utc)

    for item in items:
        date_str = item.get('date', '')
        try:
            if date_str:
                published = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                dias_publicado = (ahora - published).days
            else:
                dias_publicado = 0
        except:
            dias_publicado = 0

        views = item.get('viewCount', 0) or 0
        likes = item.get('likes', 0) or 0
        comments = item.get('commentsCount', 0) or 0

        views_safe = max(views, 1)
        engagement_rate = (likes + comments) / views_safe * 100

        video = {
            'video_id': item.get('id', ''),
            'title': item.get('title', 'Sin título'),
            'url': item.get('url', ''),
            'published_at': date_str,
            'dias_publicado': dias_publicado,
            'views': views,
            'likes': likes,
            'comments': comments,
            'engagement_rate': engagement_rate,
            'duration': item.get('duration', ''),
        }
        video['score'] = calcular_score(video)
        videos.append(video)

    return videos


def calcular_score(video: dict) -> float:
    """
    Calcula el score compuesto de un video.
    - 40% Vistas por día
    - 30% Engagement rate
    - 30% Vistas totales
    """
    views = video['views']
    dias_publicado = video['dias_publicado']
    engagement_rate = video['engagement_rate']

    dias = max(dias_publicado, 1)
    vistas_por_dia = views / dias

    score = (
        (vistas_por_dia * 0.4) +
        (engagement_rate * 100 * 0.3) +
        (views / 1000 * 0.3)
    )

    return round(score, 2)


def analizar_porque_destaca(video: dict, promedio_score: float) -> str:
    """Genera una explicación de por qué el video destaca."""
    razones = []

    if video['views'] > 10000:
        razones.append("Alto alcance")

    if video['engagement_rate'] > 5:
        razones.append("Engagement excepcional")
    elif video['engagement_rate'] > 3:
        razones.append("Buen engagement")

    if video['dias_publicado'] < 7 and video['views'] > 1000:
        razones.append("Viral reciente")

    if promedio_score > 0 and video['score'] > promedio_score * 2:
        razones.append("Outlier significativo")

    return ", ".join(razones) if razones else "Rendimiento consistente"


def analizar_canal(client: ApifyClient, channel_url: str) -> dict:
    """
    Analiza un canal de YouTube y devuelve los datos procesados.
    """
    # Obtener info del canal
    channel_info = obtener_info_canal(client, channel_url)
    channel_name = channel_info['channel_name']
    real_channel_url = channel_info['channel_url']

    # Obtener videos
    videos = obtener_videos_canal(client, real_channel_url, max_videos=10)

    if not videos:
        return {
            'channel_name': channel_name,
            'channel_url': channel_url,
            'error': 'No se encontraron videos',
            'videos': [],
            'top_5': [],
            'promedio_score': 0
        }

    # Calcular estadísticas
    scores = [v['score'] for v in videos]
    promedio_score = round(sum(scores) / len(scores), 2) if scores else 0

    # Ordenar y obtener top 5
    videos_ordenados = sorted(videos, key=lambda x: x['score'], reverse=True)
    top_5 = videos_ordenados[:5]

    # Agregar análisis a cada video del top 5
    for v in top_5:
        v['razon_destaca'] = analizar_porque_destaca(v, promedio_score)
        if promedio_score > 0:
            v['vs_promedio'] = round(((v['score'] / promedio_score) - 1) * 100, 1)
        else:
            v['vs_promedio'] = 0

    return {
        'channel_name': channel_name,
        'channel_url': channel_url,
        'videos': videos_ordenados,
        'top_5': top_5,
        'promedio_score': promedio_score,
        'total_videos': len(videos)
    }


def obtener_credenciales_sheets():
    """Obtiene las credenciales OAuth para Google Sheets desde variables de entorno o archivos."""
    creds = None

    # Intentar cargar desde variable de entorno (para Render)
    token_json = os.getenv('GOOGLE_TOKEN_JSON')
    if token_json:
        import json
        token_data = json.loads(token_json)
        creds = Credentials.from_authorized_user_info(token_data, SCOPES)

    # Fallback a archivo local
    token_path = 'token.json'
    if not creds and os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            raise ValueError(
                "No hay credenciales válidas. "
                "Configura GOOGLE_TOKEN_JSON o ejecuta la autenticación local primero."
            )

    return creds


def exportar_multiples_canales_a_sheets(
    resultados: list[dict],
    spreadsheet_id: str
) -> str:
    """
    Exporta los resultados de múltiples canales a un Google Sheet.
    Retorna la URL del spreadsheet.
    """
    creds = obtener_credenciales_sheets()
    gc = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(spreadsheet_id)

    # --- Hoja 1: Resumen de Canales ---
    try:
        hoja_resumen = spreadsheet.worksheet("Resumen Canales")
        hoja_resumen.clear()
    except gspread.WorksheetNotFound:
        hoja_resumen = spreadsheet.add_worksheet(title="Resumen Canales", rows=100, cols=15)

    headers_resumen = [
        'Canal', 'Videos Analizados', 'Score Promedio',
        'Mejor Video', 'Score Mejor', 'Vistas Mejor',
        'Engagement Mejor', 'URL Mejor Video'
    ]
    hoja_resumen.append_row(headers_resumen)

    for resultado in resultados:
        if resultado.get('error'):
            hoja_resumen.append_row([
                resultado['channel_name'],
                'Error',
                resultado.get('error', 'Desconocido'),
                '', '', '', '', ''
            ])
            continue

        mejor = resultado['top_5'][0] if resultado['top_5'] else {}
        row = [
            resultado['channel_name'],
            resultado['total_videos'],
            resultado['promedio_score'],
            mejor.get('title', 'N/A'),
            mejor.get('score', 0),
            mejor.get('views', 0),
            round(mejor.get('engagement_rate', 0), 2),
            mejor.get('url', '')
        ]
        hoja_resumen.append_row(row)

    # --- Hoja 2: Top 5 de Cada Canal ---
    try:
        hoja_top = spreadsheet.worksheet("Top 5 Por Canal")
        hoja_top.clear()
    except gspread.WorksheetNotFound:
        hoja_top = spreadsheet.add_worksheet(title="Top 5 Por Canal", rows=200, cols=15)

    headers_top = [
        'Canal', 'Ranking', 'Título', 'Score', 'vs Promedio %',
        'Vistas', 'Likes', 'Engagement %', 'Por qué destaca', 'URL'
    ]
    hoja_top.append_row(headers_top)

    for resultado in resultados:
        if resultado.get('error'):
            continue

        for i, v in enumerate(resultado['top_5'], 1):
            video_url = v.get('url') or f"https://youtube.com/watch?v={v.get('video_id', '')}"
            row = [
                resultado['channel_name'],
                i,
                v['title'],
                v['score'],
                v.get('vs_promedio', 0),
                v['views'],
                v['likes'],
                round(v['engagement_rate'], 2),
                v.get('razon_destaca', ''),
                video_url
            ]
            hoja_top.append_row(row)

    # --- Hoja 3: Todos los Videos ---
    try:
        hoja_todos = spreadsheet.worksheet("Todos los Videos")
        hoja_todos.clear()
    except gspread.WorksheetNotFound:
        hoja_todos = spreadsheet.add_worksheet(title="Todos los Videos", rows=500, cols=15)

    headers_todos = [
        'Canal', 'Título', 'Vistas', 'Likes', 'Comentarios',
        'Días Publicado', 'Engagement %', 'Score', 'URL'
    ]
    hoja_todos.append_row(headers_todos)

    for resultado in resultados:
        if resultado.get('error'):
            continue

        for v in resultado['videos']:
            video_url = v.get('url') or f"https://youtube.com/watch?v={v.get('video_id', '')}"
            row = [
                resultado['channel_name'],
                v['title'],
                v['views'],
                v['likes'],
                v['comments'],
                v['dias_publicado'],
                round(v['engagement_rate'], 2),
                v['score'],
                video_url
            ]
            hoja_todos.append_row(row)

    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
