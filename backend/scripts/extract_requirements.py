"""Print paragraphs and tables from the QC requirements DOCX for review."""

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

NAMESPACE = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
document_path = next((Path(__file__).resolve().parents[1] / "data").glob("*.docx"))

with ZipFile(document_path) as archive:
    root = ET.fromstring(archive.read("word/document.xml"))

for index, paragraph in enumerate(root.findall(".//w:body/w:p", NAMESPACE)):
    text = "".join(node.text or "" for node in paragraph.findall(".//w:t", NAMESPACE)).strip()
    if text:
        print(f"P{index}: {text}")

for table_index, table in enumerate(root.findall(".//w:body/w:tbl", NAMESPACE)):
    print(f"-- TABLE {table_index} --")
    for row in table.findall("w:tr", NAMESPACE):
        cells = ["".join(node.text or "" for node in cell.findall(".//w:t", NAMESPACE)).strip() for cell in row.findall("w:tc", NAMESPACE)]
        print(" | ".join(cells))
