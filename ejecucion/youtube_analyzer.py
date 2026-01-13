#!/usr/bin/env python3
"""
Analizador de Videos Destacados de YouTube (usando Apify)

Dado un video de YouTube, analiza los últimos 10 videos del canal
y determina cuáles 5 han sobresalido respecto al promedio.

Uso:
    python youtube_analyzer.py "https://www.youtube.com/watch?v=VIDEO_ID"
"""

import os
import sys
import re
from datetime import datetime, timezone
from dotenv import load_dotenv
from apify_client import ApifyClient
import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Cargar variables de entorno
load_dotenv()

APIFY_API_TOKEN = os.getenv('APIFY_API_TOKEN')
GOOGLE_SHEETS_ID = os.getenv('GOOGLE_SHEETS_ID')

# Scopes para Google Sheets
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']

# Actor de Apify para YouTube
YOUTUBE_SCRAPER_ACTOR = "streamers/youtube-scraper"


def extraer_video_id(url: str) -> str:
    """Extrae el video ID de una URL de YouTube."""
    patterns = [
        r'(?:v=|\/)([0-9A-Za-z_-]{11}).*',
        r'(?:youtu\.be\/)([0-9A-Za-z_-]{11})',
        r'(?:embed\/)([0-9A-Za-z_-]{11})',
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    raise ValueError(f"No se pudo extraer video ID de: {url}")


def obtener_info_video_y_canal(client: ApifyClient, video_url: str) -> dict:
    """Obtiene información del video y su canal usando Apify."""
    print("   Consultando Apify para obtener info del video...")

    run_input = {
        "startUrls": [{"url": video_url}],
        "maxResults": 1,
        "maxResultsShorts": 0,
        "maxResultStreams": 0,
    }

    run = client.actor(YOUTUBE_SCRAPER_ACTOR).call(run_input=run_input)

    items = list(client.dataset(run["defaultDatasetId"]).iterate_items())

    if not items:
        raise ValueError("No se pudo obtener información del video")

    video_info = items[0]
    return {
        'channel_name': video_info.get('channelName', 'Desconocido'),
        'channel_url': video_info.get('channelUrl', ''),
    }


def obtener_videos_canal(client: ApifyClient, channel_url: str, max_videos: int = 10) -> list[dict]:
    """Obtiene los últimos N videos de un canal usando Apify."""
    print(f"   Obteniendo últimos {max_videos} videos del canal...")

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
        # Parsear fecha de publicación
        date_str = item.get('date', '')
        try:
            if date_str:
                # Apify devuelve fechas en formato ISO o similar
                published = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                dias_publicado = (ahora - published).days
            else:
                dias_publicado = 0
        except:
            dias_publicado = 0

        views = item.get('viewCount', 0) or 0
        likes = item.get('likes', 0) or 0
        comments = item.get('commentsCount', 0) or 0

        # Calcular engagement rate
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

    Pesos:
    - 40% Vistas por día (normaliza por antigüedad)
    - 30% Engagement rate
    - 30% Vistas totales
    """
    views = video['views']
    dias_publicado = video['dias_publicado']
    engagement_rate = video['engagement_rate']

    # Evitar división por cero
    dias = max(dias_publicado, 1)

    vistas_por_dia = views / dias

    # Score compuesto normalizado
    score = (
        (vistas_por_dia * 0.4) +
        (engagement_rate * 100 * 0.3) +
        (views / 1000 * 0.3)
    )

    return round(score, 2)


def obtener_credenciales_sheets():
    """Obtiene las credenciales OAuth para Google Sheets."""
    creds = None
    token_path = 'token.json'
    creds_path = 'credentials.json'

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(creds_path):
                raise FileNotFoundError(
                    "No se encontró credentials.json. "
                    "Descargalo desde Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(creds_path, SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, 'w') as token:
            token.write(creds.to_json())

    return creds


def exportar_a_sheets(videos: list[dict], top_videos: list[dict], channel_name: str, promedio_score: float):
    """Exporta los resultados a Google Sheets."""
    creds = obtener_credenciales_sheets()
    gc = gspread.authorize(creds)

    # Abrir el spreadsheet
    spreadsheet = gc.open_by_key(GOOGLE_SHEETS_ID)

    # Hoja 1: Todos los Videos
    try:
        hoja_todos = spreadsheet.worksheet("Todos los Videos")
        hoja_todos.clear()
    except gspread.WorksheetNotFound:
        hoja_todos = spreadsheet.add_worksheet(title="Todos los Videos", rows=100, cols=10)

    # Headers
    headers = ['Título', 'Vistas', 'Likes', 'Comentarios', 'Días Publicado',
               'Engagement %', 'Score', 'URL']
    hoja_todos.append_row(headers)

    # Datos
    for v in videos:
        row = [
            v['title'],
            v['views'],
            v['likes'],
            v['comments'],
            v['dias_publicado'],
            round(v['engagement_rate'], 2),
            v['score'],
            v['url'] or f"https://youtube.com/watch?v={v['video_id']}"
        ]
        hoja_todos.append_row(row)

    # Agregar promedio
    hoja_todos.append_row([])
    hoja_todos.append_row([f"Canal: {channel_name}", f"Score Promedio: {promedio_score}"])

    # Hoja 2: Top 5 Destacados
    try:
        hoja_top = spreadsheet.worksheet("Top 5 Destacados")
        hoja_top.clear()
    except gspread.WorksheetNotFound:
        hoja_top = spreadsheet.add_worksheet(title="Top 5 Destacados", rows=50, cols=10)

    headers_top = ['Ranking', 'Título', 'Score', 'vs Promedio', 'Vistas',
                   'Engagement %', 'Por qué destaca', 'URL']
    hoja_top.append_row(headers_top)

    for i, v in enumerate(top_videos, 1):
        diferencia = round(((v['score'] / promedio_score) - 1) * 100, 1) if promedio_score > 0 else 0
        razon = analizar_porque_destaca(v, promedio_score)
        row = [
            i,
            v['title'],
            v['score'],
            f"+{diferencia}%",
            v['views'],
            round(v['engagement_rate'], 2),
            razon,
            v['url'] or f"https://youtube.com/watch?v={v['video_id']}"
        ]
        hoja_top.append_row(row)

    print(f"\n✅ Resultados exportados a Google Sheets")
    print(f"   https://docs.google.com/spreadsheets/d/{GOOGLE_SHEETS_ID}")


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


def main():
    if len(sys.argv) < 2:
        print("Uso: python youtube_analyzer.py <URL_VIDEO_YOUTUBE>")
        sys.exit(1)

    video_url = sys.argv[1]

    # Validar configuración
    if not APIFY_API_TOKEN or APIFY_API_TOKEN == 'tu_apify_token_aqui':
        print("❌ Error: Configurá APIFY_API_TOKEN en el archivo .env")
        sys.exit(1)

    if not GOOGLE_SHEETS_ID or GOOGLE_SHEETS_ID == 'id_de_tu_spreadsheet':
        print("❌ Error: Configurá GOOGLE_SHEETS_ID en el archivo .env")
        sys.exit(1)

    print(f"🔍 Analizando video: {video_url}")

    # Inicializar cliente de Apify
    client = ApifyClient(APIFY_API_TOKEN)

    # 1. Obtener info del video y canal
    print("\n📺 Obteniendo información del canal...")
    channel_info = obtener_info_video_y_canal(client, video_url)
    channel_name = channel_info['channel_name']
    channel_url = channel_info['channel_url']
    print(f"   Canal: {channel_name}")

    if not channel_url:
        print("❌ No se pudo obtener la URL del canal")
        sys.exit(1)

    # 2. Obtener últimos 10 videos del canal
    print("\n📥 Obteniendo videos del canal...")
    videos = obtener_videos_canal(client, channel_url, max_videos=10)

    if not videos:
        print("❌ No se encontraron videos en el canal")
        sys.exit(1)

    print(f"   Encontrados: {len(videos)} videos")

    # 3. Calcular promedio y encontrar destacados
    scores = [v['score'] for v in videos]
    promedio_score = round(sum(scores) / len(scores), 2) if scores else 0

    # Ordenar por score y tomar top 5
    videos_ordenados = sorted(videos, key=lambda x: x['score'], reverse=True)
    top_5 = videos_ordenados[:5]

    print(f"\n📈 Score promedio del canal: {promedio_score}")
    print(f"\n🏆 Top 5 Videos Destacados:")
    for i, v in enumerate(top_5, 1):
        diferencia = round(((v['score'] / promedio_score) - 1) * 100, 1) if promedio_score > 0 else 0
        print(f"   {i}. {v['title'][:50]}...")
        print(f"      Score: {v['score']} (+{diferencia}% vs promedio)")
        print(f"      Vistas: {v['views']:,} | Likes: {v['likes']:,} | Engagement: {v['engagement_rate']:.2f}%")
        video_url_display = v['url'] or f"https://youtube.com/watch?v={v['video_id']}"
        print(f"      URL: {video_url_display}")

    # Mostrar tabla completa
    print(f"\n📋 Todos los videos analizados:")
    print("-" * 80)
    for v in videos_ordenados:
        print(f"  • {v['title'][:60]}")
        print(f"    Vistas: {v['views']:,} | Score: {v['score']} | Engagement: {v['engagement_rate']:.2f}%")

    # 4. Exportar a Google Sheets (opcional)
    try:
        print("\n📤 Exportando a Google Sheets...")
        exportar_a_sheets(videos, top_5, channel_name, promedio_score)
    except Exception as e:
        print(f"\n⚠️  No se pudo exportar a Google Sheets: {e}")
        print("   Los resultados se mostraron arriba en consola.")


if __name__ == '__main__':
    main()
