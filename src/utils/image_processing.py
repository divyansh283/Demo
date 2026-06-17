import io
import cv2
import numpy as np
from PIL import Image
import pillow_heif
from src.utils.constants import TARGET_DPI

# Register HEIC opener with Pillow
pillow_heif.register_heif_opener()

def normalize_image_for_ocr(pil_image: Image.Image) -> Image.Image:
    if pil_image.mode not in ("RGB", "L"):
        pil_image = pil_image.convert("RGB")

    src_dpi = pil_image.info.get("dpi", (TARGET_DPI, TARGET_DPI))
    src_dpi_x = src_dpi[0] if src_dpi[0] > 0 else TARGET_DPI
    if src_dpi_x < TARGET_DPI:
        scale = TARGET_DPI / src_dpi_x
        new_w = max(1, int(pil_image.width * scale))
        new_h = max(1, int(pil_image.height * scale))
        pil_image = pil_image.resize((new_w, new_h), Image.LANCZOS)

    if pil_image.mode == "L":
        pil_image = pil_image.convert("RGB")

    return pil_image


def prepare_image_for_azure(pil_image: Image.Image) -> bytes:
    src_dpi = pil_image.info.get("dpi", (TARGET_DPI, TARGET_DPI))
    src_dpi_x = src_dpi[0] if src_dpi[0] > 0 else TARGET_DPI

    if src_dpi_x > TARGET_DPI:
        scale = TARGET_DPI / src_dpi_x
        new_w = max(1, int(pil_image.width * scale))
        new_h = max(1, int(pil_image.height * scale))
        pil_image = pil_image.resize((new_w, new_h), Image.LANCZOS)

    if pil_image.mode not in ("RGB", "L"):
        pil_image = pil_image.convert("RGB")

    buf = io.BytesIO()
    pil_image.save(buf, format="PNG", dpi=(TARGET_DPI, TARGET_DPI))
    return buf.getvalue()


def mask_stamp_ink(pil_image: Image.Image) -> Image.Image:
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")
    
    img_np = np.array(pil_image)
    
    R = img_np[:, :, 0].astype(np.int32)
    B = img_np[:, :, 2].astype(np.int32)
    
    mask_blue = (B > R + 25) & (B > 100)
    mask_red = (R > B + 25) & (R > 100)
    
    img_np[mask_blue | mask_red] = [255, 255, 255]
    
    gray = cv2.cvtColor(img_np, cv2.COLOR_RGB2GRAY)
    thresh = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)[1]
    
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if 1000 < area < 50000:
            (x, y), radius = cv2.minEnclosingCircle(cnt)
            circle_area = np.pi * (radius ** 2)
            if circle_area > 0 and (area / circle_area) > 0.6:
                x_min, y_min, w, h = cv2.boundingRect(cnt)
                cv2.rectangle(img_np, (x_min, y_min), (x_min + w, y_min + h), (255, 255, 255), -1)
                
    return Image.fromarray(img_np.astype(np.uint8))

def remove_grid_lines(pil_image: Image.Image) -> Image.Image:
    if pil_image.mode != "RGB":
        pil_image = pil_image.convert("RGB")
        
    img = np.array(pil_image)
    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    
    thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
    
    horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
    detect_horizontal = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, horizontal_kernel, iterations=2)
    
    vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
    detect_vertical = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, vertical_kernel, iterations=2)
    
    lines = cv2.addWeighted(detect_horizontal, 1.0, detect_vertical, 1.0, 0.0)
    img[lines > 0] = [255, 255, 255]
    
    return Image.fromarray(img)
