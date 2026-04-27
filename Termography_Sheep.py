"""
thermography_sheep.py
---------------------
Processes FLIR radiometric JPEG images to extract spot temperature
measurements (Sp1–Sp5) defined in FLIR Tools (or equivalent software).

Each image is expected to have:
  - Planck calibration constants (PlanckR1, PlanckB, PlanckF, PlanckO, PlanckR2)
  - Emissivity and ReflectedApparentTemperature metadata
  - Up to 5 measurement spots (Meas1Params–Meas5Params)
  - An embedded 16-bit RawThermalImage

Output: Excel file with columns [Image, SP1, SP2, SP3, SP4, SP5, Mean]

Usage:
    python thermography_sheep.py --input ./images --output results.xlsx

Dependencies:
    pip install pandas numpy pillow opencv-python-headless openpyxl
    # System: sudo apt-get install -y exiftool
"""

import argparse
import io
import json
import logging
import math
import os
import subprocess
import warnings
from typing import Optional

import numpy as np
import pandas as pd
from PIL import Image

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Metadata extraction
# ---------------------------------------------------------------------------
def extract_metadata(image_path: str) -> dict:
    """
    Extracts all EXIF/metadata from a FLIR radiometric JPEG using exiftool.

    Parameters
    ----------
    image_path : str
        Full path to the .jpg file.

    Returns
    -------
    dict
        Dictionary of metadata fields. Empty dict on failure.
    """
    cmd = ["exiftool", "-j", "-q", "-S", image_path]
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.DEVNULL)
        records = json.loads(output.decode("utf-8"))
        return records[0] if records else {}
    except (subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        log.warning("exiftool failed for '%s': %s", image_path, exc)
        return {}


def extract_raw_thermal(image_path: str) -> Optional[bytes]:
    """
    Extracts the embedded raw thermal image binary from a FLIR JPEG.

    If the standard tag fails, falls back to 'APP1:RawThermalImage'.

    Parameters
    ----------
    image_path : str
        Full path to the .jpg file.

    Returns
    -------
    bytes or None
        Raw binary of the embedded thermal image, or None on failure.
    """
    for tag in ["-RawThermalImage", "-APP1:RawThermalImage"]:
        try:
            data = subprocess.check_output(
                ["exiftool", "-b", tag, image_path],
                stderr=subprocess.DEVNULL,
            )
            if data:
                return data
        except subprocess.CalledProcessError:
            continue
    return None


# ---------------------------------------------------------------------------
# Radiometric conversion (Planck-based FLIR formula)
# ---------------------------------------------------------------------------
def planck_inverse(temp_k: float, R1: float, B: float, F: float,
                   O: float, R2: float) -> float:
    """
    Converts a temperature in Kelvin to a raw sensor value using the inverse
    Planck equation from FLIR's calibration model.

    Formula:  raw = R1 / (R2 * (exp(B / T) - F)) - O

    Parameters
    ----------
    temp_k : float
        Temperature in Kelvin.
    R1, B, F, O, R2 : float
        FLIR Planck calibration constants from image metadata.

    Returns
    -------
    float
        Equivalent raw sensor value (digital number).
    """
    return R1 / (R2 * (math.exp(B / temp_k) - F)) - O


def raw_to_kelvin(raw: np.ndarray, R1: float, B: float, F: float,
                  O: float, R2: float) -> np.ndarray:
    """
    Converts a 2-D array of raw 16-bit sensor values to temperatures in Kelvin.

    Formula: T(K) = B / ln(R1 / (R2 * (raw - O)) + F)

    Note: O is stored as a negative value in FLIR metadata, so (raw - O)
    effectively adds its absolute value to the raw signal.

    Parameters
    ----------
    raw : np.ndarray
        2-D uint16 array of raw sensor readings.
    R1, B, F, O, R2 : float
        FLIR Planck calibration constants.

    Returns
    -------
    np.ndarray
        Array of temperatures in Kelvin (float64). Invalid pixels → NaN.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        # O is typically negative, so subtracting it adds its magnitude
        signal = raw.astype(np.float64) - O
        signal = np.where(signal < 1.0, np.nan, signal)   # avoid log(≤0)
        temp_k = B / np.log(R1 / (R2 * signal) + F)
    return temp_k


def apply_emissivity_correction(raw: np.ndarray, R1: float, B: float,
                                 F: float, O: float, R2: float,
                                 emissivity: float,
                                 t_reflected_c: float) -> np.ndarray:
    """
    Applies emissivity and reflected temperature correction, then converts
    the corrected raw array to degrees Celsius.

    Physics:
      raw_reflected = planck_inverse(T_ref)
      raw_corrected = (raw - (1 - ε) * raw_reflected) / ε
      T(°C) = T(K) - 273.15

    Parameters
    ----------
    raw : np.ndarray
        2-D uint16 array of raw sensor readings.
    R1, B, F, O, R2 : float
        FLIR Planck calibration constants.
    emissivity : float
        Surface emissivity (0–1). Typical biological tissue ≈ 0.95–0.98.
    t_reflected_c : float
        Reflected apparent temperature in °C (ambient temperature of surroundings).

    Returns
    -------
    np.ndarray
        2-D float64 array of corrected temperatures in °C. Invalid → NaN.
    """
    t_ref_k = t_reflected_c + 273.15
    raw_reflected = planck_inverse(t_ref_k, R1, B, F, O, R2)

    raw_corrected = (raw.astype(np.float64) - (1.0 - emissivity) * raw_reflected) / emissivity
    raw_corrected = np.where(raw_corrected < 1.0, np.nan, raw_corrected)

    temp_k = raw_to_kelvin(raw_corrected, R1, B, F, O, R2)
    temp_k = np.where(temp_k <= 0, np.nan, temp_k)
    return temp_k - 273.15


# ---------------------------------------------------------------------------
# Spot extraction
# ---------------------------------------------------------------------------
def parse_spot_coords(meta: dict, spot_index: int) -> Optional[tuple[int, int]]:
    """
    Reads the (x, y) pixel coordinates of a measurement spot from metadata.

    Handles both plain string values ("259 96") and dict-wrapped values
    ({"val": "259 96"}) as exiftool may return either format.

    Parameters
    ----------
    meta : dict
        Full metadata dictionary from exiftool.
    spot_index : int
        Spot number (1–5).

    Returns
    -------
    tuple[int, int] or None
        (x, y) pixel coordinates, or None if the field is absent/invalid.
    """
    coords_raw = meta.get(f"Meas{spot_index}Params")
    if not coords_raw:
        return None

    if isinstance(coords_raw, dict):
        coords_raw = coords_raw.get("val", "")

    parts = str(coords_raw).strip().split()
    if len(parts) < 2:
        return None

    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        return None


def extract_spots(meta: dict, temp_celsius: np.ndarray,
                  n_spots: int = 5) -> dict[str, Optional[float]]:
    """
    Reads up to `n_spots` measurement spot coordinates from metadata and
    returns the corresponding temperature at each pixel.

    Parameters
    ----------
    meta : dict
        Full metadata dictionary from exiftool.
    temp_celsius : np.ndarray
        2-D array of corrected temperatures in °C.
    n_spots : int
        Maximum number of spots to look for (default 5).

    Returns
    -------
    dict
        {"Sp1": float|None, "Sp2": float|None, ..., "SpN": float|None}
    """
    h, w = temp_celsius.shape
    spots: dict[str, Optional[float]] = {f"Sp{i}": None for i in range(1, n_spots + 1)}

    for i in range(1, n_spots + 1):
        coords = parse_spot_coords(meta, i)
        if coords is None:
            continue

        x, y = coords
        if not (0 <= x < w and 0 <= y < h):
            log.debug("Spot %d coords (%d, %d) out of bounds (%dx%d)", i, x, y, w, h)
            continue

        val = temp_celsius[y, x]
        if not np.isnan(val):
            spots[f"Sp{i}"] = round(float(val), 1)

    return spots


# ---------------------------------------------------------------------------
# Per-image processing
# ---------------------------------------------------------------------------
def process_image(image_path: str, n_spots: int = 5) -> list:
    """
    Processes a single FLIR radiometric JPEG and returns a result row.

    Parameters
    ----------
    image_path : str
        Full path to the .jpg file.
    n_spots : int
        Maximum number of measurement spots to extract.

    Returns
    -------
    list
        [filename, Sp1, Sp2, ..., SpN, mean_temperature]
    """
    filename = os.path.basename(image_path)
    null_row = [filename] + [None] * n_spots + [None]

    # --- Metadata ---
    meta = extract_metadata(image_path)
    if not meta:
        log.warning("%s: empty metadata — skipping.", filename)
        return null_row

    def _float(key: str, default: float = 1.0) -> float:
        val = meta.get(key, default)
        if isinstance(val, str):
            val = val.replace(" C", "").strip()
        return float(val)

    try:
        R1 = _float("PlanckR1")
        B  = _float("PlanckB")
        F  = _float("PlanckF")
        O  = _float("PlanckO", 0.0)
        R2 = _float("PlanckR2")
        emissivity = _float("Emissivity", 0.95)
        t_ref_c    = _float("ReflectedApparentTemperature", 20.0)
    except (TypeError, ValueError) as exc:
        log.warning("%s: could not parse Planck constants — %s", filename, exc)
        return null_row

    # --- Raw thermal image ---
    raw_bytes = extract_raw_thermal(image_path)
    if not raw_bytes:
        log.warning("%s: no RawThermalImage found.", filename)
        return null_row

    try:
        pil_img = Image.open(io.BytesIO(raw_bytes))
        # Force 16-bit unsigned integer mode
        raw_arr = np.array(pil_img, dtype=np.uint16)
    except Exception as exc:
        log.warning("%s: failed to decode raw thermal image — %s", filename, exc)
        return null_row

    # --- Temperature conversion ---
    temp_c = apply_emissivity_correction(raw_arr, R1, B, F, O, R2, emissivity, t_ref_c)

    # --- Spot extraction ---
    spots = extract_spots(meta, temp_c, n_spots)

    valid_vals = [v for v in spots.values() if v is not None]
    mean_val = round(sum(valid_vals) / len(valid_vals), 1) if valid_vals else None

    row = [filename] + [spots.get(f"Sp{i}") for i in range(1, n_spots + 1)] + [mean_val]
    return row


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------
def process_folder(input_folder: str, output_excel: str, n_spots: int = 5) -> pd.DataFrame:
    """
    Processes all FLIR JPEG images in a folder and saves results to Excel.

    Parameters
    ----------
    input_folder : str
        Directory containing .jpg images.
    output_excel : str
        Path for the output .xlsx file.
    n_spots : int
        Maximum number of measurement spots per image (default 5).

    Returns
    -------
    pd.DataFrame
        DataFrame with one row per image.
    """
    if not os.path.isdir(input_folder):
        log.error("Input folder not found: %s", input_folder)
        return pd.DataFrame()

    jpg_files = sorted(
        f for f in os.listdir(input_folder) if f.lower().endswith(".jpg")
    )
    log.info("Found %d .jpg file(s) in '%s'", len(jpg_files), input_folder)

    records = []
    for filename in jpg_files:
        path = os.path.join(input_folder, filename)
        log.info("Processing: %s", filename)
        try:
            row = process_image(path, n_spots)
        except Exception as exc:
            log.error("%s: unexpected error — %s", filename, exc)
            row = [filename] + [None] * n_spots + [None]
        records.append(row)

    columns = ["Image"] + [f"SP{i}" for i in range(1, n_spots + 1)] + ["Mean"]
    df = pd.DataFrame(records, columns=columns)

    os.makedirs(os.path.dirname(os.path.abspath(output_excel)), exist_ok=True)
    df.to_excel(output_excel, index=False)
    log.info("Results saved to: %s", output_excel)

    return df


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract spot temperatures from FLIR radiometric JPEG images. "
            "Reads up to 5 measurement spots (Sp1–Sp5) defined in FLIR Tools "
            "and outputs an Excel file with corrected temperatures in °C."
        )
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        metavar="FOLDER",
        help="Folder containing FLIR radiometric .jpg images.",
    )
    parser.add_argument(
        "--output", "-o",
        default="results_spots.xlsx",
        metavar="FILE",
        help="Output Excel file path (default: results_spots.xlsx).",
    )
    parser.add_argument(
        "--spots", "-n",
        type=int,
        default=5,
        metavar="N",
        help="Maximum number of measurement spots to extract (default: 5).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    df = process_folder(args.input, args.output, args.spots)

    if not df.empty:
        print("\n--- Preview (first 10 rows) ---")
        print(df.head(10).to_string(index=False))
        print(f"\nTotal images processed: {len(df)}")
        valid = df[[f"SP{i}" for i in range(1, args.spots + 1)]].notna().any(axis=1).sum()
        print(f"Images with at least one valid spot: {valid}")
