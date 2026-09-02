# Plataforma de Zoneamento Agrícola — Levantamento de Funcionalidades

Documento de referência para o escopo do módulo de processamento e da plataforma.

Legenda de origem:
- `[S]` já existe no script atual (`geracao_zoneamento.ipynb`)
- `[N]` novo requisito
- `[P]` exigência que surge por ser plataforma (não existia no notebook)

Legenda de prioridade: **P0** = MVP · **P1** = próxima etapa · **P2** = futuro

---

## 1. Ingestão de dados

| # | Funcionalidade | Origem | Prio |
|---|---|---|---|
| 1.1 | Upload de GeoTIFF (`.tif` / `.tiff`), single ou multibanda | [S] | P0 |
| 1.2 | Upload direto para storage via presigned URL (sem passar pela API) | [P] | P0 |
| 1.3 | Validação na entrada: CRS presente, `transform` válido, dtype, nº de bandas, nodata | [P] | P0 |
| 1.4 | Extração de metadados (resolução, extensão, nº de pixels, data) para o banco | [P] | P0 |
| 1.5 | Conversão automática para **COG** com overviews internos | [P] | P0 |
| 1.6 | Detecção/seleção de perfil de sensor com mapa de bandas | [P] | P0 |
| 1.7 | Suporte a bandas em arquivos separados, agrupadas por sufixo (`_red_(Raw).tiff`, `_nir_(Raw).tiff`) | [S] | P1 |
| 1.8 | Entrada de raster de índice já calculado (banda única, ex: NDVI pronto) | [S] | P0 |
| 1.9 | Upload de shapefile/GeoJSON de contorno de talhão | [P] | P1 |
| 1.10 | Reprojeção automática para CRS métrico (UTM) quando o original for geográfico | [P] | P1 |
| 1.11 | Upload de múltiplos arquivos em lote / pasta zipada | [S] | P1 |

**Perfis de sensor a suportar (item 1.6)**

Os índices de banda estão hardcoded hoje (`bandas[5]`, `bandas[7]`). Isso vira uma tabela de perfis:

| Perfil | Bandas | Mapeamento |
|---|---|---|
| PlanetScope 8 bandas | 8 | coastal, blue, green_i, green, yellow, red, rededge, nir |
| PlanetScope 4 bandas | 4 | blue, green, red, nir |
| Sentinel-2 (subset) | var. | por nome de banda |
| Drone multiespectral | 5 | blue, green, red, rededge, nir |
| Drone RGB | 3 | blue, green, red |
| Índice pronto | 1 | value |
| Customizado | var. | definido pelo usuário na UI |

---

## 2. Índices vegetativos

| # | Índice | Fórmula | Origem | Prio |
|---|---|---|---|---|
| 2.1 | NDVI | (NIR − RED)/(NIR + RED) | [S] | P0 |
| 2.2 | NDRE | (NIR − REDEDGE)/(NIR + REDEDGE) | [S] | P0 |
| 2.3 | GNDVI | (NIR − GREEN)/(NIR + GREEN) | [S] | P0 |
| 2.4 | NDWI | (GREEN − NIR)/(GREEN + NIR) | [S] | P0 |
| 2.5 | TGI (normalizado min-max) | G − 0.39·R − 0.61·B | [S] | P0 |
| 2.6 | SAVI / MSAVI (solo exposto) | — | [N] | P1 |
| 2.7 | EVI | — | [N] | P1 |
| 2.8 | CIgreen / CIrededge | — | [N] | P1 |
| 2.9 | VARI / ExG (só RGB) | — | [N] | P1 |
| 2.10 | Fórmula customizada com parser seguro de expressão | [N] | P2 |

**Funcionalidades de apoio**

- 2.11 `[S]` **P0** — Máscara de validade: descartar valores fora de faixa (ex.: NDVI > 1 ou ≤ −1), nodata e divisão por zero
- 2.12 `[P]` **P0** — Definir nodata explícito no raster de saída em vez de depender de NaN
- 2.13 `[S]` **P1** — Normalização min-max opcional para qualquer índice
- 2.14 `[N]` **P1** — Máscara de solo exposto / não-vegetação por limiar antes do zoneamento
- 2.15 `[N]` **P2** — Máscara de nuvem e sombra

---

## 3. Composição multi-temporal (NOVO)

Combinar 2 ou mais imagens (datas ou índices distintos) numa camada única antes do K-Means.

| # | Funcionalidade | Prio |
|---|---|---|
| 3.1 | **Alinhamento de grid**: verificar CRS, resolução e extensão; reamostrar todas para um grid de referência | P0 |
| 3.2 | Escolha do grid de referência: primeira imagem, a de maior resolução, ou o talhão | P0 |
| 3.3 | **Normalização por imagem antes de compor** (min-max ou z-score) | P0 |
| 3.4 | Agregador: **média** | P0 |
| 3.5 | Agregadores: mediana, mínimo, máximo, desvio padrão, percentil N | P1 |
| 3.6 | Pesos por imagem (data recente pesa mais) | P1 |
| 3.7 | Política de máscara: interseção (só pixels válidos em todas) vs união (ignora NaN) | P0 |
| 3.8 | Nº mínimo de observações válidas por pixel | P1 |
| 3.9 | Camada de **estabilidade temporal** (CV = desvio/média) como saída extra | P1 |
| 3.10 | Composição de índices diferentes na mesma data (NDVI + NDRE) | P1 |

**Ponto crítico do item 3.3.** Fazer média direta de NDVI de datas diferentes é a principal fonte de erro nesse tipo de composição. Estádios fenológicos distintos produzem faixas de valor distintas, e a imagem com maior amplitude domina o resultado. A média precisa ser feita sobre valores normalizados por imagem, ou o zoneamento reflete a data e não o potencial produtivo do talhão. Deve ser o comportamento padrão, com opção de desligar.

---

## 4. Pré-processamento

| # | Funcionalidade | Origem | Prio |
|---|---|---|---|
| 4.1 | Filtro de mediana com kernel configurável | [S] | P0 |
| 4.2 | Clip / máscara pelo contorno do talhão | [P] | P1 |
| 4.3 | Remoção de outliers por percentil (ex.: corta abaixo de P2 e acima de P98) | [S] | P0 |
| 4.4 | Downsample opcional para acelerar (processa em resolução menor, exporta na original) | [N] | P1 |
| 4.5 | Erosão de borda (remove pixels de bordadura/carreador) | [N] | P1 |
| 4.6 | Preenchimento de falhas pequenas | [N] | P2 |

---

## 5. Zoneamento

| # | Método | Origem | Prio |
|---|---|---|---|
| 5.1 | **K-Means** com nº de classes configurável | [S] | P0 |
| 5.2 | Segmentação por limiares lineares entre P20 e P95 | [S] | P1 |
| 5.3 | Quantis (zonas de área equivalente) | [N] | P1 |
| 5.4 | Jenks natural breaks | [N] | P2 |
| 5.5 | K-Means multivariado (vários índices/camadas como features) | [N] | P2 |

**Funcionalidades de apoio**

- 5.6 `[P]` **P0** — **Ordenação determinística das classes pelo valor do centróide.** Os labels do K-Means são arbitrários entre execuções; sem reordenar, a "zona 1" muda de significado a cada rodada e a prescrição fica inconsistente.
- 5.7 `[S]` **P0** — Padronização do intervalo final de classes (0–100 em degraus regulares)
- 5.8 `[S]` **P1** — Passe duplo: K-Means → suavização → K-Means novamente
- 5.9 `[N]` **P1** — Sugestão de nº ótimo de zonas (silhouette / elbow / índice de Davies-Bouldin)
- 5.10 `[N]` **P1** — `random_state` fixo e registrado no job, para reprodutibilidade
- 5.11 `[N]` **P1** — Área mínima por zona (zonas abaixo do limite são fundidas)

---

## 6. Estratégia de processamento e chunking (NOVO)

Decisão automática por volume, com override manual.

| # | Funcionalidade | Prio |
|---|---|---|
| 6.1 | Contagem de pixels na ingestão e escolha automática da estratégia | P0 |
| 6.2 | **Modo in-memory** para rasters abaixo do limiar | P0 |
| 6.3 | **Modo chunked** por janelas (`rasterio.windows` / blocos do COG) acima do limiar | P0 |
| 6.4 | Limiar configurável por ambiente (não hardcoded no código) | P0 |
| 6.5 | K-Means em duas passadas no modo chunked | P0 |
| 6.6 | Estatísticas globais (percentis, min/max) por amostragem ou histograma acumulado | P0 |
| 6.7 | `MiniBatchKMeans` quando a amostra ainda for grande demais | P1 |
| 6.8 | Progresso incremental do job (% de chunks concluídos) | P1 |
| 6.9 | Migração para `rioxarray` + `dask` se o chunking manual não bastar | P2 |

**Sobre o item 6.5.** No modo chunked o K-Means não pode ver todos os pixels de uma vez. O fluxo é: amostrar aleatoriamente N pixels válidos do raster inteiro → `fit` nessa amostra → varrer o raster janela por janela aplicando `predict` e gravando o resultado direto no COG de saída. O resultado é estatisticamente equivalente ao K-Means completo, desde que a amostra seja grande o bastante (na prática, algumas centenas de milhares de pixels já saturam).

**Sobre o item 6.6.** Os percentis (P20/P95) usados hoje pelo `zoneamento` e pela remoção de outliers exigem o array inteiro. No modo chunked isso é resolvido com a mesma amostra do 6.5, ou com um histograma construído em uma passada prévia.

**Sobre o filtro de mediana em chunks.** Filtros de janela precisam de **overlap** entre os blocos, senão aparecem costuras visíveis nas bordas. A janela de leitura deve ser expandida pelo raio do kernel e o resultado recortado antes de gravar.

**Sobre performance.** O K-Means do script atual atribui os centróides pixel a pixel em loop Python. Essa é a origem do gargalo, mais do que o volume de dados. A versão vetorizada é ordens de magnitude mais rápida e deve ser adotada nos dois modos, não só no chunked.

---

## 7. Pós-processamento raster

| # | Funcionalidade | Origem | Prio |
|---|---|---|---|
| 7.1 | Filtro majoritário para eliminar ruído sal-e-pimenta | [S] (escrito, desativado) | P0 |
| 7.2 | Remoção de manchas menores que área mínima, absorvidas pelo vizinho dominante | [N] | P1 |
| 7.3 | Suavização de bordas entre zonas | [N] | P1 |

---

## 8. Vetorização e exportação

| # | Funcionalidade | Origem | Prio |
|---|---|---|---|
| 8.1 | Raster → polígonos (`rasterio.features.shapes`) com máscara de nodata | [S] | P0 |
| 8.2 | Dissolve por classe | [S] | P0 |
| 8.3 | Snap entre geometrias vizinhas (evita slivers) | [S] | P0 |
| 8.4 | Simplify com tolerância configurável, preservando topologia | [S] | P0 |
| 8.5 | Multipart → singlepart opcional | [N] | P1 |
| 8.6 | Cálculo de área em hectares por polígono e por zona | [P] | P0 |
| 8.7 | Validação/reparo de geometria (`make_valid`) | [P] | P0 |
| 8.8 | Gravação das geometrias no **PostGIS** | [P] | P0 |
| 8.9 | Buffer positivo + negativo para arredondar cantos | [S] (comentado) | P2 |

---

## 9. Prescrição (Rx)

Hoje é uma função `regra()` com degraus fixos de 10 em 10. Precisa virar configuração.

| # | Funcionalidade | Prio |
|---|---|---|
| 9.1 | Tabela de regras zona → dose, editável pelo usuário | P0 |
| 9.2 | Perfis de recomendação salvos e reutilizáveis (por cultura, insumo, cliente) | P1 |
| 9.3 | Relação direta (mais dose onde produz mais) ou inversa (mais dose onde produz menos) | P0 |
| 9.4 | Dose mínima e máxima, e dose zero para zonas descartadas | P0 |
| 9.5 | Cálculo do insumo total necessário (dose × área) | P0 |
| 9.6 | Ajuste para bater com uma quantidade total pré-definida de insumo | P1 |
| 9.7 | Múltiplos insumos na mesma prescrição | P2 |

---

## 10. Saídas

| # | Artefato | Origem | Prio |
|---|---|---|---|
| 10.1 | COG do índice calculado | [S] (GeoTIFF simples) | P0 |
| 10.2 | COG das zonas classificadas | [S] | P0 |
| 10.3 | Shapefile zipado (`.shp` + `.shx` + `.dbf` + `.prj`) | [S] | P0 |
| 10.4 | GeoJSON | [P] | P0 |
| 10.5 | Preview PNG com paleta RdYlGn | [S] | P0 |
| 10.6 | CSV/XLSX com estatísticas por zona (área, média, dose, total) | [N] | P1 |
| 10.7 | Relatório PDF com mapa, tabela e parâmetros | [N] | P1 |
| 10.8 | Formatos de monitor de bordo (ISOXML, Trimble, John Deere) | [N] | P2 |
| 10.9 | KML/KMZ | [N] | P2 |

---

## 11. Visualização

| # | Funcionalidade | Prio |
|---|---|---|
| 11.1 | Mapa web com tiles servidos do COG (TiTiler + MapLibre) | P0 |
| 11.2 | Paletas configuráveis e escala min/max ajustável | P0 |
| 11.3 | Histograma do índice | P1 (existe no script) |
| 11.4 | Sobreposição das zonas vetorizadas com o índice | P1 |
| 11.5 | Comparação lado a lado entre datas | P2 |
| 11.6 | Edição manual de polígonos de zona | P2 |

---

## 12. Plataforma

| # | Funcionalidade | Prio |
|---|---|---|
| 12.1 | Autenticação e organizações (multi-tenant) | P0 |
| 12.2 | Hierarquia Cliente → Fazenda → Talhão → Imagem → Job | P0 |
| 12.3 | Fila assíncrona com status (`queued`, `running`, `done`, `failed`) | P0 |
| 12.4 | Registro dos parâmetros de cada job (reprodutibilidade) | P0 |
| 12.5 | Mensagem de erro legível quando o job falha (sem `except: pass`) | P0 |
| 12.6 | Reprocessar mudando parâmetros sem refazer as etapas caras | P0 |
| 12.7 | Separação dos jobs em etapas (índice / composição / zoneamento / vetorização) | P0 |
| 12.8 | Histórico e versionamento de resultados | P1 |
| 12.9 | Processamento em lote de vários talhões | P1 |
| 12.10 | API pública com token | P1 |
| 12.11 | Timeout e retry por job | P0 |
| 12.12 | Cotas por plano (nº de hectares ou de jobs) | P2 |
| 12.13 | Webhook de conclusão | P2 |

---

## Dependência entre etapas

```
ingestão → [índice] ──┐
                      ├→ [composição multi-temporal] → [zoneamento] → [vetorização] → [Rx] → exportação
ingestão → [índice] ──┘
```

Cada colchete é um job independente, com entrada e saída persistidas. Isso permite trocar o número de zonas sem recalcular índice nem composição, que é a operação mais frequente na prática.

---

## Questões em aberto

1. Qual o tamanho típico e o tamanho máximo dos rasters? Define o limiar de chunking e o tamanho do worker.
2. Quantas imagens entram numa composição típica? Duas, ou uma safra inteira?
3. As imagens de uma composição vêm sempre do mesmo sensor, ou pode misturar Planet com drone? Se misturar, a normalização por imagem passa de recomendada a obrigatória.
4. O usuário desenha o talhão na plataforma ou sempre sobe um shapefile?
5. Qual monitor de bordo os clientes usam? Define a prioridade do item 10.8.
6. A prescrição é sempre de um insumo só por arquivo?
7. Existe dado de produtividade (colheita) para validar as zonas, ou o zoneamento é só por imagem?