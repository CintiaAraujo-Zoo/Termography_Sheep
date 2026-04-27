# 🌡️ Thermography Sheep — FLIR Spot Temperature Extractor

A Python tool that automatically extracts spot temperature measurements from **FLIR radiometric JPEG images**, applying full emissivity and reflected-temperature correction using the Planck radiometric model.

Originally developed to support thermal infrared studies in **sheep** (_Ovis aries_), but compatible with any FLIR camera output that embeds Planck calibration constants in the image metadata.

---

## How It Works

Each FLIR radiometric `.jpg` file contains:

- A **16-bit raw thermal image** embedded in the JPEG stream
- **Planck calibration constants** (`PlanckR1`, `PlanckB`, `PlanckF`, `PlanckO`, `PlanckR2`) in the EXIF metadata
- **Emissivity** and **reflected apparent temperature** fields
- Up to 5 **measurement spot coordinates** (`Meas1Params`–`Meas5Params`) placed using FLIR Tools (or equivalent)

This script:

1. Reads all metadata using [`exiftool`](https://exiftool.org/)
2. Extracts the embedded 16-bit raw thermal array
3. Applies the **FLIR Planck radiometric formula** with emissivity correction:
   - Converts the reflected temperature to an equivalent raw value (`planck_inverse`)
   - Corrects each pixel: `raw_corrected = (raw − (1 − ε) × raw_reflected) / ε`
   - Converts to °C: `T(K) = B / ln(R1 / (R2 × (raw − O)) + F)` → `T(°C) = T(K) − 273.15`
4. Reads the (x, y) coordinates of each defined spot
5. Saves results to an **Excel file** with columns: `Image, SP1, SP2, SP3, SP4, SP5, Mean`

---

## Requirements

### System dependency

```bash
# Ubuntu / Debian
sudo apt-get install -y exiftool

# macOS (Homebrew)
brew install exiftool
```

### Python packages

```bash
pip install -r requirements.txt
```

**`requirements.txt`**
```
pandas>=1.5
numpy>=1.23
Pillow>=9.0
opencv-python-headless>=4.7
openpyxl>=3.0
```

Python 3.9+ is recommended.

---

## Usage

### Command line

```bash
python thermography_sheep.py --input ./images --output results.xlsx
```

| Argument | Short | Description |
|---|---|---|
| `--input FOLDER` | `-i` | Folder containing FLIR radiometric `.jpg` images |
| `--output FILE` | `-o` | Output Excel file path (default: `results_spots.xlsx`) |
| `--spots N` | `-n` | Maximum number of spots to extract per image (default: `5`) |
| `--verbose` | `-v` | Enable debug-level logging |

### Google Colab / Jupyter

```python
# Install dependencies
import subprocess
subprocess.run(["apt-get", "install", "-y", "exiftool"])
subprocess.run(["pip", "install", "pandas", "numpy", "pillow",
                "opencv-python-headless", "openpyxl"])

from thermography_sheep import process_folder

df = process_folder(
    input_folder="/content/drive/MyDrive/thermography/images",
    output_excel="/content/drive/MyDrive/thermography/results.xlsx",
    n_spots=5,
)
print(df)
```

---

## Output Example

| Image | SP1 | SP2 | SP3 | SP4 | SP5 | Mean |
|---|---|---|---|---|---|---|
| IMG_001.jpg | 38.4 | 37.9 | 38.1 | None | None | 38.1 |
| IMG_002.jpg | 39.0 | 38.6 | 38.8 | 38.2 | 38.5 | 38.6 |
| IMG_003.jpg | None | None | None | None | None | None |

- `None` indicates that the spot was not defined in the image or had invalid coordinates.
- Temperatures are rounded to 1 decimal place.

---

## Biological Background

Infrared thermography (IRT) is a non-invasive technique used to assess surface temperature patterns in livestock. In sheep, IRT has been applied to:

- Monitor physiological stress responses
- Detect early-stage mastitis and foot disorders
- Evaluate thermoregulation under different environmental conditions
- Assess body condition and peripheral blood flow

The emissivity correction is critical for biological tissue: wool and bare skin have distinct emissivity values (typically ε ≈ 0.95–0.99), and using the default camera setting without adjustment can introduce systematic bias.

---

## Troubleshooting

| Problem | Likely cause | Solution |
|---|---|---|
| All spots return `None` | Field names differ (e.g., `MakerNotes:PlanckR1`) | Run `exiftool -j image.jpg` and check the exact key names |
| Temperatures seem offset | `O` sign convention | Try `raw + O` instead of `raw - O` in `raw_to_kelvin()` |
| Spot coordinates appear flipped | x/y axis order | Swap `temp_c[y, x]` → `temp_c[x, y]` in `extract_spots()` |
| Wrong image mode error | Non-standard FLIR encoding | Check `img.mode` before conversion; some cameras use PNG-16 embedded |
| `exiftool` not found | Not installed | `sudo apt-get install exiftool` or `brew install exiftool` |

---

## Project Structure

```
Thermography_Sheep/
├── thermography_sheep.py   # Main script
├── requirements.txt        # Python dependencies
├── LICENSE                 # MIT License
└── README.md
```

---

## Citation

If you use this tool in a scientific publication, please cite it as:

```
Araujo, C. (2024). Thermography Sheep: FLIR spot temperature extractor for livestock 
infrared thermography studies. GitHub. https://github.com/CintiaAraujo-Zoo/Termography_Sheep
```

---

## License

This project is licensed under the **MIT License** — see [`LICENSE`](LICENSE) for details.

You are free to use, modify, and distribute this code with attribution.

---

## Author

**Cintia Araujo**  
Faculty, UESPI — Campus Corrente  
Doctoral Researcher, Programa de Pós-Graduação em Zootecnia, UNIVASF  
Visiting Researcher, University of Illinois at Urbana-Champaign (UIUC)

Research interests: Precision Livestock Technology · Ruminant Nutrition · Animal Biometrics
