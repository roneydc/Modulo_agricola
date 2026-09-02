param([Parameter(Position=0)][string]$Alvo = "help")

switch ($Alvo) {
    "dados" {
        New-Item -ItemType Directory -Force -Path dados | Out-Null
        python scripts\gerar_teste.py --saida .\dados\t1.tif --lado 800
        python scripts\gerar_teste.py --saida .\dados\t2.tif --lado 800 --seed 2
    }
    "exemplo"  { python cli.py .\dados\t1.tif --zonas 5 --mediana 5 --saida .\out -v }
    "db"       { docker run -d --name zon-db -e POSTGRES_USER=zon -e POSTGRES_PASSWORD=zon -e POSTGRES_DB=zoneamento -p 5432:5432 postgis/postgis:16-3.4 }
    "migrate"  { alembic upgrade head; python scripts\bootstrap.py }
    "api"      { uvicorn main:app --reload --host 127.0.0.1 --port 8000 }
    "cliente"  { python client.py .\dados\t1.tif --zonas 5 --mediana 5 }
    "test"     { python -m pytest tests\ -v }
    "up"       { docker compose up -d --build }
    "down"     { docker compose down }
    default    { "Alvos: dados, exemplo, db, migrate, api, cliente, test, up, down" }
}
