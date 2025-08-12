import datetime
import shutil
import os

# Generate timestamp
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

# Resolve project root as this script's parent directory
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "."))
backup_dir = os.path.join(project_root, "backup")

main_py_src = os.path.join(project_root, "main.py")
main_py_dst = os.path.join(backup_dir, f"main_{timestamp}.py")

index_html_src = os.path.join(project_root, "index.html")
index_html_dst = os.path.join(backup_dir, f"index_{timestamp}.html")

# Create backup directory if it doesn't exist
os.makedirs(backup_dir, exist_ok=True)

# Copy files if they exist
copied = []
for src, dst in [(main_py_src, main_py_dst), (index_html_src, index_html_dst)]:
    if os.path.exists(src):
        shutil.copy2(src, dst)
        copied.append(os.path.basename(dst))

print(f"Backup created: {', '.join(copied)}")
