
import sys
import os

# Set up path to include app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    print("Attempting to import app.tasks.features...")
    from app.tasks import features
    print("Successfully imported app.tasks.features")
except Exception as e:
    print(f"FAILED to import app.tasks.features: {e}")
    import traceback
    traceback.print_exc()
