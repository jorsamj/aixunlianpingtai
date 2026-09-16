from pathlib import Path

path = Path(".github/scripts/fix_training_jpeg_normalization.py")
text = path.read_text(encoding="utf-8")
old = '''replace_once(
    "platform_core/training_bundle_cache.py",
    dedent(''' + "'''" + '''
            try:
                os.link(source_image, destination_image)
                hardlinked_images += 1
                hardlinked_image_bytes += expected_size
            except OSError:
                shutil.copy2(source_image, destination_image)
                copied_images += 1
                copied_image_bytes += expected_size
    ''' + "'''" + ''').lstrip(),
    dedent(''' + "'''" + '''
            # Trainer work is writable. Never share a cache inode with a task.
            # A future reflink/CoW optimization is safe only if writes remain isolated.
            shutil.copy2(source_image, destination_image)
            copied_images += 1
            copied_image_bytes += expected_size
    ''' + "'''" + ''').lstrip(),
)
'''
new = '''replace_once(
    "platform_core/training_bundle_cache.py",
    "            try:\\n"
    "                os.link(source_image, destination_image)\\n"
    "                hardlinked_images += 1\\n"
    "                hardlinked_image_bytes += expected_size\\n"
    "            except OSError:\\n"
    "                shutil.copy2(source_image, destination_image)\\n"
    "                copied_images += 1\\n"
    "                copied_image_bytes += expected_size\\n",
    "            # Trainer work is writable. Never share a cache inode with a task.\\n"
    "            # A future reflink/CoW optimization is safe only if writes remain isolated.\\n"
    "            shutil.copy2(source_image, destination_image)\\n"
    "            copied_images += 1\\n"
    "            copied_image_bytes += expected_size\\n",
)
'''
if old not in text:
    raise SystemExit("cache hardlink patch source anchor not found")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
