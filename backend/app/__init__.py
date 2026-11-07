from pathlib import Path
from dotenv import load_dotenv

# Variables from the launching terminal take precedence over the local file.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")
