# Análisis de Videos Destacados de YouTube

## Objetivo
Dado un video de YouTube, identificar el canal y analizar los últimos 10 videos para determinar cuáles 5 han sobresalido respecto al rendimiento promedio del canal.

## Entrada
- URL de cualquier video de YouTube (se extrae el canal automáticamente)

## Salida
- Google Sheet con:
  - Lista de los 10 últimos videos con métricas
  - Top 5 videos destacados con score compuesto
  - Promedio del canal para comparación
  - Análisis de por qué cada video sobresalió

## Herramientas
- `ejecucion/youtube_analyzer.py` - Script principal

## Flujo de Ejecución

### 1. Extraer Canal del Video
- Parsear la URL del video para obtener el video ID
- Llamar a YouTube API para obtener el channel ID del video

### 2. Obtener Últimos 10 Videos
- Buscar uploads del canal ordenados por fecha
- Extraer: video ID, título, fecha de publicación

### 3. Obtener Métricas de Cada Video
Para cada video obtener:
- `views`: Vistas totales
- `likes`: Cantidad de likes
- `comments`: Cantidad de comentarios
- `published_at`: Fecha de publicación

### 4. Calcular Score Compuesto
```
dias_publicado = (hoy - published_at).days
vistas_por_dia = views / max(dias_publicado, 1)
engagement_rate = (likes + comments) / views * 100

score = (vistas_por_dia * 0.4) + (engagement_rate * 100 * 0.3) + (views / 1000 * 0.3)
```

Pesos:
- 40% Vistas por día (normaliza por antigüedad)
- 30% Engagement rate (indica calidad del contenido)
- 30% Vistas totales (indica alcance absoluto)

### 5. Identificar Videos Destacados
- Calcular score promedio del canal
- Identificar videos con score > promedio
- Rankear y seleccionar top 5

### 6. Exportar a Google Sheets
- Hoja 1: "Todos los Videos" - Lista completa con métricas
- Hoja 2: "Top 5 Destacados" - Videos sobresalientes con análisis

## Variables de Entorno Requeridas
- `YOUTUBE_API_KEY`: API key de YouTube Data API v3
- `GOOGLE_SHEETS_ID`: ID del spreadsheet de destino
- `credentials.json`: OAuth credentials para Google Sheets

## Límites y Consideraciones
- YouTube API tiene quota de 10,000 unidades/día
- Cada búsqueda cuesta ~100 unidades
- Cada video.list cuesta ~1 unidad por video
- Este flujo consume aprox ~120 unidades por ejecución

## Casos Límite
- Canal con menos de 10 videos: Analizar todos los disponibles
- Video privado/eliminado: Saltar y continuar
- API quota excedida: Informar al usuario, no reintentar

## Ejemplo de Uso
```bash
python ejecucion/youtube_analyzer.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Aprendizajes
(Actualizar esta sección con descubrimientos durante la ejecución)
