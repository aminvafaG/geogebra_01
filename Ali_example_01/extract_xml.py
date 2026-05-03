import zipfile
import sys
from pathlib import Path

def find_ggb_file():
    """Search for any .ggb file in the script's directory or the parent directory."""
    here = Path(__file__).resolve().parent
    for folder in (here, here.parent):
        for ggb in folder.glob("*.ggb"):
            return ggb
    return None

def extract_ggb_xml(ggb_path_str: str = None):
    # Determine the directory where this script is located
    script_dir = Path(__file__).parent.resolve()

    if ggb_path_str:
        ggb_path = Path(ggb_path_str).resolve()
    else:
        ggb_path = find_ggb_file()
    
    if ggb_path is None or not ggb_path.exists():
        print("Error: No .ggb file found. Please provide a path or place a .ggb file nearby.")
        return

    try:
        with zipfile.ZipFile(ggb_path, 'r') as z:
            if 'geogebra.xml' in z.namelist():
                # Extract geogebra.xml to the script's directory
                z.extract('geogebra.xml', path=script_dir)
                print(f"Source file: {ggb_path}")
                print(f"Extracted to: {script_dir / 'geogebra.xml'}")
            else:
                print(f"Error: 'geogebra.xml' not found inside {ggb_path.name}")
    except zipfile.BadZipFile:
        print(f"Error: {ggb_path} is not a valid .ggb (zip) file.")

if __name__ == "__main__":
    # Use command line argument if provided, otherwise try to auto-find
    path_arg = sys.argv[1] if len(sys.argv) > 1 else None
    extract_ggb_xml(path_arg)