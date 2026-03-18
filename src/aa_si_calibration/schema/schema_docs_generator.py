"""Generate schema documentation with custom metadata details inlined."""

from __future__ import annotations

import argparse
import json
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from json_schema_for_humans.generate import generate_from_file_object
from json_schema_for_humans.generation_configuration import GenerationConfiguration


DEFAULT_SCHEMA_PATH = Path(__file__).parent / "standardized_calibration_file_schema.json"
DEFAULT_OUTPUT_PATH = Path(__file__).parent / "standardized_calibration_file_schema.md"
CUSTOM_FIELD_PREFIX = "x-"


def load_schema(schema_path: Path) -> Dict[str, Any]:
	with open(schema_path, "r", encoding="utf-8") as schema_file:
		return json.load(schema_file)


def format_custom_label(key: str) -> str:
	label = key[len(CUSTOM_FIELD_PREFIX) :].replace("_", " ").strip()
	return label[:1].upper() + label[1:]


def format_custom_value(value: Any) -> str:
	if isinstance(value, (dict, list)):
		return json.dumps(value, ensure_ascii=False)
	return str(value)


def _format_range_constraints(node: Dict[str, Any]) -> str | None:
	parts: list[str] = []
	exclusive_min = node.get("exclusiveMinimum")
	if isinstance(exclusive_min, (int, float)):
		parts.append(f"> {exclusive_min}")
	elif node.get("minimum") is not None:
		parts.append(f">= {node['minimum']}")

	exclusive_max = node.get("exclusiveMaximum")
	if isinstance(exclusive_max, (int, float)):
		parts.append(f"< {exclusive_max}")
	elif node.get("maximum") is not None:
		parts.append(f"<= {node['maximum']}")

	if node.get("multipleOf") is not None:
		parts.append(f"Multiple of {node['multipleOf']}")

	return ", ".join(parts) if parts else None


def _format_length_constraints(node: Dict[str, Any]) -> str | None:
	min_length = node.get("minLength")
	max_length = node.get("maxLength")
	if min_length is None and max_length is None:
		return None
	segments = []
	if min_length is not None:
		segments.append(f">= {min_length}")
	if max_length is not None:
		segments.append(f"<= {max_length}")
	return ", ".join(segments)


def _format_collection_constraints(node: Dict[str, Any]) -> str | None:
	min_items = node.get("minItems")
	max_items = node.get("maxItems")
	if min_items is None and max_items is None:
		return None
	segments = []
	if min_items is not None:
		segments.append(f">= {min_items}")
	if max_items is not None:
		segments.append(f"<= {max_items}")
	return ", ".join(segments)


def _augment_description(node: Dict[str, Any], custom_fields: Dict[str, Any]) -> None:
	additions: list[str] = []
	for key, value in sorted(custom_fields.items()):
		label = format_custom_label(key)
		formatted_value = format_custom_value(value)
		additions.append(f"{label}: {formatted_value}")

	range_constraints = _format_range_constraints(node)
	if range_constraints:
		additions.append(f"Numeric constraints: {range_constraints}")

	length_constraints = _format_length_constraints(node)
	if length_constraints:
		additions.append(f"Length constraints: {length_constraints}")

	collection_constraints = _format_collection_constraints(node)
	if collection_constraints:
		additions.append(f"Collection size: {collection_constraints}")

	if not additions:
		return

	base_description = (node.get("description") or "").strip()
	parts = [base_description] if base_description else []
	parts.extend(additions)
	node["description"] = "\n\n".join(parts)


def _inject_custom_fields(node: Any) -> None:
	if isinstance(node, dict):
		custom_fields = {
			key: value
			for key, value in node.items()
			if isinstance(key, str) and key.startswith(CUSTOM_FIELD_PREFIX)
		}
		_augment_description(node, custom_fields)

		for child in node.values():
			_inject_custom_fields(child)
	elif isinstance(node, list):
		for item in node:
			_inject_custom_fields(item)


def enrich_schema_descriptions(schema: Dict[str, Any]) -> Dict[str, Any]:
	schema_copy = deepcopy(schema)
	_inject_custom_fields(schema_copy)
	return schema_copy


def _strip_na_restriction_sections(markdown_text: str) -> str:
	lines = markdown_text.splitlines()
	result: list[str] = []
	i = 0
	while i < len(lines):
		line = lines[i]
		if line.startswith("| Restrictions"):
			block: list[str] = []
			j = i
			while j < len(lines) and lines[j].strip():
				block.append(lines[j])
				j += 1

			row_values: list[str] = []
			for block_line in block:
				if block_line.startswith("| **"):
					parts = [segment.strip() for segment in block_line.split("|")]
					if len(parts) >= 3:
						row_values.append(parts[2])

			if row_values and all(value.upper() == "N/A" for value in row_values):
				i = j
				while i < len(lines) and not lines[i].strip():
					i += 1
				continue
			else:
				result.extend(block)
				i = j
				continue

		result.append(line)
		i += 1
	return "\n".join(result)


def generate_documentation(
	schema: Dict[str, Any],
	output_path: Path,
	template_name: str,
	augmented_schema_output: Path | None = None,
) -> None:
	output_path.parent.mkdir(parents=True, exist_ok=True)

	schema_json = json.dumps(schema, ensure_ascii=False, indent=2)

	if augmented_schema_output is not None:
		augmented_schema_output.parent.mkdir(parents=True, exist_ok=True)
		augmented_schema_output.write_text(schema_json, encoding="utf-8")

	config = GenerationConfiguration(template_name=template_name)

	with tempfile.NamedTemporaryFile("w+", suffix=".json", delete=False, encoding="utf-8") as tmp_schema:
		tmp_schema.write(schema_json)
		tmp_schema.flush()
		tmp_schema.seek(0)

		with open(output_path, "w", encoding="utf-8") as documentation_file:
			generate_from_file_object(tmp_schema, documentation_file, config=config)

	Path(tmp_schema.name).unlink(missing_ok=True)

	markdown_contents = output_path.read_text(encoding="utf-8")
	processed_markdown = _strip_na_restriction_sections(markdown_contents)
	output_path.write_text(processed_markdown, encoding="utf-8")


def generate_schema_docs(
	schema_path: Path | str = DEFAULT_SCHEMA_PATH,
	output_path: Path | str = DEFAULT_OUTPUT_PATH,
	template: str = "md",
	write_augmented_schema: Path | str | None = None,
	cleanup_augmented_schema: bool = False,
) -> None:
	"""Convenience wrapper for notebooks and scripts."""
	schema_path = Path(schema_path)
	output_path = Path(output_path)
	augmented_schema_path = Path(write_augmented_schema) if write_augmented_schema else None

	schema = load_schema(schema_path)
	enriched_schema = enrich_schema_descriptions(schema)

	generate_documentation(
		enriched_schema,
		output_path=output_path,
		template_name=template,
		augmented_schema_output=augmented_schema_path,
	)

	if cleanup_augmented_schema and augmented_schema_path and augmented_schema_path.exists():
		augmented_schema_path.unlink()


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description="Generate Markdown documentation for the calibration schema with custom metadata inlined."
	)
	parser.add_argument(
		"--schema-path",
		type=Path,
		default=DEFAULT_SCHEMA_PATH,
		help="Path to the JSON Schema file to document.",
	)
	parser.add_argument(
		"--output-path",
		type=Path,
		default=DEFAULT_OUTPUT_PATH,
		help="Destination path for the generated documentation.",
	)
	parser.add_argument(
		"--template",
		default="md",
		help="json-schema-for-humans template to use for rendering (default: md).",
	)
	parser.add_argument(
		"--write-augmented-schema",
		type=Path,
		help="Optional path for writing the schema that includes the expanded descriptions.",
	)
	parser.add_argument(
		"--cleanup-augmented-schema",
		action="store_true",
		help="Delete the augmented schema file after documentation is generated.",
	)
	return parser.parse_args()


def main() -> None:
	args = parse_args()

	generate_schema_docs(
		schema_path=args.schema_path,
		output_path=args.output_path,
		template=args.template,
		write_augmented_schema=args.write_augmented_schema,
		cleanup_augmented_schema=args.cleanup_augmented_schema,
	)

	print(f"Documentation written to {args.output_path}")
	if args.write_augmented_schema:
		if args.cleanup_augmented_schema:
			print("Augmented schema was cleaned up after generation")
		else:
			print(f"Augmented schema written to {args.write_augmented_schema}")


if __name__ == "__main__":
	main()