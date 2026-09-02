# Plataforma de Zoneamento Agrícola

Geração de zonas de manejo a partir de imagens multiespectrais: índices
vegetativos → K-Means → vetorização → prescrição (Rx) em shapefile.

## Princípio de arquitetura

`processing/` não importa nada de FastAPI, Celery, banco ou storage. É NumPy,
rasterio e geopandas puros. Quem chama é o worker (em produção) ou o `cli.py`
(em desenvolvimento). Manter esse isolamento é o que permite testar a lógica de
imagem sem subir infraestrutura, e trocar de infra depois sem reescrever nada.

```
navegador → API (FastAPI) → fila (Redis) → worker (Celery) → processing/
                ↓                                ↓
           PostgreSQL/PostGIS            object storage (COG)
```

## Dois simuladores

Testam coisas diferentes; não são intercambiáveis.

| Arquivo | Fala com | Usa para |
|---|---|---|
| `cli.py` | `processing/` direto | desenvolver e depurar a lógica de imagem |
| `client.py` | HTTP com a API | validar a plataforma; substitui o navegador |

`client.py` não importa `processing/` de propósito. Se importasse, estaria
testando o `cli.py` com passos extras em vez da plataforma.

## Rodando sem infraestrutura

```bash
pip install -r requirements.txt
make dados                       # gera GeoTIFFs sintéticos
python cli.py ./dados/t1.tif --zonas 5 --mediana 5 --saida ./out -v
```

Outros exemplos:

```bash
# composição multi-temporal
python cli.py ./dados/t1.tif ./dados/t2.tif ./dados/t3.tif --agregador media --zonas 6

# forçar chunking e ver o efeito
python cli.py ./dados/big.tif --sensor indice_pronto --estrategia chunked --chunk-px 2048

# sugerir número de zonas por silhouette
python cli.py ./dados/t1.tif --sugerir-zonas

# prescrição linear de 40 a 80 kg/ha, mais dose na zona fraca
python cli.py ./dados/t1.tif --zonas 5 --dose-min 40 --dose-max 80 --dose-inversa
```

## Rodando a plataforma (modo  desenvolvimento)

Precisa só de Postgres. O storage vai para disco e o processamento roda no
próprio processo da API, sem Redis nem worker separado.

```powershell
docker run -d --name zon-db -e POSTGRES_USER=zon -e POSTGRES_PASSWORD=zon `
  -e POSTGRES_DB=zoneamento -p 5432:5432 postgis/postgis:16-3.4

copy .env.example .env
alembic upgrade head
python scripts\bootstrap.py          # cria a organização demo

uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Depois, em outro terminal:

```powershell
python client.py .\dados\t1.tif --zonas 5 --mediana 5
```

Ou abra `http://127.0.0.1:8000` no navegador: há uma página de teste com upload
e mapa Leaflet, registrada só em modo debug. `http://127.0.0.1:8000/docs` traz
o Swagger.

Use `127.0.0.1` e não `localhost`: no Windows, `localhost` costuma resolver
para IPv6 (`::1`) enquanto o uvicorn escuta em IPv4, e a conexão é recusada.

### Dois modos, mesma API

| | dev | produção |
|---|---|---|
| `STORAGE_BACKEND` | `local` (disco + rota `/files`) | `s3` (R2/S3/MinIO) |
| `CELERY_EAGER` | `true` (síncrono, no processo) | `false` (worker separado) |
| Infra | só Postgres | + Redis + storage + worker |

As rotas e o `client.py` são idênticos nos dois. Trocar de modo é editar o
`.env`. O `client.py` já faz polling mesmo no modo síncrono, justamente para
que a migração não mude nada nele.

## Rodando a plataforma completa

```bash
cp .env.example .env
make up                          # postgres+postgis, redis, minio, api, worker, titiler
make migrate                     # aplica a migration inicial
python client.py /tmp/t1.tif --zonas 5
```

Os testes de banco só rodam se `DATABASE_URL_TEST` estiver definida; sem ela são
pulados, para que `pytest tests/` continue funcionando sem infraestrutura:

```bash
make test                        # 21 testes, sem infra
make test-db                     # + 4 testes contra PostGIS real
```

### Migrations

```bash
make migrate                     # alembic upgrade head
make migration m="add coluna x"  # autogenerate
make check-drift                 # models.py vs migration: deve dar zero
```

`check-drift` é o alvo que mais evita dor: roda o autogenerate e falha se
detectar qualquer diferença entre os modelos e o schema aplicado. Sem ele, a
divergência só aparece em produção.

## Estrutura

```
main.py              # só monta o app FastAPI (15 linhas)
cli.py               # simulador local, chama processing/ direto
client.py            # simulador HTTP, substitui o navegador

processing/          # Python puro, sem dependência de web
  params.py          #   dataclasses compartilhadas por CLI e API
  sensors.py         #   mapa de bandas por perfil de sensor
  io.py              #   leitura por janela, escrita COG
  indices.py         #   NDVI, NDRE, GNDVI, NDWI, TGI
  composite.py       #   alinhamento e agregação multi-temporal
  filters.py         #   mediana, majoritário, outliers
  zoning.py          #   KMeans, limiares, quantis
  vectorize.py       #   shapes → dissolve → simplify → SHP/GeoJSON
  prescription.py    #   regras de dose
  pipeline.py        #   orquestração, escolha de estratégia

api/                 # rotas, schemas Pydantic
db/                  # modelos SQLAlchemy + PostGIS, migrations
workers/             # tasks Celery
storage/             # cliente S3/R2/MinIO
tests/               # 19 testes, rodam sem infraestrutura
scripts/             # gerador de dados sintéticos
```

## Estratégias de processamento

A escolha é automática pelo número de pixels (`limiar_chunk_px`, padrão 40M),
com override via `--estrategia`.

**memória** — lê o raster inteiro. Simples e rápido para arquivos pequenos.

**chunked** — duas passadas. A primeira varre o raster amostrando pixels
válidos, para ajustar o modelo e calcular os percentis globais. A segunda
aplica o modelo janela por janela, escrevendo direto no arquivo de saída.

Os filtros de vizinhança exigem **overlap** entre as janelas de leitura, senão
aparecem costuras nas bordas dos blocos. O overlap é calculado a partir do
maior kernel em uso (mediana e majoritário), e o resultado é recortado para a
região útil antes de gravar.

As duas estratégias convergem para ~97% de concordância pixel a pixel. O
resíduo vem da amostragem do K-Means, não de costura: o resultado é
insensível ao tamanho do bloco (verificado em `test_chunked_sem_costura`).

## Diferenças em relação ao notebook original

Correções que valem registro, porque várias eram silenciosas:

| Problema | Efeito |
|---|---|
| `PyQt5.QFileDialog` para entrada | impossível num servidor |
| `salvar()` usava a global `processamento` | quebrava fora do notebook |
| `__init__` carregava todas as bandas | 8 bandas de 10k×10k passam de 6 GB |
| K-Means atribuía centroides em loop Python | 69s → 2,8s num raster de 600×600 |
| labels do K-Means não ordenados | a "zona 3" mudava de significado entre execuções |
| `padronizar_intervalo` reclassificava in-place | valores já convertidos eram convertidos de novo |
| `snap(geom, unary_union(tudo))` por geometria | 38s dos 56s de vetorização; trocado por `set_precision` |
| `unary_union` | deprecado no Shapely 2 → `union_all` |
| `try/except: pass` no batch | erros sumiam sem rastro |
| índices de banda hardcoded | só funcionava com Planet 8 bandas |
| `src` usado fora do bloco `with` | funcionava por acidente |
| filtro de mediana zerava NaN antes de filtrar | puxava as bordas do talhão para baixo |
| tolerâncias métricas aplicadas sobre graus | em EPSG:4326, `set_precision(1.0)` = 111 km: apagava tudo |
| área do pixel = res_x·res_y/10000 com res em graus | todas as zonas com 0,00 ha |

## Decisões de schema

`JSONB` em vez de `JSON`: permite indexar e consultar dentro do campo
(`metadados->>'n_zonas'`), o que `JSON` no Postgres não faz.

`BigInteger` no tamanho do arquivo: mosaicos passam de 2 GB e estouram `Integer`.

`ondelete=CASCADE` nas zonas: apagar um job precisa levar os polígonos junto,
senão sobram órfãos no PostGIS.

Índice composto `(org_id, status)` em jobs: o polling do front consulta jobs em
andamento da organização o tempo todo.

A extensão PostGIS é criada na migration antes de qualquer tabela com coluna
`Geometry`. O autogenerate do Alembic não inclui `CREATE EXTENSION` sozinho, e
sem ela o `CREATE TABLE` falha.

Duas escolhas de projeto que não estavam no original:

**Normalização por imagem antes de compor.** Média direta de NDVI de datas
diferentes faz a imagem de maior amplitude dominar o resultado, e o zoneamento
passa a refletir o estádio fenológico em vez do potencial produtivo. Vem ligada
por padrão.

**Ordem única de filtros nos dois modos.** A mediana roda antes da remoção de
outliers, em memória e em chunks. Quando as ordens divergiam, os dois modos
ajustavam o K-Means sobre distribuições diferentes e produziam centroides
diferentes para o mesmo raster.

## CRS geográfico (EPSG:4326)

Vários fornecedores entregam GeoTIFF em EPSG:4326, onde as coordenadas são
graus. As tolerâncias de `snap` e `simplify` e o cálculo de área são em metros,
então o pipeline reprojeta internamente para o UTM estimado antes de aplicá-las
e volta ao CRS original. A área do pixel é convertida pelo comprimento real de
um grau na latitude do centro do raster.

Sem isso, `snap_tolerancia=1.0` significaria 1 grau (~111 km) e colapsaria um
talhão de 2 km num único ponto, com o erro pouco informativo
`NaN or None values are not allowed`.

## Índices saturados

Em dossel denso o NDVI satura: num talhão real de teste, o intervalo
interquartil era 0,886 a 0,896, uma variação de 0,01, com uma cauda de pixels de
borda descendo até −0,02. O K-Means gasta os clusters na cauda e joga 83% da
área numa zona só.

O pipeline avisa quando a maior zona passa de 60% da área, e grava
`concentracao_maior_zona` nos metadados. Duas saídas:

- `--metodo quantis` gera zonas de área equivalente, ignorando a forma da
  distribuição
- `--indice NDRE` usa a borda do vermelho, que não satura como o NDVI em
  biomassa alta (exige banda `rededge` no sensor)

No talhão de teste, NDVI + K-Means dava 83% numa zona; NDRE + quantis distribuiu
20% em cada.

## Ordem de desenvolvimento

1. `processing/` + `cli.py`, validando contra as saídas do notebook antigo ✅
2. Chunking e composição multi-temporal, ainda pelo `cli.py` ✅
3. Postgres, modelos, Alembic ✅
4. FastAPI + storage + `client.py` — *esqueleto pronto, falta auth*
5. Celery e Redis — *esqueleto pronto*
6. Front-end, traduzindo o `client.py` para JS
7. TiTiler para visualização

O `client.py` já faz polling desde a etapa 4, mesmo quando a resposta é
instantânea. Assim a migração para processamento assíncrono na etapa 5 não
quebra nada nele.

## Pendências antes de produção

- Autenticação real (`ORG_DEMO` está hardcoded em `api/routes/`)
- Reprocessamento reaproveitando o job pai (a rota existe, a lógica de pular
  etapas ainda não)
- Reprojeção automática para UTM quando o CRS for geográfico
- Conversão explícita para COG na ingestão
- Retry e timeout por job
