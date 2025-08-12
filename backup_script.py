import datetime
import shutil
import os

# Generate timestamp
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

# Define source and destination paths
project_root = "/home/miumigy/gemini/scsim"
backup_dir = os.path.join(project_root, "backup")

main_py_src = os.path.join(project_root, "main.py")
main_py_dst = os.path.join(backup_dir, f"main_{timestamp}.py")

index_html_src = os.path.join(project_root, "index.html")
index_html_dst = os.path.join(backup_dir, f"index_{timestamp}.html")

# Create backup directory if it doesn't exist
os.makedirs(backup_dir, exist_ok=True)

# Copy files
shutil.copy2(main_py_src, main_py_dst)
shutil.copy2(index_html_src, index_html_dst)

print(f"Backup created: main_{timestamp}.py and index_{timestamp}.html")
