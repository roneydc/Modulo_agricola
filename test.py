
class Processamento:
    def __init__(self, imagem):
        self.parametros = InputArquivo()
        self.path = imagem      
        with rasterio.open(imagem) as src:
            self.src = src        
            self.n_bandas = src.count
            # Crie uma lista de bandas
            self.bandas = [src.read(i) for i in range(1, self.n_bandas + 1)]
    def NDVI(self, bandaRed, bandaNir):
        indice = np.where((bandaNir + bandaRed) != 0,  (bandaNir - bandaRed)/ (bandaNir + bandaRed), np.nan)
        return indice


    def suavisar(self, indice, kernel = (10,10)):
        mascara_nan = np.isnan(indice)
        indice[mascara_nan] = 0
        mascara = (indice > 0)
        indice_suavizado = np.where(mascara, median_filter(indice, size=kernel), indice)
        #indice_suavizado = median_filter(indice, size=tamanho_kernel)
        return indice_suavizado   

    def zoneamento_kmeans(self, img_suavisada, n_classes):
        img_suavisada = img_suavisada.astype(float)
        mascara = img_suavisada == 0
        img_suavisada[mascara] = np.nan
        n_classes = n_classes 
        # Crie um array de pixels não-NaN
        pixels_validos = img_suavisada[~np.isnan(img_suavisada)].reshape(-1, 1)
        # Use o algoritmo K-Means para agrupar os pixels em 'n_classes' clusters
        kmeans = KMeans(n_clusters=n_classes, n_init=20, random_state=0).fit(pixels_validos)
        # Obtenha os centros dos clusters
        centros_clusters = kmeans.cluster_centers_
        # Atribua cada pixel à classe correspondente
        labels = kmeans.labels_
        # Crie uma matriz com os valores dos clusters e substitua NaN por NaN
        segmentacao = np.full_like(img_suavisada, np.nan)
        valid_pixel_indices = np.argwhere(~np.isnan(img_suavisada))
        cluster_labels = kmeans.predict(pixels_validos)
        x, y = np.where(~np.isnan(img_suavisada))
        lista = []
        for i in range(len(x)):
            cluster_label = cluster_labels[i]
            #segmentacao[x[i], y[i]] = centros_clusters[cluster_label]
            segmentacao[x[i], y[i]] = centros_clusters[cluster_label].item()

        return segmentacao

    def padronizar_intervalo(self, segmentacao):
        # Abrir o raster classificado
        img = segmentacao.copy() 

        # Garantir que não há NaN ou valores negativos inesperados
        img = np.nan_to_num(img, nan=-1)  # Substituir NaN por um valor de placeholder (caso necessário)

        # Definir novos valores igualmente espaçados
        num_classes = len(np.unique(segmentacao))
        new_values = np.linspace(0, (num_classes-1)*10, num_classes, dtype=int)

        # Substituir os valores antigos pelos novos
        unique_values = np.unique(img)
        reclass_map = {old: new for old, new in zip(unique_values, new_values)}

        # Aplicar a reclassificação
        for old_val, new_val in reclass_map.items():
            img[img == old_val] = new_val
            
        mascara = img == 0
        img[mascara] = np.nan
        return img


if __name__ == "__main__":

    
    path_arquivo = InputArquivo()
    imagem = path_arquivo.select_file()

    #PROCESSAMENTO DE IMAGEM BRUTA DE SATELITE
    processamento = Processamento(imagem)
    img_ndvi = processamento.NDVI(processamento.bandas[5],processamento.bandas[7])
    mascara2 = img_ndvi > 1
    img_ndvi[mascara2] = np.nan

    #PROCESSAMETNO DE IMAGEM COM NDVI JÁ CALCULADO
    processamento = Processamento(imagem)
    img_ndvi = processamento.bandas[0]
    mascara = img_ndvi <= -1
    img_ndvi[mascara] = np.nan


    #GERAR O ZONEAMENTO
    zonas = 10
    segmentacao = processamento.zoneamento_kmeans(img_ndvi, zonas)
    img_suavisada = processamento.suavisar(segmentacao, kernel=(20,20))
    segmentacao = processamento.zoneamento_kmeans(img_suavisada, zonas)
    segmentacao = processamento.padronizar_intervalo(segmentacao)
