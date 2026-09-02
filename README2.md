POST /jobs  {arquivo_id, sensor, indice: NDVI, n_zonas: 10, regra_rx: {...}}
   → grava job no Postgres (status=queued), retorna job_id
   → Celery: 
        1. lê COG do storage (windowed)
        2. calcula índice
        3. máscara de validade + suavização
        4. KMeans vetorizado
        5. padroniza classes
        6. grava raster de zonas como COG → storage
        7. vetoriza (rasterio.features.shapes) → dissolve → simplify
        8. aplica regra de dose (Rx)
        9. grava geometrias no PostGIS + gera SHP/GeoJSON zipado
   → status=done
GET /jobs/{id}  → status, links do COG, do SHP e do GeoJSON