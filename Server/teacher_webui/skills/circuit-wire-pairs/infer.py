"""Run the wire-pair skill and emit the teacher UI response."""
import argparse
import json
import os
from pathlib import Path
import sys



HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from teacher_webui.vision_panel import read_schematic, image_content, BAILIAN_BASE, DEFAULT_VISION_MODEL, vision_client


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path)
    parser.add_argument("--installation", type=Path)
    args = parser.parse_args()
    client = vision_client(os.getenv("CIRCUIT_VLM_BASE_URL", BAILIAN_BASE))
    if not (args.image or args.installation):
        parser.error("需要原理图或施工图")
    def load(path):
        if path:
            with path.open("rb") as stream:
                return image_content(stream)
    result = read_schematic(client, os.getenv("CIRCUIT_VLM_MODEL", DEFAULT_VISION_MODEL),
                            load(args.image), load(args.installation))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
