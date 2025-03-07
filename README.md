# Termography_Sheep
Este script processa imagens térmicas provenientes de câmeras FLIR, em que cada imagem contém até cinco pontos de medição (“Meas1” a “Meas5”) definidos no software FLIR Tools (ou equivalente). 

# Script de Processamento de Imagens Térmicas FLIR

Este repositório contém um script em Python que processa **imagens térmicas** (geralmente em formato `.jpg` radiométrico) geradas por câmeras **FLIR**. Cada imagem pode conter até **cinco pontos de medição** (definidos no FLIR Tools ou software equivalente), cujas coordenadas são armazenadas nos metadados (`Meas1Params`, `Meas2Params`, etc.). O script:

1. **Lê** os metadados (PlanckR1, PlanckB, PlanckF, PlanckO, PlanckR2, emissividade, temperatura refletida, coordenadas dos pontos etc.) usando o `exiftool`.
2. **Extrai** o binário radiométrico (`RawThermalImage`), que é um TIFF/PNG de 16 bits embutido no arquivo `.jpg`.
3. **Converte** cada pixel para temperatura em °C, aplicando a fórmula radiométrica da FLIR, considerando **emissividade** e **temperatura refletida**.
4. **Identifica** as coordenadas (x,y) de até 5 spots (Sp1..Sp5) e obtém a temperatura desses pixels, arredondando para **1 casa decimal**.
5. **Gera** um arquivo Excel com colunas: `Imagem, SP1..SP5, Media`, sendo que cada linha representa uma imagem processada.

---

## Requisitos

- **Python 3.7+**
- **exiftool** (instalado no sistema)
- Bibliotecas Python:
  - [pandas](https://pandas.pydata.org/)
  - [numpy](https://numpy.org/)
  - [pillow](https://pillow.readthedocs.io/en/stable/)
  - [opencv-python-headless](https://pypi.org/project/opencv-python-headless/)

Para instalar via pip (exemplo no Google Colab ou local):
```bash
apt-get install -y exiftool
pip install pandas numpy pillow opencv-python-headless
```
# Como Usar
1. Clonar este repositório ou baixar o script .py.
   
2. Ajustar as variáveis no script:
   
pasta_imagens: caminho para a pasta onde estão suas imagens .jpg.
arquivo_excel: caminho e nome do arquivo Excel de saída (por exemplo, resultados_spots.xlsx).

3. Executar o script:
```
python script_processa_spots.py
```
Ele irá:

- Percorrer todas as imagens .jpg na pasta especificada.
- Para cada imagem, extrair o RawThermalImage e metadados Planck, emissividade e Tref.
- Calcular a temperatura real em cada pixel (corrigindo (raw_val + O) para offsets negativos).
- Ler as coordenadas Meas1Params..Meas5Params, obtendo a temperatura em cada spot.
- Armazenar tudo em um DataFrame e salvar no Excel.

4. Verificar o arquivo Excel gerado, que terá as colunas:
   
Imagem (nome do arquivo)
SP1, SP2, SP3, SP4, SP5 (temperaturas de cada spot)
Media (média das temperaturas válidas)

# Observações
- Se seus metadados Planck ou coordenadas estiverem em prefixos diferentes (ex.: MakerNotes:PlanckR1 em vez de PlanckR1), ajuste as chaves no script.
- Se (raw + O) ainda gerar temperaturas incorretas, teste (raw - O) no denominador da fórmula.
- A leitura dos pontos (MeasNParams) depende de o FLIR Tools gravar Meas1Params, Meas1Label etc. Se esses campos não existirem, a coluna aparecerá como None no Excel.
- O script assume que (x, y) é a forma correta de indexar temp_c[y, x]. Se os pontos parecerem invertidos, troque a ordem.

# Exemplo de Execução
```
# Instalar dependências
apt-get install -y exiftool
pip install pandas numpy pillow opencv-python-headless

# Ajustar o script
vim script_processa_spots.py

# Executar
python script_processa_spots.py

# Verificar o Excel
ls -l resultados_spots.xlsx
```

# Licença
Sinta-se livre para usar, modificar e distribuir, desde que mantenha a atribuição adequada.
```

> **Dica**: Você pode personalizar essa descrição no seu README para incluir exemplos de saída, prints do Excel, referências a documentação FLIR, etc.
