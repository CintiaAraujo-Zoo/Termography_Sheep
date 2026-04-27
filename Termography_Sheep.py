!apt-get install -y exiftool
!pip install pandas numpy pillow opencv-python-headless

import os
import subprocess
import json
import math
import numpy as np
import pandas as pd
from PIL import Image
import io

######################################
# CONFIGURAÇÕES
######################################
pasta_imagens = "/content/drive/MyDrive/projeto_termografia/termografia_ovinos"  # Ajuste o caminho
arquivo_excel  = "/content/drive/MyDrive/projeto_termografia/resultados_spots.xlsx"
n_spots = 5  # Número máximo de "MeasN" que vamos procurar (Meas1..Meas5)

def extrair_metadados(caminho):
    """Extrai metadados via exiftool -j e retorna dicionário."""
    cmd = ["exiftool", "-j", "-q", "-S", caminho]
    saida = subprocess.check_output(cmd)
    lista = json.loads(saida.decode("utf-8"))
    if lista:
        return lista[0]
    return {}

def extrair_raw_thermal_image(caminho):
    """
    Extrai o binário do RawThermalImage (radiométrico).
    Se estiver em outro prefixo, troque '-RawThermalImage' para '-APP1:RawThermalImage'.
    """
    cmd = ["exiftool", "-b", "-RawThermalImage", caminho]
    try:
        return subprocess.check_output(cmd)
    except subprocess.CalledProcessError:
        return None

def planck_direct(raw_val, R1, B, F, O, R2):
    """
    T(K) = B / ln(R1 / [R2*(raw_val + O)] + F).
    Se O=-6622 => (raw_val - 6622).
    """
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        offset_arr = raw_val + O
        offset_arr[offset_arr < 1] = 1  # clamp para evitar log(<=0)
        tempK = B / np.log(R1 / (R2*offset_arr) + F)
    return tempK

def planck_inverse(tempK, R1, B, F, O, R2):
    """Inverte a eq. Planck => raw_val."""
    expBT = math.exp(B / tempK)
    return (R1 / (expBT - F)) / R2 - O

def calcular_temp_corrigida(raw_array, R1, B, F, O, R2, emiss, tref_c):
    """
    1) raw_refl p/ Tref => planck_inverse
    2) raw_corr = (raw - (1-e)*raw_refl)/ e
    3) T(K) = planck_direct(raw_corr)
    => °C
    """
    tref_k = tref_c + 273.15
    raw_refl = planck_inverse(tref_k, R1, B, F, O, R2)
    raw_corr = (raw_array - (1.0 - emiss)*raw_refl) / emiss
    raw_corr[raw_corr < 1] = 1

    tempK = planck_direct(raw_corr, R1, B, F, O, R2)
    tempK[tempK <= 0] = np.nan
    return tempK - 273.15

######################################
# PROCESSAR TODAS AS IMAGENS DA PASTA
######################################
if not os.path.exists(pasta_imagens):
    print(f"❌ Pasta não encontrada: {pasta_imagens}")
else:
    # Lista de linhas p/ DataFrame final
    registros = []

    arquivos = [f for f in os.listdir(pasta_imagens) if f.lower().endswith(".jpg")]
    print(f"Encontrados {len(arquivos)} arquivos .jpg em {pasta_imagens}")

    for arq in arquivos:
        caminho = os.path.join(pasta_imagens, arq)
        try:
            meta = extrair_metadados(caminho)
            if not meta:
                print(f"{arq}: Metadados vazios.")
                registros.append([arq, None, None, None, None, None, None])
                continue

            # Ler Planck e emiss/Tref (sem prefixo, pois no JSON elas aparecem diretas)
            R1 = float(meta.get("PlanckR1", 1.0))
            B  = float(meta.get("PlanckB", 1.0))
            F  = float(meta.get("PlanckF", 1.0))
            O  = float(meta.get("PlanckO", 0.0))
            R2 = float(meta.get("PlanckR2", 1.0))

            emiss_str = meta.get("Emissivity", "1.0")
            if isinstance(emiss_str, str):
                emiss_str = emiss_str.replace(" C","").strip()
            emiss = float(emiss_str)

            tref_str = meta.get("ReflectedApparentTemperature", "20.0")
            if isinstance(tref_str, str):
                tref_str = tref_str.replace(" C","").strip()
            tref_c = float(tref_str)

            raw_bytes = extrair_raw_thermal_image(caminho)
            if not raw_bytes:
                print(f"{arq}: sem RawThermalImage.")
                registros.append([arq, None, None, None, None, None, None])
                continue

            # Abrir como 16 bits
            img_pil = Image.open(io.BytesIO(raw_bytes))
            if img_pil.mode != "I;16":
                img_pil = img_pil.convert("I")
            raw_arr = np.array(img_pil, dtype=np.uint16)

            # Calcular temp corrigida
            temp_c = calcular_temp_corrigida(raw_arr, R1, B, F, O, R2, emiss, tref_c)

            # Lê até 5 spots
            sp_dict = {"Sp1":None, "Sp2":None, "Sp3":None, "Sp4":None, "Sp5":None}
            for i in range(1, n_spots+1):
                coords_str = meta.get(f"Meas{i}Params")
                label_str  = meta.get(f"Meas{i}Label")
                if not coords_str or not label_str:
                    continue

                # Se coords vier como dict {val:"259 96"}, extrair
                if isinstance(coords_str, dict) and "val" in coords_str:
                    coords_str = coords_str["val"]
                if isinstance(label_str, dict) and "val" in label_str:
                    label_str = label_str["val"]

                xs, ys = coords_str.split()
                x_coord, y_coord = int(xs), int(ys)

                sp_name = label_str  # "Sp1", "Sp2" etc.
                if sp_name not in sp_dict:
                    sp_name = f"Sp{i}"

                # Se coords válidas
                h, w = temp_c.shape
                if 0 <= y_coord < h and 0 <= x_coord < w:
                    val = temp_c[y_coord, x_coord]
                    # Arredonda p/ 1 casa decimal
                    sp_dict[sp_name] = round(val, 1)

            # Média
            valid_vals = [v for v in sp_dict.values() if v is not None and not np.isnan(v)]
            media_val = round(sum(valid_vals)/len(valid_vals),1) if valid_vals else None

            registros.append([
                arq,
                sp_dict["Sp1"], sp_dict["Sp2"], sp_dict["Sp3"],
                sp_dict["Sp4"], sp_dict["Sp5"],
                media_val
            ])

        except Exception as e:
            print(f"{arq}: erro => {e}")
            registros.append([arq, None, None, None, None, None, None])

    # Gera DataFrame e salva
    df = pd.DataFrame(registros, columns=[
        "Imagem","SP1","SP2","SP3","SP4","SP5","Media"
    ])
    df.to_excel(arquivo_excel, index=False)
    print(f"✅ Excel gerado em: {arquivo_excel}")
    print(df)
