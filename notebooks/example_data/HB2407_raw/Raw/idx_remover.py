from pathlib import Path


extensions_to_remove = ("idx", "evi")


def remove_files_with_extensions(folder: Path, extensions: tuple[str, ...]) -> int:
	removed_count = 0
	suffixes = {f".{extension.lstrip('.')}" for extension in extensions}

	for file_path in folder.iterdir():
		if file_path.is_file() and file_path.suffix in suffixes:
			file_path.unlink()
			removed_count += 1

	return removed_count


if __name__ == "__main__":
	current_folder = Path(__file__).resolve().parent
	removed_count = remove_files_with_extensions(current_folder, extensions_to_remove)
	print(f"Removed {removed_count} file(s) with extensions {extensions_to_remove} from {current_folder}")
