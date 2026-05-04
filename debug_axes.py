#!/usr/bin/env python3
import zipfile
import re
from pathlib import Path

ggb_path = Path("Ali_example_01/Final_Helal_1404_BSe_BMo.ggb")
with zipfile.ZipFile(ggb_path) as zf:
    with zf.open("geogebra.xml") as f:
        xml = f.read().decode("utf-8")

# Test the regex from ggb2pdf.py
ax_m = re.search(r'<euclidianView3D>.*?<axis\s+id="0"[^>]*show="(true|false)"', xml, re.S)
if ax_m:
    print(f"Regex MATCHED: show=\"{ax_m.group(1)}\"")
else:
    print("Regex NOT MATCHED")
    
# Print the euclidianView3D section for debugging
m = re.search(r"<euclidianView3D>.*?</euclidianView3D>", xml, re.S)
if m:
    print("\neuclidianView3D content:")
    print(m.group(0))
