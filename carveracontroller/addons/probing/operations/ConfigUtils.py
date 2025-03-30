import json
import os

class ConfigUtils:
    CONFIG_DIR = os.path.expanduser("~/.kivy/")

    @staticmethod
    def save_config(config: dict, filename: str):
        try:
            os.makedirs(ConfigUtils.CONFIG_DIR, exist_ok=True)  # Ensure directory exists
            file_path = os.path.join(ConfigUtils.CONFIG_DIR, filename)
            with open(file_path, "w") as f:
                json.dump(config, f, indent=4)
            print(f"Configuration saved to {file_path}")
        except Exception as e:
            print(f"Error saving configuration: {e}")

    @staticmethod
    def load_config(filename: str) -> dict:
        file_path = os.path.join(ConfigUtils.CONFIG_DIR, filename)
        if os.path.exists(file_path):
            try:
                with open(file_path, "r") as f:
                    return json.load(f)
            except Exception as e:
                print(f"Error loading configuration: {e}")
        return {}  # Return an empty dictionary if loading fails or file doesn't exist
